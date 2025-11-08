from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mai.api.routes import (
    auth,
    books,
    dashboard,
    events,
    files,
    health,
    imports,
    opds,
    organize,
    providers,
    review,
)
from mai.core.config import get_settings
from mai.core.logging import configure_logging
from mai.db.init import apply_schema
from mai.ingest.service import start_watcher, stop_watcher, watcher_disabled


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.debug)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        apply_schema()
        watcher_started = False
        if settings.watch_paths and not watcher_disabled():
            paths = [Path(p).resolve() for p in settings.watch_paths]
            watcher_started = start_watcher(paths, settings.google_books_key)
        try:
            yield
        finally:
            if watcher_started:
                stop_watcher()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.include_router(health.router)
    app.include_router(books.router)
    app.include_router(imports.router)
    static_dir = Path(__file__).resolve().parents[2] / "static"
    app.include_router(organize.router)
    app.include_router(dashboard.router)
    app.include_router(auth.router)
    app.include_router(events.router)
    app.include_router(providers.router)
    app.include_router(files.router)
    app.include_router(review.router)
    app.include_router(opds.router)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    ui_dist = Path(__file__).resolve().parents[2] / "ui" / "dist"
    if ui_dist.exists():
        app.mount("/app", StaticFiles(directory=ui_dist, html=True), name="ui-app")

    return app


def run() -> None:
    settings = get_settings()
    app = create_app()
    uvicorn.run(app, host=settings.api_host, port=settings.api_port, reload=settings.debug)


app = create_app()
