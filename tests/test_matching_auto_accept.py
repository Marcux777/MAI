from __future__ import annotations

from mai.ingest.pipeline import ACCEPT_THRESHOLD, reconcile, score_candidates
from mai.ingest.types import Candidate, LocalMetadata


def test_reconcile_can_auto_accept_strong_title_and_author_match_without_year_or_language():
    local = LocalMetadata(
        title="Compilers: Principles, Techniques, and Tools",
        authors=["Alfred V. Aho", "Monica S. Lam", "Ravi Sethi", "Jeffrey D. Ullman"],
        identifiers=[],
        language=None,
        year=None,
    )
    top = Candidate(
        source="dummy",
        title="Compilers: Principles, Techniques, and Tools",
        authors=["Jeffrey D. Ullman", "Alfred V. Aho", "Monica S. Lam", "Ravi Sethi"],
        year=None,
        publisher="Pearson",
        language=None,
        ids={},
        cover_url=None,
        payload={},
    )
    weaker = Candidate(
        source="dummy",
        title="Compilers: Principles, Techniques, and Tools",
        authors=["Alfred V. Aho"],
        year=None,
        publisher="Pearson",
        language=None,
        ids={},
        cover_url=None,
        payload={},
    )

    scored = score_candidates(local, [("search", top), ("search", weaker)])
    chosen, top_score, _ranked = reconcile(scored)

    assert chosen == top
    assert top_score < ACCEPT_THRESHOLD

