from __future__ import annotations

import json

from sqlalchemy import select

from mai.db import models
from mai.db.session import session_scope
from mai.review.service import list_pending_reviews, resolve_review


def create_review_fixture(title: str = "Edição Local") -> int:
    with session_scope() as session:
        work = models.Work(title="Obra Local", sort_title="obra_local")
        session.add(work)
        session.flush()

        edition = models.Edition(
            work_id=work.id,
            title=title,
            format="PDF",
            language="pt",
            pub_year=2018,
        )
        session.add(edition)
        session.flush()

        author = models.Author(name="Autor Local")
        session.add(author)
        session.flush()
        work.authors.append(author)

        file_rec = models.File(
            edition_id=edition.id,
            path="/tmp/demo.pdf",
            ext="pdf",
            size_bytes=2048,
            sha256="cafebabe",
        )
        session.add(file_rec)

        candidates_json = json.dumps(
            [
                {
                    "stage": "search",
                    "provider": "openlibrary",
                    "score": 0.72,
                    "title": "Título Remoto",
                    "authors": ["Autor Remoto"],
                    "ids": {"OLID": "OL123"},
                    "publisher": "Editora X",
                    "year": 2021,
                    "language": "pt",
                    "cover_url": None,
                    "payload": {"id": "OL123"},
                }
            ],
            ensure_ascii=False,
        )

        identify = models.IdentifyResult(
            edition_id=edition.id,
            auto_accepted=False,
            chosen_provider=None,
            top_score=0.72,
            candidates_json=candidates_json,
        )
        session.add(identify)
        session.flush()
        return edition.id


def test_list_pending_reviews_returns_candidates(temp_db):
    edition_id = create_review_fixture()
    with session_scope() as session:
        total, items = list_pending_reviews(session)
        assert total == 1
        assert items[0]["edition_id"] == edition_id
        assert items[0]["candidates"][0]["provider"] == "openlibrary"
        assert items[0]["candidates"][0]["title"] == "Título Remoto"


def test_resolve_review_applies_candidate_metadata(temp_db):
    edition_id = create_review_fixture(title="Sem Metadados")
    with session_scope() as session:
        status, provider = resolve_review(session, edition_id, candidate_index=0)
        session.flush()
        assert status == "accepted"
        assert provider == "openlibrary"

        edition = session.get(models.Edition, edition_id)
        assert edition.title == "Título Remoto"
        assert edition.pub_year == 2021
        assert [a.name for a in edition.work.authors] == ["Autor Remoto"]

        identify = session.get(models.IdentifyResult, edition_id)
        assert identify.auto_accepted is True
        assert identify.chosen_provider == "openlibrary"

        hit = session.scalar(
            select(models.ProviderHit).where(models.ProviderHit.provider == "openlibrary", models.ProviderHit.edition_id == edition_id)
        )
        assert hit is not None


def test_resolve_review_rejects_candidate(temp_db):
    edition_id = create_review_fixture()
    with session_scope() as session:
        status, provider = resolve_review(session, edition_id, candidate_index=None, reject=True)
        session.flush()
        assert status == "rejected"
        assert provider is None
        result = session.get(models.IdentifyResult, edition_id)
        assert result.auto_accepted is True
