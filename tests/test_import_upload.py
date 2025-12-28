from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from mai.core.config import get_settings as settings_cache
from mai.db import models
from mai.db.session import session_scope
from mai.ingest import pipeline
from mai.ingest.types import Candidate, LocalMetadata
from mai.main import create_app


def test_upload_triggers_metadata_fetch(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_cache.cache_clear()

    calls: dict[str, object] = {"search_queries": []}

    class DummyProvider:
        slug = "dummy"

        def get_by_isbn(self, isbn13: str):
            return None

        def search(self, query: str):
            calls["search_queries"].append(query)
            return [
                Candidate(
                    source="dummy",
                    title="Livro Teste",
                    authors=["Autor Teste"],
                    year=2020,
                    publisher="Editora Teste",
                    language="pt",
                    ids={"ISBN13": "9781234567890"},
                    cover_url=None,
                    payload={},
                    series="Saga do Teste",
                    series_position=2,
                )
            ]

    import mai.api.routes.imports as imports_routes

    monkeypatch.setattr(imports_routes, "build_providers", lambda google_key=None: [DummyProvider()])
    monkeypatch.setattr(
        pipeline.extractors,
        "extract_metadata",
        lambda path: LocalMetadata(
            title="Livro Teste",
            authors=["Autor Teste"],
            identifiers=[],
            language="pt",
            year=2020,
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )

    assert resp.status_code == 201
    payload = resp.json()
    assert payload["status"] == "ingested"
    assert payload["file_id"] > 0
    assert payload["edition_id"] > 0
    assert Path(payload["path"]).exists()
    assert calls["search_queries"]

    with session_scope() as session:
        edition = session.scalar(select(models.Edition).limit(1))
        assert edition is not None
        entry = session.scalar(
            select(models.SeriesEntry).where(models.SeriesEntry.work_id == edition.work_id)
        )
        assert entry is not None
        series = session.get(models.Series, entry.series_id)
        assert series is not None
        assert series.name == "Saga do Teste"
        assert entry.position == 2


def test_upload_requires_file_field(temp_db):
    settings_cache.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/import/upload")

    assert resp.status_code == 422


def test_upload_rejects_missing_extension(temp_db, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(upload_dir))
    settings_cache.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro", b"conteudo", "application/octet-stream")},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Arquivo sem extensão"
    assert not list(upload_dir.glob("*"))


def test_upload_rejects_unsupported_extension(temp_db, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(upload_dir))
    settings_cache.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro.exe", b"conteudo", "application/octet-stream")},
        )

    assert resp.status_code == 400
    assert "Formato não suportado" in resp.json()["detail"]
    assert not list(upload_dir.glob("*"))


def test_upload_save_failure_returns_500(temp_db, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(upload_dir, 0o555)
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(upload_dir))
    settings_cache.cache_clear()

    app = create_app()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/import/upload",
                files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
            )
    finally:
        os.chmod(upload_dir, 0o755)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Falha ao salvar upload"
    assert not list(upload_dir.glob("*"))


def test_upload_provider_failure_is_non_fatal(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_cache.cache_clear()

    calls: dict[str, object] = {"attempted": False}

    class FailingProvider:
        slug = "fail"

        def get_by_isbn(self, isbn13: str):
            return None

        def search(self, query: str):
            calls["attempted"] = True
            raise RuntimeError("provider down")

    import mai.api.routes.imports as imports_routes

    monkeypatch.setattr(imports_routes, "build_providers", lambda google_key=None: [FailingProvider()])
    monkeypatch.setattr(
        pipeline.extractors,
        "extract_metadata",
        lambda path: LocalMetadata(
            title="Livro Teste",
            authors=["Autor Teste"],
            identifiers=[],
            language="pt",
            year=2020,
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )

    assert resp.status_code == 201
    payload = resp.json()
    assert payload["status"] == "ingested"
    assert payload["file_id"] > 0
    assert payload["edition_id"] > 0
    assert Path(payload["path"]).exists()
    assert calls["attempted"] is True


def test_upload_ingest_failure_rolls_back_and_cleans_file(temp_db, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(upload_dir))
    settings_cache.cache_clear()

    import mai.api.routes.imports as imports_routes

    def _raise(_: Path) -> LocalMetadata:
        raise RuntimeError("boom")

    monkeypatch.setattr(imports_routes, "build_providers", lambda google_key=None: [])
    monkeypatch.setattr(pipeline.extractors, "extract_metadata", _raise)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Falha ao ingerir upload"
    assert not list(upload_dir.glob("*"))

    with session_scope() as session:
        assert session.scalar(select(models.File.id).limit(1)) is None


def test_upload_commit_failure_rolls_back_and_cleans_file(temp_db, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(upload_dir))
    settings_cache.cache_clear()

    import sqlalchemy.orm.session as sa_session
    import mai.api.routes.imports as imports_routes

    original_commit = sa_session.Session.commit

    def _fail_commit(self: OrmSession) -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(imports_routes, "build_providers", lambda google_key=None: [])
    monkeypatch.setattr(
        pipeline.extractors,
        "extract_metadata",
        lambda path: LocalMetadata(
            title="Livro Teste",
            authors=["Autor Teste"],
            identifiers=[],
            language="pt",
            year=2020,
        ),
    )
    monkeypatch.setattr(sa_session.Session, "commit", _fail_commit)

    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )

    monkeypatch.setattr(sa_session.Session, "commit", original_commit)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Falha ao ingerir upload"
    assert not list(upload_dir.glob("*"))

    with session_scope() as session:
        assert session.scalar(select(models.File.id).limit(1)) is None


def test_upload_duplicate_sha256_does_not_refetch_metadata(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MAI_UPLOAD_DIR", str(tmp_path / "uploads"))
    settings_cache.cache_clear()

    calls: dict[str, object] = {"search_queries": []}

    class DummyProvider:
        slug = "dummy"

        def get_by_isbn(self, isbn13: str):
            return None

        def search(self, query: str):
            calls["search_queries"].append(query)
            return [
                Candidate(
                    source="dummy",
                    title="Livro Teste",
                    authors=["Autor Teste"],
                    year=2020,
                    publisher="Editora Teste",
                    language="pt",
                    ids={"ISBN13": "9781234567890"},
                    cover_url=None,
                    payload={},
                )
            ]

    import mai.api.routes.imports as imports_routes

    provider = DummyProvider()
    monkeypatch.setattr(imports_routes, "build_providers", lambda google_key=None: [provider])
    monkeypatch.setattr(
        pipeline.extractors,
        "extract_metadata",
        lambda path: LocalMetadata(
            title="Livro Teste",
            authors=["Autor Teste"],
            identifiers=[],
            language="pt",
            year=2020,
        ),
    )

    app = create_app()
    with TestClient(app) as client:
        first = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )
        second = client.post(
            "/import/upload",
            files={"file": ("livro.epub", b"conteudo", "application/epub+zip")},
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["file_id"] == second.json()["file_id"]
    assert first.json()["edition_id"] == second.json()["edition_id"]
    assert len(calls["search_queries"]) == 1
    assert Path(second.json()["path"]).exists()
