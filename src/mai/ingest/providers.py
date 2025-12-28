from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

import httpx

from mai.ingest.types import Candidate


class Provider:
    slug: str = "provider"

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:  # pragma: no cover
        raise NotImplementedError

    def search(self, query: str) -> List[Candidate]:  # pragma: no cover
        raise NotImplementedError


def _as_string_list(value: object | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        items: List[str] = []
        for entry in value:
            if isinstance(entry, str):
                items.append(entry)
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("label") or entry.get("value")
                if name:
                    items.append(str(name))
        return items
    return []


def _merge_categories(*values: Iterable[str]) -> List[str]:
    merged: List[str] = []
    for seq in values:
        for item in seq:
            if item:
                merged.append(str(item))
    return merged


_SERIES_POSITION_RE = re.compile(r"(?i)(?:#|book|vol(?:\.|ume)?|tome|no\.?)\s*(\d+(?:\.\d+)?)")
_SERIES_IN_PARENS_RE = re.compile(
    r"(?i)\((?P<series>[^)]*?)\s*(?:#|book|vol(?:\.|ume)?|tome|no\.?)\s*(?P<num>\d+(?:\.\d+)?)\)"
)
_SERIES_TRAILING_NUM_RE = re.compile(r"(?i)^(?P<name>.+?)[\s,;:-]+(?P<num>\d+(?:\.\d+)?)$")


def _parse_series_position(value: object | None) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"\d+(?:\.\d+)?", value)
        if match:
            return float(match.group(0))
    return None


def _parse_series_entry(raw: str) -> tuple[str | None, Optional[float]]:
    text = " ".join((raw or "").strip().split())
    if not text:
        return None, None

    match = _SERIES_POSITION_RE.search(text)
    if match:
        position = _parse_series_position(match.group(1))
        name = _SERIES_POSITION_RE.sub("", text).strip(" -–:;,#()[]")
        return name or None, position

    trailing = _SERIES_TRAILING_NUM_RE.match(text)
    if trailing:
        name = trailing.group("name").strip(" -–:;,#()[]")
        position = _parse_series_position(trailing.group("num"))
        return name or None, position

    return text, None


def _infer_series_from_title(title: str | None) -> tuple[str | None, Optional[float]]:
    if not title:
        return None, None
    match = _SERIES_IN_PARENS_RE.search(title)
    if not match:
        return None, None
    name = (match.group("series") or "").strip(" -–:;,#()[]")
    position = _parse_series_position(match.group("num"))
    return (name or None), position


def _extract_series(value: object | None) -> tuple[str | None, Optional[float]]:
    if value is None:
        return None, None
    if isinstance(value, str):
        return _parse_series_entry(value)
    if isinstance(value, dict):
        name = value.get("name") or value.get("title") or value.get("series")
        position = _parse_series_position(
            value.get("position")
            or value.get("number")
            or value.get("sequence")
            or value.get("orderNumber")
            or value.get("bookDisplayNumber")
        )
        if name:
            return str(name), position
        nested = value.get("series") or value.get("seriesList") or value.get("volumeSeries")
        if nested:
            return _extract_series(nested)
        return None, position
    if isinstance(value, Sequence):
        for entry in value:
            name, position = _extract_series(entry)
            if name:
                return name, position
        return None, None
    return None, None


class OpenLibraryProvider(Provider):
    base_url = "https://openlibrary.org"
    slug = "openlibrary"

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:
        resp = httpx.get(f"{self.base_url}/search.json", params={"q": f"isbn:{isbn13}", "limit": 1}, timeout=15)
        resp.raise_for_status()
        docs = resp.json().get("docs") or []
        if not docs:
            return None
        doc = docs[0]
        categories = _merge_categories(
            _as_string_list(doc.get("subject")),
            _as_string_list(doc.get("subject_facet")),
            _as_string_list(doc.get("subject_key")),
        )
        series_name, series_position = _extract_series(doc.get("series") or doc.get("series_name"))
        if not series_name:
            series_name, series_position = _infer_series_from_title(doc.get("title"))
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
            payload=doc,
            categories=categories,
            series=series_name,
            series_position=series_position,
        )

    def search(self, query: str) -> List[Candidate]:
        resp = httpx.get(f"{self.base_url}/search.json", params={"q": query, "limit": 5}, timeout=15)
        resp.raise_for_status()
        hits: List[Candidate] = []
        for doc in resp.json().get("docs", [])[:5]:
            categories = _merge_categories(
                _as_string_list(doc.get("subject")),
                _as_string_list(doc.get("subject_facet")),
                _as_string_list(doc.get("subject_key")),
            )
            series_name, series_position = _extract_series(doc.get("series") or doc.get("series_name"))
            if not series_name:
                series_name, series_position = _infer_series_from_title(doc.get("title"))
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
                    categories=categories,
                    series=series_name,
                    series_position=series_position,
                )
            )
        return hits


class GoogleBooksProvider(Provider):
    base_url = "https://www.googleapis.com/books/v1/volumes"
    slug = "google_books"

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
        series_name, series_position = _extract_series(info.get("seriesInfo"))
        if not series_name:
            series_name, series_position = _extract_series(info.get("series"))
        if not series_name:
            series_name, series_position = _infer_series_from_title(info.get("title"))
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
            categories=_as_string_list(info.get("categories")),
            series=series_name,
            series_position=series_position,
        )

    def search(self, query: str) -> List[Candidate]:
        data = self._request({"q": query, "maxResults": 5})
        hits: List[Candidate] = []
        for item in data.get("items", [])[:5]:
            info = item.get("volumeInfo", {})
            series_name, series_position = _extract_series(info.get("seriesInfo"))
            if not series_name:
                series_name, series_position = _extract_series(info.get("series"))
            if not series_name:
                series_name, series_position = _infer_series_from_title(info.get("title"))
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
                    categories=_as_string_list(info.get("categories")),
                    series=series_name,
                    series_position=series_position,
                )
            )
        return hits


class BookBrainzProvider(Provider):
    base_url = "https://bookbrainz.org/ws/1"
    slug = "bookbrainz"

    def _search(self, query: str, limit: int = 5) -> List[dict]:
        resp = httpx.get(
            f"{self.base_url}/search/edition",
            params={"q": query, "limit": limit, "fmt": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:
        results = self._search(isbn13, limit=1)
        if not results:
            return None
        return self._build_candidate(results[0])

    def search(self, query: str) -> List[Candidate]:
        hits: List[Candidate] = []
        for item in self._search(query, limit=5):
            candidate = self._build_candidate(item)
            if candidate:
                hits.append(candidate)
        return hits

    def _build_candidate(self, item: dict) -> Optional[Candidate]:
        entity = item.get("entity") or item.get("edition") or item
        if not entity:
            return None
        alias = entity.get("defaultAlias") or {}
        if isinstance(alias, list) and alias:
            alias = alias[0]
        title = entity.get("title") or alias.get("name")
        if not title:
            return None
        authors: List[str] = []
        for credit in entity.get("creatorCredits") or entity.get("authorCredits") or []:
            name = credit.get("name") or (credit.get("alias") or {}).get("name")
            if name:
                authors.append(name)
        identifiers = entity.get("identifierSet", {}).get("identifiers") or []
        ids = {"BBID": entity.get("bbid")}
        for identifier in identifiers:
            scheme = (identifier.get("type") or "").upper()
            value = identifier.get("value")
            if not value:
                continue
            if "ISBN" in scheme and len(value) >= 10:
                ids["ISBN13"] = value.replace("-", "")
        publisher = None
        publisher_set = entity.get("publisherSet", {}).get("publishers") or []
        if publisher_set:
            publisher = publisher_set[0].get("name")
        year = _year_from_date(entity.get("publicationDate") or entity.get("firstPublicationDate"))
        language = alias.get("language") if isinstance(alias, dict) else None
        categories = _merge_categories(
            _as_string_list(entity.get("genres")),
            _as_string_list(entity.get("tags")),
            _as_string_list(entity.get("subjects")),
            _as_string_list(entity.get("subject")),
        )
        series_name, series_position = _extract_series(entity.get("seriesSet") or entity.get("series"))
        if not series_name:
            series_name, series_position = _infer_series_from_title(title)
        return Candidate(
            source="bookbrainz",
            title=title,
            authors=authors,
            year=year,
            publisher=publisher,
            language=language,
            ids=ids,
            cover_url=None,
            payload=entity,
            categories=categories,
            series=series_name,
            series_position=series_position,
        )


def _year_from_date(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None
