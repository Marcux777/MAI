from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mai.api.dependencies import get_db
from mai.db import models
from mai.schemas.tasks import TaskItem, TaskQueueResponse
from mai.tasks.queue import TaskQueue

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=TaskQueueResponse)
def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> TaskQueueResponse:
    stmt = select(models.Task).order_by(models.Task.id.desc())
    count_stmt = select(func.count()).select_from(models.Task)
    if status:
        stmt = stmt.where(models.Task.status == status)
        count_stmt = count_stmt.where(models.Task.status == status)
    if kind:
        stmt = stmt.where(models.Task.kind == kind)
        count_stmt = count_stmt.where(models.Task.kind == kind)

    total = db.scalar(count_stmt) or 0
    tasks = db.scalars(stmt.limit(limit).offset(offset)).all()

    pending = (
        db.scalar(select(func.count()).select_from(models.Task).where(models.Task.status == "pending"))
        or 0
    )
    running = (
        db.scalar(select(func.count()).select_from(models.Task).where(models.Task.status == "running"))
        or 0
    )

    items = [
        TaskItem(
            id=task.id,
            kind=task.kind,
            label=TaskQueue.get_label(task.kind),
            status=task.status,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            payload=_safe_json_loads(task.payload_json),
            result=_safe_json_loads(task.result_json),
        )
        for task in tasks
    ]

    return TaskQueueResponse(total=total, pending=pending, running=running, items=items)


@router.get("/tasks/{task_id}", response_model=TaskItem)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskItem:
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task não encontrada")
    return TaskItem(
        id=task.id,
        kind=task.kind,
        label=TaskQueue.get_label(task.kind),
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        payload=_safe_json_loads(task.payload_json),
        result=_safe_json_loads(task.result_json),
    )


def _safe_json_loads(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None
