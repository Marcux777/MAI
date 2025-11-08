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

        info = QLabel("Resultados carregados da base local")
        info.setObjectName("infoLabel")

        header.addWidget(self.search_input)
        header.addWidget(self.refresh_btn)
        header.addWidget(info)
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

    def refresh(self) -> None:
        query = self.search_input.text().strip()
        rows = self.service.list_books(query=query)
        self.model.set_rows(rows)
