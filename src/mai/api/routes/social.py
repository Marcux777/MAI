from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.schemas.social import GoodreadsImportResponse, GoodreadsImportSummary
from mai.social.goodreads import GoodreadsSyncOptions, sync_goodreads_csv

router = APIRouter(prefix="/social", tags=["social"])


@router.post("/goodreads/import", response_model=GoodreadsImportResponse)
def import_goodreads(
    file: UploadFile = File(...),
    create_missing: bool = Query(default=True),
    apply_read_status: bool = Query(default=True),
    force_read_status: bool = Query(default=False),
    apply_rating: bool = Query(default=True),
    overwrite_rating: bool = Query(default=False),
    apply_tags: bool = Query(default=True),
    include_bookshelves: bool = Query(default=False),
    tag_prefix: str | None = Query(default=None),
    apply_identifiers: bool = Query(default=True),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> GoodreadsImportResponse:
    options = GoodreadsSyncOptions(
        create_missing=create_missing,
        apply_read_status=apply_read_status,
        force_read_status=force_read_status,
        apply_rating=apply_rating,
        overwrite_rating=overwrite_rating,
        apply_tags=apply_tags,
        include_bookshelves=include_bookshelves,
        tag_prefix=tag_prefix,
        apply_identifiers=apply_identifiers,
        dry_run=dry_run,
    )

    try:
        with io.TextIOWrapper(file.file, encoding="utf-8-sig") as handle:
            result = sync_goodreads_csv(db, handle, options)
    except (UnicodeDecodeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Falha ao ler CSV: {exc}")
    except Exception as exc:  # pragma: no cover - defensivo
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Falha ao importar Goodreads: {exc}")
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    if options.dry_run:
        db.rollback()
        status = "dry-run"
    else:
        db.commit()
        status = "imported"

    summary = GoodreadsImportSummary(**result.as_dict())
    return GoodreadsImportResponse(
        status=status,
        summary=summary,
        warnings=result.warnings,
        errors=result.errors,
    )
