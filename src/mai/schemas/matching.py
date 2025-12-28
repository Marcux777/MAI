from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CandidateInfo(BaseModel):
    stage: str
    provider: str
    score: float
    title: Optional[str]
    authors: List[str]
    ids: Dict[str, Optional[str]]
    publisher: Optional[str]
    year: Optional[int]
    pages: Optional[int] = None
    language: Optional[str]
    cover_url: Optional[str]
    categories: List[str] = Field(default_factory=list)
    series: Optional[str] = None
    series_position: Optional[float] = None
