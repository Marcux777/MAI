from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from sqlalchemy import or_, select

from mai.db import models
from mai.db.session import session_scope
from mai.db.indexer import upsert_for_edition


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


class BackendClient:
    """Cliente HTTP simples para reutilizar os endpoints FastAPI no app Qt."""

    def __init__(self, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or os.getenv("MAI_API_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        resp = httpx.request(method, url, timeout=self.timeout, **kwargs)
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
    def list_books(self, query: str = "", limit: int = 500) -> List[BookRow]:
        with session_scope() as session:
            stmt = select(models.Edition).join(models.Work)
            if query:
                like = f"%{query}%"
                stmt = stmt.where(
                    or_(
                        models.Edition.title.ilike(like),
                        models.Work.title.ilike(like),
                        models.Edition.subtitle.ilike(like),
                    )
                )
            stmt = stmt.limit(limit)
            editions = session.scalars(stmt).unique().all()

            if not editions:
                return self._mock_books()

            rows: List[BookRow] = []
            for edition in editions:
                authors = ", ".join(a.name for a in (edition.work.authors if edition.work else []))
                tags = ", ".join(t.name for t in edition.tags)
                file_path = edition.files[0].path if edition.files else None
                rows.append(
                    BookRow(
                        edition_id=edition.id,
                        title=edition.title or (edition.work.title if edition.work else "(sem título)"),
                        authors=authors,
                        year=edition.pub_year,
                        series=None,
                        language=edition.language,
                        tags=tags,
                        fmt=edition.format,
                        added_at=edition.created_at.isoformat() if edition.created_at else None,
                        file_path=file_path,
                    )
                )
            return rows

    def _mock_books(self) -> List[BookRow]:
        sample = []
        for idx in range(1, 21):
            sample.append(
                BookRow(
                    edition_id=idx,
                    title=f"Livro demonstrativo {idx}",
                    authors="Ana Becker" if idx % 2 == 0 else "Joana Lima",
                    year=2010 + idx,
                    series=None,
                    language="pt",
                    tags="demo,offline",
                    fmt="EPUB" if idx % 2 == 0 else "PDF",
                    added_at=None,
                    file_path=None,
                )
            )
        return sample

    def get_detail(self, edition_id: int) -> EditionDetail | None:
        with session_scope() as session:
            edition = session.get(models.Edition, edition_id)
            if not edition:
                return None
            work = edition.work
            authors = [a.name for a in (work.authors if work else [])]
            detail = EditionDetail(
                edition_id=edition.id,
                title=edition.title or (work.title if work else ""),
                subtitle=edition.subtitle or "",
                authors=authors,
                year=edition.pub_year,
                language=edition.language or (work.language if work else None),
                description=(work.description if work else None),
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
            if detail.language:
                work.language = detail.language

            # Atualiza autores
            new_names = [name.strip() for name in detail.authors if name.strip()]
            work.authors.clear()
            for name in new_names:
                author = session.scalar(select(models.Author).where(models.Author.name == name))
                if not author:
                    author = models.Author(name=name)
                    session.add(author)
                    session.flush()
                work.authors.append(author)

            session.flush()
            upsert_for_edition(session, edition.id)
