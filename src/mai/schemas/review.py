from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from .matching import CandidateInfo


class ReviewQueueItem(BaseModel):
    edition_id: int
    work_title: str
    edition_title: Optional[str]
    top_score: float
    file_path: Optional[str]
    auto_accepted: bool
    candidates: List[CandidateInfo]


class ReviewQueue(BaseModel):
    total: int
    items: List[ReviewQueueItem]


class ReviewResolveRequest(BaseModel):
    edition_id: int = Field(gt=0)
    candidate_index: Optional[int] = Field(default=None, ge=0)
    reject: bool = False

    @model_validator(mode="after")
    def _ensure_choice(self) -> "ReviewResolveRequest":
        if not self.reject and self.candidate_index is None:
            raise ValueError("candidate_index é obrigatório quando reject=False")
        return self


class ReviewResolveResponse(BaseModel):
    edition_id: int
    status: str
    provider: Optional[str]
