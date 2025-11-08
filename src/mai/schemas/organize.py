from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class OrganizePreviewIn(BaseModel):
    root: Optional[Path] = Field(default=None, description="Diretório base para organizar arquivos")
    template: Optional[str] = Field(default=None, description="Template de path")
    edition_ids: Optional[List[int]] = Field(default=None, description="IDs específicos de edição")


class OrganizeOpOut(BaseModel):
    id: int
    edition_id: int
    src_path: str
    dst_path: str
    status: Literal['planned', 'skipped']
    reason: Optional[str] = None


class OrganizePreviewOut(BaseModel):
    manifest_id: int
    summary: dict
    ops: List[OrganizeOpOut]


class OrganizeActionOut(BaseModel):
    manifest_id: int
    status: str
    summary: dict


class OrganizeApplyIn(BaseModel):
    statuses: Optional[List[str]] = None


class OrganizeManifestDetail(BaseModel):
    manifest_id: int
    status: str
    template: str
    root: str
    summary: dict
    ops: List[OrganizeOpOut]
