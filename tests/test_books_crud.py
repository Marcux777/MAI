from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from mai.api.routes import books as books_routes
from mai.api.routes import files as files_routes
from mai.db import models
from mai.db.session import session_scope
from mai.schemas.books import BookUpdateRequest


def _create_book(*, title: str, sha256: str, path: Path) -> tuple[int, int, int]:
    with session_scope() as session:
        work = models.Work(title=title, sort_title=title.lower())
        session.add(work)
        session.flush()

        edition = models.Edition(work_id=work.id, title=title, format="epub", language="pt", pub_year=2020)
        session.add(edition)
        session.flush()

        author = models.Author(name="Autor Original")
        session.add(author)
        session.flush()
        work.authors.append(author)

        file_rec = models.File(
            edition_id=edition.id,
            path=str(path),
            ext="epub",
            size_bytes=1,
            sha256=sha256,
        )
        session.add(file_rec)
        session.flush()

        return int(work.id), int(edition.id), int(file_rec.id)


def test_patch_book_updates_metadata_and_search(temp_db, tmp_path):
    _, edition_id, _ = _create_book(title="Original", sha256="a" * 64, path=tmp_path / "a.epub")

    with session_scope() as session:
        detail = books_routes.update_book(
            edition_id,
            BookUpdateRequest(
                title="Novo Título",
                authors=["Ana", "Bruno"],
                tags=["python", "ebook"],
                description="Desc",
                rating=4.0,
                read_status="read",
            ),
            db=session,
        )
        assert detail.edition.title == "Novo Título"
        assert detail.edition.rating == 4.0
        assert detail.edition.read_status == "read"
        assert [a.name for a in detail.authors] == ["Ana", "Bruno"]
        assert sorted(detail.tags) == ["ebook", "python"]
        assert detail.work and detail.work.description == "Desc"

        # Tag deve estar indexada no FTS via upsert_for_edition (não depende de trigger do SQLite)
        search = books_routes.list_books(
            q="python",
            author=None,
            tag=None,
            language=None,
            year=None,
            limit=10,
            offset=0,
            db=session,
        )
        assert search.total == 1
        assert search.items[0].edition.id == edition_id


def test_patch_book_rejects_identifier_conflict(temp_db, tmp_path):
    _, edition_a, _ = _create_book(title="A", sha256="b" * 64, path=tmp_path / "b.epub")
    _, edition_b, _ = _create_book(title="B", sha256="c" * 64, path=tmp_path / "c.epub")

    with session_scope() as session:
        session.add(models.Identifier(edition_id=edition_a, scheme="ISBN13", value="9781234567890"))

    with session_scope() as session:
        try:
            books_routes.update_book(
                edition_b,
                BookUpdateRequest(identifiers=[{"scheme": "ISBN13", "value": "9781234567890"}]),
                db=session,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
        else:  # pragma: no cover
            raise AssertionError("Esperava conflito de identificador (409)")


def test_delete_book_removes_edition_and_files(temp_db, tmp_path):
    work_id, edition_id, file_id = _create_book(title="Del", sha256="d" * 64, path=tmp_path / "d.epub")

    with session_scope() as session:
        payload = books_routes.delete_book(edition_id, delete_files=True, delete_disk=False, db=session)
        assert payload.status == "deleted"
        assert payload.edition_id == edition_id
        assert payload.deleted_files == 1
        try:
            books_routes.get_book_detail(edition_id, db=session)
        except HTTPException as exc:
            assert exc.status_code == 404

    with session_scope() as session:
        assert session.get(models.File, file_id) is None
        assert session.get(models.Edition, edition_id) is None
        assert session.get(models.Work, work_id) is None


def test_delete_file_can_remove_from_disk(temp_db, tmp_path):
    path = tmp_path / "disk.epub"
    path.write_bytes(b"demo")
    _, _, file_id = _create_book(title="Disk", sha256="e" * 64, path=path)

    with session_scope() as session:
        payload = files_routes.delete_file(file_id, delete_disk=True, db=session)
        assert payload.status == "deleted"
        assert payload.file_id == file_id
        assert payload.deleted_disk is True

    assert not path.exists()

    with session_scope() as session:
        assert session.scalar(select(models.File.id).where(models.File.id == file_id)) is None
