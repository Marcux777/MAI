from __future__ import annotations

import json
import mimetypes
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from rapidfuzz import fuzz
from sqlalchemy import select, delete
from threading import Event

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from mai.core.logging import logger
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.db.session import session_scope
from mai.ingest import extractors
from mai.ingest.providers import BookBrainzProvider, GoogleBooksProvider, OpenLibraryProvider, Provider
from mai.ingest.types import Candidate, LocalMetadata
from mai.utils.files import compute_sha256

SUPPORTED_EXTENSIONS = {".epub", ".pdf", ".mobi", ".azw", ".azw3"}
ACCEPT_THRESHOLD = 0.85


def build_providers(google_key: Optional[str] = None) -> List[Provider]:
    providers: List[Provider] = [
        OpenLibraryProvider(),
        GoogleBooksProvider(api_key=google_key),
        BookBrainzProvider(),
    ]
    return providers


def ingest_paths(paths: List[Path], providers: Optional[List[Provider]] = None) -> None:
    providers = providers or build_providers()
    for path in paths:
        files = scan_directory(path)
        for file_path in files:
            logger.info("Processando %s", file_path)
            try:
                with session_scope() as session:
                    ingest_file(session, file_path, providers)
            except Exception as exc:  # pragma: no cover - log and continue
                logger.exception("Falha ao ingerir %s: %s", file_path, exc)


def watch_directories(
    paths: List[Path], providers: Optional[List[Provider]] = None, stop_event: Optional[Event] = None
) -> None:
    providers = providers or build_providers()
    handler = IngestEventHandler(providers)
    observer = Observer()
    for path in paths:
        observer.schedule(handler, str(path), recursive=True)
        logger.info("Observando %s", path)
    observer.start()
    try:
        while True:
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("Watcher interrompido pelo usuário")
    finally:
        observer.stop()
        observer.join()


def scan_directory(root: Path) -> List[Path]:
    return [path for path in root.rglob("*") if path.suffix.lower() in SUPPORTED_EXTENSIONS]


class IngestEventHandler(FileSystemEventHandler):
    def __init__(self, providers: Iterable[Provider]) -> None:
        super().__init__()
        self.providers = list(providers)

    def on_created(self, event):  # pragma: no cover - depende de watchdog
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        logger.info("Arquivo detectado via watcher: %s", path)
        with session_scope() as session:
            ingest_file(session, path, self.providers)


def ingest_file(session, path: Path, providers: Iterable[Provider]) -> None:
    path = path.resolve()
    if not path.exists():
        logger.warning("Arquivo %s não existe", path)
        return

    sha256 = compute_sha256(path)
    existing = session.scalar(select(models.File).where(models.File.sha256 == sha256))
    if existing:
        existing.path = str(path)
        existing.last_seen = datetime.utcnow()
        session.flush()
        logger.info("Arquivo já existente atualizado: %s", path)
        return

    local = extractors.extract_metadata(path)
    local.identifiers.append(path.stem)
    hits = search_providers(local, providers)
    scored_candidates = score_candidates(local, hits)
    candidate, top_score, ranked_candidates = reconcile(scored_candidates)
    persist(session, path, sha256, local, candidate, ranked_candidates, top_score)
    logger.info("Ingestão concluída para %s", path)


def persist(
    session,
    path: Path,
    sha256: str,
    local: LocalMetadata,
    candidate: Optional[Candidate],
    ranked_candidates: List[dict],
    top_score: float,
) -> None:
    now = datetime.utcnow()
    title = candidate.title if candidate and candidate.title else local.title or path.stem
    sort_title = normalize(title)
    language = (candidate.language if candidate and candidate.language else local.language)

    work = session.scalar(select(models.Work).where(models.Work.sort_title == sort_title))
    if not work:
        work = models.Work(title=title, sort_title=sort_title, language=language)
        session.add(work)
        session.flush()

    authors = candidate.authors if candidate and candidate.authors else (local.authors or ["Desconhecido"])
    author_objs = []
    for author_name in authors:
        author = session.scalar(select(models.Author).where(models.Author.name == author_name))
        if not author:
            author = models.Author(name=author_name)
            session.add(author)
            session.flush()
        author_objs.append(author)
        if author not in work.authors:
            work.authors.append(author)

    edition = models.Edition(
        work_id=work.id,
        title=candidate.title if candidate and candidate.title else local.title,
        subtitle=None,
        publisher=candidate.publisher if candidate else None,
        pub_year=candidate.year if candidate else local.year,
        format=path.suffix.lstrip("."),
        language=language,
        cover_url=candidate.cover_url if candidate else None,
        created_at=now,
    )
    session.add(edition)
    session.flush()
    upsert_for_edition(session, edition.id)

    identifiers = []
    if candidate:
        for key, value in candidate.ids.items():
            if value:
                identifiers.append((key, value))
    for identifier in local.identifiers:
        isbn = isbn13(identifier)
        if isbn:
            identifiers.append(("ISBN13", isbn))
    for scheme, value in identifiers:
        if not session.scalar(
            select(models.Identifier).where(
                models.Identifier.scheme == scheme,
                models.Identifier.value == value,
            )
        ):
            session.add(models.Identifier(edition_id=edition.id, scheme=scheme, value=value))

    file_record = models.File(
        edition_id=edition.id,
        path=str(path),
        ext=path.suffix.lower().lstrip("."),
        size_bytes=path.stat().st_size,
        sha256=sha256,
        mime=attach_mime(path),
        drm=False,
        added_at=now,
        last_seen=now,
    )
    session.add(file_record)

    if candidate:
        upsert_provider_hit(session, edition.id, candidate, score=1.0)

    record_identification(session, edition.id, ranked_candidates, candidate, top_score)


def search_providers(local: LocalMetadata, providers: Iterable[Provider]) -> List[Tuple[str, Candidate]]:
    hits: List[Tuple[str, Candidate]] = []
    isbn = next((isbn13(i) for i in local.identifiers if isbn13(i)), None)
    query = " ".join(filter(None, [local.title, " ".join(local.authors)]))
    for provider in providers:
        try:
            if isbn:
                result = provider.get_by_isbn(isbn)
                if result:
                    hits.append(("by_isbn", result))
                    continue
            if query:
                hits.extend(("search", candidate) for candidate in provider.search(query))
        except Exception as exc:  # pragma: no cover
            logger.warning("Provider %s falhou: %s", provider.__class__.__name__, exc)
    return hits


def score_candidates(local: LocalMetadata, hits: List[Tuple[str, Candidate]]) -> List[dict]:
    return [
        {"stage": stage, "candidate": candidate, "score": score_candidate(local, candidate)}
        for stage, candidate in hits
    ]


def reconcile(scored_candidates: List[dict]) -> tuple[Optional[Candidate], float, List[dict]]:
    if not scored_candidates:
        return None, 0.0, []
    ranked = sorted(scored_candidates, key=lambda item: item["score"], reverse=True)
    top_score = ranked[0]["score"]
    if top_score >= ACCEPT_THRESHOLD:
        return ranked[0]["candidate"], top_score, ranked
    return None, top_score, ranked


def score_candidate(local: LocalMetadata, candidate: Candidate) -> float:
    score = 0.0
    local_isbn = next((isbn13(i) for i in local.identifiers if isbn13(i)), None)
    remote_isbn = candidate.ids.get("ISBN13")
    if local_isbn and remote_isbn and local_isbn == remote_isbn:
        return 1.0
    if local.title and candidate.title:
        score += 0.35 * (fuzz.WRatio(normalize(local.title), normalize(candidate.title)) / 100)
    if local.authors and candidate.authors:
        score += 0.35 * (fuzz.token_set_ratio(" ".join(local.authors), " ".join(candidate.authors)) / 100)
    if local.year and candidate.year and abs(local.year - candidate.year) <= 1:
        score += 0.1
    if local.language and candidate.language and normalize(local.language) == normalize(candidate.language):
        score += 0.05
    if candidate.publisher:
        score += 0.05
    return score


def attach_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "M")
    return " ".join("".join(ch for ch in text if ch.isalnum() or ch.isspace()).lower().split())


def isbn13(value: str) -> Optional[str]:
    digits = [c for c in value if c.isdigit() or c in {"X", "x"}]
    if len(digits) == 10:
        return isbn10_to_13("".join(digits))
    if len(digits) == 13 and validate_isbn13("".join(digits)):
        return "".join(digits)
    return None


def isbn10_to_13(isbn10: str) -> Optional[str]:
    if len(isbn10) != 10:
        return None
    core = "978" + isbn10[:-1]
    check = 0
    for i, char in enumerate(core):
        check += int(char) * (1 if i % 2 == 0 else 3)
    check = (10 - (check % 10)) % 10
    return core + str(check)


def validate_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    total = 0
    for idx, char in enumerate(value):
        weight = 1 if idx % 2 == 0 else 3
        total += int(char) * weight
    return total % 10 == 0


def record_identification(
    session,
    edition_id: int,
    ranked_candidates: List[dict],
    chosen: Optional[Candidate],
    top_score: float,
) -> None:
    auto_accepted = bool(chosen)
    payload = []
    for item in ranked_candidates:
        candidate = item["candidate"]
        payload.append(
            {
                "stage": item["stage"],
                "provider": candidate.source,
                "score": round(item["score"], 4),
                "title": candidate.title,
                "authors": candidate.authors,
                "ids": candidate.ids,
                "publisher": candidate.publisher,
                "year": candidate.year,
                "language": candidate.language,
                "cover_url": candidate.cover_url,
                "payload": candidate.payload,
            }
        )

    result = session.get(models.IdentifyResult, edition_id)
    if result:
        result.auto_accepted = auto_accepted
        result.chosen_provider = chosen.source if chosen else None
        result.top_score = top_score
        result.candidates_json = json.dumps(payload, ensure_ascii=False)
    else:
        session.add(
            models.IdentifyResult(
                edition_id=edition_id,
                auto_accepted=auto_accepted,
                chosen_provider=chosen.source if chosen else None,
                top_score=top_score,
                candidates_json=json.dumps(payload, ensure_ascii=False),
            )
        )

    session.execute(delete(models.MatchEvent).where(models.MatchEvent.edition_id == edition_id))
    events = []
    for rank, item in enumerate(ranked_candidates, start=1):
        candidate = item["candidate"]
        accepted = bool(chosen and candidate == chosen)
        events.append(
            models.MatchEvent(
                edition_id=edition_id,
                stage=item["stage"],
                provider=candidate.source,
                candidate_rank=rank,
                score=item["score"],
                accepted=accepted,
            )
        )
    if events:
        session.add_all(events)


def build_local_metadata_from_edition(edition: models.Edition) -> LocalMetadata:
    work = edition.work
    title = edition.title or (work.title if work else None)
    authors = [author.name for author in (work.authors if work else [])]
    identifiers = [identifier.value for identifier in edition.identifiers]
    language = edition.language or (work.language if work else None)
    return LocalMetadata(
        title=title,
        authors=authors,
        identifiers=identifiers,
        language=language,
        year=edition.pub_year,
    )


def apply_candidate_to_edition(session, edition: models.Edition, candidate: Candidate) -> None:
    work = edition.work
    if not work:
        work = models.Work(
            title=candidate.title or edition.title or "Sem título",
            sort_title=normalize(candidate.title or edition.title),
            language=candidate.language or edition.language,
        )
        session.add(work)
        session.flush()
        edition.work = work
        edition.work_id = work.id

    if candidate.title:
        edition.title = candidate.title
        work.title = candidate.title
        work.sort_title = normalize(candidate.title)

    if candidate.language:
        edition.language = candidate.language
        work.language = candidate.language

    if candidate.publisher:
        edition.publisher = candidate.publisher

    if candidate.year:
        edition.pub_year = candidate.year

    if candidate.cover_url:
        edition.cover_url = candidate.cover_url

    if candidate.authors:
        work.authors.clear()
        for name in candidate.authors:
            author = session.scalar(select(models.Author).where(models.Author.name == name))
            if not author:
                author = models.Author(name=name)
                session.add(author)
                session.flush()
            work.authors.append(author)

    session.flush()


def upsert_provider_hit(session, edition_id: int, candidate: Candidate, score: float) -> None:
    remote_id = _candidate_remote_id(candidate.ids)
    payload = json.dumps(candidate.payload, ensure_ascii=False)
    hit = session.scalar(
        select(models.ProviderHit).where(
            models.ProviderHit.provider == candidate.source,
            models.ProviderHit.remote_id == remote_id,
        )
    )
    now = datetime.utcnow()
    if hit:
        hit.payload_json = payload
        hit.score = score
        hit.fetched_at = now
        hit.edition_id = edition_id
    else:
        session.add(
            models.ProviderHit(
                provider=candidate.source,
                remote_id=remote_id,
                edition_id=edition_id,
                payload_json=payload,
                score=score,
                fetched_at=now,
            )
        )


def _candidate_remote_id(ids: Dict[str, Optional[str]]) -> Optional[str]:
    for key in ("OLID", "GBID", "ISBN13"):
        value = ids.get(key)
        if value:
            return value
    for value in ids.values():
        if value:
            return value
    return None


def deserialize_ranked_candidates(payload_json: str) -> List[dict]:
    if not payload_json:
        return []
    try:
        raw = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    ranked: List[dict] = []
    for item in raw:
        candidate = Candidate(
            source=item.get("provider"),
            title=item.get("title"),
            authors=item.get("authors") or [],
            year=item.get("year"),
            publisher=item.get("publisher"),
            language=item.get("language"),
            ids=item.get("ids") or {},
            cover_url=item.get("cover_url"),
            payload=item.get("payload") or {},
        )
        ranked.append(
            {
                "stage": item.get("stage", "search"),
                "candidate": candidate,
                "score": item.get("score", 0.0),
            }
        )
    return ranked
