from __future__ import annotations

from mai.ingest import providers


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_openlibrary_provider_extracts_external_ids(monkeypatch):
    payload = {
        "docs": [
            {
                "title": "Teste",
                "author_name": ["Autor"],
                "first_publish_year": 2021,
                "publisher": ["Editora"],
                "language": ["pt"],
                "isbn": ["9781234567890", "1234567890"],
                "edition_key": ["OL123M"],
                "key": "/works/OL456W",
                "id_goodreads": [12345],
                "id_librarything": [67890],
                "oclc": ["ocn123456"],
                "lccn": ["2001023456"],
                "doi": ["10.1000/XYZ123"],
            }
        ]
    }

    def fake_get(*_args, **_kwargs):
        return DummyResponse(payload)

    monkeypatch.setattr(providers.httpx, "get", fake_get)

    provider = providers.OpenLibraryProvider()
    hits = provider.search("teste")
    assert len(hits) == 1
    ids = hits[0].ids
    assert ids["ISBN13"] == "9781234567890"
    assert ids["OLID"] == "OL123M"
    assert ids["OLWORK"] == "OL456W"
    assert ids["GOODREADS"] == "12345"
    assert ids["LIBRARYTHING"] == "67890"
    assert ids["OCLC"] == "ocn123456"
    assert ids["LCCN"] == "2001023456"
    assert ids["DOI"] == "10.1000/xyz123"
    assert hits[0].cover_url == "https://covers.openlibrary.org/b/isbn/9781234567890-L.jpg"
