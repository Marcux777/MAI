from __future__ import annotations

from typing import List

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from .services import BookRow


HEADERS = ["Título", "Autores", "Ano", "Idioma", "Tags", "Formato", "Arquivo"]


class LibraryTableModel(QAbstractTableModel):
    def __init__(self, rows: List[BookRow] | None = None) -> None:
        super().__init__()
        self._rows = rows or []

    def set_rows(self, rows: List[BookRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        book = self._rows[index.row()]
        col = index.column()
        mapping = {
            0: book.title,
            1: book.authors,
            2: book.year or "",
            3: (book.language or "").upper(),
            4: book.tags,
            5: book.fmt or "",
            6: book.file_path or "",
        }
        return mapping.get(col, "")

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return HEADERS[section]
        return section + 1

    def book_at(self, row: int) -> BookRow | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None
