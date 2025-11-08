from __future__ import annotations

import os
from pathlib import Path
from threading import Event, Thread
from typing import List, Optional

from mai.core.logging import logger
from mai.ingest.pipeline import build_providers, watch_directories

_watcher_thread: Thread | None = None
_stop_event: Event | None = None


def watcher_disabled() -> bool:
    return os.getenv("DISABLE_WATCHER") == "1" or os.getenv("MAI_DISABLE_WATCHER") == "1"


def start_watcher(paths: List[Path], google_key: Optional[str] = None) -> bool:
    global _watcher_thread, _stop_event
    if watcher_disabled():
        logger.info("Watcher desabilitado por configuração de ambiente")
        return False
    if not paths:
        logger.info("Nenhum caminho configurado para watcher")
        return False
    if _watcher_thread and _watcher_thread.is_alive():
        logger.info("Watcher já em execução")
        return False
    providers = build_providers(google_key)
    _stop_event = Event()
    _watcher_thread = Thread(
        target=watch_directories,
        args=(paths, providers, _stop_event),
        daemon=True,
    )
    _watcher_thread.start()
    logger.info("Watcher iniciado para %s", paths)
    return True


def stop_watcher() -> bool:
    global _watcher_thread, _stop_event
    if not _watcher_thread:
        return False
    if _stop_event:
        _stop_event.set()
    _watcher_thread.join(timeout=5)
    logger.info("Watcher encerrado")
    _watcher_thread = None
    _stop_event = None
    return True


def is_watcher_running() -> bool:
    return bool(_watcher_thread and _watcher_thread.is_alive())
