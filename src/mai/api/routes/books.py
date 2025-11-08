from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import column, func, or_, select, table, text
from sqlalchemy.orm import Session, selectinload

from mai.api.dependencies import get_db
from mai.db import models
from mai.schemas.books import (
    AuthorSchema,
    BookDetail,
    BookListItem,
    EditionSchema,
    FileDetailSchema,
    FileSchema,
    IdentifierSchema,
    MatchEventSchema,
    PaginatedBooks,
    ProviderHitSchema,
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
            selectinload(models.Edition.files),
            selectinload(models.Edition.identifiers),
        )
    )

    editions = db.execute(items_stmt, params).scalars().all()
    items = [serialize_book(edition) for edition in editions]
    return PaginatedBooks(total=total, limit=limit, offset=offset, items=items)


def serialize_book(edition: models.Edition) -> BookListItem:
    authors = [AuthorSchema(id=a.id, name=a.name) for a in (edition.work.authors if edition.work else [])]
    files = [FileSchema(id=f.id, path=f.path, mime=f.mime) for f in edition.files]
    identifiers = [IdentifierSchema(scheme=i.scheme, value=i.value) for i in edition.identifiers]
    work_title = edition.work.title if edition.work else (edition.title or "")

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
    )


@router.get("/{edition_id}", response_model=BookDetail)
def get_book_detail(edition_id: int, db: Session = Depends(get_db)) -> BookDetail:
    stmt = (
        select(models.Edition)
        .where(models.Edition.id == edition_id)
        .options(
            selectinload(models.Edition.work).selectinload(models.Work.authors),
            selectinload(models.Edition.files),
            selectinload(models.Edition.identifiers),
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
        providers=providers,
        history=history,
    )
