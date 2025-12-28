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

from mai.core.config import get_settings

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
    pages: int | None
    series: str | None
    language: str | None
    tags: str
    fmt: str | None
    added_at: str | None
    file_path: str | None
    cover_url: str | None = None


@dataclass
class EditionDetail:
    edition_id: int
    title: str
    subtitle: str
    authors: List[str]
    year: Optional[int]
    pages: Optional[int]
    language: Optional[str]
    description: Optional[str]
    rating: Optional[float] = None
    read_status: str = "unread"
    series: Optional[str] = None
    series_position: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    identifiers: List['IdentifierRow'] = field(default_factory=list)
    files: List['FileRow'] = field(default_factory=list)
    providers: List['ProviderRow'] = field(default_factory=list)
    external_ratings: List['ExternalRatingRow'] = field(default_factory=list)
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
class ExternalRatingRow:
    source: str
    average: Optional[float]
    count: Optional[int]
    scale: Optional[float]
    url: Optional[str]
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


@dataclass
class CountStat:
    label: str
    count: int


@dataclass
class YearStat:
    year: int
    count: int


@dataclass
class LibraryStats:
    work_count: int
    edition_count: int
    file_count: int
    author_count: int
    format_count: int
    total_pages: int = 0
    pages_with_count: int = 0
    avg_pages: float | None = None
    max_pages: int | None = None
    max_pages_title: str | None = None
    reading_hours: float | None = None
    pages_per_hour: float = 0.0
    tag_counts: List[CountStat] = field(default_factory=list)
    format_counts: List[CountStat] = field(default_factory=list)
    year_counts: List[YearStat] = field(default_factory=list)
    missing_year_count: int = 0
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

    def apply_manifest(self, manifest_id: int, enqueue: bool = True) -> dict:
        return self._request(
            "POST",
            f"/organize/apply/{manifest_id}",
            params={"enqueue": str(enqueue).lower()},
            json={},
        )

    def rollback_manifest(self, manifest_id: int, enqueue: bool = True) -> dict:
        return self._request(
            "POST",
            f"/organize/rollback/{manifest_id}",
            params={"enqueue": str(enqueue).lower()},
            json={},
        )

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

    def fetch_tasks(self, limit: int = 50, status: str | None = None, kind: str | None = None) -> dict:
        params: dict[str, str] = {"limit": str(limit)}
        if status:
            params["status"] = status
        if kind:
            params["kind"] = kind
        return self._request("GET", "/tasks", params=params)

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
                    selectinload(models.Edition.identifiers),
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
                cover_url = edition.cover_url or self._cover_url_from_identifiers(edition.identifiers)
                rows.append(
                    BookRow(
                        edition_id=edition.id,
                        title=edition.title or (edition.work.title if edition.work else "(sem título)"),
                        authors=authors,
                        year=edition.pub_year,
                        pages=edition.pages,
                        series=series_name,
                        language=edition.language,
                        tags=tags,
                        fmt=edition.format,
                        added_at=edition.created_at.isoformat() if edition.created_at else None,
                        file_path=file_path,
                        cover_url=cover_url,
                    )
                )
            return rows

    @staticmethod
    def _cover_url_from_identifiers(identifiers: list[models.Identifier]) -> str | None:
        if not identifiers:
            return None
        isbn = None
        for ident in identifiers:
            scheme = (ident.scheme or "").upper()
            if scheme == "ISBN13":
                isbn = ident.value
                break
        if not isbn:
            for ident in identifiers:
                scheme = (ident.scheme or "").upper()
                if scheme == "ISBN10":
                    isbn = ident.value
                    break
        if not isbn:
            return None
        cleaned = "".join(ch for ch in str(isbn) if ch.isdigit() or ch in {"X", "x"})
        if not cleaned:
            return None
        return f"https://covers.openlibrary.org/b/isbn/{cleaned}-M.jpg"

    def get_library_stats(self) -> LibraryStats:
        with session_scope() as session:
            settings = get_settings()
            work_count = int(session.scalar(select(func.count(models.Work.id))) or 0)
            edition_count = int(session.scalar(select(func.count(models.Edition.id))) or 0)
            file_count = int(session.scalar(select(func.count(models.File.id))) or 0)
            author_count = int(session.scalar(select(func.count(models.Author.id))) or 0)

            fmt_expr = func.upper(models.Edition.format)
            format_count = int(
                session.scalar(
                    select(func.count(func.distinct(fmt_expr))).where(models.Edition.format.is_not(None))
                )
                or 0
            )

            tag_rows = session.execute(
                select(models.Tag.name, func.count(models.BookTag.edition_id))
                .join(models.BookTag, models.BookTag.tag_id == models.Tag.id)
                .group_by(models.Tag.id)
                .order_by(func.count(models.BookTag.edition_id).desc(), models.Tag.name.asc())
            ).all()
            tag_counts = [CountStat(label=name, count=int(count or 0)) for name, count in tag_rows]

            format_rows = session.execute(
                select(fmt_expr, func.count(models.Edition.id))
                .group_by(fmt_expr)
                .order_by(func.count(models.Edition.id).desc())
            ).all()
            format_counts = [
                CountStat(label=(fmt or "Sem formato"), count=int(count or 0))
                for fmt, count in format_rows
            ]

            year_rows = session.execute(
                select(models.Edition.pub_year, func.count(models.Edition.id))
                .where(models.Edition.pub_year.is_not(None))
                .group_by(models.Edition.pub_year)
                .order_by(models.Edition.pub_year.asc())
            ).all()
            year_counts = [
                YearStat(year=int(year), count=int(count or 0))
                for year, count in year_rows
                if year is not None
            ]

            missing_year_count = int(
                session.scalar(
                    select(func.count(models.Edition.id)).where(models.Edition.pub_year.is_(None))
                )
                or 0
            )

            pages_filter = [models.Edition.pages.is_not(None), models.Edition.pages > 0]
            total_pages = int(
                session.scalar(select(func.sum(models.Edition.pages)).where(*pages_filter)) or 0
            )
            pages_with_count = int(
                session.scalar(select(func.count(models.Edition.id)).where(*pages_filter)) or 0
            )
            avg_pages = (total_pages / pages_with_count) if pages_with_count else None
            max_pages_raw = session.scalar(select(func.max(models.Edition.pages)).where(*pages_filter))
            max_pages = int(max_pages_raw) if max_pages_raw else None
            max_pages_title = None
            if max_pages:
                max_edition = session.execute(
                    select(models.Edition)
                    .where(models.Edition.pages == max_pages)
                    .options(selectinload(models.Edition.work))
                    .limit(1)
                ).scalar_one_or_none()
                if max_edition:
                    max_pages_title = max_edition.title or (
                        max_edition.work.title if max_edition.work else None
                    )

            pages_per_hour = float(getattr(settings, "reading_pages_per_hour", 0.0) or 0.0)
            reading_hours = (
                (total_pages / pages_per_hour) if pages_per_hour > 0 and total_pages > 0 else None
            )

            return LibraryStats(
                work_count=work_count,
                edition_count=edition_count,
                file_count=file_count,
                author_count=author_count,
                format_count=format_count,
                total_pages=total_pages,
                pages_with_count=pages_with_count,
                avg_pages=avg_pages,
                max_pages=max_pages,
                max_pages_title=max_pages_title,
                reading_hours=reading_hours,
                pages_per_hour=pages_per_hour,
                tag_counts=tag_counts,
                format_counts=format_counts,
                year_counts=year_counts,
                missing_year_count=missing_year_count,
            )

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
                    selectinload(models.Edition.external_ratings),
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
                pages=edition.pages,
                language=edition.language or (work.language if work else None),
                description=(work.description if work else None),
                rating=edition.rating,
                read_status=edition.read_status,
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
            detail.external_ratings = [
                ExternalRatingRow(
                    source=rating.source,
                    average=rating.average,
                    count=rating.count,
                    scale=rating.scale,
                    url=rating.url,
                    fetched_at=rating.fetched_at.isoformat() if rating.fetched_at else None,
                )
                for rating in sorted(
                    edition.external_ratings or [],
                    key=lambda item: (item.source, item.fetched_at or ""),
                )
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
            edition.pages = detail.pages
            edition.rating = detail.rating
            edition.read_status = detail.read_status or "unread"
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

    def update_editions_bulk(
        self,
        edition_ids: List[int],
        *,
        tags: List[str] | None = None,
        merge_tags: bool = True,
        read_status: str | None = None,
        rating: float | None = None,
        rating_set: bool = False,
    ) -> dict:
        ids = [int(eid) for eid in edition_ids if int(eid) > 0]
        if not ids:
            return {"updated": 0}
        updated = 0
        with session_scope() as session:
            for edition_id in ids:
                edition = session.get(models.Edition, edition_id)
                if not edition:
                    continue
                if tags is not None:
                    if merge_tags:
                        existing = [tag.name for tag in edition.tags]
                        merged = [*existing, *tags]
                        library_crud.set_edition_tags(session, edition, merged)
                    else:
                        library_crud.set_edition_tags(session, edition, tags)
                if read_status is not None:
                    edition.read_status = read_status
                if rating_set:
                    edition.rating = rating
                library_crud.touch_edition(edition)
                session.flush()
                upsert_for_edition(session, edition.id)
                updated += 1
        return {"updated": updated}


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
