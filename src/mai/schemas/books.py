from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class FileSchema(BaseModel):
    id: int
    path: str
    mime: Optional[str]


class FileDetailSchema(FileSchema):
    size_bytes: Optional[int]
    sha256: Optional[str]
    added_at: Optional[datetime]


class IdentifierSchema(BaseModel):
    scheme: str
    value: str


class AuthorSchema(BaseModel):
    id: int
    name: str


class EditionSchema(BaseModel):
    id: int
    title: Optional[str]
    subtitle: Optional[str]
    publisher: Optional[str]
    pub_year: Optional[int]
    language: Optional[str]
    format: Optional[str]
    cover_url: Optional[str]


class BookListItem(BaseModel):
    edition: EditionSchema
    work_title: str
    authors: List[AuthorSchema]
    files: List[FileSchema]
    identifiers: List[IdentifierSchema]


class PaginatedBooks(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[BookListItem]


class ProviderHitSchema(BaseModel):
    id: int
    provider: str
    remote_id: Optional[str]
    score: Optional[float]
    fetched_at: Optional[datetime]


class MatchEventSchema(BaseModel):
    stage: str
    provider: str
    score: float
    accepted: bool
    created_at: Optional[datetime]


class WorkSchema(BaseModel):
    id: int
    title: str
    language: Optional[str]
    description: Optional[str]


class BookDetail(BaseModel):
    edition: EditionSchema
    work: Optional[WorkSchema]
    authors: List[AuthorSchema]
    identifiers: List[IdentifierSchema]
    files: List[FileDetailSchema]
    providers: List[ProviderHitSchema]
    history: List[MatchEventSchema]
