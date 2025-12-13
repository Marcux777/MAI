from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from mai.core.config import get_settings
from mai.core.logging import logger
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


_ISBN_TOKEN_RE = re.compile(
    r"(?i)\bisbn(?:-1[03])?\s*[:：]?\s*([0-9Xx][0-9Xx \t-]{8,20}[0-9Xx])"
)
_ISBN13_BARE_RE = re.compile(r"\b97[89][0-9 \t-]{10,17}[0-9]\b")

_PDF_BAD_TITLE_SUFFIX_RE = re.compile(r"(?i)\.(qxd|docx?|indd|pptx?|xlsx?|ps)$")
_PDF_EDITION_LINE_RE = re.compile(r"(?i)\b(ed[ií][cç][aã]o|edition|ed\.)\b")


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
    settings = get_settings()
    with fitz.open(path) as doc:
        info = doc.metadata or {}
        inferred_title, inferred_authors = _infer_pdf_title_and_authors(doc)
        identifiers = _extract_isbn_tokens_from_pdf(
            doc,
            info,
            ocr_enabled=bool(settings.pdf_ocr_enabled),
            ocr_lang=settings.pdf_ocr_lang,
            ocr_max_pages=int(settings.pdf_ocr_max_pages),
            ocr_dpi=int(settings.pdf_ocr_dpi),
            ocr_timeout_seconds=float(settings.pdf_ocr_timeout_seconds),
            ocr_trigger_text_chars=int(settings.pdf_ocr_trigger_text_chars),
        )
    title = info.get("title")
    author = info.get("author")
    year = info.get("creationDate")

    resolved_title = _choose_pdf_title(title, inferred_title, path)
    resolved_authors = _choose_pdf_authors(author, inferred_authors)
    return LocalMetadata(
        title=resolved_title,
        authors=resolved_authors,
        identifiers=identifiers,
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


def _choose_pdf_title(title: Optional[str], inferred_title: Optional[str], path: Path) -> Optional[str]:
    candidate = (title or "").strip()
    if candidate and not _is_suspicious_pdf_title(candidate):
        return candidate
    if inferred_title and inferred_title.strip():
        return inferred_title.strip()
    fallback = _filename_hint(path)
    return fallback or (candidate or None)


def _choose_pdf_authors(author: Optional[str], inferred_authors: list[str]) -> list[str]:
    candidate = (author or "").strip()
    if candidate and not _is_suspicious_pdf_author(candidate):
        return [candidate]
    if inferred_authors:
        return inferred_authors
    return [candidate] if candidate else []


def _is_suspicious_pdf_title(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if _PDF_BAD_TITLE_SUFFIX_RE.search(v):
        return True
    if "_" in v and " " not in v:
        return True
    return False


def _is_suspicious_pdf_author(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    if " " not in v and len(v) <= 3:
        return True
    if v.islower() and len(v) <= 6:
        return True
    return False


def _filename_hint(path: Path) -> str:
    stem = path.stem
    match = re.match(r"^[0-9a-f]{32}_(.+)$", stem, flags=re.IGNORECASE)
    if match:
        stem = match.group(1)
    stem = stem.replace("_", " ").replace("-", " ")
    return " ".join(stem.split())


def _infer_pdf_title_and_authors(doc) -> tuple[Optional[str], list[str]]:
    if fitz is None:
        return None, []
    try:
        page = doc.load_page(0)
        text = page.get_text() or ""
    except Exception:  # pragma: no cover - best-effort
        return None, []

    raw_lines = [line.replace("\u00a0", " ").strip() for line in text.splitlines()]
    raw_lines = [line for line in raw_lines if line]
    if not raw_lines:
        return None, []

    author_line = _find_pdf_author_line(raw_lines)
    authors = _parse_pdf_authors(author_line) if author_line else []

    title_lines: list[str] = []
    for line in raw_lines[:10]:
        normalized_line = " ".join(line.split())
        if author_line and line == author_line:
            break
        if _PDF_EDITION_LINE_RE.search(normalized_line):
            continue
        if _ISBN_TOKEN_RE.search(normalized_line) or _ISBN13_BARE_RE.search(normalized_line):
            continue
        title_lines.append(normalized_line)
        if len(title_lines) >= 3:
            break

    title = _join_title_lines(title_lines)
    return title, authors


def _find_pdf_author_line(lines: list[str]) -> Optional[str]:
    for line in lines[:20]:
        parts = [p.strip() for p in re.split(r"\s{2,}|\t+", line) if p.strip()]
        if len(parts) >= 2 and all(any(ch.isalpha() for ch in part) for part in parts):
            return line
    return None


def _parse_pdf_authors(line: str) -> list[str]:
    if not line:
        return []
    parts = [p.strip() for p in re.split(r"\s{2,}|\t+", line) if p.strip()]
    cleaned: list[str] = []
    for part in parts:
        part = " ".join(part.split()).strip(" ,;")
        if not part or len(part) < 3:
            continue
        cleaned.append(part)
    return _dedupe_preserve_order(cleaned)


def _join_title_lines(lines: list[str]) -> Optional[str]:
    parts = [line.strip(" -–—") for line in lines if line.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][:180]
    title = f"{parts[0]}: {' '.join(parts[1:])}"
    return title[:180]


def _extract_isbn_tokens_from_pdf(
    doc,
    info: dict,
    *,
    ocr_enabled: bool,
    ocr_lang: str,
    ocr_max_pages: int,
    ocr_dpi: int,
    ocr_timeout_seconds: float,
    ocr_trigger_text_chars: int,
) -> list[str]:
    tokens: list[str] = []
    for key in ("subject", "keywords", "title"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            tokens.extend(_extract_isbn_tokens(value))

    if tokens:
        return _dedupe_preserve_order(tokens)

    max_pages = min(3, int(getattr(doc, "page_count", 0) or 0))
    text_chars = 0
    for page_index in range(max_pages):
        try:
            page = doc.load_page(page_index)
            text = page.get_text() or ""
        except Exception:  # pragma: no cover - best-effort
            continue
        if not text:
            continue
        text_chars += _count_alnum(text)
        tokens.extend(_extract_isbn_tokens(text))
        if tokens:
            break

    if tokens:
        return _dedupe_preserve_order(tokens)

    if not ocr_enabled:
        return []

    if text_chars >= max(0, int(ocr_trigger_text_chars)):
        return []

    try:
        ocr_tokens = _extract_isbn_tokens_from_pdf_ocr(
            doc,
            max_pages=max(1, int(ocr_max_pages)),
            dpi=max(72, int(ocr_dpi)),
            lang=(ocr_lang or "").strip() or "eng",
            timeout_seconds=max(1.0, float(ocr_timeout_seconds)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("OCR falhou para PDF: %s", exc)
        return []

    return _dedupe_preserve_order(ocr_tokens)


def _extract_isbn_tokens(text: str) -> list[str]:
    if not text:
        return []
    results: list[str] = []
    for match in _ISBN_TOKEN_RE.finditer(text):
        token = (match.group(1) or "").strip()
        if _is_isbn_like(token):
            results.append(token)
    for match in _ISBN13_BARE_RE.finditer(text):
        token = (match.group(0) or "").strip()
        if _is_isbn_like(token):
            results.append(token)
    return results


def _is_isbn_like(token: str) -> bool:
    if not token:
        return False
    digits = [c for c in token if c.isdigit() or c in {"X", "x"}]
    return len(digits) in {10, 13}


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _count_alnum(text: str) -> int:
    return sum(1 for ch in text if ch.isalnum())


def _extract_isbn_tokens_from_pdf_ocr(doc, *, max_pages: int, dpi: int, lang: str, timeout_seconds: float) -> list[str]:
    if fitz is None:
        return []

    if not _tesseract_available():
        logger.info("OCR habilitado, mas 'tesseract' não está instalado/visível no PATH")
        return []

    total_pages = int(getattr(doc, "page_count", 0) or 0)
    limit = min(max_pages, total_pages)
    if limit <= 0:
        return []

    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    for page_index in range(limit):
        try:
            page = doc.load_page(page_index)
        except Exception:  # pragma: no cover - best-effort
            continue
        text = _ocr_pdf_page_text(page, matrix=matrix, lang=lang, timeout_seconds=timeout_seconds)
        tokens = _extract_isbn_tokens(text)
        if tokens:
            return tokens
    return []


def _ocr_pdf_page_text(page, *, matrix, lang: str, timeout_seconds: float) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(str(tmp_path))
        return _tesseract_image_to_text(tmp_path, lang=lang, timeout_seconds=timeout_seconds)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # pragma: no cover
            pass


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _tesseract_image_to_text(image_path: Path, *, lang: str, timeout_seconds: float) -> str:
    cmd = ["tesseract", str(image_path), "stdout"]
    if lang:
        cmd.extend(["-l", lang])
    cmd.extend(["--psm", "6"])
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        logger.debug("tesseract falhou (%s): %s", result.returncode, (result.stderr or "").strip())
        return ""
    return result.stdout or ""
