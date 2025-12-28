from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class TaskItem(BaseModel):
    id: int
    kind: str
    label: str | None = None
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class TaskQueueResponse(BaseModel):
    total: int
    pending: int
    running: int
    items: list[TaskItem]
