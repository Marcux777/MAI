from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, TextIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mai.core.logging import logger
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.ingest.pipeline import isbn13, normalize
from mai.library import crud as library_crud


@dataclass(frozen=True)
class GoodreadsRow:
    title: str
    authors: list[str]
    isbn13: str | None
    goodreads_id: str | None
    exclusive_shelf: str | None
    bookshelves: list[str]
    rating: float | None
    publisher: str | None
    pub_year: int | None
    pages: int | None


@dataclass
class GoodreadsSyncOptions:
    create_missing: bool = True
    apply_read_status: bool = True
    force_read_status: bool = False
    apply_rating: bool = True
    overwrite_rating: bool = False
    apply_tags: bool = True
    include_bookshelves: bool = False
    tag_prefix: str | None = None
    apply_identifiers: bool = True
    dry_run: bool = False


@dataclass
class GoodreadsSyncResult:
    total: int = 0
    matched: int = 0
    matched_goodreads_id: int = 0
    matched_isbn: int = 0
    matched_title: int = 0
    created: int = 0
    updated: int = 0
    read_status_updates: int = 0
    rating_updates: int = 0
    tag_updates: int = 0
    identifier_updates: int = 0
    skipped_no_title: int = 0
    skipped_missing: int = 0
    unchanged: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "matched": self.matched,
            "matched_goodreads_id": self.matched_goodreads_id,
            "matched_isbn": self.matched_isbn,
            "matched_title": self.matched_title,
            "created": self.created,
            "updated": self.updated,
            "read_status_updates": self.read_status_updates,
            "rating_updates": self.rating_updates,
            "tag_updates": self.tag_updates,
            "identifier_updates": self.identifier_updates,
            "skipped_no_title": self.skipped_no_title,
            "skipped_missing": self.skipped_missing,
            "unchanged": self.unchanged,
            "dry_run": self.dry_run,
        }


_HEADER_ALIASES = {
    "title": ["title", "book title"],
    "author": ["author"],
    "additional_authors": ["additional authors"],
    "isbn": ["isbn"],
    "isbn13": ["isbn13"],
    "goodreads_id": ["book id", "goodreads id", "goodreads book id"],
    "exclusive_shelf": ["exclusive shelf"],
    "bookshelves": ["bookshelves"],
    "rating": ["my rating"],
    "publisher": ["publisher"],
    "pages": ["number of pages", "pages"],
    "pub_year": ["year published", "original publication year"],
}


def iter_goodreads_rows(handle: TextIO) -> Iterable[GoodreadsRow]:
    reader = csv.DictReader(handle)
    if not reader.fieldnames:
        raise ValueError("CSV sem cabecalhos")
    for raw in reader:
        normalized = {
            _normalize_header(key): (value or "") for key, value in raw.items() if key is not None
        }
        title = _get_field(normalized, "title")
        author = _get_field(normalized, "author")
        additional_authors = _get_field(normalized, "additional_authors")
        authors = _parse_authors(author, additional_authors)
        isbn_raw = _get_field(normalized, "isbn13") or _get_field(normalized, "isbn")
        isbn_value = isbn13(isbn_raw) if isbn_raw else None
        goodreads_id = _get_field(normalized, "goodreads_id") or None
        exclusive_shelf = _normalize_shelf(_get_field(normalized, "exclusive_shelf"))
        bookshelves = _parse_bookshelves(_get_field(normalized, "bookshelves"))
        rating = _parse_float(_get_field(normalized, "rating"))
        publisher = _get_field(normalized, "publisher") or None
        pages = _parse_int(_get_field(normalized, "pages"))
        pub_year = _parse_int(_get_field(normalized, "pub_year"))

        yield GoodreadsRow(
            title=title,
            authors=authors,
            isbn13=isbn_value,
            goodreads_id=goodreads_id,
            exclusive_shelf=exclusive_shelf,
            bookshelves=bookshelves,
            rating=rating,
            publisher=publisher,
            pub_year=pub_year,
            pages=pages,
        )


def sync_goodreads_csv(
    session: Session,
    source: Path | TextIO,
    options: GoodreadsSyncOptions | None = None,
) -> GoodreadsSyncResult:
    opts = options or GoodreadsSyncOptions()
    result = GoodreadsSyncResult(dry_run=opts.dry_run)

    rows = _load_rows(source)
    isbn_cache: dict[str, models.Edition | None] = {}
    goodreads_cache: dict[str, models.Edition | None] = {}
    title_cache: dict[tuple[str, str], models.Edition | None] = {}
    author_cache: dict[str, models.Author] = {}

    for row in rows:
        result.total += 1
        if not row.title and not row.isbn13 and not row.goodreads_id:
            result.skipped_no_title += 1
            continue
        try:
            edition, match_kind = _find_matching_edition(
                session,
                row,
                isbn_cache,
                goodreads_cache,
                title_cache,
            )
            if edition:
                result.matched += 1
                if match_kind == "goodreads":
                    result.matched_goodreads_id += 1
                elif match_kind == "isbn":
                    result.matched_isbn += 1
                else:
                    result.matched_title += 1

                changed = _apply_updates(session, edition, row, opts, result)
                if changed:
                    result.updated += 1
                    if not opts.dry_run:
                        edition.updated_at = datetime.utcnow()
                        upsert_for_edition(session, edition.id)
                else:
                    result.unchanged += 1
                continue

            if not opts.create_missing:
                result.skipped_missing += 1
                continue

            result.created += 1
            if opts.dry_run:
                continue

            edition = _create_edition_from_row(session, row, opts, author_cache, result)
            if edition:
                upsert_for_edition(session, edition.id)
        except Exception as exc:  # pragma: no cover - defensivo
            logger.exception("Falha ao processar linha Goodreads: %s", exc)
            result.errors.append(str(exc))

    return result


def _load_rows(source: Path | TextIO) -> list[GoodreadsRow]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(iter_goodreads_rows(handle))
    return list(iter_goodreads_rows(source))


def _find_matching_edition(
    session: Session,
    row: GoodreadsRow,
    isbn_cache: dict[str, models.Edition | None],
    goodreads_cache: dict[str, models.Edition | None],
    title_cache: dict[tuple[str, str], models.Edition | None],
) -> tuple[models.Edition | None, str | None]:
    if row.goodreads_id:
        if row.goodreads_id in goodreads_cache:
            return goodreads_cache[row.goodreads_id], "goodreads"
        found = _find_by_identifier(session, "GOODREADS", row.goodreads_id)
        goodreads_cache[row.goodreads_id] = found
        if found:
            return found, "goodreads"

    if row.isbn13:
        if row.isbn13 in isbn_cache:
            return isbn_cache[row.isbn13], "isbn"
        found = _find_by_isbn(session, row.isbn13)
        isbn_cache[row.isbn13] = found
        if found:
            return found, "isbn"

    if row.title:
        key_author = _primary_author(row.authors) or ""
        key = (normalize(row.title), key_author.casefold())
        if key in title_cache:
            return title_cache[key], "title"
        found = _find_by_title_author(session, row.title, row.authors)
        title_cache[key] = found
        if found:
            return found, "title"

    return None, None


def _apply_updates(
    session: Session,
    edition: models.Edition,
    row: GoodreadsRow,
    opts: GoodreadsSyncOptions,
    result: GoodreadsSyncResult,
) -> bool:
    updated = False

    desired_status = _desired_read_status(row.exclusive_shelf)
    if opts.apply_read_status and desired_status:
        if desired_status == "read":
            if edition.read_status != "read":
                updated = True
                result.read_status_updates += 1
                if not opts.dry_run:
                    edition.read_status = "read"
        else:
            if opts.force_read_status or edition.read_status != "read":
                if edition.read_status != "unread":
                    updated = True
                    result.read_status_updates += 1
                    if not opts.dry_run:
                        edition.read_status = "unread"

    if opts.apply_rating and row.rating is not None:
        if opts.overwrite_rating or edition.rating is None:
            if edition.rating != row.rating:
                updated = True
                result.rating_updates += 1
                if not opts.dry_run:
                    edition.rating = row.rating

    if opts.apply_tags:
        new_tags = _build_tags(row, opts)
        if new_tags:
            existing = [tag.name for tag in edition.tags]
            merged = _merge_tags(existing, new_tags)
            if merged != existing:
                updated = True
                result.tag_updates += 1
                if not opts.dry_run:
                    library_crud.set_edition_tags(session, edition, merged)

    if opts.apply_identifiers:
        identifiers_added = False
        if row.goodreads_id:
            identifiers_added |= _ensure_identifier(
                session,
                edition,
                scheme="GOODREADS",
                value=row.goodreads_id,
                result=result,
                apply=not opts.dry_run,
            )
        if row.isbn13:
            identifiers_added |= _ensure_identifier(
                session,
                edition,
                scheme="ISBN13",
                value=row.isbn13,
                result=result,
                apply=not opts.dry_run,
            )
        if identifiers_added:
            updated = True
            result.identifier_updates += 1

    return updated


def _create_edition_from_row(
    session: Session,
    row: GoodreadsRow,
    opts: GoodreadsSyncOptions,
    author_cache: dict[str, models.Author],
    result: GoodreadsSyncResult,
) -> models.Edition | None:
    title = row.title or "Sem titulo"
    work = models.Work(title=title, sort_title=normalize(title))
    session.add(work)
    session.flush()

    authors = row.authors or ["Desconhecido"]
    for name in _dedupe_authors(authors):
        author = _get_or_create_author(session, name, author_cache)
        work.authors.append(author)

    edition = models.Edition(
        work_id=work.id,
        title=title,
        publisher=row.publisher,
        pub_year=row.pub_year,
        pages=row.pages,
        language=None,
        rating=row.rating if (opts.apply_rating and row.rating is not None) else None,
        read_status=_desired_read_status(row.exclusive_shelf) or "unread",
        created_at=datetime.utcnow(),
    )
    session.add(edition)
    session.flush()

    if opts.apply_identifiers:
        if row.goodreads_id:
            _ensure_identifier(
                session,
                edition,
                scheme="GOODREADS",
                value=row.goodreads_id,
                result=result,
                apply=True,
            )
        if row.isbn13:
            _ensure_identifier(
                session,
                edition,
                scheme="ISBN13",
                value=row.isbn13,
                result=result,
                apply=True,
            )

    if opts.apply_tags:
        tags = _build_tags(row, opts)
        if tags:
            library_crud.set_edition_tags(session, edition, tags)

    return edition


def _find_by_identifier(session: Session, scheme: str, value: str) -> models.Edition | None:
    identifier = session.scalar(
        select(models.Identifier).where(
            models.Identifier.scheme == scheme,
            models.Identifier.value == value,
        )
    )
    if not identifier:
        return None
    return session.get(models.Edition, identifier.edition_id)


def _find_by_isbn(session: Session, value: str) -> models.Edition | None:
    identifier = session.scalar(
        select(models.Identifier).where(
            models.Identifier.value == value,
            models.Identifier.scheme.in_(["ISBN13", "ISBN10", "ISBN"]),
        )
    )
    if not identifier:
        return None
    return session.get(models.Edition, identifier.edition_id)


def _find_by_title_author(
    session: Session,
    title: str,
    authors: list[str],
) -> models.Edition | None:
    sort_title = normalize(title)
    if not sort_title:
        return None

    for author in _dedupe_authors(authors):
        stmt = (
            select(models.Work)
            .join(models.WorkAuthor, models.WorkAuthor.work_id == models.Work.id)
            .join(models.Author, models.Author.id == models.WorkAuthor.author_id)
            .where(models.Work.sort_title == sort_title)
            .where(func.lower(models.Author.name) == author.casefold())
        )
        work = session.scalar(stmt)
        if work:
            return _pick_edition_for_work(session, work, title)

    works = session.scalars(select(models.Work).where(models.Work.sort_title == sort_title)).all()
    if len(works) == 1:
        return _pick_edition_for_work(session, works[0], title)
    return None


def _pick_edition_for_work(
    session: Session,
    work: models.Work,
    title: str | None,
) -> models.Edition | None:
    editions = session.scalars(
        select(models.Edition).where(models.Edition.work_id == work.id).order_by(models.Edition.id.asc())
    ).all()
    if not editions:
        return None
    if title:
        norm_title = normalize(title)
        for edition in editions:
            if normalize(edition.title or "") == norm_title:
                return edition
    return editions[0]


def _get_or_create_author(
    session: Session,
    name: str,
    cache: dict[str, models.Author],
) -> models.Author:
    key = name.casefold()
    if key in cache:
        return cache[key]
    author = session.scalar(select(models.Author).where(models.Author.name == name))
    if not author:
        author = models.Author(name=name)
        session.add(author)
        session.flush()
    cache[key] = author
    return author


def _ensure_identifier(
    session: Session,
    edition: models.Edition,
    scheme: str,
    value: str,
    result: GoodreadsSyncResult,
    apply: bool,
) -> bool:
    value_clean = (value or "").strip()
    if not value_clean:
        return False
    existing = session.scalar(
        select(models.Identifier).where(
            models.Identifier.scheme == scheme,
            models.Identifier.value == value_clean,
        )
    )
    if existing:
        if int(existing.edition_id) != int(edition.id):
            result.warnings.append(
                f"Identificador {scheme}={value_clean} ja pertence a edicao {existing.edition_id}"
            )
        return False
    if apply:
        session.add(models.Identifier(edition_id=edition.id, scheme=scheme, value=value_clean))
    return True


def _build_tags(row: GoodreadsRow, opts: GoodreadsSyncOptions) -> list[str]:
    tags: list[str] = []
    shelf_tag = _shelf_tag(row.exclusive_shelf)
    if shelf_tag:
        tags.append(shelf_tag)
    if opts.include_bookshelves:
        tags.extend(row.bookshelves)
    tags = [_apply_tag_prefix(tag, opts.tag_prefix) for tag in tags if tag]
    return _dedupe_tags(tags)


def _shelf_tag(exclusive_shelf: str | None) -> str | None:
    if not exclusive_shelf:
        return None
    shelf = exclusive_shelf.strip().casefold()
    if shelf == "to-read":
        return "to-read"
    if shelf == "currently-reading":
        return "currently-reading"
    return None


def _desired_read_status(exclusive_shelf: str | None) -> str | None:
    if not exclusive_shelf:
        return None
    shelf = exclusive_shelf.strip().casefold()
    if shelf == "read":
        return "read"
    if shelf in {"to-read", "currently-reading"}:
        return "unread"
    return None


def _merge_tags(existing: list[str], new_tags: list[str]) -> list[str]:
    existing_set = {tag.casefold() for tag in existing}
    merged = list(existing)
    for tag in new_tags:
        key = tag.casefold()
        if key in existing_set:
            continue
        existing_set.add(key)
        merged.append(tag)
    return merged


def _parse_authors(author: str, additional: str) -> list[str]:
    authors: list[str] = []
    if author:
        authors.append(_clean_text(author))
    if additional:
        parts = re.split(r"\s*(?:,|;|&| and )\s*", additional)
        for part in parts:
            name = _clean_text(part)
            if name:
                authors.append(name)
    return _dedupe_authors(authors)


def _dedupe_authors(authors: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for author in authors:
        name = _clean_text(author)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(name)
    return output


def _parse_bookshelves(raw: str) -> list[str]:
    if not raw:
        return []
    shelves = []
    for part in raw.split(","):
        value = _clean_text(part)
        if value:
            shelves.append(value)
    return _dedupe_tags(shelves)


def _dedupe_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for tag in tags:
        name = _clean_text(tag)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(name)
    return output


def _apply_tag_prefix(tag: str, prefix: str | None) -> str:
    if not prefix:
        return tag
    prefix = prefix.strip()
    if not prefix:
        return tag
    normalized_prefix = prefix
    if not normalized_prefix.endswith(":") and not normalized_prefix.endswith("/"):
        normalized_prefix = f"{normalized_prefix}:"
    if tag.casefold().startswith(normalized_prefix.casefold()):
        return tag
    return f"{normalized_prefix}{tag}"


def _primary_author(authors: list[str]) -> str | None:
    for author in authors:
        if author:
            return author
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _get_field(row: dict[str, str], key: str) -> str:
    for alias in _HEADER_ALIASES.get(key, [key]):
        value = row.get(_normalize_header(alias), "")
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _normalize_shelf(value: str) -> str | None:
    if not value:
        return None
    shelf = _clean_text(value).casefold()
    shelf = shelf.replace(" ", "-")
    return shelf or None


def _parse_int(value: str) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if number <= 0:
        return None
    return number
