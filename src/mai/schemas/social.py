from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class GoodreadsImportSummary(BaseModel):
    total: int
    matched: int
    matched_goodreads_id: int
    matched_isbn: int
    matched_title: int
    created: int
    updated: int
    read_status_updates: int
    rating_updates: int
    tag_updates: int
    identifier_updates: int
    skipped_no_title: int
    skipped_missing: int
    unchanged: int
    dry_run: bool


class GoodreadsImportResponse(BaseModel):
    status: str
    summary: GoodreadsImportSummary
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
