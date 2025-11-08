from __future__ import annotations

from typing import List, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload

from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.ingest.pipeline import (
    apply_candidate_to_edition,
    deserialize_ranked_candidates,
    record_identification,
    upsert_provider_hit,
)


def _candidate_to_dict(entry: dict) -> dict:
    candidate = entry["candidate"]
    return {
        "stage": entry["stage"],
        "provider": candidate.source,
        "score": float(entry["score"] or 0.0),
        "title": candidate.title,
        "authors": candidate.authors,
        "ids": candidate.ids,
        "publisher": candidate.publisher,
        "year": candidate.year,
        "language": candidate.language,
        "cover_url": candidate.cover_url,
    }


def list_pending_reviews(
    session: Session,
    min_score: float = 0.65,
    max_score: float = 0.84,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[int, List[dict]]:
    score_clause = and_(
        models.IdentifyResult.top_score >= min_score,
        models.IdentifyResult.top_score <= max_score,
    )

    total = session.scalar(
        select(func.count())
        .select_from(models.IdentifyResult)
        .where(models.IdentifyResult.auto_accepted.is_(False))
        .where(score_clause)
    ) or 0

    stmt = (
        select(models.IdentifyResult)
        .where(models.IdentifyResult.auto_accepted.is_(False))
        .where(score_clause)
        .options(
            selectinload(models.IdentifyResult.edition)
            .selectinload(models.Edition.work)
            .selectinload(models.Work.authors),
            selectinload(models.IdentifyResult.edition).selectinload(models.Edition.files),
        )
        .order_by(models.IdentifyResult.created_at.asc())
        .offset(offset)
        .limit(limit)
    )

    rows = session.scalars(stmt).unique().all()
    items: List[dict] = []
    for result in rows:
        edition = result.edition
        if not edition:
            continue
        ranked = deserialize_ranked_candidates(result.candidates_json or "[]")
        candidates = [_candidate_to_dict(entry) for entry in ranked]
        file_path = edition.files[0].path if edition.files else None
        work_title = edition.work.title if edition.work else (edition.title or "")
        items.append(
            {
                "edition_id": edition.id,
                "work_title": work_title,
                "edition_title": edition.title,
                "top_score": result.top_score,
                "file_path": file_path,
                "auto_accepted": result.auto_accepted,
                "candidates": candidates,
            }
        )
    return total, items


def resolve_review(
    session: Session,
    edition_id: int,
    candidate_index: int | None,
    reject: bool = False,
) -> Tuple[str, str | None]:
    identify = session.get(models.IdentifyResult, edition_id)
    if not identify:
        raise LookupError("Edição sem registro de identificação")
    edition = identify.edition or session.get(models.Edition, edition_id)
    if not edition:
        raise LookupError("Edição não encontrada")

    ranked = deserialize_ranked_candidates(identify.candidates_json or "[]")
    if reject:
        identify.auto_accepted = True
        identify.chosen_provider = None
        session.flush()
        return "rejected", None

    if candidate_index is None or candidate_index < 0 or candidate_index >= len(ranked):
        raise ValueError("candidate_index inválido")

    choice = ranked[candidate_index]
    candidate = choice["candidate"]
    score = float(choice["score"] or 0.0)

    apply_candidate_to_edition(session, edition, candidate)
    upsert_provider_hit(session, edition.id, candidate, score=score or 1.0)

    identify.auto_accepted = True
    identify.chosen_provider = candidate.source
    identify.top_score = score

    record_identification(session, edition.id, ranked, candidate, score)
    upsert_for_edition(session, edition.id)
    return "accepted", candidate.source
