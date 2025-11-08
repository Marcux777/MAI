from __future__ import annotations

import math
import secrets
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from mai.api.dependencies import get_db
from mai.core.config import get_settings
from mai.db import models

router = APIRouter(prefix="/opds", tags=["opds"])
basic_auth = HTTPBasic()


def _iso(dt: datetime | None) -> str:
    value = dt or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _require_basic(credentials: HTTPBasicCredentials = Depends(basic_auth)) -> None:
    settings = get_settings()
    valid_user = secrets.compare_digest(credentials.username, settings.admin_username)
    valid_password = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )


@router.get("/catalog", response_class=Response)
def opds_catalog(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Response:
    total = db.scalar(select(func.count()).select_from(models.Edition)) or 0
    offset = (page - 1) * limit
    if total and offset >= total:
        raise HTTPException(status_code=404, detail="Página fora do intervalo")

    stmt = (
        select(models.Edition)
        .order_by(models.Edition.created_at.desc())
        .offset(offset)
        .limit(limit)
        .options(
            selectinload(models.Edition.work).selectinload(models.Work.authors),
            selectinload(models.Edition.files),
        )
    )
    editions = db.scalars(stmt).all()
    last_page = max(1, math.ceil(total / limit)) if total else 1

    feed = Element("feed", xmlns="http://www.w3.org/2005/Atom")
    SubElement(feed, "id").text = f"urn:mai:catalog:{page}"
    SubElement(feed, "title").text = "MAI — Catálogo OPDS"
    SubElement(feed, "updated").text = _iso(datetime.now(timezone.utc))
    SubElement(feed, "link", rel="self", href=str(request.url.include_query_params(page=page, limit=limit)))
    SubElement(feed, "link", rel="start", href=str(request.url.include_query_params(page=1, limit=limit)))
    if page > 1:
        SubElement(feed, "link", rel="previous", href=str(request.url.include_query_params(page=page - 1, limit=limit)))
    if page < last_page:
        SubElement(feed, "link", rel="next", href=str(request.url.include_query_params(page=page + 1, limit=limit)))

    for edition in editions:
        entry = SubElement(feed, "entry")
        SubElement(entry, "id").text = f"urn:mai:edition:{edition.id}"
        SubElement(entry, "title").text = edition.title or (edition.work.title if edition.work else "")
        SubElement(entry, "updated").text = _iso(edition.updated_at or edition.created_at)
        if edition.work and edition.work.authors:
            for author in edition.work.authors:
                author_el = SubElement(entry, "author")
                SubElement(author_el, "name").text = author.name
        summary_parts = [
            f"Publisher: {edition.publisher}" if edition.publisher else "",
            f"Year: {edition.pub_year}" if edition.pub_year else "",
            f"Language: {edition.language}" if edition.language else "",
        ]
        SubElement(entry, "content", type="text").text = ", ".join(filter(None, summary_parts)) or "Entrada MAI"
        if edition.cover_url:
            SubElement(
                entry,
                "link",
                rel="http://opds-spec.org/image",
                href=edition.cover_url,
                type="image/jpeg",
            )
        for file in edition.files:
            file_url = request.url_for("opds_file", file_id=file.id)
            link_attrs = {
                "rel": "http://opds-spec.org/acquisition",
                "href": file_url,
                "type": file.mime or "application/octet-stream",
            }
            if file.size_bytes:
                link_attrs["length"] = str(file.size_bytes)
            SubElement(entry, "link", **link_attrs)

    xml_bytes = tostring(feed, encoding="utf-8", xml_declaration=True)
    return Response(
        content=xml_bytes,
        media_type="application/atom+xml;profile=opds-catalog;kind=acquisition",
    )


@router.get("/file/{file_id}", name="opds_file")
def opds_file(
    file_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_basic),
) -> FileResponse:
    file = db.get(models.File, file_id)
    if not file or not Path(file.path).exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(
        file.path,
        media_type=file.mime or "application/octet-stream",
        filename=Path(file.path).name,
    )
