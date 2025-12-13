from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from mai.db import models
from mai.db.session import session_scope
from mai.ingest.pipeline import ingest_file
from mai.ingest.types import Candidate


fitz = pytest.importorskip("fitz")


def _create_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_pdf_isbn_triggers_get_by_isbn_and_autofills_metadata(temp_db, tmp_path):
    isbn13 = "9780306406157"
    pdf_path = tmp_path / "sample.pdf"
    _create_pdf(pdf_path, f"ISBN: {isbn13}\n")

    class DummyProvider:
        slug = "dummy"

        def get_by_isbn(self, isbn: str):
            assert isbn == isbn13
            return Candidate(
                source="dummy",
                title="Título Remoto",
                authors=["Autor Remoto"],
                year=2020,
                publisher="Editora Remota",
                language="pt",
                ids={"ISBN13": isbn},
                cover_url=None,
                payload={},
            )

        def search(self, query: str):
            raise AssertionError("search() não deveria ser chamado quando ISBN está presente")

    with session_scope() as session:
        ingest_file(session, pdf_path, [DummyProvider()])

    with session_scope() as session:
        edition = session.scalar(select(models.Edition).limit(1))
        assert edition is not None
        assert edition.title == "Título Remoto"
        assert [a.name for a in edition.work.authors] == ["Autor Remoto"]

        identifier = session.scalar(
            select(models.Identifier).where(
                models.Identifier.edition_id == edition.id,
                models.Identifier.scheme == "ISBN13",
            )
        )
        assert identifier is not None
        assert identifier.value == isbn13

        identify = session.get(models.IdentifyResult, edition.id)
        assert identify is not None
        assert identify.auto_accepted is True
        assert identify.chosen_provider == "dummy"

