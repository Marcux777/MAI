from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from mai.db import models
from mai.db.session import session_scope
from mai.ingest import pipeline
from mai.ingest.types import Candidate, LocalMetadata
from mai.utils.files import compute_sha256


def test_persist_stores_author_identifiers(temp_db, tmp_path):
    path = Path(tmp_path) / "livro.epub"
    path.write_bytes(b"conteudo")
    sha256 = compute_sha256(path)

    local = LocalMetadata(
        title="Livro Local",
        authors=["Alice Example"],
        identifiers=[],
        language="en",
        year=2020,
    )
    candidate = Candidate(
        source="bookbrainz",
        title="Livro Externo",
        authors=["Alice Example"],
        year=2020,
        publisher="Editora",
        language="en",
        ids={"BBID": "bbid-123"},
        cover_url=None,
        payload={},
        author_ids={"Alice Example": {"MBID": "mbid-123"}},
    )

    with session_scope() as session:
        pipeline.persist(session, path, sha256, local, candidate, [], 1.0)
        author = session.scalar(select(models.Author).where(models.Author.name == "Alice Example"))
        assert author is not None
        identifier = session.scalar(
            select(models.AuthorIdentifier).where(models.AuthorIdentifier.author_id == author.id)
        )
        assert identifier is not None
        assert identifier.scheme == "MBID"
        assert identifier.value == "mbid-123"
