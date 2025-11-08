from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.core.config import get_settings
from mai.db import models
from mai.organizer.service import (
    preview_manifest,
    apply_manifest,
    rollback_manifest,
    load_manifest_details,
)
from mai.schemas.organize import (
    OrganizePreviewIn,
    OrganizePreviewOut,
    OrganizeOpOut,
    OrganizeActionOut,
    OrganizeApplyIn,
    OrganizeManifestDetail,
)

router = APIRouter(prefix="/organize", tags=["organize"])


@router.post("/preview", response_model=OrganizePreviewOut)
def preview(body: OrganizePreviewIn, db: Session = Depends(get_db)) -> OrganizePreviewOut:
    settings = get_settings()
    root = body.root or (settings.watch_paths[0] if settings.watch_paths else Path.cwd())
    template = body.template or settings.organizer_template
    result = preview_manifest(
        session=db,
        root=Path(root),
        template=template,
        edition_ids=body.edition_ids,
        sample_limit=100,
    )
    db.commit()

    ops = [
        OrganizeOpOut(
            id=op.id,
            edition_id=op.edition_id,
            src_path=op.src_path,
            dst_path=op.dst_path,
            status=op.status,  # type: ignore[arg-type]
            reason=op.reason,
        )
        for op in result.sample_ops
    ]

    return OrganizePreviewOut(
        manifest_id=result.manifest.id,
        summary=result.summary,
        ops=ops,
    )


@router.post("/apply/{manifest_id}", response_model=OrganizeActionOut)
def apply(
    manifest_id: int,
    body: OrganizeApplyIn | None = None,
    db: Session = Depends(get_db),
) -> OrganizeActionOut:
    settings = get_settings()
    try:
        summary = apply_manifest(db, manifest_id, settings, statuses=body.statuses if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.commit()
    manifest = db.get(models.OrganizeManifest, manifest_id)
    return OrganizeActionOut(manifest_id=manifest_id, status=manifest.status, summary=summary)


@router.post("/rollback/{manifest_id}", response_model=OrganizeActionOut)
def rollback(manifest_id: int, db: Session = Depends(get_db)) -> OrganizeActionOut:
    settings = get_settings()
    try:
        summary = rollback_manifest(db, manifest_id, settings)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    db.commit()
    manifest = db.get(models.OrganizeManifest, manifest_id)
    return OrganizeActionOut(manifest_id=manifest_id, status=manifest.status, summary=summary)


@router.get("/{manifest_id}", response_model=OrganizeManifestDetail)
def detail(
    manifest_id: int,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> OrganizeManifestDetail:
    try:
        manifest, summary, ops = load_manifest_details(
            db, manifest_id, statuses=[status] if status else None, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    op_items = [
        OrganizeOpOut(
            id=op.id,
            edition_id=op.edition_id,
            src_path=op.src_path,
            dst_path=op.dst_path,
            status=op.status,  # type: ignore[arg-type]
            reason=op.reason,
        )
        for op in ops
    ]

    return OrganizeManifestDetail(
        manifest_id=manifest.id,
        status=manifest.status,
        template=manifest.template,
        root=manifest.root,
        summary=summary,
        ops=op_items,
    )
