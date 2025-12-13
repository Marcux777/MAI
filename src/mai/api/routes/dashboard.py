from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

STATIC_ROOT = Path(__file__).resolve().parents[4] / "static"

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/organize", response_class=HTMLResponse)
def organize_dashboard() -> str:
    path = STATIC_ROOT / "organize_dashboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dashboard estático não disponível")
    return path.read_text(encoding="utf-8")
