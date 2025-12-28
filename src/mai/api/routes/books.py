from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import column, func, or_, select, table, text
from sqlalchemy.orm import Session, selectinload

from mai.api.dependencies import get_db
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.library import crud as library_crud
from mai.schemas.books import (
    AuthorSchema,
    BookDetail,
    BookDeleteResponse,
    BookListItem,
    BookUpdateRequest,
    EditionSchema,
    FileDetailSchema,
    FileSchema,
    IdentifierSchema,
    MatchEventSchema,
    PaginatedBooks,
    ProviderHitSchema,
    SeriesSchema,
    WorkSchema,
)

router = APIRouter(prefix="/books", tags=["books"])

search_table = table(
    "search",
    column("rowid"),
    column("title"),
    column("authors"),
    column("series"),
    column("publisher"),
    column("tags"),
)


@router.get("", response_model=PaginatedBooks)
def list_books(
    q: Optional[str] = Query(default=None, description="Consulta textual"),
    author: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    language: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedBooks:
    stmt = select(models.Edition).join(models.Work)
    params: dict[str, object] = {}

    if q:
        params["fts_query"] = q
        stmt = stmt.join(search_table, search_table.c.rowid == models.Edition.id)
        stmt = stmt.where(text("search MATCH :fts_query"))

    if author:
        like = f"%{author}%"
        stmt = stmt.join(models.WorkAuthor, models.WorkAuthor.work_id == models.Work.id).join(
            models.Author, models.Author.id == models.WorkAuthor.author_id
        )
        stmt = stmt.where(models.Author.name.ilike(like))

    if tag:
        like = f"%{tag}%"
        stmt = stmt.join(models.BookTag, models.BookTag.edition_id == models.Edition.id).join(
            models.Tag, models.Tag.id == models.BookTag.tag_id
        )
        stmt = stmt.where(models.Tag.name.ilike(like))

    if language:
        stmt = stmt.where(models.Edition.language == language)

    if year:
        stmt = stmt.where(models.Edition.pub_year == year)

    stmt = stmt.distinct()

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(total_stmt, params).scalar() or 0

    items_stmt = (
        stmt.order_by(models.Edition.created_at.desc())
        .offset(offset)
        .limit(limit)
        .options(
            selectinload(models.Edition.work).selectinload(models.Work.authors),
            selectinload(models.Edition.work)
            .selectinload(models.Work.series_entries)
            .selectinload(models.SeriesEntry.series),
            selectinload(models.Edition.files),
            selectinload(models.Edition.identifiers),
            selectinload(models.Edition.tags),
        )
    )

    editions = db.execute(items_stmt, params).scalars().all()
    items = [serialize_book(edition) for edition in editions]
    return PaginatedBooks(total=total, limit=limit, offset=offset, items=items)


def serialize_book(edition: models.Edition) -> BookListItem:
    authors = [AuthorSchema(id=a.id, name=a.name) for a in (edition.work.authors if edition.work else [])]
    files = [FileSchema(id=f.id, path=f.path, mime=f.mime) for f in edition.files]
    identifiers = [IdentifierSchema(scheme=i.scheme, value=i.value) for i in edition.identifiers]
    tags = [t.name for t in edition.tags]
    work_title = edition.work.title if edition.work else (edition.title or "")
    series_schema = _series_for_work(edition.work) if edition.work else None

    edition_schema = EditionSchema(
        id=edition.id,
        title=edition.title if edition.title else (edition.work.title if edition.work else None),
        subtitle=edition.subtitle,
        publisher=edition.publisher,
        pub_year=edition.pub_year,
        language=edition.language,
        format=edition.format,
        cover_url=edition.cover_url,
    )

    return BookListItem(
        edition=edition_schema,
        work_title=work_title,
        authors=authors,
        files=files,
        identifiers=identifiers,
        tags=tags,
        series=series_schema,
    )


@router.get("/{edition_id}", response_model=BookDetail)
def get_book_detail(edition_id: int, db: Session = Depends(get_db)) -> BookDetail:
    stmt = (
        select(models.Edition)
        .where(models.Edition.id == edition_id)
        .options(
            selectinload(models.Edition.work).selectinload(models.Work.authors),
            selectinload(models.Edition.work)
            .selectinload(models.Work.series_entries)
            .selectinload(models.SeriesEntry.series),
            selectinload(models.Edition.files),
            selectinload(models.Edition.identifiers),
            selectinload(models.Edition.tags),
        )
    )
    edition = db.execute(stmt).scalar_one_or_none()
    if not edition:
        raise HTTPException(status_code=404, detail="Edição não encontrada")

    provider_hits = db.scalars(
        select(models.ProviderHit)
        .where(models.ProviderHit.edition_id == edition.id)
        .order_by(models.ProviderHit.fetched_at.desc())
    ).all()

    events = db.scalars(
        select(models.MatchEvent)
        .where(models.MatchEvent.edition_id == edition.id)
        .order_by(models.MatchEvent.created_at.desc())
    ).all()

    work_schema = (
        WorkSchema(id=edition.work.id, title=edition.work.title, language=edition.work.language, description=edition.work.description)
        if edition.work
        else None
    )
    authors = [AuthorSchema(id=a.id, name=a.name) for a in (edition.work.authors if edition.work else [])]
    identifiers = [IdentifierSchema(scheme=i.scheme, value=i.value) for i in edition.identifiers]
    tags = [t.name for t in edition.tags]
    files = [
        FileDetailSchema(
            id=file.id,
            path=file.path,
            mime=file.mime,
            size_bytes=file.size_bytes,
            sha256=file.sha256,
            added_at=file.added_at,
        )
        for file in edition.files
    ]
    providers = [
        ProviderHitSchema(
            id=hit.id,
            provider=hit.provider,
            remote_id=hit.remote_id,
            score=hit.score,
            fetched_at=hit.fetched_at,
        )
        for hit in provider_hits
    ]
    history = [
        MatchEventSchema(
            stage=event.stage,
            provider=event.provider,
            score=event.score,
            accepted=event.accepted,
            created_at=event.created_at,
        )
        for event in events
    ]
    edition_schema = EditionSchema(
        id=edition.id,
        title=edition.title,
        subtitle=edition.subtitle,
        publisher=edition.publisher,
        pub_year=edition.pub_year,
        language=edition.language,
        format=edition.format,
        cover_url=edition.cover_url,
    )
    return BookDetail(
        edition=edition_schema,
        work=work_schema,
        authors=authors,
        identifiers=identifiers,
        files=files,
        tags=tags,
        series=_series_for_work(edition.work) if edition.work else None,
        providers=providers,
        history=history,
    )


def _series_for_work(work: models.Work | None) -> SeriesSchema | None:
    if not work:
        return None
    entries = list(work.series_entries or [])
    if not entries:
        return None
    entries.sort(key=lambda entry: (entry.position is None, entry.position or 0.0, entry.series.name))
    entry = entries[0]
    if not entry.series:
        return None
    return SeriesSchema(name=entry.series.name, position=entry.position)


@router.patch("/{edition_id}", response_model=BookDetail)
def update_book(edition_id: int, body: BookUpdateRequest, db: Session = Depends(get_db)) -> BookDetail:
    edition = db.get(models.Edition, edition_id)
    if not edition:
        raise HTTPException(status_code=404, detail="Edição não encontrada")
    work = edition.work
    if not work:
        raise HTTPException(status_code=500, detail="Obra associada não encontrada")

    fields = set(body.model_fields_set or set())
    touched_work = False

    if "title" in fields:
        title = (body.title or "").strip()
        edition.title = title or None
        if title:
            work.title = title
            touched_work = True

    if "subtitle" in fields:
        subtitle = (body.subtitle or "").strip()
        edition.subtitle = subtitle or None

    if "publisher" in fields:
        publisher = (body.publisher or "").strip()
        edition.publisher = publisher or None

    if "pub_year" in fields:
        edition.pub_year = body.pub_year

    if "language" in fields:
        language = (body.language or "").strip() or None
        edition.language = language
        work.language = language
        touched_work = True

    if "description" in fields:
        description = (body.description or "").strip() or None
        work.description = description
        touched_work = True

    if "authors" in fields:
        library_crud.set_work_authors(db, work, body.authors or [])
        touched_work = True

    if "tags" in fields:
        library_crud.set_edition_tags(db, edition, body.tags or [])

    if "identifiers" in fields:
        pairs = [(item.scheme, item.value) for item in (body.identifiers or [])]
        try:
            library_crud.set_edition_identifiers(db, edition, pairs)
        except library_crud.IdentifierConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    if "series" in fields or "series_position" in fields:
        current = _series_for_work(work)
        series_name = body.series if "series" in fields else (current.name if current else None)
        series_position = (
            body.series_position
            if "series_position" in fields
            else (current.position if current else None)
        )
        library_crud.set_work_series(db, work, series_name, series_position)
        touched_work = True

    now = datetime.utcnow()
    library_crud.touch_edition(edition)
    if touched_work:
        library_crud.touch_work(work)
        work.updated_at = now
    edition.updated_at = now

    db.flush()
    upsert_for_edition(db, edition.id)
    db.commit()
    return get_book_detail(edition_id, db)


@router.delete("/{edition_id}", response_model=BookDeleteResponse)
def delete_book(
    edition_id: int,
    delete_files: bool = Query(default=True, description="Remove os registros de arquivos associados"),
    delete_disk: bool = Query(default=False, description="Remove os arquivos também do disco (requer delete_files)"),
    db: Session = Depends(get_db),
) -> BookDeleteResponse:
    try:
        result = library_crud.delete_edition(
            db,
            edition_id,
            delete_files=delete_files,
            delete_disk=delete_disk,
        )
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return BookDeleteResponse(
        edition_id=result.edition_id,
        deleted_files=result.deleted_files,
        deleted_disk_files=result.deleted_disk_files,
        deleted_work=result.deleted_work,
        disk_errors=result.disk_errors,
    )
