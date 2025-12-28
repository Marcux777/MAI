from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mai.ingest.service import is_watcher_running
from mai.tasks.queue import get_task_queue

router = APIRouter()


def _format_last_ingest(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@router.websocket("/ws/status")
async def status_socket(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            stats = get_task_queue().get_stats()
            payload = {
                "watcher": "running" if is_watcher_running() else "stopped",
                "queue": stats.pending,
                "running": stats.running,
                "last_ingest": _format_last_ingest(stats.last_finished_at),
            }
            await ws.send_json(payload)
            await asyncio.sleep(2)
    except WebSocketDisconnect:  # pragma: no cover
        return
