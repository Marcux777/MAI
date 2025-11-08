from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from mai.api.dependencies import get_db  # ensures DB ready
from mai.core.config import get_settings
from mai.core.logging import logger
from mai.ingest.pipeline import build_providers, ingest_paths
from mai.ingest.service import start_watcher, stop_watcher
from mai.schemas.imports import ImportRequest, ImportResponse, WatchRequest, WatchResponse

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


@router.post("/scan", response_model=ImportResponse, status_code=202)
def scan(payload: ImportRequest, background: BackgroundTasks) -> ImportResponse:
    settings = get_settings()
    paths = _resolve_paths(payload.paths, settings.watch_paths)
    providers = build_providers(settings.google_books_key)
    background.add_task(ingest_paths, paths, providers)
    logger.info("Importação agendada para %s", paths)
    return ImportResponse(status="scheduled", paths=[str(p) for p in paths])


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
