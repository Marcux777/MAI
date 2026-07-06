from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from ..services import BackendClient


class _TaskFetchSignals(QObject):
    loaded = Signal(dict)
    error = Signal(str)


class _TaskFetchTask(QRunnable):
    def __init__(self, backend: BackendClient, limit: int = 100) -> None:
        super().__init__()
        self.backend = BackendClient(base_url=backend.base_url, timeout=backend.timeout)
        self.limit = limit
        self.signals = _TaskFetchSignals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - runs in Qt threadpool
        try:
            payload = self.backend.fetch_tasks(limit=self.limit)
        except Exception as exc:
            self.signals.error.emit(str(exc))
            return
        self.signals.loaded.emit(payload)


class TasksPage(QWidget):
    def __init__(self, backend: BackendClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._pool = QThreadPool.globalInstance()
        self._refresh_running = False
        self._auto_started = False
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)  # type: ignore[attr-defined]
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header = QLabel("<h2>Tarefas</h2><p>Fila de processamento e status das operacoes em background.</p>")
        header.setTextFormat(Qt.TextFormat.RichText)
        header_layout.addWidget(header, 1)

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh)  # type: ignore[attr-defined]
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.status_label = QLabel("Sem tarefas carregadas.")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "Tipo", "Status", "Progresso", "Mensagem"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

    def showEvent(self, event) -> None:  # pragma: no cover - GUI
        super().showEvent(event)
        if not self._auto_started:
            self._auto_started = True
            self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # pragma: no cover - GUI
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self) -> None:
        if self._refresh_running:
            return
        self._refresh_running = True
        task = _TaskFetchTask(self.backend)
        task.signals.loaded.connect(self._on_loaded)  # type: ignore[attr-defined]
        task.signals.error.connect(self._on_error)  # type: ignore[attr-defined]
        self._pool.start(task)

    def _on_loaded(self, payload: dict[str, Any]) -> None:
        self._refresh_running = False
        items = payload.get("items", [])
        pending = payload.get("pending", 0)
        running = payload.get("running", 0)
        total = payload.get("total", 0)
        self.status_label.setText(f"Pendentes: {pending} | Executando: {running} | Total: {total}")
        self._populate_table(items)

    def _on_error(self, message: str) -> None:
        self._refresh_running = False
        self.status_label.setText(f"Falha ao carregar tarefas: {message}")

    def _populate_table(self, items: list[dict[str, Any]]) -> None:
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(item.get("id"))))
            self.table.setItem(row, 1, QTableWidgetItem(item.get("label") or item.get("kind", "")))
            self.table.setItem(row, 2, QTableWidgetItem(item.get("status", "")))
            progress_text, message = _format_progress(item)
            self.table.setItem(row, 3, QTableWidgetItem(progress_text))
            self.table.setItem(row, 4, QTableWidgetItem(message))


def _format_progress(item: dict[str, Any]) -> tuple[str, str]:
    result = item.get("result") or {}
    progress = result.get("progress") or {}
    message = progress.get("message") or ""
    current = progress.get("current")
    total = progress.get("total")
    percent = progress.get("percent")
    if isinstance(current, int) and isinstance(total, int) and total > 0:
        if isinstance(percent, (int, float)):
            return f"{current}/{total} ({percent:.0f}%)", message
        return f"{current}/{total}", message
    summary = result.get("summary") or {}
    if item.get("status") == "done" and summary:
        total = summary.get("total")
        ok = summary.get("ok")
        if isinstance(total, int) and isinstance(ok, int):
            return f"{ok}/{total}", message
        return "Concluido", message
    if item.get("status") == "failed":
        error = result.get("error")
        return "Falha", str(error or "")
    return "-", message
