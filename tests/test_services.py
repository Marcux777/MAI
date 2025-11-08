from __future__ import annotations

import os

from mai.db import models
from mai.db.session import session_scope
from mai.core.config import get_settings
from mai_qt.services import LibraryService, EditionDetail


def create_sample_data():
    with session_scope() as session:
        work = models.Work(title="Obra Original", sort_title="obra_original")
        session.add(work)
        session.flush()

        edition = models.Edition(
            work_id=work.id,
            title="Edição Original",
            format="EPUB",
            language="pt",
            pub_year=2020,
        )
        session.add(edition)
        session.flush()

        author = models.Author(name="Ana Becker")
        session.add(author)
        session.flush()
        work.authors.append(author)

        identifier = models.Identifier(edition_id=edition.id, scheme="ISBN13", value="9781234567890")
        session.add(identifier)

        file_rec = models.File(
            edition_id=edition.id,
            path="/tmp/demo.epub",
            ext="epub",
            size_bytes=1024,
            sha256="deadbeef",
        )
        session.add(file_rec)

        hit = models.ProviderHit(
            provider="openlibrary",
            remote_id="OL123",
            edition_id=edition.id,
            payload_json="{}",
            score=0.9,
        )
        session.add(hit)

        event = models.MatchEvent(
            edition_id=edition.id,
            stage="search",
            provider="openlibrary",
            candidate_rank=1,
            score=0.9,
            accepted=True,
        )
        session.add(event)
        session.flush()
        return edition.id


def test_get_detail_returns_related_data(temp_db):
    edition_id = create_sample_data()
    service = LibraryService()
    detail = service.get_detail(edition_id)
    assert detail is not None
    assert detail.title == "Edição Original"
    assert detail.authors == ["Ana Becker"]
    assert detail.identifiers[0].scheme == "ISBN13"
    assert detail.files[0].path == "/tmp/demo.epub"
    assert detail.providers[0].provider == "openlibrary"
    assert detail.history[0].stage == "search"


def test_save_detail_updates_metadata(temp_db):
    edition_id = create_sample_data()
    service = LibraryService()
    detail = EditionDetail(
        edition_id=edition_id,
        title="Nova Edição",
        subtitle="Sub",
        authors=["Joana Lima"],
        year=2022,
        language="en",
        description="Atualizado",
    )
    service.save_detail(detail)
    with session_scope() as session:
        edition = session.get(models.Edition, edition_id)
        assert edition.title == "Nova Edição"
        assert edition.pub_year == 2022
        assert edition.language == "en"
        work = edition.work
        assert [a.name for a in work.authors] == ["Joana Lima"]
