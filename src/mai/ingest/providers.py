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


_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")


def _first_identifier(value: object | None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return None
        return str(int(value)) if isinstance(value, int) else str(value)
    if isinstance(value, dict):
        for key in ("value", "id", "key", "identifier"):
            found = _first_identifier(value.get(key))
            if found:
                return found
        return None
    if isinstance(value, Sequence):
        for entry in value:
            found = _first_identifier(entry)
            if found:
                return found
    return None


def _normalize_identifier_scheme(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    cleaned = _NON_ALNUM_RE.sub("", raw.strip().upper())
    if "ISBN13" in cleaned:
        return "ISBN13"
    if "ISBN10" in cleaned:
        return "ISBN10"
    if "GOODREADS" in cleaned:
        return None
    if "LIBRARYTHING" in cleaned:
        return "LIBRARYTHING"
    if "MUSICBRAINZ" in cleaned or cleaned == "MBID":
        return "MBID"
    if "OPENLIBRARY" in cleaned and "WORK" in cleaned:
        return "OLWORK"
    if "OPENLIBRARY" in cleaned or cleaned == "OLID":
        return "OLID"
    if "OCLC" in cleaned:
        return "OCLC"
    if "LCCN" in cleaned:
        return "LCCN"
    if "DOI" in cleaned:
        return "DOI"
    return raw.strip().upper()


def _normalize_identifier_value(scheme: str, value: str) -> str:
    text = value.strip()
    if scheme in {"ISBN10", "ISBN13"}:
        return re.sub(r"[^0-9Xx]", "", text)
    if scheme in {"DOI", "MBID"}:
        return text.lower()
    return text


def _add_identifier(target: dict[str, str], scheme: str | None, value: object | None) -> None:
    normalized_scheme = _normalize_identifier_scheme(scheme)
    if not normalized_scheme:
        return
    raw_value = _first_identifier(value)
    if not raw_value:
        return
    cleaned_value = _normalize_identifier_value(normalized_scheme, raw_value)
    if not cleaned_value:
        return
    target.setdefault(normalized_scheme, cleaned_value)


def _normalize_openlibrary_key(value: object | None) -> Optional[str]:
    raw = _first_identifier(value)
    if not raw:
        return None
    text = raw.strip()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or None


def _extract_isbn_from_list(values: object | None) -> dict[str, str]:
    ids: dict[str, str] = {}
    if values is None:
        return ids
    if not isinstance(values, Sequence) or isinstance(values, str):
        values = [values]
    for item in values:
        raw = _first_identifier(item)
        if not raw:
            continue
        cleaned = _normalize_identifier_value("ISBN13", raw)
        if len(cleaned) == 13 and cleaned.isdigit():
            ids.setdefault("ISBN13", cleaned)
            return ids
    for item in values:
        raw = _first_identifier(item)
        if not raw:
            continue
        cleaned = _normalize_identifier_value("ISBN10", raw)
        if len(cleaned) == 10:
            ids.setdefault("ISBN10", cleaned)
            break
    return ids


def _openlibrary_cover_url(ids: dict[str, str]) -> Optional[str]:
    isbn = ids.get("ISBN13") or ids.get("ISBN10")
    if isbn:
        return f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
    olid = ids.get("OLID")
    if olid:
        return f"https://covers.openlibrary.org/b/olid/{olid}-L.jpg"
    librarything = ids.get("LIBRARYTHING")
    if librarything:
        return f"https://covers.openlibrary.org/b/librarything/{librarything}-L.jpg"
    return None


def _extract_openlibrary_ids(doc: dict, *, isbn13: str | None = None) -> dict[str, str]:
    ids: dict[str, str] = {}
    if isbn13:
        _add_identifier(ids, "ISBN13", isbn13)
    ids.update(_extract_isbn_from_list(doc.get("isbn")))

    _add_identifier(ids, "OLID", _normalize_openlibrary_key(doc.get("edition_key")))
    _add_identifier(ids, "OLID", _normalize_openlibrary_key(doc.get("cover_edition_key")))
    _add_identifier(ids, "OLWORK", _normalize_openlibrary_key(doc.get("work_key")))
    _add_identifier(ids, "OLWORK", _normalize_openlibrary_key(doc.get("key")))

    _add_identifier(ids, "LIBRARYTHING", doc.get("id_librarything"))
    _add_identifier(ids, "OCLC", doc.get("oclc"))
    _add_identifier(ids, "LCCN", doc.get("lccn"))
    _add_identifier(ids, "DOI", doc.get("doi"))
    return ids


def _collect_identifiers_from_set(target: dict[str, str], identifier_set: object | None) -> None:
    if identifier_set is None:
        return
    identifiers = None
    if isinstance(identifier_set, dict):
        identifiers = identifier_set.get("identifiers") or identifier_set.get("identifierSet")
        if isinstance(identifiers, dict):
            identifiers = identifiers.get("identifiers")
    if identifiers is None:
        identifiers = identifier_set
    if not isinstance(identifiers, Sequence) or isinstance(identifiers, str):
        return
    for identifier in identifiers:
        if not isinstance(identifier, dict):
            continue
        scheme = _normalize_identifier_scheme(identifier.get("type") or identifier.get("scheme"))
        value = identifier.get("value") or identifier.get("identifier")
        if scheme and value:
            _add_identifier(target, scheme, value)


def _extract_musicbrainz_id(value: object | None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower == "mbid" or "musicbrainz" in key_lower:
                found = _first_identifier(item)
                if found:
                    return found
            if isinstance(item, (dict, list)):
                found = _extract_musicbrainz_id(item)
                if found:
                    return found
        return None
    if isinstance(value, list):
        for entry in value:
            found = _extract_musicbrainz_id(entry)
            if found:
                return found
    return None


def _extract_bookbrainz_author_ids(entity: dict) -> dict[str, dict[str, str]]:
    author_ids: dict[str, dict[str, str]] = {}
    credits = entity.get("creatorCredits") or entity.get("authorCredits") or []
    if not isinstance(credits, Sequence) or isinstance(credits, str):
        return author_ids
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        name = credit.get("name") or (credit.get("alias") or {}).get("name")
        if not name:
            continue
        ids: dict[str, str] = {}
        _collect_identifiers_from_set(ids, credit.get("identifierSet"))
        for key in ("creator", "author", "entity", "artist"):
            _collect_identifiers_from_set(ids, credit.get(key))
        mbid = _extract_musicbrainz_id(credit)
        if mbid:
            _add_identifier(ids, "MBID", mbid)
        if ids:
            filtered = {k: v for k, v in ids.items() if k == "MBID"}
            if filtered:
                author_ids[name] = filtered
    return author_ids


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


def _parse_page_count(value: object | None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        pages = int(value)
        return pages if pages > 0 else None
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            pages = int(digits)
            return pages if pages > 0 else None
        return None
    if isinstance(value, dict):
        for key in ("pages", "pageCount", "numberOfPages", "number_of_pages"):
            parsed = _parse_page_count(value.get(key))
            if parsed:
                return parsed
        return None
    if isinstance(value, Sequence):
        for entry in value:
            parsed = _parse_page_count(entry)
            if parsed:
                return parsed
    return None


def _coerce_float(value: object | None) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: object | None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return int(digits)
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


def fetch_openlibrary_rating(olid: str, *, timeout: float = 8.0) -> tuple[float | None, int | None] | None:
    if not olid:
        return None
    try:
        resp = httpx.get(f"{OpenLibraryProvider.base_url}/works/{olid}/ratings.json", timeout=timeout)
    except httpx.HTTPError:
        return None
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return None
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    average = _coerce_float(summary.get("average") or summary.get("avg") or data.get("average"))
    count = _coerce_int(
        summary.get("count")
        or summary.get("ratings_count")
        or summary.get("total")
        or data.get("count")
        or data.get("ratings_count")
    )
    if average is None and count is None:
        return None
    return average, count


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
        ids = _extract_openlibrary_ids(doc, isbn13=isbn13)
        pages = _parse_page_count(doc.get("number_of_pages_median") or doc.get("number_of_pages"))
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
            pages=pages,
            publisher=(doc.get("publisher") or [None])[0],
            language=(doc.get("language") or [None])[0],
            ids=ids,
            cover_url=_openlibrary_cover_url(ids),
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
            pages = _parse_page_count(doc.get("number_of_pages_median") or doc.get("number_of_pages"))
            categories = _merge_categories(
                _as_string_list(doc.get("subject")),
                _as_string_list(doc.get("subject_facet")),
                _as_string_list(doc.get("subject_key")),
            )
            series_name, series_position = _extract_series(doc.get("series") or doc.get("series_name"))
            if not series_name:
                series_name, series_position = _infer_series_from_title(doc.get("title"))
            ids = _extract_openlibrary_ids(doc)
            hits.append(
                Candidate(
                    source="openlibrary",
                    title=doc.get("title"),
                    authors=doc.get("author_name") or [],
                    year=doc.get("first_publish_year"),
                    pages=pages,
                    publisher=(doc.get("publisher") or [None])[0],
                    language=(doc.get("language") or [None])[0],
                    ids=ids,
                    cover_url=_openlibrary_cover_url(ids),
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
        pages = _parse_page_count(info.get("pageCount"))
        series_name, series_position = _extract_series(info.get("seriesInfo"))
        if not series_name:
            series_name, series_position = _extract_series(info.get("series"))
        if not series_name:
            series_name, series_position = _infer_series_from_title(info.get("title"))
        ids: dict[str, str] = {}
        _add_identifier(ids, "GBID", item.get("id"))
        for identifier in info.get("industryIdentifiers") or []:
            if not isinstance(identifier, dict):
                continue
            scheme = identifier.get("type")
            value = identifier.get("identifier")
            _add_identifier(ids, scheme, value)
        _add_identifier(ids, "ISBN13", isbn13)
        return Candidate(
            source="google_books",
            title=info.get("title"),
            authors=info.get("authors") or [],
            year=_year_from_date(info.get("publishedDate")),
            pages=pages,
            publisher=info.get("publisher"),
            language=info.get("language"),
            ids=ids,
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
            pages = _parse_page_count(info.get("pageCount"))
            series_name, series_position = _extract_series(info.get("seriesInfo"))
            if not series_name:
                series_name, series_position = _extract_series(info.get("series"))
            if not series_name:
                series_name, series_position = _infer_series_from_title(info.get("title"))
            ids: dict[str, str] = {}
            _add_identifier(ids, "GBID", item.get("id"))
            for identifier in info.get("industryIdentifiers") or []:
                if not isinstance(identifier, dict):
                    continue
                scheme = identifier.get("type")
                value = identifier.get("identifier")
                _add_identifier(ids, scheme, value)
            hits.append(
                Candidate(
                    source="google_books",
                    title=info.get("title"),
                    authors=info.get("authors") or [],
                    year=_year_from_date(info.get("publishedDate")),
                    pages=pages,
                    publisher=info.get("publisher"),
                    language=info.get("language"),
                    ids=ids,
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
        ids: dict[str, str] = {}
        _add_identifier(ids, "BBID", entity.get("bbid"))
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue
            scheme = identifier.get("type") or identifier.get("scheme")
            value = identifier.get("value") or identifier.get("identifier")
            _add_identifier(ids, scheme, value)
        publisher = None
        publisher_set = entity.get("publisherSet", {}).get("publishers") or []
        if publisher_set:
            publisher = publisher_set[0].get("name")
        year = _year_from_date(entity.get("publicationDate") or entity.get("firstPublicationDate"))
        language = alias.get("language") if isinstance(alias, dict) else None
        pages = _parse_page_count(
            entity.get("numberOfPages")
            or entity.get("number_of_pages")
            or entity.get("pages")
            or entity.get("pageCount")
        )
        categories = _merge_categories(
            _as_string_list(entity.get("genres")),
            _as_string_list(entity.get("tags")),
            _as_string_list(entity.get("subjects")),
            _as_string_list(entity.get("subject")),
        )
        series_name, series_position = _extract_series(entity.get("seriesSet") or entity.get("series"))
        if not series_name:
            series_name, series_position = _infer_series_from_title(title)
        author_ids = _extract_bookbrainz_author_ids(entity)
        return Candidate(
            source="bookbrainz",
            title=title,
            authors=authors,
            year=year,
            pages=pages,
            publisher=publisher,
            language=language,
            ids=ids,
            cover_url=None,
            payload=entity,
            author_ids=author_ids,
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
