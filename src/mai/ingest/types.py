from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LocalMetadata:
    title: Optional[str]
    authors: List[str] = field(default_factory=list)
    identifiers: List[str] = field(default_factory=list)
    language: Optional[str] = None
    year: Optional[int] = None


@dataclass
class Candidate:
    source: str
    title: Optional[str]
    authors: List[str]
    year: Optional[int]
    publisher: Optional[str]
    language: Optional[str]
    ids: Dict[str, Optional[str]]
    cover_url: Optional[str]
    payload: Dict
