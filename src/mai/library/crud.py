from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mai.db import models
from mai.ingest.pipeline import normalize


class IdentifierConflictError(ValueError):
    def __init__(self, scheme: str, value: str, edition_id: int) -> None:
        super().__init__(f"Identificador já está associado à edição {edition_id}: {scheme}={value}")
        self.scheme = scheme
        self.value = value
        self.edition_id = edition_id


@dataclass(frozen=True)
class DeleteFileResult:
    file_id: int
    edition_id: int | None
    deleted_disk: bool
    disk_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeleteEditionResult:
    edition_id: int
    deleted_files: int
    deleted_disk_files: int
    deleted_work: bool
    disk_errors: list[str] = field(default_factory=list)


def set_work_authors(session: Session, work: models.Work, author_names: Sequence[str]) -> None:
    names = _clean_strings(author_names)
    work.authors.clear()
    for name in names:
        author = session.scalar(select(models.Author).where(models.Author.name == name))
        if not author:
            author = models.Author(name=name)
            session.add(author)
            session.flush()
        work.authors.append(author)


def set_edition_tags(session: Session, edition: models.Edition, tag_names: Sequence[str]) -> None:
    names = _clean_strings(tag_names)
    tags: list[models.Tag] = []
    for name in names:
        tag = session.scalar(select(models.Tag).where(models.Tag.name == name))
        if not tag:
            tag = models.Tag(name=name)
            session.add(tag)
            session.flush()
        tags.append(tag)
    edition.tags = tags


def set_edition_identifiers(session: Session, edition: models.Edition, identifiers: Sequence[tuple[str, str]]) -> None:
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for scheme, value in identifiers:
        scheme_clean = (scheme or "").strip()
        value_clean = (value or "").strip()
        if not scheme_clean or not value_clean:
            continue
        key = (scheme_clean, value_clean)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)

    conflicts = _find_identifier_conflicts(session, edition.id, normalized)
    if conflicts:
        scheme, value, other_edition = conflicts[0]
        raise IdentifierConflictError(scheme, value, other_edition)

    keep = set(normalized)
    for existing in list(edition.identifiers):
        if (existing.scheme, existing.value) not in keep:
            session.delete(existing)

    existing_set = {(i.scheme, i.value) for i in edition.identifiers}
    for scheme, value in normalized:
        if (scheme, value) in existing_set:
            continue
        session.add(models.Identifier(edition_id=edition.id, scheme=scheme, value=value))


def set_work_series(
    session: Session,
    work: models.Work,
    series_name: str | None,
    position: float | None,
) -> None:
    name = " ".join((series_name or "").strip().split())
    entries = session.scalars(
        select(models.SeriesEntry).where(models.SeriesEntry.work_id == work.id)
    ).all()
    if not name:
        for entry in entries:
            session.delete(entry)
        return

    series = session.scalar(select(models.Series).where(models.Series.name == name))
    if not series:
        series = models.Series(name=name)
        session.add(series)
        session.flush()

    entry = next((item for item in entries if item.series_id == series.id), None)
    for item in entries:
        if item.series_id != series.id:
            session.delete(item)

    if entry:
        entry.position = position
    else:
        session.add(
            models.SeriesEntry(
                series_id=series.id,
                work_id=work.id,
                position=position,
            )
        )


def touch_work(work: models.Work) -> None:
    work.updated_at = datetime.utcnow()
    work.sort_title = normalize(work.title)


def touch_edition(edition: models.Edition) -> None:
    edition.updated_at = datetime.utcnow()


def delete_file(session: Session, file_id: int, *, delete_disk: bool = False) -> DeleteFileResult:
    file_record = session.get(models.File, file_id)
    if not file_record:
        raise LookupError("Arquivo não encontrado")

    deleted_disk = False
    disk_errors: list[str] = []
    if delete_disk:
        path = Path(file_record.path)
        try:
            path.unlink(missing_ok=True)
            deleted_disk = True
        except Exception as exc:  # pragma: no cover - depende do filesystem
            disk_errors.append(f"{path}: {exc}")

    edition_id = file_record.edition_id
    session.delete(file_record)
    session.flush()
    return DeleteFileResult(
        file_id=file_id,
        edition_id=edition_id,
        deleted_disk=deleted_disk,
        disk_errors=disk_errors,
    )


def delete_edition(
    session: Session,
    edition_id: int,
    *,
    delete_files: bool = True,
    delete_disk: bool = False,
    delete_orphan_work: bool = True,
) -> DeleteEditionResult:
    edition = session.get(models.Edition, edition_id)
    if not edition:
        raise LookupError("Edição não encontrada")

    if delete_disk and not delete_files:
        raise ValueError("delete_disk requer delete_files=true")

    work_id = edition.work_id
    files = list(edition.files)
    disk_errors: list[str] = []
    deleted_disk_files = 0

    if delete_files:
        for file_record in files:
            if delete_disk:
                path = Path(file_record.path)
                try:
                    path.unlink(missing_ok=True)
                    deleted_disk_files += 1
                except Exception as exc:  # pragma: no cover - depende do filesystem
                    disk_errors.append(f"{path}: {exc}")
            session.delete(file_record)

    session.delete(edition)
    session.flush()

    deleted_work = False
    if delete_orphan_work:
        remaining = session.scalar(
            select(func.count(models.Edition.id)).where(models.Edition.work_id == work_id)
        )
        if int(remaining or 0) == 0:
            work = session.get(models.Work, work_id)
            if work:
                session.delete(work)
                deleted_work = True
                session.flush()

    return DeleteEditionResult(
        edition_id=edition_id,
        deleted_files=len(files) if delete_files else 0,
        deleted_disk_files=deleted_disk_files,
        deleted_work=deleted_work,
        disk_errors=disk_errors,
    )


def _clean_strings(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        name = (item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _find_identifier_conflicts(
    session: Session, edition_id: int, identifiers: Sequence[tuple[str, str]]
) -> list[tuple[str, str, int]]:
    conflicts: list[tuple[str, str, int]] = []
    for scheme, value in identifiers:
        existing = session.scalar(
            select(models.Identifier).where(
                models.Identifier.scheme == scheme,
                models.Identifier.value == value,
            )
        )
        if existing and int(existing.edition_id) != int(edition_id):
            conflicts.append((scheme, value, int(existing.edition_id)))
    return conflicts
