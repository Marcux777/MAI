from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

from ..services import BackendClient


class OrganizerPanel(QWidget):
    def __init__(self, backend: BackendClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.manifest_id_input = QLineEdit()
        self.summary_label = QLabel("Informe um manifesto e clique em Atualizar.")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Op", "Status", "Origem", "Destino", "Motivo"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.manifest_id_input.setPlaceholderText("Manifesto #")
        self.manifest_id_input.setFixedWidth(120)
        refresh_btn = QPushButton("Atualizar")
        refresh_btn.clicked.connect(self.refresh)
        apply_btn = QPushButton("Aplicar")
        apply_btn.clicked.connect(self.apply_manifest)
        rollback_btn = QPushButton("Rollback")
        rollback_btn.clicked.connect(self.rollback_manifest)
        controls.addWidget(QLabel("Manifesto"))
        controls.addWidget(self.manifest_id_input)
        controls.addWidget(refresh_btn)
        controls.addStretch(1)
        controls.addWidget(apply_btn)
        controls.addWidget(rollback_btn)
        layout.addLayout(controls)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def _current_manifest_id(self) -> int | None:
        text = self.manifest_id_input.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, "Manifesto", "Informe um ID válido (número).")
            return None
        return int(text)

    def refresh(self) -> None:
        manifest_id = self._current_manifest_id()
        if manifest_id is None:
            return
        try:
            detail = self.backend.get_manifest_detail(manifest_id)
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Organizer", str(exc))
            return
        self.summary_label.setText(
            f"Status: {detail.get('status')} — Template: {detail.get('template')} — Root: {detail.get('root')} — Resumo: {detail.get('summary')}"
        )
        self._populate_table(detail.get("ops", []))

    def _populate_table(self, ops: List[dict]) -> None:
        self.table.setRowCount(len(ops))
        for row, op in enumerate(ops):
            self.table.setItem(row, 0, QTableWidgetItem(str(op.get("id"))))
            status_item = QTableWidgetItem(op.get("status", ""))
            status_item.setData(Qt.UserRole, op.get("status"))
            self.table.setItem(row, 1, status_item)
            self.table.setItem(row, 2, QTableWidgetItem(op.get("src_path") or ""))
            self.table.setItem(row, 3, QTableWidgetItem(op.get("dst_path") or ""))
            self.table.setItem(row, 4, QTableWidgetItem(op.get("reason") or ""))

    def apply_manifest(self) -> None:
        manifest_id = self._current_manifest_id()
        if manifest_id is None:
            return
        try:
            result = self.backend.apply_manifest(manifest_id)
        except Exception as exc:
            QMessageBox.critical(self, "Organizer", str(exc))
            return
        QMessageBox.information(self, "Organizer", f"Manifesto aplicado: {result.get('summary')}")
        self.refresh()

    def rollback_manifest(self) -> None:
        manifest_id = self._current_manifest_id()
        if manifest_id is None:
            return
        try:
            result = self.backend.rollback_manifest(manifest_id)
        except Exception as exc:
            QMessageBox.critical(self, "Organizer", str(exc))
            return
        QMessageBox.information(self, "Organizer", f"Rollback realizado: {result.get('summary')}")
        self.refresh()
