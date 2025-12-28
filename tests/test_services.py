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
        tags=["fantasy", "python"],
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


def test_save_detail_updates_tags_and_fts(temp_db):
    edition_id = create_sample_data()
    service = LibraryService()
    detail = EditionDetail(
        edition_id=edition_id,
        title="Nova Edição",
        subtitle="",
        authors=["Joana Lima"],
        tags=["fantasy"],
        year=2022,
        language="pt",
        description=None,
    )
    service.save_detail(detail)

    rows = service.list_books(query="fantasy", limit=50)
    assert len(rows) == 1
    assert rows[0].edition_id == edition_id
    assert "fantasy" in rows[0].tags.lower()


def _create_stats_data():
    with session_scope() as session:
        work1 = models.Work(title="Livro A", sort_title="livro_a")
        work2 = models.Work(title="Livro B", sort_title="livro_b")
        work3 = models.Work(title="Livro C", sort_title="livro_c")
        session.add_all([work1, work2, work3])
        session.flush()

        edition1 = models.Edition(
            work_id=work1.id,
            title="Livro A (EPUB)",
            format="EPUB",
            pub_year=2001,
        )
        edition2 = models.Edition(
            work_id=work2.id,
            title="Livro B (PDF)",
            format="PDF",
            pub_year=2010,
        )
        edition3 = models.Edition(
            work_id=work3.id,
            title="Livro C (sem ano)",
            format=None,
            pub_year=None,
        )
        session.add_all([edition1, edition2, edition3])
        session.flush()

        author1 = models.Author(name="Autor Um")
        author2 = models.Author(name="Autor Dois")
        author3 = models.Author(name="Autor Tres")
        session.add_all([author1, author2, author3])
        session.flush()
        work1.authors.append(author1)
        work2.authors.append(author2)
        work3.authors.append(author3)

        tag1 = models.Tag(name="Ficcao")
        tag2 = models.Tag(name="Fantasia")
        tag3 = models.Tag(name="Nao-ficcao")
        session.add_all([tag1, tag2, tag3])
        session.flush()
        edition1.tags.extend([tag1, tag2])
        edition2.tags.append(tag3)
        edition3.tags.append(tag1)

        session.add_all(
            [
                models.File(edition_id=edition1.id, path="/tmp/a.epub", ext="epub", size_bytes=100),
                models.File(edition_id=edition2.id, path="/tmp/b.pdf", ext="pdf", size_bytes=200),
                models.File(edition_id=edition3.id, path="/tmp/c.unknown", ext=None, size_bytes=300),
            ]
        )
        session.flush()


def test_get_library_stats_returns_counts(temp_db):
    _create_stats_data()
    service = LibraryService()
    stats = service.get_library_stats()

    assert stats.work_count == 3
    assert stats.edition_count == 3
    assert stats.file_count == 3
    assert stats.author_count == 3
    assert stats.format_count == 2
    assert stats.missing_year_count == 1

    tag_counts = {item.label: item.count for item in stats.tag_counts}
    assert tag_counts["Ficcao"] == 2
    assert tag_counts["Fantasia"] == 1
    assert tag_counts["Nao-ficcao"] == 1

    year_counts = {item.year: item.count for item in stats.year_counts}
    assert year_counts[2001] == 1
    assert year_counts[2010] == 1
