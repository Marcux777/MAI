from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db  # ensures DB ready
from mai.core.config import get_settings
from mai.core.logging import logger
from mai.db import models
from mai.ingest.pipeline import SUPPORTED_EXTENSIONS, build_providers, ingest_file
from mai.ingest.service import start_watcher, stop_watcher
from mai.schemas.imports import ImportRequest, ImportResponse, UploadResponse, WatchRequest, WatchResponse
from mai.tasks.queue import TASK_KIND_IMPORT_SCAN, get_task_queue

router = APIRouter(prefix="/import", tags=["import"])


def _resolve_paths(payload_paths, settings_paths) -> List[Path]:
    paths = payload_paths or settings_paths
    if not paths:
        raise HTTPException(status_code=400, detail="Nenhum caminho informado para importação")
    resolved: List[Path] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"Caminho inexistente: {path}")
        resolved.append(path)
    return resolved


def _sanitize_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    if not name:
        return "upload.bin"
    name = name.replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:180] if name else "upload.bin"


@router.post("/scan", response_model=ImportResponse, status_code=202)
def scan(payload: ImportRequest) -> ImportResponse:
    settings = get_settings()
    paths = _resolve_paths(payload.paths, settings.watch_paths)
    task_id = get_task_queue().enqueue(
        TASK_KIND_IMPORT_SCAN,
        {"paths": [str(p) for p in paths]},
    )
    logger.info("Importação enfileirada task_id=%s para %s", task_id, paths)
    return ImportResponse(status="queued", paths=[str(p) for p in paths], task_id=task_id)


@router.post("/watch", response_model=WatchResponse)
def start_watch(payload: WatchRequest) -> WatchResponse:
    settings = get_settings()
    paths = _resolve_paths(payload.paths, settings.watch_paths)
    started = start_watcher(paths, settings.google_books_key)
    return WatchResponse(status="started" if started else "running", watching=True, paths=[str(p) for p in paths])


@router.delete("/watch", response_model=WatchResponse)
def stop_watch() -> WatchResponse:
    stopped = stop_watcher()
    return WatchResponse(status="stopped" if stopped else "idle", watching=False, paths=[])


@router.post("/upload", response_model=UploadResponse, status_code=201)
def upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> UploadResponse:
    filename = _sanitize_filename(file.filename)
    suffix = Path(filename).suffix.lower()
    if not suffix:
        raise HTTPException(status_code=400, detail="Arquivo sem extensão")
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {suffix}")

    settings = get_settings()
    upload_dir = settings.upload_dir.expanduser()
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid4().hex}_{filename}"

    try:
        try:
            with dest.open("wb") as out:
                shutil.copyfileobj(file.file, out)
        except Exception:  # pragma: no cover - depende de I/O
            logger.exception("Falha ao salvar upload: %s", dest)
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                logger.warning("Falha ao limpar upload parcial: %s", dest)
            raise HTTPException(status_code=500, detail="Falha ao salvar upload")
    finally:
        try:
            file.file.close()
        except Exception:  # pragma: no cover - best-effort close
            pass

    providers = build_providers(settings.google_books_key)
    try:
        resolved_dest = dest.resolve()
        ingest_file(db, resolved_dest, providers)
        db.commit()
    except Exception:  # pragma: no cover - defensive
        db.rollback()
        logger.exception("Falha ao ingerir upload: %s", dest)
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            logger.warning("Falha ao remover upload após erro: %s", dest)
        raise HTTPException(status_code=500, detail="Falha ao ingerir upload")

    file_record = db.scalar(select(models.File).where(models.File.path == str(resolved_dest)))
    if not file_record:
        raise HTTPException(status_code=500, detail="Falha ao localizar upload após ingestão")

    return UploadResponse(
        status="ingested",
        file_id=file_record.id,
        edition_id=file_record.edition_id,
        path=file_record.path,
    )
