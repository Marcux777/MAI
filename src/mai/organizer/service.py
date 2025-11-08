from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from mai.core.config import Settings
from mai.core.logging import logger
from mai.db import models
from mai.db.indexer import upsert_for_edition
from mai.ingest.service import start_watcher, stop_watcher
from mai.organizer.fs import safe_move
from mai.organizer.namer import SAFE_TEMPLATE, build_context, render_destination
from mai.utils.files import compute_sha256


@dataclass
class PreviewResult:
    manifest: models.OrganizeManifest
    summary: Dict[str, int]
    sample_ops: List[models.OrganizeOp]


def preview_manifest(
    session: Session,
    root: Path,
    template: Optional[str] = None,
    edition_ids: Optional[List[int]] = None,
    sample_limit: int = 100,
) -> PreviewResult:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    manifest = models.OrganizeManifest(template=template or SAFE_TEMPLATE, root=str(root), status="preview")
    session.add(manifest)
    session.flush()

    stmt = (
        select(models.File)
        .join(models.Edition)
        .where(models.File.edition_id.isnot(None))
        .options(
            selectinload(models.File.edition)
            .selectinload(models.Edition.work)
            .selectinload(models.Work.authors),
            selectinload(models.File.edition).selectinload(models.Edition.identifiers),
        )
    )
    if edition_ids:
        stmt = stmt.where(models.File.edition_id.in_(edition_ids))

    files = session.scalars(stmt).unique().all()

    summary = {"planned": 0, "skipped": 0}
    sample_ops: List[models.OrganizeOp] = []

    for file in files:
        edition = file.edition
        if not edition or not edition.work:
            status = "skipped"
            reason = "missing_work"
            dst_path = file.path
        else:
            ctx = build_context(edition, file)
            try:
                relative = render_destination(template or SAFE_TEMPLATE, ctx)
            except ValueError as exc:
                status = "skipped"
                reason = str(exc)
                dst_path = file.path
            else:
                dst_full = (root / relative).resolve()
                if dst_full == Path(file.path).resolve():
                    status = "skipped"
                    reason = "already_in_place"
                else:
                    status = "planned"
                    reason = None
                dst_path = str(dst_full)

        op = models.OrganizeOp(
            manifest_id=manifest.id,
            edition_id=file.edition_id,
            src_path=file.path,
            dst_path=dst_path,
            reason=reason,
            status=status,
            src_sha256=file.sha256,
        )
        session.add(op)

        summary[status] = summary.get(status, 0) + 1
        if len(sample_ops) < sample_limit:
            sample_ops.append(op)

    session.flush()

    logger.info(
        "Organize preview manifest=%s planned=%s skipped=%s",
        manifest.id,
        summary.get("planned", 0),
        summary.get("skipped", 0),
    )

    return PreviewResult(manifest=manifest, summary=summary, sample_ops=sample_ops)


def apply_manifest(
    session: Session,
    manifest_id: int,
    settings: Settings,
    statuses: Optional[List[str]] = None,
) -> Dict[str, int]:
    manifest = session.get(models.OrganizeManifest, manifest_id)
    if not manifest:
        raise ValueError(f"Manifesto {manifest_id} não encontrado")

    ops = (
        session.scalars(
            select(models.OrganizeOp)
            .where(models.OrganizeOp.manifest_id == manifest_id)
            .order_by(models.OrganizeOp.id)
        )
        .unique()
        .all()
    )

    manifest.status = "applying"
    session.flush()

    was_running = stop_watcher()
    manifest.watcher_state = "running" if was_running else "stopped"
    summary = {"done": 0, "failed": 0, "skipped": 0}
    allowed = set(statuses or ["planned", "failed"])

    for op in ops:
        if op.status == "skipped":
            summary["skipped"] += 1
            continue
        if op.status not in allowed:
            continue

        try:
            _apply_op(session, op)
            summary["done"] += 1
        except Exception as exc:  # pragma: no cover - logged for diagnostics
            op.status = "failed"
            op.error = str(exc)
            summary["failed"] += 1
            logger.exception("Falha ao aplicar operação %s: %s", op.id, exc)

    manifest.status = "applied" if summary["failed"] == 0 else "failed"
    session.flush()

    _restart_watcher(settings, was_running)
    return summary


def rollback_manifest(session: Session, manifest_id: int, settings: Settings) -> Dict[str, int]:
    manifest = session.get(models.OrganizeManifest, manifest_id)
    if not manifest:
        raise ValueError(f"Manifesto {manifest_id} não encontrado")

    ops = (
        session.scalars(
            select(models.OrganizeOp)
            .where(models.OrganizeOp.manifest_id == manifest_id)
            .order_by(models.OrganizeOp.id)
        )
        .unique()
        .all()
    )

    was_running = stop_watcher()
    summary = {"reverted": 0, "failed": 0}

    for op in ops:
        if op.status != "done":
            continue
        try:
            _rollback_op(session, op)
            summary["reverted"] += 1
        except Exception as exc:  # pragma: no cover
            op.status = "failed"
            op.error = str(exc)
            summary["failed"] += 1
            logger.exception("Falha ao reverter operação %s: %s", op.id, exc)

    manifest.status = "rolled_back" if summary["failed"] == 0 else "failed"
    session.flush()

    should_restart = was_running or (manifest.watcher_state == "running")
    _restart_watcher(settings, should_restart)
    return summary


def _apply_op(session: Session, op: models.OrganizeOp) -> None:
    src = Path(op.src_path)
    dst = Path(op.dst_path)
    if not src.exists():
        raise FileNotFoundError(f"Arquivo origem não encontrado: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst_hash = compute_sha256(dst)
        if op.src_sha256 and dst_hash == op.src_sha256:
            op.status = "skipped"
            op.reason = "duplicate_destination"
            return
        backup = dst.with_suffix(dst.suffix + f".mai.keep.{op.id}")
        os.replace(dst, backup)

    safe_move(src, dst)

    file_record = session.scalar(select(models.File).where(models.File.path == str(src)))
    if file_record is None:
        file_record = session.scalar(
            select(models.File)
            .where(models.File.edition_id == op.edition_id)
            .order_by(models.File.id)
        )
    if file_record:
        file_record.path = str(dst)
        file_record.last_seen = datetime.utcnow()

    op.status = "done"
    op.reason = None
    op.dst_sha256 = compute_sha256(dst)

    upsert_for_edition(session, op.edition_id)


def _rollback_op(session: Session, op: models.OrganizeOp) -> None:
    dst = Path(op.dst_path)
    src = Path(op.src_path)
    if not dst.exists():
        raise FileNotFoundError(f"Arquivo atual não encontrado: {dst}")

    safe_move(dst, src)

    file_record = session.scalar(select(models.File).where(models.File.path == str(op.dst_path)))
    if file_record is None:
        file_record = session.scalar(
            select(models.File)
            .where(models.File.edition_id == op.edition_id)
            .order_by(models.File.id)
        )
    if file_record:
        file_record.path = str(src)
        file_record.last_seen = datetime.utcnow()

    op.status = "reverted"
    op.reason = "rolled_back"
    upsert_for_edition(session, op.edition_id)


def _restart_watcher(settings: Settings, was_running: bool) -> None:
    if not was_running:
        return
    paths = [Path(p).resolve() for p in settings.watch_paths]
    if not paths:
        return
    start_watcher(paths, settings.google_books_key)


def load_manifest_details(
    session: Session,
    manifest_id: int,
    statuses: Optional[List[str]] = None,
    limit: int = 100,
    offset: int = 0,
):
    manifest = session.get(models.OrganizeManifest, manifest_id)
    if not manifest:
        raise ValueError(f"Manifesto {manifest_id} não encontrado")

    summary = dict(
        session.execute(
            select(models.OrganizeOp.status, func.count())
            .where(models.OrganizeOp.manifest_id == manifest_id)
            .group_by(models.OrganizeOp.status)
        ).all()
    )

    stmt = (
        select(models.OrganizeOp)
        .where(models.OrganizeOp.manifest_id == manifest_id)
        .order_by(models.OrganizeOp.id)
        .offset(offset)
        .limit(limit)
    )
    if statuses:
        stmt = stmt.where(models.OrganizeOp.status.in_(statuses))

    ops = session.scalars(stmt).unique().all()
    return manifest, summary, ops
