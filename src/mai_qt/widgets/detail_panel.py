from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QWidget,
    QTabWidget,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
)

from ..services import EditionDetail


class DetailPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._metadata_tab(), "Metadados")
        self.ident_table = self._create_table(["Esquema", "Valor"])
        self.file_table = self._create_table(["Arquivo", "Formato", "Tamanho", "Adicionado"])
        self.provider_table = self._create_table(["Provedor", "Remote ID", "Score", "Quando"])
        self.history_table = self._create_table(["Stage", "Provider", "Score", "Aceito", "Quando"])
        self.tabs.addTab(self.ident_table, "Identificadores")
        self.tabs.addTab(self.file_table, "Arquivos")
        self.tabs.addTab(self.provider_table, "Provedores")
        self.tabs.addTab(self.history_table, "Histórico")
        layout.addWidget(self.tabs)
        self.status = QLabel("Selecione um item para editar.")
        layout.addWidget(self.status)
        self._on_save: Callable[[EditionDetail], None] | None = None
        self._on_fetch: Callable[[], None] | None = None
        self.current_detail: EditionDetail | None = None

    def _metadata_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.title_edit = QLineEdit()
        self.subtitle_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.year_edit = QLineEdit()
        self.language_edit = QLineEdit()
        self.description_edit = QTextEdit()
        form.addRow("Título", self.title_edit)
        form.addRow("Subtítulo", self.subtitle_edit)
        form.addRow("Autores", self.author_edit)
        form.addRow("Ano", self.year_edit)
        form.addRow("Idioma", self.language_edit)
        form.addRow("Descrição", self.description_edit)
        button_row = QHBoxLayout()
        self.save_btn = QPushButton("Salvar")
        self.save_btn.clicked.connect(self._emit_save)
        self.fetch_btn = QPushButton("Enriquecer metadados")
        self.fetch_btn.clicked.connect(self._emit_fetch)
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.fetch_btn)
        form.addRow(button_row)
        return widget

    def bind_save(self, handler: Callable[[EditionDetail], None]) -> None:
        self._on_save = handler

    def bind_fetch(self, handler: Callable[[], None]) -> None:
        self._on_fetch = handler

    def set_detail(self, detail: EditionDetail | None) -> None:
        self.current_detail = detail
        if not detail:
            self.title_edit.clear()
            self.subtitle_edit.clear()
            self.author_edit.clear()
            self.year_edit.clear()
            self.language_edit.clear()
            self.description_edit.clear()
            self.status.setText("Selecione um item para editar.")
            self.save_btn.setEnabled(False)
            self.fetch_btn.setEnabled(False)
            return
        self.save_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.title_edit.setText(detail.title)
        self.subtitle_edit.setText(detail.subtitle or "")
        self.author_edit.setText(", ".join(detail.authors))
        self.year_edit.setText(str(detail.year or ""))
        self.language_edit.setText(detail.language or "")
        self.description_edit.setPlainText(detail.description or "")
        self.status.setText("Edite os campos e clique em Salvar.")
        self._populate_tables(detail)

    def _emit_save(self) -> None:
        if not self._on_save or not self.current_detail:
            return
        try:
            year_value = int(self.year_edit.text()) if self.year_edit.text().strip() else None
        except ValueError:
            year_value = None
        detail = EditionDetail(
            edition_id=self.current_detail.edition_id,
            title=self.title_edit.text().strip(),
            subtitle=self.subtitle_edit.text().strip(),
            authors=[name.strip() for name in self.author_edit.text().split(",") if name.strip()],
            year=year_value,
            language=self.language_edit.text().strip() or None,
            description=self.description_edit.toPlainText().strip() or None,
        )
        self._on_save(detail)

    def _emit_fetch(self) -> None:
        if self._on_fetch:
            self._on_fetch()

    def update_status(self, message: str) -> None:
        self.status.setText(message)

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    def _populate_tables(self, detail: EditionDetail) -> None:
        self._fill_table(self.ident_table, [[row.scheme, row.value] for row in detail.identifiers])
        self._fill_table(
            self.file_table,
            [[row.path, row.fmt or "", str(row.size or ""), row.added_at or ""] for row in detail.files],
        )
        self._fill_table(
            self.provider_table,
            [[row.provider, row.remote_id or "", str(row.score or ""), row.fetched_at or ""] for row in detail.providers],
        )
        self._fill_table(
            self.history_table,
            [
                [row.stage, row.provider, str(row.score or ""), "Sim" if row.accepted else "Não", row.created_at or ""]
                for row in detail.history
            ],
        )

    def _fill_table(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                table.setItem(i, j, QTableWidgetItem(value))
