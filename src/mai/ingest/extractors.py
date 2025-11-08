from __future__ import annotations

from pathlib import Path
from typing import Optional

from mai.ingest.types import LocalMetadata

try:  # Optional dependency
    from ebooklib import epub
except ImportError:  # pragma: no cover - optional
    epub = None

try:  # Optional dependency
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional
    fitz = None

try:  # Optional dependency for MOBI/AZW
    from mobi import Mobi
except ImportError:  # pragma: no cover
    Mobi = None


def extract_metadata(path: Path) -> LocalMetadata:
    ext = path.suffix.lower()
    if ext == ".epub":
        return extract_epub_meta(path)
    if ext == ".pdf":
        return extract_pdf_meta(path)
    if ext in {".mobi", ".azw", ".azw3"}:
        return extract_mobi_meta(path)
    return LocalMetadata(title=path.stem)


def extract_epub_meta(path: Path) -> LocalMetadata:
    if epub is None:
        raise RuntimeError("ebooklib não instalado (pip install ebooklib)")
    book = epub.read_epub(str(path))

    def _first(ns: str, key: str) -> Optional[str]:
        values = book.get_metadata(ns, key)
        return values[0][0] if values else None

    title = _first("DC", "title")
    language = _first("DC", "language")
    authors = [value[0] for value in book.get_metadata("DC", "creator")]
    identifiers = [value[0] for value in book.get_metadata("DC", "identifier")]
    return LocalMetadata(title=title, authors=authors, identifiers=identifiers, language=language)


def extract_pdf_meta(path: Path) -> LocalMetadata:
    if fitz is None:
        raise RuntimeError("PyMuPDF não instalado (pip install pymupdf)")
    with fitz.open(path) as doc:
        info = doc.metadata or {}
    title = info.get("title")
    author = info.get("author")
    year = info.get("creationDate")
    return LocalMetadata(
        title=title,
        authors=[author] if author else [],
        identifiers=[],
        language=None,
        year=_year_from_date(year),
    )


def extract_mobi_meta(path: Path) -> LocalMetadata:
    if Mobi is None:  # optional dependency; fall back to filename-based metadata
        return LocalMetadata(title=path.stem)
    book = Mobi(str(path))
    book.parse()
    metadata = book.getmetadata() or {}
    title = metadata.get(b"Title")
    author = metadata.get(b"Author")
    identifier = metadata.get(b"ASIN")
    return LocalMetadata(
        title=title.decode("utf-8", errors="ignore") if isinstance(title, bytes) else title,
        authors=[author.decode("utf-8", errors="ignore")] if isinstance(author, bytes) else ([author] if author else []),
        identifiers=[identifier.decode("utf-8", errors="ignore")] if isinstance(identifier, bytes) else ([identifier] if identifier else []),
    )


def _year_from_date(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None
