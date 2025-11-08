from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def safe_move(src: Path, dst: Path) -> None:
    ensure_parent(dst)
    if src.resolve() == dst.resolve():
        return
    try:
        os.replace(src, dst)
    except OSError:
        tmp = dst.parent / f".{dst.name}.mai.tmp.{uuid4().hex}"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        os.remove(src)
