from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from mai.core.config import get_settings as settings_cache
from mai.db import models
from mai.db.session import session_scope
from mai.ingest.pipeline import ingest_file
from mai.ingest.types import Candidate


fitz = pytest.importorskip("fitz")


def _create_scanned_like_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()  # sem texto selecionável
    doc.save(path)
    doc.close()


def test_pdf_ocr_can_extract_isbn_and_autofill_metadata(temp_db, tmp_path, monkeypatch):
    isbn13 = "9780306406157"
    pdf_path = tmp_path / "scan.pdf"
    _create_scanned_like_pdf(pdf_path)

    monkeypatch.setenv("MAI_PDF_OCR_ENABLED", "true")
    settings_cache.cache_clear()

    import mai.ingest.extractors as extractors

    calls: dict[str, int] = {"ocr": 0}

    monkeypatch.setattr(extractors, "_tesseract_available", lambda: True)

    def _fake_ocr_page_text(*args, **kwargs) -> str:
        calls["ocr"] += 1
        return f"ISBN: {isbn13}\n"

    monkeypatch.setattr(extractors, "_ocr_pdf_page_text", _fake_ocr_page_text)

    class DummyProvider:
        slug = "dummy"

        def get_by_isbn(self, isbn: str):
            assert isbn == isbn13
            return Candidate(
                source="dummy",
                title="Título OCR",
                authors=["Autor OCR"],
                year=2021,
                publisher="Editora OCR",
                language="pt",
                ids={"ISBN13": isbn},
                cover_url=None,
                payload={},
            )

        def search(self, query: str):
            raise AssertionError("search() não deveria ser chamado quando ISBN está presente")

    with session_scope() as session:
        ingest_file(session, pdf_path, [DummyProvider()])

    assert calls["ocr"] >= 1

    with session_scope() as session:
        edition = session.scalar(select(models.Edition).limit(1))
        assert edition is not None
        assert edition.title == "Título OCR"
        assert [a.name for a in edition.work.authors] == ["Autor OCR"]

        identifier = session.scalar(
            select(models.Identifier).where(
                models.Identifier.edition_id == edition.id,
                models.Identifier.scheme == "ISBN13",
            )
        )
        assert identifier is not None
        assert identifier.value == isbn13

