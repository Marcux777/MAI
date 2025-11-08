from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QMessageBox,
)

from ..services import BackendClient


class ImportPanel(QWidget):
    def __init__(self, backend: BackendClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.paths_input = QLineEdit()
        self.paths_input.setPlaceholderText("Caminhos separados por ponto e vírgula ou deixe vazio para usar os paths configurados")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Caminhos para import/watcher"))
        layout.addWidget(self.paths_input)

        buttons = QHBoxLayout()
        scan_btn = QPushButton("Executar Scan")
        scan_btn.clicked.connect(self.run_scan)
        watch_btn = QPushButton("Iniciar Watcher")
        watch_btn.clicked.connect(self.start_watcher)
        stop_btn = QPushButton("Parar Watcher")
        stop_btn.clicked.connect(self.stop_watcher)
        buttons.addWidget(scan_btn)
        buttons.addWidget(watch_btn)
        buttons.addWidget(stop_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.log)

    def _parse_paths(self) -> List[str]:
        text = self.paths_input.text().strip()
        if not text:
            return []
        return [part.strip() for part in text.split(";") if part.strip()]

    def run_scan(self) -> None:
        try:
            result = self.backend.import_scan(self._parse_paths())
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Importação", f"Falha no scan: {exc}")
            return
        self.log.append(f"Scan agendado: {result}")

    def start_watcher(self) -> None:
        try:
            result = self.backend.watch_start(self._parse_paths())
        except Exception as exc:
            QMessageBox.critical(self, "Watcher", f"Falha ao iniciar: {exc}")
            return
        self.log.append(f"Watcher: {result}")

    def stop_watcher(self) -> None:
        try:
            result = self.backend.watch_stop()
        except Exception as exc:
            QMessageBox.critical(self, "Watcher", f"Falha ao parar: {exc}")
            return
        self.log.append(f"Watcher parado: {result}")
