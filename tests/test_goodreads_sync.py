from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select

from mai.db import models
from mai.db.session import session_scope
from mai.ingest.pipeline import isbn13 as to_isbn13
from mai.social.goodreads import GoodreadsSyncOptions, sync_goodreads_csv


def _write_goodreads_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Book Id",
        "Title",
        "Author",
        "Additional Authors",
        "ISBN",
        "ISBN13",
        "My Rating",
        "Publisher",
        "Number of Pages",
        "Year Published",
        "Bookshelves",
        "Exclusive Shelf",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _seed_book(title: str, author: str, isbn_value: str) -> int:
    with session_scope() as session:
        work = models.Work(title=title, sort_title=title.lower())
        session.add(work)
        session.flush()

        author_obj = models.Author(name=author)
        session.add(author_obj)
        session.flush()
        work.authors.append(author_obj)

        edition = models.Edition(work_id=work.id, title=title, read_status="unread")
        session.add(edition)
        session.flush()

        session.add(models.Identifier(edition_id=edition.id, scheme="ISBN13", value=isbn_value))
        return int(edition.id)


def test_goodreads_sync_updates_existing_and_creates_new(temp_db, tmp_path):
    existing_isbn = "9780441013593"
    _seed_book("Dune", "Frank Herbert", existing_isbn)

    csv_path = tmp_path / "goodreads.csv"
    _write_goodreads_csv(
        csv_path,
        [
            {
                "Book Id": "123",
                "Title": "Dune",
                "Author": "Frank Herbert",
                "ISBN13": existing_isbn,
                "My Rating": "5",
                "Bookshelves": "sci-fi, favorites",
                "Exclusive Shelf": "read",
            },
            {
                "Book Id": "999",
                "Title": "Neuromancer",
                "Author": "William Gibson",
                "ISBN": "0441569595",
                "Bookshelves": "cyberpunk",
                "Exclusive Shelf": "to-read",
            },
        ],
    )

    options = GoodreadsSyncOptions(
        create_missing=True,
        include_bookshelves=True,
        apply_tags=True,
        apply_rating=True,
        apply_read_status=True,
    )

    with session_scope() as session:
        result = sync_goodreads_csv(session, csv_path, options)

    assert result.total == 2
    assert result.created == 1
    assert result.matched == 1
    assert result.updated >= 1

    with session_scope() as session:
        existing = session.scalar(
            select(models.Edition)
            .join(models.Identifier)
            .where(models.Identifier.scheme == "ISBN13")
            .where(models.Identifier.value == existing_isbn)
        )
        assert existing is not None
        assert existing.read_status == "read"
        assert existing.rating == 5.0
        existing_tags = {tag.name for tag in existing.tags}
        assert "sci-fi" in existing_tags
        assert "favorites" in existing_tags

        new_isbn = to_isbn13("0441569595")
        new_edition = session.scalar(
            select(models.Edition)
            .join(models.Identifier)
            .where(models.Identifier.scheme == "ISBN13")
            .where(models.Identifier.value == new_isbn)
        )
        assert new_edition is not None
        assert new_edition.read_status == "unread"
        new_tags = {tag.name for tag in new_edition.tags}
        assert "to-read" in new_tags
        assert "cyberpunk" in new_tags

        goodreads_id = session.scalar(
            select(models.Identifier).where(
                models.Identifier.scheme == "GOODREADS",
                models.Identifier.value == "999",
            )
        )
        assert goodreads_id is not None


def test_goodreads_sync_can_skip_missing(temp_db, tmp_path):
    csv_path = tmp_path / "goodreads.csv"
    _write_goodreads_csv(
        csv_path,
        [
            {
                "Book Id": "111",
                "Title": "Unknown Book",
                "Author": "Unknown",
                "Exclusive Shelf": "read",
            }
        ],
    )

    options = GoodreadsSyncOptions(create_missing=False)

    with session_scope() as session:
        result = sync_goodreads_csv(session, csv_path, options)

    assert result.total == 1
    assert result.created == 0
    assert result.skipped_missing == 1
    with session_scope() as session:
        count = session.scalar(select(models.Edition.id))
        assert count is None
