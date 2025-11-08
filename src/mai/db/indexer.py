from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

DELETE_SQL = text(
    "INSERT INTO search(search, rowid, title, authors, series, publisher, tags)"
    " VALUES('delete', :edition_id, NULL, NULL, NULL, NULL, NULL)"
)

INSERT_SQL = text(
    """
    INSERT INTO search(rowid, title, authors, series, publisher, tags)
    SELECT
      e.id,
      COALESCE(NULLIF(e.title,''), w.title, ''),
      COALESCE((
        SELECT GROUP_CONCAT(DISTINCT a.name)
        FROM work_author wa
        JOIN author a ON a.id = wa.author_id
        WHERE wa.work_id = w.id
      ), ''),
      COALESCE((
        SELECT GROUP_CONCAT(DISTINCT s.name)
        FROM series_entry se
        JOIN series s ON s.id = se.series_id
        WHERE se.work_id = w.id
      ), ''),
      COALESCE(e.publisher, ''),
      COALESCE((
        SELECT GROUP_CONCAT(DISTINCT t.name)
        FROM book_tag bt
        JOIN tag t ON t.id = bt.tag_id
        WHERE bt.edition_id = e.id
      ), '')
    FROM edition e
    LEFT JOIN work w ON w.id = e.work_id
    WHERE e.id = :edition_id
    """
)


def upsert_for_edition(session: Session, edition_id: int) -> None:
    session.execute(DELETE_SQL, {"edition_id": edition_id})
    session.execute(INSERT_SQL, {"edition_id": edition_id})
