from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .matching import CandidateInfo


class ProviderFetchRequest(BaseModel):
    edition_id: int = Field(gt=0)
    providers: Optional[List[str]] = None
    auto_apply: bool = True


class ProviderFetchResponse(BaseModel):
    edition_id: int
    auto_applied: bool
    top_score: float
    candidates: List[CandidateInfo]
