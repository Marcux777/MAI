from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

from sqlalchemy import column, delete, func, or_, select, table, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import selectinload

from mai.db import models
from mai.db.session import session_scope
from mai.db.indexer import upsert_for_edition
from mai.library import crud as library_crud


@dataclass
class BookRow:
    edition_id: int
    title: str
    authors: str
    year: int | None
    series: str | None
    language: str | None
    tags: str
    fmt: str | None
    added_at: str | None
    file_path: str | None


@dataclass
class EditionDetail:
    edition_id: int
    title: str
    subtitle: str
    authors: List[str]
    year: Optional[int]
    language: Optional[str]
    description: Optional[str]
    series: Optional[str] = None
    series_position: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    identifiers: List['IdentifierRow'] = field(default_factory=list)
    files: List['FileRow'] = field(default_factory=list)
    providers: List['ProviderRow'] = field(default_factory=list)
    history: List['HistoryRow'] = field(default_factory=list)


@dataclass
class IdentifierRow:
    scheme: str
    value: str


@dataclass
class FileRow:
    path: str
    fmt: Optional[str]
    size: Optional[int]
    sha256: Optional[str]
    added_at: Optional[str]


@dataclass
class ProviderRow:
    provider: str
    remote_id: Optional[str]
    score: Optional[float]
    fetched_at: Optional[str]


@dataclass
class HistoryRow:
    stage: str
    provider: str
    score: Optional[float]
    accepted: bool
    created_at: Optional[str]


@dataclass
class CollectionRow:
    id: int
    name: str
    parent_id: int | None
    item_count: int


class BackendClient:
    """Cliente HTTP simples para reutilizar os endpoints FastAPI no app Qt."""

    def __init__(self, base_url: str | None = None, timeout: float = 15.0) -> None:
        default_base_url = "http://127.0.0.1:8000"
        if Path("/.dockerenv").exists():
            default_base_url = "http://api:8000"
        self.base_url = (base_url or os.getenv("MAI_API_URL") or default_base_url).rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", self.timeout)
        resp = httpx.request(method, url, timeout=timeout, **kwargs)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    def fetch_review_queue(self) -> dict:
        return self._request("GET", "/review-pending")

    def resolve_review(self, edition_id: int, candidate_index: Optional[int], reject: bool) -> dict:
        payload = {"edition_id": edition_id, "reject": reject}
        if candidate_index is not None:
            payload["candidate_index"] = candidate_index
        return self._request("POST", "/review/resolve", json=payload)

    def get_manifest_detail(self, manifest_id: int) -> dict:
        return self._request("GET", f"/organize/{manifest_id}")

    def apply_manifest(self, manifest_id: int) -> dict:
        return self._request("POST", f"/organize/apply/{manifest_id}", json={})

    def rollback_manifest(self, manifest_id: int) -> dict:
        return self._request("POST", f"/organize/rollback/{manifest_id}")

    def import_scan(self, paths: List[str]) -> dict:
        return self._request("POST", "/import/scan", json={"paths": paths or None})

    def import_upload(self, path: str | Path) -> dict:
        file_path = Path(path).expanduser()
        if not file_path.exists() and file_path.is_absolute() and Path("/host").exists():
            mapped = Path("/host") / file_path.relative_to("/")
            if mapped.exists():
                file_path = mapped
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
        mime, _ = mimetypes.guess_type(file_path.name)
        handle = file_path.open("rb")
        try:
            return self._request(
                "POST",
                "/import/upload",
                files={"file": (file_path.name, handle, mime or "application/octet-stream")},
                timeout=max(float(self.timeout), 120.0),
            )
        finally:
            handle.close()

    def watch_start(self, paths: List[str]) -> dict:
        return self._request("POST", "/import/watch", json={"paths": paths or None})

    def watch_stop(self) -> dict:
        return self._request("DELETE", "/import/watch")

    def fetch_providers(self, edition_id: int, providers: Optional[List[str]] = None, auto_apply: bool = True) -> dict:
        payload = {
            "edition_id": edition_id,
            "providers": providers,
            "auto_apply": auto_apply,
        }
        return self._request("POST", "/providers/fetch", json=payload)


class LibraryService:
    _search_table = table("search", column("rowid"))

    def list_books(
        self,
        query: str = "",
        limit: int = 500,
        collection_id: int | None = None,
        unfiled_only: bool = False,
    ) -> List[BookRow]:
        with session_scope() as session:
            stmt = select(models.Edition).join(models.Work)
            params: dict[str, object] = {}

            if collection_id is not None:
                stmt = stmt.join(models.CollectionItem).where(
                    models.CollectionItem.collection_id == collection_id
                )
            elif unfiled_only:
                stmt = stmt.outerjoin(
                    models.CollectionItem, models.CollectionItem.edition_id == models.Edition.id
                ).where(models.CollectionItem.edition_id.is_(None))

            if query:
                params["fts_query"] = query
                stmt = stmt.join(self._search_table, self._search_table.c.rowid == models.Edition.id)
                stmt = stmt.where(text("search MATCH :fts_query"))

            stmt = (
                stmt.order_by(models.Edition.created_at.desc())
                .limit(limit)
                .options(
                    selectinload(models.Edition.work).selectinload(models.Work.authors),
                    selectinload(models.Edition.work)
                    .selectinload(models.Work.series_entries)
                    .selectinload(models.SeriesEntry.series),
                    selectinload(models.Edition.tags),
                    selectinload(models.Edition.files),
                )
            )

            editions = session.execute(stmt, params).scalars().unique().all()
            if not editions:
                return []

            rows: List[BookRow] = []
            for edition in editions:
                series_name, series_position = _series_for_work(edition.work)
                authors = ", ".join(a.name for a in (edition.work.authors if edition.work else []))
                tags = ", ".join(t.name for t in edition.tags)
                file_path = edition.files[0].path if edition.files else None
                rows.append(
                    BookRow(
                        edition_id=edition.id,
                        title=edition.title or (edition.work.title if edition.work else "(sem título)"),
                        authors=authors,
                        year=edition.pub_year,
                        series=series_name,
                        language=edition.language,
                        tags=tags,
                        fmt=edition.format,
                        added_at=edition.created_at.isoformat() if edition.created_at else None,
                        file_path=file_path,
                    )
                )
            return rows

    def get_detail(self, edition_id: int) -> EditionDetail | None:
        with session_scope() as session:
            stmt = (
                select(models.Edition)
                .where(models.Edition.id == edition_id)
                .options(
                    selectinload(models.Edition.work).selectinload(models.Work.authors),
                    selectinload(models.Edition.work)
                    .selectinload(models.Work.series_entries)
                    .selectinload(models.SeriesEntry.series),
                    selectinload(models.Edition.identifiers),
                    selectinload(models.Edition.files),
                    selectinload(models.Edition.tags),
                )
            )
            edition = session.execute(stmt).scalar_one_or_none()
            if edition is None:
                return None
            work = edition.work
            authors = [a.name for a in (work.authors if work else [])]
            series_name, series_position = _series_for_work(work)
            detail = EditionDetail(
                edition_id=edition.id,
                title=edition.title or (work.title if work else ""),
                subtitle=edition.subtitle or "",
                authors=authors,
                year=edition.pub_year,
                language=edition.language or (work.language if work else None),
                description=(work.description if work else None),
                series=series_name,
                series_position=series_position,
                tags=[t.name for t in edition.tags],
            )
            detail.identifiers = [IdentifierRow(id.scheme, id.value) for id in edition.identifiers]
            detail.files = [
                FileRow(
                    path=file.path,
                    fmt=file.ext,
                    size=file.size_bytes,
                    sha256=file.sha256,
                    added_at=file.added_at.isoformat() if file.added_at else None,
                )
                for file in edition.files
            ]
            provider_hits = session.scalars(
                select(models.ProviderHit)
                .where(models.ProviderHit.edition_id == edition.id)
                .order_by(models.ProviderHit.fetched_at.desc())
            ).all()
            detail.providers = [
                ProviderRow(
                    provider=hit.provider,
                    remote_id=hit.remote_id,
                    score=hit.score,
                    fetched_at=hit.fetched_at.isoformat() if hit.fetched_at else None,
                )
                for hit in provider_hits
            ]
            match_events = session.scalars(
                select(models.MatchEvent)
                .where(models.MatchEvent.edition_id == edition.id)
                .order_by(models.MatchEvent.created_at.desc())
            ).all()
            detail.history = [
                HistoryRow(
                    stage=event.stage,
                    provider=event.provider,
                    score=event.score,
                    accepted=bool(event.accepted),
                    created_at=event.created_at.isoformat() if event.created_at else None,
                )
                for event in match_events
            ]
            return detail

    def save_detail(self, detail: EditionDetail) -> None:
        with session_scope() as session:
            edition = session.get(models.Edition, detail.edition_id)
            if not edition:
                raise ValueError("Edição não encontrada")
            work = edition.work
            if work is None:
                raise ValueError("Obra associada não encontrada")

            edition.title = detail.title or None
            edition.subtitle = detail.subtitle or None
            edition.language = detail.language or None
            edition.pub_year = detail.year
            work.title = detail.title or work.title
            work.description = detail.description
            work.language = detail.language or None

            # Atualiza autores
            library_crud.set_work_authors(session, work, detail.authors)

            library_crud.set_work_series(session, work, detail.series, detail.series_position)

            # Atualiza tags
            library_crud.set_edition_tags(session, edition, detail.tags)

            library_crud.touch_edition(edition)
            library_crud.touch_work(work)

            session.flush()
            upsert_for_edition(session, edition.id)

    def delete_editions(self, edition_ids: List[int], delete_disk: bool = False) -> dict:
        ids = [int(eid) for eid in edition_ids if int(eid) > 0]
        if not ids:
            return {"deleted": 0, "deleted_files": 0, "disk_errors": []}

        deleted = 0
        deleted_files = 0
        disk_errors: list[str] = []
        with session_scope() as session:
            for edition_id in ids:
                with session.begin_nested():
                    try:
                        result = library_crud.delete_edition(
                            session,
                            edition_id,
                            delete_files=True,
                            delete_disk=delete_disk,
                        )
                    except LookupError:
                        continue
                    deleted += 1
                    deleted_files += result.deleted_files
                    disk_errors.extend(result.disk_errors)
        return {"deleted": deleted, "deleted_files": deleted_files, "disk_errors": disk_errors}


def _series_for_work(work: models.Work | None) -> tuple[str | None, float | None]:
    if not work:
        return None, None
    entries = list(work.series_entries or [])
    if not entries:
        return None, None
    entries.sort(key=lambda entry: (entry.position is None, entry.position or 0.0, entry.series.name))
    entry = entries[0]
    if not entry.series:
        return None, None
    return entry.series.name, entry.position


class CollectionService:
    def list_collections(self) -> List[CollectionRow]:
        with session_scope() as session:
            counts = dict(
                session.execute(
                    select(
                        models.CollectionItem.collection_id,
                        func.count(models.CollectionItem.edition_id),
                    ).group_by(models.CollectionItem.collection_id)
                ).all()
            )
            collections = session.scalars(select(models.Collection).order_by(models.Collection.name.asc())).all()
            return [
                CollectionRow(
                    id=c.id,
                    name=c.name,
                    parent_id=c.parent_id,
                    item_count=int(counts.get(c.id, 0)),
                )
                for c in collections
            ]

    def total_editions(self) -> int:
        with session_scope() as session:
            return int(session.scalar(select(func.count(models.Edition.id))) or 0)

    def unfiled_count(self) -> int:
        with session_scope() as session:
            stmt = (
                select(func.count(models.Edition.id))
                .outerjoin(models.CollectionItem, models.CollectionItem.edition_id == models.Edition.id)
                .where(models.CollectionItem.edition_id.is_(None))
            )
            return int(session.scalar(stmt) or 0)

    def create_collection(self, name: str, parent_id: int | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Nome da coleção é obrigatório")
        with session_scope() as session:
            collection = models.Collection(name=name, parent_id=parent_id)
            session.add(collection)
            session.flush()
            return int(collection.id)

    def rename_collection(self, collection_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Nome da coleção é obrigatório")
        with session_scope() as session:
            collection = session.get(models.Collection, collection_id)
            if not collection:
                raise LookupError("Coleção não encontrada")
            collection.name = name
            session.flush()

    def delete_collection(self, collection_id: int) -> None:
        with session_scope() as session:
            collection = session.get(models.Collection, collection_id)
            if not collection:
                return
            session.delete(collection)
            session.flush()

    def add_editions(self, collection_id: int, edition_ids: List[int]) -> int:
        values = [{"collection_id": collection_id, "edition_id": eid} for eid in edition_ids]
        if not values:
            return 0
        with session_scope() as session:
            stmt = sqlite_insert(models.CollectionItem).values(values)
            stmt = stmt.on_conflict_do_nothing(index_elements=["collection_id", "edition_id"])
            result = session.execute(stmt)
            session.flush()
            return int(result.rowcount or 0)

    def remove_editions(self, collection_id: int, edition_ids: List[int]) -> int:
        if not edition_ids:
            return 0
        with session_scope() as session:
            result = session.execute(
                delete(models.CollectionItem).where(
                    models.CollectionItem.collection_id == collection_id,
                    models.CollectionItem.edition_id.in_(edition_ids),
                )
            )
            session.flush()
            return int(result.rowcount or 0)
