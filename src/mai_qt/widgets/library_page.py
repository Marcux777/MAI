from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..library_model import LibraryTableModel
from ..services import LibraryService


class LibraryPage(QWidget):
    def __init__(self, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.model = LibraryTableModel()
        self.collection_id: int | None = None
        self.unfiled_only: bool = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar título, autor ou tag...")
        self.search_input.returnPressed.connect(self.refresh)  # type: ignore[attr-defined]

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh)  # type: ignore[attr-defined]

        self.info = QLabel("")
        self.info.setObjectName("infoLabel")

        header.addWidget(self.search_input)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.info)
        layout.addLayout(header)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)

        layout.addWidget(self.table)

    def set_collection_filter(self, collection_id: int | None, unfiled_only: bool = False) -> None:
        self.collection_id = collection_id
        self.unfiled_only = unfiled_only
        self.refresh()

    def refresh(self) -> None:
        query = self.search_input.text().strip()
        rows = self.service.list_books(
            query=query,
            collection_id=self.collection_id,
            unfiled_only=self.unfiled_only,
        )
        self.model.set_rows(rows)
        self.info.setText(f"{len(rows)} itens")

    def selected_edition_ids(self) -> list[int]:
        selection = self.table.selectionModel().selectedRows()
        ids: list[int] = []
        for index in selection:
            row = self.model.book_at(index.row())
            if row:
                ids.append(int(row.edition_id))
        return ids

    def select_edition(self, edition_id: int) -> bool:
        for row_index in range(self.model.rowCount()):
            row = self.model.book_at(row_index)
            if not row:
                continue
            if int(row.edition_id) != int(edition_id):
                continue
            self.table.selectRow(row_index)
            self.table.scrollTo(self.model.index(row_index, 0))
            return True
        return False
