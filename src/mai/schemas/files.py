from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class AttachFileRequest(BaseModel):
    edition_id: int = Field(gt=0)
    file_id: Optional[int] = Field(default=None, gt=0)
    path: Optional[Path] = None

    @model_validator(mode="after")
    def _validate_choice(self) -> "AttachFileRequest":
        if not self.file_id and not self.path:
            raise ValueError("Informe file_id ou path para anexar o arquivo")
        return self


class AttachFileResponse(BaseModel):
    file_id: int
    edition_id: int
    path: str
