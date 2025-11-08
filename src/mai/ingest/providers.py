from __future__ import annotations

from typing import List, Optional

import httpx

from mai.ingest.types import Candidate


class Provider:
    slug: str = "provider"

    def get_by_isbn(self, isbn13: str) -> Optional[Candidate]:  # pragma: no cover
        raise NotImplementedError

    def search(self, query: str) -> List[Candidate]:  # pragma: no cover
        raise NotImplementedError


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
        )

    def search(self, query: str) -> List[Candidate]:
        resp = httpx.get(f"{self.base_url}/search.json", params={"q": query, "limit": 5}, timeout=15)
        resp.raise_for_status()
        hits: List[Candidate] = []
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
        hits: List[Candidate] = []
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
        )


def _year_from_date(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    return None
