from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict

from mai.db import models

SAFE_TEMPLATE = "{author_last}/{title}.{ext}"
INVALID_CHARS = re.compile(r"[<>:\\|?*]")
MULTI_SEP = re.compile(r"[\s_]+")


class SafeDict(dict):
    def __missing__(self, key):  # pragma: no cover - defensive
        return ""


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = INVALID_CHARS.sub("", value)
    value = value.replace("/", "-").replace("\\", "-")
    value = MULTI_SEP.sub("_", value.strip())
    value = value.strip("._")
    return value or "sem_nome"


def build_context(edition: models.Edition, file: models.File) -> Dict[str, str]:
    work = edition.work
    title = edition.title or (work.title if work else None) or Path(file.path).stem
    authors = work.authors if work else []
    primary_author = authors[0].name if authors else "Desconhecido"
    author_last = primary_author.split()[-1] if primary_author else "autor"
    identifiers = {identifier.scheme.upper(): identifier.value for identifier in edition.identifiers}
    isbn13 = identifiers.get("ISBN13", "")
    context = {
        "title": title,
        "author": primary_author,
        "author_last": author_last,
        "year": str(edition.pub_year or ""),
        "isbn13": isbn13,
        "format": (edition.format or (file.ext or "")).upper(),
        "ext": (file.ext or Path(file.path).suffix.lstrip(".")).lower(),
        "series": "",
        "series_index": "",
    }
    return context


def render_destination(template: str, context: Dict[str, str]) -> Path:
    if not template:
        template = SAFE_TEMPLATE
    rendered = template.format_map(SafeDict(context))
    parts = [slugify(part) for part in rendered.split("/") if part]
    if not parts:
        raise ValueError("template resultou em caminho vazio")
    return Path(*parts)
