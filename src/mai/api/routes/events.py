from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mai.ingest.service import is_watcher_running

router = APIRouter()


@router.websocket("/ws/status")
async def status_socket(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            payload = {
                "watcher": "running" if is_watcher_running() else "stopped",
                "queue": random.randint(0, 5),
                "last_ingest": asyncio.get_event_loop().time(),
            }
            await ws.send_json(payload)
            await asyncio.sleep(2)
    except WebSocketDisconnect:  # pragma: no cover
        return
