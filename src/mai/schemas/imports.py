from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class ImportRequest(BaseModel):
    paths: Optional[List[Path]] = Field(default=None, description="Lista de diretórios/arquivos")

    @validator("paths", each_item=True)
    def _must_exist(cls, value: Path) -> Path:  # pragma: no cover - validação simples
        return value


class ImportResponse(BaseModel):
    status: str
    paths: List[str]


class WatchRequest(BaseModel):
    paths: Optional[List[Path]] = None


class WatchResponse(BaseModel):
    status: str
    watching: bool
    paths: List[str]
