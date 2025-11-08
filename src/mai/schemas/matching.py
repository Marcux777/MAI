from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class CandidateInfo(BaseModel):
    stage: str
    provider: str
    score: float
    title: Optional[str]
    authors: List[str]
    ids: Dict[str, Optional[str]]
    publisher: Optional[str]
    year: Optional[int]
    language: Optional[str]
    cover_url: Optional[str]
