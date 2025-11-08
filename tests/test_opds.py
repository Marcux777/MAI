from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from mai.core.config import get_settings
from mai.db import models
from mai.db.session import session_scope
from mai.main import create_app

os.environ.setdefault("MAI_DISABLE_WATCHER", "1")


def _create_sample_book(tmp_path: Path) -> tuple[int, int, Path]:
    file_path = tmp_path / "sample.epub"
    file_path.write_bytes(b"demo epub")
    with session_scope() as session:
        work = models.Work(title="OPDS Work", sort_title="opds_work")
        session.add(work)
        session.flush()
        edition = models.Edition(
            work_id=work.id,
            title="OPDS Edition",
            format="EPUB",
            language="pt",
            pub_year=2021,
        )
        session.add(edition)
        session.flush()
        file_rec = models.File(
            edition_id=edition.id,
            path=str(file_path),
            ext="epub",
            size_bytes=file_path.stat().st_size,
            sha256="1234",
            mime="application/epub+zip",
        )
        session.add(file_rec)
        session.flush()
        return edition.id, file_rec.id, file_path


def test_opds_catalog_returns_feed(temp_db, tmp_path):
    _create_sample_book(tmp_path)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/opds/catalog?page=1&limit=5")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/atom+xml")
    assert b"<feed" in response.content
    assert b"http://testserver/opds/file/" in response.content


def test_opds_file_returns_response(temp_db, tmp_path):
    _, file_id, file_path = _create_sample_book(tmp_path)
    app = create_app()
    settings = get_settings()
    with TestClient(app) as client:
        unauthorized = client.get(f"/opds/file/{file_id}")
        assert unauthorized.status_code == 401
        response = client.get(
            f"/opds/file/{file_id}",
            auth=(settings.admin_username, settings.admin_password),
        )
        assert response.status_code == 200
        assert response.content == file_path.read_bytes()
