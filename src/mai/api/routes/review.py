from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.review.service import list_pending_reviews, resolve_review
from mai.schemas.matching import CandidateInfo
from mai.schemas.review import ReviewQueue, ReviewQueueItem, ReviewResolveRequest, ReviewResolveResponse

router = APIRouter(tags=["review"])


@router.get("/review-pending", response_model=ReviewQueue)
def review_pending(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_score: float = Query(default=0.65, ge=0.0, le=1.0),
    max_score: float = Query(default=0.84, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> ReviewQueue:
    total, items = list_pending_reviews(db, min_score=min_score, max_score=max_score, limit=limit, offset=offset)
    queue_items = [
        ReviewQueueItem(
            edition_id=item["edition_id"],
            work_title=item["work_title"],
            edition_title=item["edition_title"],
            top_score=item["top_score"],
            file_path=item["file_path"],
            auto_accepted=item["auto_accepted"],
            candidates=[CandidateInfo(**candidate) for candidate in item["candidates"]],
        )
        for item in items
    ]
    return ReviewQueue(total=total, items=queue_items)


@router.post("/review/resolve", response_model=ReviewResolveResponse)
def review_resolve(body: ReviewResolveRequest, db: Session = Depends(get_db)) -> ReviewResolveResponse:
    try:
        status, provider = resolve_review(db, body.edition_id, body.candidate_index, body.reject)
        db.commit()
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return ReviewResolveResponse(edition_id=body.edition_id, status=status, provider=provider)
