"""Gera um conjunto de arquivos sintéticos para testar o pipeline da MAI."""
from __future__ import annotations

from pathlib import Path

import fitz
from ebooklib import epub

DATASET = [
    {"title": "Aventuras em Marte", "author": "Joana Lima", "year": 2020, "format": "pdf"},
    {"title": "História dos Algoritmos", "author": "Caio Prado", "year": 2018, "format": "pdf"},
    {"title": "Crônicas de Orion", "author": "Ana Becker", "year": 2022, "format": "epub"},
    {"title": "Manual do Jardineiro", "author": "Lia Campos", "year": 2015, "format": "epub"},
    {"title": "Mistérios de Fobos", "author": "Ricardo Azevedo", "year": 2019, "format": "pdf"},
    {"title": "Sombras de Saturno", "author": "Joana Lima", "year": 2021, "format": "epub"},
    {"title": "Sombras de Saturno", "author": "Carlos Dias", "year": 2023, "format": "pdf"},
    {"title": "Tratado dos Ventos", "author": "Helena Prado", "year": 2010, "format": "pdf"},
    {"title": "Guia das Constelações", "author": "Miguel Neto", "year": 2017, "format": "epub"},
    {"title": "Códigos Esquecidos", "author": "Ana Becker", "year": 2014, "format": "pdf"},
    {"title": "Crônicas Urbanas", "author": "Ricardo Azevedo", "year": 2011, "format": "epub"},
    {"title": "Crônicas Urbanas", "author": "Mariana Azevedo", "year": 2011, "format": "pdf"},
]

ROOT = Path("beta_pack")


def generate_pdf(path: Path, title: str, author: str, year: int) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), title, fontsize=24)
    page.insert_text((72, 120), f"Autor: {author}\nAno: {year}", fontsize=14)
    doc.metadata = {
        "title": title,
        "author": author,
        "creationDate": f"D:{year}0101000000",
    }
    doc.save(path)


def generate_epub(path: Path, title: str, author: str, year: int) -> None:
    book = epub.EpubBook()
    book.set_identifier(f"demo-{title[:5].lower()}")
    book.set_title(title)
    book.set_language("pt-BR")
    book.add_author(author)
    c1 = epub.EpubHtml(title="Capítulo 1", file_name="chap_01.xhtml")
    c1.content = f"<h1>{title}</h1><p>Obra demonstrativa criada em {year}.</p>"
    book.add_item(c1)
    book.spine = ["nav", c1]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    for item in DATASET:
        slug_title = item['title'].lower().replace(' ', '_')
        slug_author = item['author'].lower().replace(' ', '_')
        filename = f"{slug_title}__{slug_author}"
        if item["format"] == "pdf":
            target = ROOT / f"{filename}.pdf"
            generate_pdf(target, item["title"], item["author"], item["year"])
        else:
            target = ROOT / f"{filename}.epub"
            generate_epub(target, item["title"], item["author"], item["year"])
        print("Gerado", target)


if __name__ == "__main__":
    main()
