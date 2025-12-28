from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QTabWidget,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView

from ..services import EditionDetail


@dataclass(frozen=True)
class _PreviewFile:
    path: str
    fmt: str


class _EpubSignals(QObject):
    done = Signal(int, str)  # token, html
    failed = Signal(int, str)  # token, error


class _EpubLoadTask(QRunnable):
    def __init__(self, token: int, path: str, max_bytes: int = 2_000_000) -> None:
        super().__init__()
        self.token = token
        self.path = path
        self.max_bytes = max_bytes
        self.signals = _EpubSignals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - runs in Qt threadpool
        try:
            from ebooklib import ITEM_DOCUMENT, epub  # local import (startup speed)

            book = epub.read_epub(self.path)
            chunks: list[str] = []
            total = 0
            for item in book.get_items_of_type(ITEM_DOCUMENT):
                content = item.get_content() or b""
                total += len(content)
                chunks.append(content.decode("utf-8", errors="ignore"))
                if total >= self.max_bytes:
                    break
            html = "<hr/>".join(chunks) if chunks else "<p>(EPUB sem conteúdo renderizável)</p>"
            self.signals.done.emit(self.token, html)
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))


class PreviewTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._dirty = False
        self._load_token = 0
        self._pool = QThreadPool.globalInstance()
        self._reader_dialog: ReaderDialog | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.file_box = QComboBox()
        self.file_box.currentIndexChanged.connect(self._on_file_changed)  # type: ignore[attr-defined]
        header.addWidget(QLabel("Arquivo"))
        header.addWidget(self.file_box, 1)

        self.read_btn = QPushButton("Ler")
        self.read_btn.clicked.connect(self._open_reader)  # type: ignore[attr-defined]
        header.addWidget(self.read_btn)

        self.open_btn = QPushButton("Abrir no sistema")
        self.open_btn.clicked.connect(self._open_current)  # type: ignore[attr-defined]
        header.addWidget(self.open_btn)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.message = QLabel("Selecione um item para pré-visualizar.")
        self.message.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.stack.addWidget(self.message)

        self.pdf_doc = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_doc)
        self.stack.addWidget(self.pdf_view)

        self.html = QTextBrowser()
        self.html.setOpenExternalLinks(False)
        self.stack.addWidget(self.html)

        layout.addWidget(self.stack, 1)
        self._show_message("Selecione um item para pré-visualizar.")

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._dirty:
            self._dirty = False
            self._load_preview()

    def set_detail(self, detail: EditionDetail | None) -> None:
        self.file_box.blockSignals(True)
        self.file_box.clear()
        self.file_box.blockSignals(False)

        if not detail or not detail.files:
            self.open_btn.setEnabled(False)
            self.read_btn.setEnabled(False)
            self._show_message("Nenhum arquivo associado.")
            return

        files = [_PreviewFile(path=f.path, fmt=(f.fmt or PathLike.guess_fmt(f.path))) for f in detail.files]
        for f in files:
            label = os.path.basename(f.path)
            self.file_box.addItem(label, f.path)

        self.open_btn.setEnabled(True)
        self.read_btn.setEnabled(True)
        self._dirty = True
        if self._active:
            self._dirty = False
            self._load_preview()
        else:
            self._show_message("Abra a aba Preview para carregar.")

    def _on_file_changed(self) -> None:
        self._dirty = True
        if self._active:
            self._dirty = False
            self._load_preview()

    def _current_path(self) -> str | None:
        data = self.file_box.currentData()
        return str(data) if data else None

    def _open_current(self) -> None:
        path = self._current_path()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_reader(self) -> None:
        path = self._current_path()
        if not path:
            return
        if self._reader_dialog is None:
            self._reader_dialog = ReaderDialog(self)
        self._reader_dialog.open_path(path)
        self._reader_dialog.show()
        self._reader_dialog.raise_()
        self._reader_dialog.activateWindow()

    def _load_preview(self) -> None:
        path = self._current_path()
        if not path:
            self._show_message("Nenhum arquivo selecionado.")
            return
        if not os.path.exists(path):
            self._show_message("Arquivo não encontrado no disco.")
            return

        ext = PathLike.guess_fmt(path)
        if ext == "pdf":
            self._load_pdf(path)
        elif ext == "epub":
            self._load_epub(path)
        else:
            self._show_message(f"Preview não suportado para .{ext}. Use “Abrir no sistema”.")

    def _load_pdf(self, path: str) -> None:
        error = self.pdf_doc.load(path)
        if self.pdf_doc.status() != QPdfDocument.Status.Ready:
            self._show_message(f"Falha ao carregar PDF: {error}")
            return
        self.stack.setCurrentWidget(self.pdf_view)

    def _load_epub(self, path: str) -> None:
        self._load_token += 1
        token = self._load_token
        self._show_message("Carregando EPUB…")
        task = _EpubLoadTask(token=token, path=path)
        task.signals.done.connect(self._on_epub_done)  # type: ignore[attr-defined]
        task.signals.failed.connect(self._on_epub_failed)  # type: ignore[attr-defined]
        self._pool.start(task)

    def _on_epub_done(self, token: int, html: str) -> None:
        if token != self._load_token:
            return
        self.html.setHtml(html)
        self.stack.setCurrentWidget(self.html)

    def _on_epub_failed(self, token: int, error: str) -> None:
        if token != self._load_token:
            return
        self._show_message(f"Falha ao carregar EPUB: {error}")

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)


class ReaderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Leitor")
        self.resize(1000, 760)
        self._pool = QThreadPool.globalInstance()
        self._load_token = 0
        self._current_path: str | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title_label = QLabel("Selecione um arquivo para leitura.")
        self.title_label.setWordWrap(True)
        header.addWidget(self.title_label, 1)

        self.external_btn = QPushButton("Abrir no sistema")
        self.external_btn.clicked.connect(self._open_external)  # type: ignore[attr-defined]
        header.addWidget(self.external_btn)

        self.close_btn = QPushButton("Fechar")
        self.close_btn.clicked.connect(self.close)  # type: ignore[attr-defined]
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.message = QLabel("Selecione um arquivo para leitura.")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.message)

        self.pdf_doc = QPdfDocument(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_doc)
        self.stack.addWidget(self.pdf_view)

        self.html = QTextBrowser()
        self.html.setOpenExternalLinks(True)
        self.stack.addWidget(self.html)

        layout.addWidget(self.stack, 1)
        self._show_message("Selecione um arquivo para leitura.")

    def open_path(self, path: str) -> None:
        self._current_path = path
        self.title_label.setText(os.path.basename(path))
        if not path or not os.path.exists(path):
            self._show_message("Arquivo não encontrado no disco.")
            return
        fmt = PathLike.guess_fmt(path)
        if fmt == "pdf":
            self._load_pdf(path)
            return
        if fmt == "epub":
            self._load_epub(path)
            return
        self._show_message(f"Formato .{fmt} não suportado no leitor. Abrindo no sistema…")
        self._open_external()

    def _open_external(self) -> None:
        if not self._current_path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_path))

    def _load_pdf(self, path: str) -> None:
        error = self.pdf_doc.load(path)
        if self.pdf_doc.status() != QPdfDocument.Status.Ready:
            self._show_message(f"Falha ao carregar PDF: {error}")
            return
        self.stack.setCurrentWidget(self.pdf_view)

    def _load_epub(self, path: str) -> None:
        self._load_token += 1
        token = self._load_token
        self._show_message("Carregando EPUB…")
        task = _EpubLoadTask(token=token, path=path)
        task.signals.done.connect(self._on_epub_done)  # type: ignore[attr-defined]
        task.signals.failed.connect(self._on_epub_failed)  # type: ignore[attr-defined]
        self._pool.start(task)

    def _on_epub_done(self, token: int, html: str) -> None:
        if token != self._load_token:
            return
        self.html.setHtml(html)
        self.stack.setCurrentWidget(self.html)

    def _on_epub_failed(self, token: int, error: str) -> None:
        if token != self._load_token:
            return
        self._show_message(f"Falha ao carregar EPUB: {error}")

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self.stack.setCurrentWidget(self.message)


class PathLike:
    @staticmethod
    def guess_fmt(path: str) -> str:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        return ext or "file"


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
        self.preview_tab = PreviewTab()
        self.preview_index = self.tabs.addTab(self.preview_tab, "Preview")
        self.tabs.currentChanged.connect(self._on_tab_changed)  # type: ignore[attr-defined]
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
        self.series_edit = QLineEdit()
        self.series_position_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.tags_edit = QLineEdit()
        self.year_edit = QLineEdit()
        self.pages_edit = QLineEdit()
        self.language_edit = QLineEdit()
        self.read_status_combo = QComboBox()
        self.read_status_combo.addItem("Não lido", "unread")
        self.read_status_combo.addItem("Lido", "read")
        self.rating_combo = QComboBox()
        self.rating_combo.addItem("Sem nota", None)
        for value in range(0, 6):
            self.rating_combo.addItem(str(value), float(value))
        self.external_rating_label = QLabel("—")
        self.description_edit = QTextEdit()
        form.addRow("Título", self.title_edit)
        form.addRow("Subtítulo", self.subtitle_edit)
        form.addRow("Série", self.series_edit)
        form.addRow("Volume", self.series_position_edit)
        form.addRow("Autores", self.author_edit)
        form.addRow("Tags", self.tags_edit)
        form.addRow("Ano", self.year_edit)
        form.addRow("Páginas", self.pages_edit)
        form.addRow("Idioma", self.language_edit)
        form.addRow("Status leitura", self.read_status_combo)
        form.addRow("Nota", self.rating_combo)
        form.addRow("Avaliação externa", self.external_rating_label)
        form.addRow("Descrição", self.description_edit)
        button_row = QHBoxLayout()
        self.save_btn = QPushButton("Salvar")
        self.save_btn.clicked.connect(self._emit_save)
        self.fetch_btn = QPushButton("Enriquecer metadados")
        self.fetch_btn.clicked.connect(self._emit_fetch)
        style = QApplication.style()
        if style:
            self.save_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_DialogSaveButton))
            self.fetch_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_BrowserReload))
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
            self.series_edit.clear()
            self.series_position_edit.clear()
            self.author_edit.clear()
            self.tags_edit.clear()
            self.year_edit.clear()
            self.pages_edit.clear()
            self.language_edit.clear()
            self.description_edit.clear()
            self.read_status_combo.setCurrentIndex(0)
            self.rating_combo.setCurrentIndex(0)
            self.external_rating_label.setText("—")
            self.status.setText("Selecione um item para editar.")
            self.save_btn.setEnabled(False)
            self.fetch_btn.setEnabled(False)
            self.preview_tab.set_detail(None)
            return
        self.save_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.title_edit.setText(detail.title)
        self.subtitle_edit.setText(detail.subtitle or "")
        self.series_edit.setText(detail.series or "")
        self.series_position_edit.setText("" if detail.series_position is None else str(detail.series_position))
        self.author_edit.setText(", ".join(detail.authors))
        self.tags_edit.setText(", ".join(detail.tags))
        self.year_edit.setText(str(detail.year or ""))
        self.pages_edit.setText(str(detail.pages or ""))
        self.language_edit.setText(detail.language or "")
        status_index = self.read_status_combo.findData(detail.read_status)
        self.read_status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        rating_index = self.rating_combo.findData(detail.rating)
        self.rating_combo.setCurrentIndex(rating_index if rating_index >= 0 else 0)
        self.external_rating_label.setText(self._format_external_ratings(detail))
        self.description_edit.setPlainText(detail.description or "")
        self.status.setText("Edite os campos e clique em Salvar.")
        self._populate_tables(detail)
        self.preview_tab.set_detail(detail)

    def _emit_save(self) -> None:
        if not self._on_save or not self.current_detail:
            return
        try:
            year_value = int(self.year_edit.text()) if self.year_edit.text().strip() else None
        except ValueError:
            year_value = None
        try:
            pages_value = int(self.pages_edit.text()) if self.pages_edit.text().strip() else None
        except ValueError:
            pages_value = None
        try:
            series_position = (
                float(self.series_position_edit.text())
                if self.series_position_edit.text().strip()
                else None
            )
        except ValueError:
            series_position = None
        detail = EditionDetail(
            edition_id=self.current_detail.edition_id,
            title=self.title_edit.text().strip(),
            subtitle=self.subtitle_edit.text().strip(),
            series=self.series_edit.text().strip() or None,
            series_position=series_position,
            authors=[name.strip() for name in self.author_edit.text().split(",") if name.strip()],
            tags=[name.strip() for name in self.tags_edit.text().split(",") if name.strip()],
            year=year_value,
            pages=pages_value,
            language=self.language_edit.text().strip() or None,
            description=self.description_edit.toPlainText().strip() or None,
            read_status=(self.read_status_combo.currentData() or "unread"),
            rating=self.rating_combo.currentData(),
        )
        self._on_save(detail)

    def _emit_fetch(self) -> None:
        if self._on_fetch:
            self._on_fetch()

    def update_status(self, message: str) -> None:
        self.status.setText(message)
        if message:
            QTimer.singleShot(4000, lambda: self.status.setText(""))

    def focus_title(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _on_tab_changed(self, index: int) -> None:
        self.preview_tab.set_active(index == self.preview_index)

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        return table

    def _format_external_ratings(self, detail: EditionDetail) -> str:
        ratings = detail.external_ratings or []
        if not ratings:
            return "—"
        parts: list[str] = []
        for rating in ratings:
            label = rating.source.replace("_", " ").title()
            avg = f"{rating.average:.2f}" if rating.average is not None else "—"
            if rating.count is not None:
                parts.append(f"{label}: {avg} ({rating.count})")
            else:
                parts.append(f"{label}: {avg}")
        return " | ".join(parts)

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
