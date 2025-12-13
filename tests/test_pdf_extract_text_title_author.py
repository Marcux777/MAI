from __future__ import annotations

from pathlib import Path

import pytest

from mai.ingest import extractors


fitz = pytest.importorskip("fitz")


def _create_pdf_with_bad_metadata(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Compiladores\n"
        "2a edição\n"
        "Princípios, técnicas e ferramentas\n"
        "Alfred V. Aho      Monica S. Lam      Ravi Sethi     Jeffrey D. Ullman\n",
    )
    doc.set_metadata({"title": "Iniciais_AHO.qxd", "author": "erj"})
    doc.save(path)
    doc.close()


def test_pdf_text_title_and_authors_override_bad_metadata(tmp_path):
    pdf_path = tmp_path / "Ullman, Jeffrey D.pdf"
    _create_pdf_with_bad_metadata(pdf_path)

    meta = extractors.extract_pdf_meta(pdf_path)

    assert meta.title
    assert "Compiladores" in meta.title
    assert "Iniciais_AHO.qxd" not in meta.title
    assert "Jeffrey D. Ullman" in meta.authors
    assert "erj" not in meta.authors

