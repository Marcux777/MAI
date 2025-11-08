"""Esqueleto de ingestão + identificação para MAI."""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

import httpx
from rapidfuzz import fuzz

try:
    from ebooklib import epub
except ImportError:  # pragma: no cover - depende de extra opcional
    epub = None

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


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
    ids: dict
    cover_url: Optional[str]
    payload: dict


class Provider:
    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:  # pragma: no cover
        raise NotImplementedError

    def search(self, query: str) -> List[Candidate]:  # pragma: no cover
        raise NotImplementedError


class OpenLibraryProvider(Provider):
    base_url = "https://openlibrary.org"

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:
        resp = httpx.get(f"{self.base_url}/search.json", params={"q": f"isbn:{isbn13}", "limit": 1}, timeout=15)
        resp.raise_for_status()
        docs = resp.json().get("docs") or []
        if not docs:
            return None
        doc = docs[0]
        payload = {
            "title": doc.get("title"),
            "authors": doc.get("author_name"),
            "publisher": doc.get("publisher"),
            "language": doc.get("language"),
            "edition_key": doc.get("edition_key"),
        }
        return Candidate(
            source="openlibrary",
            title=doc.get("title"),
            authors=doc.get("author_name") or [],
            year=doc.get("first_publish_year"),
            publisher=(doc.get("publisher") or [None])[0],
            language=(doc.get("language") or [None])[0],
            ids={
                "ISBN13": isbn13,
                "OLID": (doc.get("edition_key") or [None])[0],
            },
            cover_url=f"https://covers.openlibrary.org/b/isbn/{isbn13}-L.jpg",
            payload=payload,
        )

    def search(self, query: str) -> List[Candidate]:
        resp = httpx.get(f"{self.base_url}/search.json", params={"q": query, "limit": 5}, timeout=15)
        resp.raise_for_status()
        hits = []
        for doc in resp.json().get("docs", [])[:5]:
            hits.append(
                Candidate(
                    source="openlibrary",
                    title=doc.get("title"),
                    authors=doc.get("author_name") or [],
                    year=doc.get("first_publish_year"),
                    publisher=(doc.get("publisher") or [None])[0],
                    language=(doc.get("language") or [None])[0],
                    ids={
                        "OLID": (doc.get("edition_key") or [None])[0],
                        "ISBN13": (doc.get("isbn") or [None])[0],
                    },
                    cover_url=None,
                    payload=doc,
                )
            )
        return hits


class GoogleBooksProvider(Provider):
    base_url = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key

    def _request(self, params: dict) -> dict:
        if self.api_key:
            params = {**params, "key": self.api_key}
        resp = httpx.get(self.base_url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:
        data = self._request({"q": f"isbn:{isbn13}", "maxResults": 1})
        items = data.get("items") or []
        if not items:
            return None
        item = items[0]
        info = item.get("volumeInfo", {})
        return Candidate(
            source="google_books",
            title=info.get("title"),
            authors=info.get("authors") or [],
            year=_year_from_date(info.get("publishedDate")),
            publisher=info.get("publisher"),
            language=info.get("language"),
            ids={"GBID": item.get("id"), "ISBN13": isbn13},
            cover_url=(info.get("imageLinks") or {}).get("thumbnail"),
            payload=item,
        )

    def search(self, query: str) -> List[Candidate]:
        data = self._request({"q": query, "maxResults": 5})
        hits = []
        for item in data.get("items", [])[:5]:
            info = item.get("volumeInfo", {})
            hits.append(
                Candidate(
                    source="google_books",
                    title=info.get("title"),
                    authors=info.get("authors") or [],
                    year=_year_from_date(info.get("publishedDate")),
                    publisher=info.get("publisher"),
                    language=info.get("language"),
                    ids={"GBID": item.get("id")},
                    cover_url=(info.get("imageLinks") or {}).get("thumbnail"),
                    payload=item,
                )
            )
        return hits


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    return LocalMetadata(title=title, authors=[author] if author else [], identifiers=[], language=None, year=_year_from_date(year))


def extract_metadata(path: Path) -> LocalMetadata:
    ext = path.suffix.lower()
    if ext == ".epub":
        return extract_epub_meta(path)
    if ext == ".pdf":
        return extract_pdf_meta(path)
    return LocalMetadata(title=None)


def normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "M")
    return " ".join("".join(ch for ch in text if ch.isalnum() or ch.isspace()).lower().split())


def isbn13(value: str) -> Optional[str]:
    digits = [c for c in value if c.isdigit() or c in {"X", "x"}]
    if len(digits) == 10:
        return isbn10_to_13("".join(digits))
    if len(digits) == 13 and validate_isbn13("".join(digits)):
        return "".join(digits)
    return None


def isbn10_to_13(isbn10: str) -> Optional[str]:
    if len(isbn10) != 10:
        return None
    core = "978" + isbn10[:-1]
    check = 0
    for i, char in enumerate(core):
        check += int(char) * (1 if i % 2 == 0 else 3)
    check = (10 - (check % 10)) % 10
    return core + str(check)


def validate_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    total = 0
    for idx, char in enumerate(value):
        weight = 1 if idx % 2 == 0 else 3
        total += int(char) * weight
    return total % 10 == 0


def score_candidate(local: LocalMetadata, candidate: Candidate) -> float:
    score = 0.0
    local_isbn = next((isbn13(i) for i in local.identifiers if isbn13(i)), None)
    remote_isbn = candidate.ids.get("ISBN13")
    if local_isbn and remote_isbn and local_isbn == remote_isbn:
        return 1.0
    if local.title and candidate.title:
        score += 0.35 * (fuzz.WRatio(normalize(local.title), normalize(candidate.title)) / 100)
    if local.authors and candidate.authors:
        score += 0.35 * (fuzz.token_set_ratio(" ".join(local.authors), " ".join(candidate.authors)) / 100)
    if local.year and candidate.year and abs(local.year - candidate.year) <= 1:
        score += 0.1
    if local.language and candidate.language and normalize(local.language) == normalize(candidate.language):
        score += 0.05
    if candidate.publisher:
        score += 0.05
    return score


def search_providers(local: LocalMetadata, providers: Iterable[Provider]) -> List[Candidate]:
    hits: List[Candidate] = []
    isbn = next((isbn13(i) for i in local.identifiers if isbn13(i)), None)
    query = " ".join(filter(None, [local.title, " ".join(local.authors)]))
    for provider in providers:
        try:
            if isbn:
                result = provider.get_by_isbn(isbn)
                if result:
                    hits.append(result)
                    continue
            if query:
                hits.extend(provider.search(query))
        except httpx.HTTPError as exc:
            print(f"[warn] provider {provider.__class__.__name__} falhou: {exc}")
    return hits


def reconcile(local: LocalMetadata, hits: List[Candidate]) -> Optional[Candidate]:
    ranked = sorted(((score_candidate(local, c), c) for c in hits), key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    top_score, top_candidate = ranked[0]
    if top_score >= 0.85:
        return top_candidate
    return None


def scan_directory(root: Path) -> List[Path]:
    supported = {".epub", ".pdf", ".mobi"}
    return [path for path in root.rglob("*") if path.suffix.lower() in supported]


def _year_from_date(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None


def attach_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo de ingestão MAI")
    parser.add_argument("directory", type=Path, help="Diretório com ebooks")
    parser.add_argument("--google-key", dest="google_key")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Imprime resultado em JSON")
    args = parser.parse_args()

    providers: List[Provider] = [OpenLibraryProvider(), GoogleBooksProvider(api_key=args.google_key)]

    results = []
    for path in scan_directory(args.directory):
        local = extract_metadata(path)
        local.identifiers.append(path.stem)
        hits = search_providers(local, providers)
        chosen = reconcile(local, hits)
        entry = {
            "file": str(path),
            "sha256": compute_sha256(path),
            "mime": attach_mime(path),
            "local": local.__dict__,
            "match": chosen.payload if chosen else None,
            "source": chosen.source if chosen else None,
        }
        results.append(entry)
        if not args.json_output:
            print(f"{path.name} -> {chosen.source if chosen else 'pending review'}")
    if args.json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
