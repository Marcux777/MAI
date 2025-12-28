from __future__ import annotations

import httpx

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from ..library_model import LibraryTableModel
from ..services import LibraryService


class _CoverSignals(QObject):
    loaded = Signal(str, bytes)
    failed = Signal(str, str)


class _CoverLoadTask(QRunnable):
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        super().__init__()
        self.url = url
        self.timeout = timeout
        self.signals = _CoverSignals()

    @Slot()
    def run(self) -> None:  # pragma: no cover - runs in Qt threadpool
        try:
            resp = httpx.get(self.url, timeout=self.timeout)
            resp.raise_for_status()
            data = bytes(resp.content or b"")
            if not data:
                raise RuntimeError("Resposta vazia")
            self.signals.loaded.emit(self.url, data)
        except Exception as exc:
            self.signals.failed.emit(self.url, str(exc))


class LibraryPage(QWidget):
    request_upload = Signal()
    request_scan = Signal()
    request_watcher = Signal()

    def __init__(self, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.model = LibraryTableModel()
        self.collection_id: int | None = None
        self.unfiled_only: bool = False
        self.query_text = ""
        self._rows = []
        self._cover_cache: dict[str, QPixmap] = {}
        self._cover_pending: set[str] = set()
        self._pool = QThreadPool.globalInstance()
        self._syncing = False
        self._view_mode = "list"
        self._cover_size = QSize(110, 160)
        self._placeholder = self._build_placeholder()
        self._placeholder_icon = QIcon(self._placeholder)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self.refresh)  # type: ignore[attr-defined]
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh)  # type: ignore[attr-defined]

        self.view_list_btn = QPushButton("Lista")
        self.view_list_btn.setCheckable(True)
        self.view_list_btn.setChecked(True)
        self.view_list_btn.clicked.connect(lambda: self._set_view_mode("list"))  # type: ignore[attr-defined]

        self.view_grid_btn = QPushButton("Grade")
        self.view_grid_btn.setCheckable(True)
        self.view_grid_btn.clicked.connect(lambda: self._set_view_mode("grid"))  # type: ignore[attr-defined]

        style = QApplication.style()
        if style:
            self.refresh_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_BrowserReload))
            self.view_list_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_FileDialogDetailedView))
            self.view_grid_btn.setIcon(style.standardIcon(style.StandardPixmap.SP_FileDialogListView))

        self.info = QLabel("")
        self.info.setObjectName("infoLabel")

        header.addWidget(self.refresh_btn)
        header.addWidget(self.view_list_btn)
        header.addWidget(self.view_grid_btn)
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
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection)  # type: ignore[attr-defined]

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWrapping(True)
        self.grid.setIconSize(self._cover_size)
        self.grid.setGridSize(QSize(self._cover_size.width() + 30, self._cover_size.height() + 50))
        self.grid.setSpacing(10)
        self.grid.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.grid.itemSelectionChanged.connect(self._on_grid_selection)  # type: ignore[attr-defined]

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.table)
        self.view_stack.addWidget(self.grid)
        self.empty_state = self._build_empty_state()
        self.view_stack.addWidget(self.empty_state)
        layout.addWidget(self.view_stack)

    def set_collection_filter(self, collection_id: int | None, unfiled_only: bool = False) -> None:
        self.collection_id = collection_id
        self.unfiled_only = unfiled_only
        self.refresh()

    def set_query(self, text: str) -> None:
        self.query_text = (text or "").strip()
        self._schedule_refresh()

    def refresh(self) -> None:
        rows = self.service.list_books(
            query=self.query_text,
            collection_id=self.collection_id,
            unfiled_only=self.unfiled_only,
        )
        self._rows = rows
        self.model.set_rows(rows)
        self._populate_grid(rows)
        self.info.setText(f"{len(rows)} itens")
        self._search_timer.stop()
        self._update_empty_state()

    def selected_edition_ids(self) -> list[int]:
        if self.view_stack.currentWidget() == self.grid:
            ids = []
            for item in self.grid.selectedItems():
                edition_id = item.data(Qt.ItemDataRole.UserRole)
                if edition_id is not None:
                    ids.append(int(edition_id))
            return ids
        selection = self.table.selectionModel().selectedRows()
        ids: list[int] = []
        for index in selection:
            row = self.model.book_at(index.row())
            if row:
                ids.append(int(row.edition_id))
        return ids

    def select_edition(self, edition_id: int) -> bool:
        if self._syncing:
            return False
        self._syncing = True
        for row_index in range(self.model.rowCount()):
            row = self.model.book_at(row_index)
            if not row:
                continue
            if int(row.edition_id) != int(edition_id):
                continue
            self.table.selectRow(row_index)
            self.table.scrollTo(self.model.index(row_index, 0))
            self._select_grid_item(edition_id)
            self._syncing = False
            return True
        self._syncing = False
        return False

    def _schedule_refresh(self) -> None:
        self._search_timer.start()

    def _set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        if not self._rows:
            self.view_stack.setCurrentWidget(self.empty_state)
            self.view_list_btn.setChecked(mode != "grid")
            self.view_grid_btn.setChecked(mode == "grid")
            return
        if mode == "grid":
            self.view_list_btn.setChecked(False)
            self.view_grid_btn.setChecked(True)
            self.view_stack.setCurrentWidget(self.grid)
        else:
            self.view_list_btn.setChecked(True)
            self.view_grid_btn.setChecked(False)
            self.view_stack.setCurrentWidget(self.table)

    def _populate_grid(self, rows) -> None:
        self.grid.clear()
        for row in rows:
            item = QListWidgetItem(row.title)
            item.setData(Qt.ItemDataRole.UserRole, int(row.edition_id))
            cover_url = row.cover_url
            item.setData(Qt.ItemDataRole.UserRole + 1, cover_url)
            icon = self._placeholder_icon
            if cover_url:
                cached = self._cover_cache.get(cover_url)
                if cached:
                    icon = QIcon(cached)
                else:
                    self._queue_cover(cover_url)
            item.setIcon(icon)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addItem(item)

    def _queue_cover(self, url: str) -> None:
        if url in self._cover_pending:
            return
        self._cover_pending.add(url)
        task = _CoverLoadTask(url)
        task.signals.loaded.connect(self._on_cover_loaded)  # type: ignore[attr-defined]
        task.signals.failed.connect(self._on_cover_failed)  # type: ignore[attr-defined]
        self._pool.start(task)

    def _on_cover_loaded(self, url: str, data: bytes) -> None:
        self._cover_pending.discard(url)
        image = QImage.fromData(data)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self._cover_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_cache[url] = pixmap
        self._update_grid_icons(url, QIcon(pixmap))

    def _on_cover_failed(self, url: str, _error: str) -> None:
        self._cover_pending.discard(url)

    def _update_grid_icons(self, url: str, icon: QIcon) -> None:
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1) == url:
                item.setIcon(icon)

    def _build_placeholder(self) -> QPixmap:
        pixmap = QPixmap(self._cover_size)
        pixmap.fill(QColor("#2d2d2d"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#d0d0d0"))
        painter.drawRect(pixmap.rect().adjusted(0, 0, -1, -1))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Sem\ncapa")
        painter.end()
        return pixmap

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Sua biblioteca esta vazia")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        subtitle = QLabel("Importe arquivos ou escaneie uma pasta para comecar.")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        buttons = QHBoxLayout()
        btn_import = QPushButton("Importar arquivos")
        btn_import.clicked.connect(self.request_upload.emit)  # type: ignore[attr-defined]
        btn_scan = QPushButton("Executar scan")
        btn_scan.clicked.connect(self.request_scan.emit)  # type: ignore[attr-defined]
        btn_watch = QPushButton("Iniciar watcher")
        btn_watch.clicked.connect(self.request_watcher.emit)  # type: ignore[attr-defined]
        buttons.addWidget(btn_import)
        buttons.addWidget(btn_scan)
        buttons.addWidget(btn_watch)

        hint = QLabel("Arraste e solte arquivos aqui")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(buttons)
        layout.addWidget(hint)
        return widget

    def _update_empty_state(self) -> None:
        if not self._rows:
            self.view_stack.setCurrentWidget(self.empty_state)
            return
        if self._view_mode == "grid":
            self.view_stack.setCurrentWidget(self.grid)
        else:
            self.view_stack.setCurrentWidget(self.table)

    def _on_table_selection(self) -> None:
        if self._syncing:
            return
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            return
        row = self.model.book_at(selection[0].row())
        if not row:
            return
        self._syncing = True
        self._select_grid_item(int(row.edition_id))
        self._syncing = False

    def _on_grid_selection(self) -> None:
        if not self.grid.selectedItems():
            if not self._syncing:
                self._syncing = True
                self.table.clearSelection()
                self._syncing = False
            return
        item = self.grid.currentItem()
        if not item:
            return
        edition_id = item.data(Qt.ItemDataRole.UserRole)
        if edition_id is None:
            return
        self.select_edition(int(edition_id))

    def _select_grid_item(self, edition_id: int) -> None:
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == int(edition_id):
                self.grid.setCurrentItem(item)
                self.grid.scrollToItem(item)
                break
