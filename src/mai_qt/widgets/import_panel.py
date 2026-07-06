from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QApplication,
    QProgressBar,
)

from ..services import BackendClient


_SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw", ".azw3"}


class _UploadSignals(QObject):
    log = Signal(str)
    error = Signal(str)
    ingested = Signal(int)  # edition_id
    finished = Signal()


class _UploadBatchTask(QRunnable):
    def __init__(self, backend: BackendClient, paths: List[str]) -> None:
        super().__init__()
        self.backend = BackendClient(base_url=backend.base_url, timeout=backend.timeout)
        self.paths = paths
        self.signals = _UploadSignals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - runs in Qt threadpool
        for path in self.paths:
            try:
                result = self.backend.import_upload(path)
            except Exception as exc:
                self.signals.error.emit(f"Falha no upload ({path}): {exc}")
                continue
            self.signals.log.emit(f"Upload concluído: {result}")
            edition_id = result.get("edition_id")
            if isinstance(edition_id, int):
                self.signals.ingested.emit(edition_id)
            else:
                self.signals.error.emit(f"Upload concluído, mas sem edition_id: {result}")
        self.signals.finished.emit()


class ImportPanel(QWidget):
    ingested = Signal(int)  # edition_id
    upload_log = Signal(str)
    upload_error = Signal(str)
    upload_finished = Signal(int, int)  # ok, failed

    def __init__(self, backend: BackendClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self.setAcceptDrops(True)
        self._pool = QThreadPool.globalInstance()
        self._upload_running = False
        self._batch_ok = 0
        self._batch_failed = 0
        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        self.file_path.setPlaceholderText("Selecione um arquivo (PDF/EPUB/MOBI/AZW...)")
        self.paths_input = QLineEdit()
        self.paths_input.setPlaceholderText("Caminhos separados por ponto e vírgula ou deixe vazio para usar os paths configurados")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Upload de arquivo (ingestão imediata)"))

        upload_row = QHBoxLayout()
        upload_row.addWidget(self.file_path, 1)
        self.select_btn = QPushButton("Selecionar…")
        self.select_btn.clicked.connect(self.select_file)  # type: ignore[attr-defined]
        self.upload_btn = QPushButton("Upload")
        self.upload_btn.clicked.connect(self.upload_file)  # type: ignore[attr-defined]
        upload_row.addWidget(self.select_btn)
        upload_row.addWidget(self.upload_btn)
        layout.addLayout(upload_row)

        layout.addWidget(QLabel("Caminhos para import/watcher"))
        layout.addWidget(self.paths_input)

        buttons = QHBoxLayout()
        scan_btn = QPushButton("Executar Scan")
        scan_btn.clicked.connect(self.run_scan)
        watch_btn = QPushButton("Iniciar Watcher")
        watch_btn.clicked.connect(self.start_watcher)
        stop_btn = QPushButton("Parar Watcher")
        stop_btn.clicked.connect(self.stop_watcher)
        style = QApplication.style()
        if style:
            self.select_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_DialogOpenButton))
            self.upload_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_ArrowUp))
            scan_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_FileDialogContentsView))
            watch_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaPlay))
            stop_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_MediaStop))
        buttons.addWidget(scan_btn)
        buttons.addWidget(watch_btn)
        buttons.addWidget(stop_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.progress)
        layout.addWidget(self.log)

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if any(Path(p).suffix.lower() in _SUPPORTED_EXTENSIONS for p in paths):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:  # pragma: no cover - GUI
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.upload_files(paths)
        event.acceptProposedAction()

    def _parse_paths(self) -> List[str]:
        text = self.paths_input.text().strip()
        if not text:
            return []
        return [part.strip() for part in text.split(";") if part.strip()]

    def select_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo",
            str(Path.home()),
            "Ebooks (*.pdf *.epub *.mobi *.azw *.azw3);;Todos (*.*)",
        )
        if not selected:
            return
        self.file_path.setText(selected)

    def upload_files(self, paths: List[str]) -> None:
        candidates: list[str] = []
        for raw in paths:
            path = (raw or "").strip()
            if not path:
                continue
            suffix = Path(path).suffix.lower()
            if suffix not in _SUPPORTED_EXTENSIONS:
                continue
            p = Path(path)
            if not p.exists() and p.is_absolute() and Path("/host").exists():
                alt = Path("/host") / p.relative_to("/")
                if alt.exists():
                    p = alt
            candidates.append(str(p))

        if not candidates:
            QMessageBox.information(
                self,
                "Upload",
                "Arraste ou selecione um arquivo suportado (PDF/EPUB/MOBI/AZW...).",
            )
            return

        if self._upload_running:
            QMessageBox.information(self, "Upload", "Já existe um upload em andamento.")
            return

        self._upload_running = True
        self._batch_ok = 0
        self._batch_failed = 0
        self.select_btn.setEnabled(False)
        self.upload_btn.setEnabled(False)
        self.progress.setVisible(True)
        start_msg = f"Iniciando upload: {', '.join(Path(p).name for p in candidates)}"
        self.log.append(start_msg)
        self.upload_log.emit(start_msg)

        task = _UploadBatchTask(self.backend, candidates)
        task.signals.log.connect(self._on_task_log)  # type: ignore[attr-defined]
        task.signals.error.connect(self._on_task_error)  # type: ignore[attr-defined]
        task.signals.ingested.connect(self._on_task_ingested)  # type: ignore[attr-defined]
        task.signals.finished.connect(self._on_upload_finished)  # type: ignore[attr-defined]
        self._pool.start(task)

    def _on_task_log(self, message: str) -> None:
        self.log.append(message)
        self.upload_log.emit(message)

    def _on_task_error(self, message: str) -> None:
        self._batch_failed += 1
        self.log.append(message)
        self.upload_error.emit(message)

    def _on_task_ingested(self, edition_id: int) -> None:
        self._batch_ok += 1
        self.ingested.emit(edition_id)

    def _on_upload_finished(self) -> None:
        self._upload_running = False
        self.select_btn.setEnabled(True)
        self.upload_btn.setEnabled(True)
        self.progress.setVisible(False)
        summary = f"Upload finalizado: {self._batch_ok} ok, {self._batch_failed} falha(s)."
        self.log.append(summary)
        self.upload_log.emit(summary)
        self.upload_finished.emit(self._batch_ok, self._batch_failed)

    def upload_file(self) -> None:
        path = self.file_path.text().strip()
        if not path:
            QMessageBox.information(self, "Upload", "Selecione um arquivo antes de enviar.")
            return
        self.upload_files([path])

    def run_scan(self) -> None:
        try:
            result = self.backend.import_scan(self._parse_paths())
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, "Importação", f"Falha no scan: {exc}")
            return
        task_id = result.get("task_id")
        if task_id:
            self.log.append(f"Scan enfileirado (task {task_id}).")
        else:
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
