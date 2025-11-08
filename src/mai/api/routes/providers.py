from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.core.config import get_settings
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.ingest.pipeline import (
    ACCEPT_THRESHOLD,
    apply_candidate_to_edition,
    build_providers,
    build_local_metadata_from_edition,
    record_identification,
    reconcile,
    score_candidates,
    search_providers,
    upsert_provider_hit,
)
from mai.ingest.providers import Provider
from mai.schemas.matching import CandidateInfo
from mai.schemas.providers import ProviderFetchRequest, ProviderFetchResponse

router = APIRouter(prefix="/providers", tags=["providers"])


@router.post("/fetch", response_model=ProviderFetchResponse)
def fetch(body: ProviderFetchRequest, db: Session = Depends(get_db)) -> ProviderFetchResponse:
    edition = db.get(models.Edition, body.edition_id)
    if not edition:
        raise HTTPException(status_code=404, detail="Edição não encontrada")

    settings = get_settings()
    providers = build_providers(settings.google_books_key)
    providers = _filter_providers(providers, body.providers)
    if not providers:
        raise HTTPException(status_code=400, detail="Nenhum provedor selecionado")

    local = build_local_metadata_from_edition(edition)
    hits = search_providers(local, providers)
    scored = score_candidates(local, hits)
    candidate, top_score, ranked = reconcile(scored)

    auto_applied = bool(body.auto_apply and candidate and top_score >= ACCEPT_THRESHOLD)
    if auto_applied and candidate:
        apply_candidate_to_edition(db, edition, candidate)
        upsert_provider_hit(db, edition.id, candidate, score=top_score or 1.0)
        upsert_for_edition(db, edition.id)

    record_identification(db, edition.id, ranked, candidate if auto_applied else None, top_score)
    db.commit()

    candidates = [
        CandidateInfo(
            stage=item["stage"],
            provider=item["candidate"].source,
            score=float(item["score"] or 0.0),
            title=item["candidate"].title,
            authors=item["candidate"].authors,
            ids=item["candidate"].ids,
            publisher=item["candidate"].publisher,
            year=item["candidate"].year,
            language=item["candidate"].language,
            cover_url=item["candidate"].cover_url,
        )
        for item in ranked
    ]

    return ProviderFetchResponse(
        edition_id=edition.id,
        auto_applied=auto_applied,
        top_score=top_score,
        candidates=candidates,
    )


def _filter_providers(providers: list[Provider], allowed: list[str] | None) -> list[Provider]:
    if not allowed:
        return providers
    allowed_set = {name.lower() for name in allowed}
    filtered: list[Provider] = []
    for provider in providers:
        slug = getattr(provider, "slug", provider.__class__.__name__.lower())
        if slug.lower() in allowed_set:
            filtered.append(provider)
    return filtered
