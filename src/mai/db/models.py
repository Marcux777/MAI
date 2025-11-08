from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class WorkAuthor(Base):
    __tablename__ = "work_author"

    work_id: Mapped[int] = mapped_column(ForeignKey("work.id", ondelete="CASCADE"), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String, default="author", primary_key=True)


class Work(Base):
    __tablename__ = "work"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    sort_title: Mapped[Optional[str]]
    language: Mapped[Optional[str]]
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    editions: Mapped[List["Edition"]] = relationship(back_populates="work")
    authors: Mapped[List["Author"]] = relationship(
        secondary="work_author",
        back_populates="works",
        viewonly=False,
    )


class Edition(Base):
    __tablename__ = "edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("work.id", ondelete="CASCADE"))
    title: Mapped[Optional[str]]
    subtitle: Mapped[Optional[str]]
    publisher: Mapped[Optional[str]]
    pub_year: Mapped[Optional[int]]
    pages: Mapped[Optional[int]]
    format: Mapped[Optional[str]]
    language: Mapped[Optional[str]]
    cover_path: Mapped[Optional[str]]
    cover_url: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    work: Mapped[Work] = relationship(back_populates="editions")
    files: Mapped[List["File"]] = relationship(back_populates="edition")
    identifiers: Mapped[List["Identifier"]] = relationship(back_populates="edition")
    tags: Mapped[List["Tag"]] = relationship(
        secondary="book_tag",
        back_populates="editions",
    )


class Author(Base):
    __tablename__ = "author"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    sort_name: Mapped[Optional[str]]

    works: Mapped[List[Work]] = relationship(
        secondary="work_author",
        back_populates="authors",
    )


class Identifier(Base):
    __tablename__ = "identifier"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id", ondelete="CASCADE"))
    scheme: Mapped[str]
    value: Mapped[str]

    edition: Mapped[Edition] = relationship(back_populates="identifiers")


class File(Base):
    __tablename__ = "file"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("edition.id", ondelete="SET NULL"))
    path: Mapped[str]
    ext: Mapped[Optional[str]]
    size_bytes: Mapped[Optional[int]]
    sha256: Mapped[Optional[str]]
    mime: Mapped[Optional[str]]
    drm: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)

    edition: Mapped[Optional[Edition]] = relationship(back_populates="files")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    editions: Mapped[List[Edition]] = relationship(
        secondary="book_tag",
        back_populates="tags",
    )


class BookTag(Base):
    __tablename__ = "book_tag"

    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class ProviderHit(Base):
    __tablename__ = "provider_hit"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str]
    remote_id: Mapped[Optional[str]]
    edition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("edition.id", ondelete="SET NULL"))
    payload_json: Mapped[str]
    score: Mapped[Optional[float]]
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    edition: Mapped[Optional[Edition]] = relationship()


class Series(Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    entries: Mapped[List["SeriesEntry"]] = relationship(back_populates="series")


class SeriesEntry(Base):
    __tablename__ = "series_entry"

    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("work.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[Optional[float]]

    series: Mapped[Series] = relationship(back_populates="entries")
    work: Mapped[Work] = relationship()


class Task(Base):
    __tablename__ = "task"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    payload_json: Mapped[Optional[str]]
    status: Mapped[str] = mapped_column(default="pending")
    result_json: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]]
    finished_at: Mapped[Optional[datetime]]


class IdentifyResult(Base):
    __tablename__ = "identify_result"

    edition_id: Mapped[int] = mapped_column(
        ForeignKey("edition.id", ondelete="CASCADE"), primary_key=True
    )
    auto_accepted: Mapped[bool]
    chosen_provider: Mapped[Optional[str]]
    top_score: Mapped[float]
    candidates_json: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    edition: Mapped[Edition] = relationship()


class MatchEvent(Base):
    __tablename__ = "match_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id", ondelete="CASCADE"))
    stage: Mapped[str]
    provider: Mapped[str]
    candidate_rank: Mapped[int]
    score: Mapped[float]
    accepted: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    edition: Mapped[Edition] = relationship()


class OrganizeManifest(Base):
    __tablename__ = "organize_manifest"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    template: Mapped[str]
    root: Mapped[str]
    status: Mapped[str] = mapped_column(default="preview")
    watcher_state: Mapped[Optional[str]]
    notes: Mapped[Optional[str]]

    operations: Mapped[List["OrganizeOp"]] = relationship(back_populates="manifest")


class OrganizeOp(Base):
    __tablename__ = "organize_op"

    id: Mapped[int] = mapped_column(primary_key=True)
    manifest_id: Mapped[int] = mapped_column(
        ForeignKey("organize_manifest.id", ondelete="CASCADE")
    )
    edition_id: Mapped[int] = mapped_column(ForeignKey("edition.id", ondelete="CASCADE"))
    src_path: Mapped[str]
    dst_path: Mapped[str]
    reason: Mapped[Optional[str]]
    status: Mapped[str] = mapped_column(default="planned")
    error: Mapped[Optional[str]]
    src_sha256: Mapped[Optional[str]]
    dst_sha256: Mapped[Optional[str]]

    manifest: Mapped[OrganizeManifest] = relationship(back_populates="operations")
    edition: Mapped[Edition] = relationship()
