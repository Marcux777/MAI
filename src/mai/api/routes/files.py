from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.schemas.files import AttachFileRequest, AttachFileResponse

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/attach", response_model=AttachFileResponse)
def attach_file(body: AttachFileRequest, db: Session = Depends(get_db)) -> AttachFileResponse:
    edition = db.get(models.Edition, body.edition_id)
    if not edition:
        raise HTTPException(status_code=404, detail="Edição não encontrada")

    file_record = _resolve_file(db, body)
    if not file_record:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    previous_edition = file_record.edition_id
    file_record.edition_id = edition.id
    file_record.last_seen = datetime.utcnow()

    upsert_for_edition(db, edition.id)
    if previous_edition and previous_edition != edition.id:
        upsert_for_edition(db, previous_edition)

    db.commit()
    return AttachFileResponse(file_id=file_record.id, edition_id=edition.id, path=file_record.path)


def _resolve_file(db: Session, body: AttachFileRequest):
    if body.file_id:
        return db.get(models.File, body.file_id)
    if body.path:
        resolved = str(Path(body.path).expanduser())
        return db.scalar(select(models.File).where(models.File.path == resolved))
    return None
