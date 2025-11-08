from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from ..services import BackendClient


class ReviewPage(QWidget):
    def __init__(self, backend: BackendClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.queue: list[dict] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)

        header.addWidget(QLabel("Candidato"))
        self.candidate_box = QComboBox()
        header.addWidget(self.candidate_box)

        self.accept_btn = QPushButton("Aceitar")
        self.accept_btn.clicked.connect(self.accept_selection)
        header.addWidget(self.accept_btn)

        self.reject_btn = QPushButton("Rejeitar")
        self.reject_btn.clicked.connect(self.reject_selection)
        header.addWidget(self.reject_btn)
        header.addStretch(1)
        layout.addLayout(header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Edição", "Obra", "Score", "Arquivo"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._update_detail)
        layout.addWidget(self.table)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)

        self.status_label = QLabel("Revise os candidatos antes de aceitar.")
        layout.addWidget(self.status_label)

    def refresh(self) -> None:
        try:
            payload = self.backend.fetch_review_queue()
        except Exception as exc:  # pragma: no cover - GUI feedback
            QMessageBox.critical(self, "Revisão", f"Falha ao buscar fila: {exc}")
            return
        self.queue = payload.get("items", [])
        self._populate_table()
        self.status_label.setText(f"{payload.get('total', 0)} itens pendentes.")

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.queue))
        for row, item in enumerate(self.queue):
            self.table.setItem(row, 0, QTableWidgetItem(str(item["edition_id"])))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("work_title") or ""))
            self.table.setItem(row, 2, QTableWidgetItem(f"{item.get('top_score', 0):.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(item.get("file_path") or ""))
        if self.queue:
            self.table.selectRow(0)
        else:
            self.detail.clear()
            self.candidate_box.clear()

    def _current_item(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self.queue[indexes[0].row()]

    def _update_detail(self) -> None:
        item = self._current_item()
        self.candidate_box.clear()
        if not item:
            self.detail.clear()
            return
        buf = []
        for idx, candidate in enumerate(item.get("candidates", [])):
            summary = (
                f"{candidate.get('provider')} — {candidate.get('title') or 'Sem título'}"
                f" ({candidate.get('score', 0):.2f})"
            )
            self.candidate_box.addItem(summary, idx)
            details = [
                f"Provider: {candidate.get('provider')}",
                f"Score: {candidate.get('score')}",
                f"Title: {candidate.get('title')}",
                f"Authors: {', '.join(candidate.get('authors') or [])}",
                f"Publisher: {candidate.get('publisher')}",
                f"Year: {candidate.get('year')}",
                f"Language: {candidate.get('language')}",
                f"IDs: {candidate.get('ids')}",
            ]
            buf.append("\n".join(details))
        self.detail.setPlainText("\n\n---\n\n".join(buf) if buf else "Sem candidatos disponíveis.")

    def accept_selection(self) -> None:
        item = self._current_item()
        if not item:
            QMessageBox.information(self, "Revisão", "Selecione uma edição.")
            return
        candidate_idx = self.candidate_box.currentData()
        if candidate_idx is None:
            QMessageBox.warning(self, "Revisão", "Escolha um candidato antes de aceitar.")
            return
        try:
            result = self.backend.resolve_review(item["edition_id"], int(candidate_idx), reject=False)
        except Exception as exc:
            QMessageBox.critical(self, "Revisão", f"Falha ao aceitar: {exc}")
            return
        QMessageBox.information(self, "Revisão", f"Edição {item['edition_id']} aceita ({result.get('provider')}).")
        self.refresh()

    def reject_selection(self) -> None:
        item = self._current_item()
        if not item:
            QMessageBox.information(self, "Revisão", "Selecione uma edição.")
            return
        try:
            self.backend.resolve_review(item["edition_id"], candidate_index=None, reject=True)
        except Exception as exc:
            QMessageBox.critical(self, "Revisão", f"Falha ao rejeitar: {exc}")
            return
        QMessageBox.information(self, "Revisão", f"Edição {item['edition_id']} rejeitada.")
        self.refresh()
