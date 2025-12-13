from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QUrl, Qt
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QMessageBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..services import BackendClient, CollectionService, EditionDetail, LibraryService
from ..widgets.library_page import LibraryPage
from ..widgets.detail_panel import DetailPanel
from ..widgets.collection_tree import CollectionTree
from ..widgets.organizer_panel import OrganizerPanel
from ..widgets.review_page import ReviewPage
from ..widgets.import_panel import ImportPanel
from ..pages.simple_pages import _simple_page

_SUPPORTED_DROP_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw", ".azw3"}


class _DropOverlay(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.setVisible(False)
        self.setAcceptDrops(True)
        self._label = QLabel("Solte o arquivo para importar")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: white; font-size: 22px; font-weight: 600;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.setStyleSheet(
            "background-color: rgba(0, 0, 0, 140);"
            "border: 3px dashed rgba(255, 255, 255, 200);"
            "border-radius: 10px;"
        )

    def set_count(self, count: int) -> None:
        if count <= 1:
            self._label.setText("Solte o arquivo para importar")
        else:
            self._label.setText(f"Solte {count} arquivos para importar")

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._window._accept_drag_event(event):
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._window._accept_drag_event(event):
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._window._handle_drop_event(event):
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # pragma: no cover - GUI
        self._window._hide_drop_overlay()
        event.accept()


class _GlobalFileDropFilter(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # pragma: no cover - GUI
        if event.type() not in {
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.DragLeave,
            QEvent.Type.Drop,
        }:
            return False

        target = QApplication.widgetAt(QCursor.pos())
        if target is None and isinstance(obj, QWidget):
            target = obj
        if target is None or target.window() is not self._window:
            return False

        if hasattr(self._window, "_drop_overlay") and target is self._window._drop_overlay:
            return False

        if event.type() in {QEvent.Type.DragEnter, QEvent.Type.DragMove}:
            return self._window._accept_drag_event(event)

        if event.type() == QEvent.Type.DragLeave:
            self._window._hide_drop_overlay()
            return False

        if event.type() == QEvent.Type.Drop:
            return self._window._handle_drop_event(event)

        return False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MAI — Biblioteca Local")
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.library_service = LibraryService()
        self.collection_service = CollectionService()
        self.backend = BackendClient()
        self.current_detail: EditionDetail | None = None
        self._build_ui()
        self._install_global_drop_filter()

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.stack.setAcceptDrops(True)
        self.setCentralWidget(self.stack)
        self._drop_overlay = _DropOverlay(self)
        self._drop_overlay.setGeometry(self.rect())

        self.library_page = LibraryPage(self.library_service)
        self.library_page.setAcceptDrops(True)
        self.library_page.table.setAcceptDrops(True)
        self.library_page.table.viewport().setAcceptDrops(True)
        self.stack.addWidget(self.library_page)

        self.review_page = ReviewPage(self.backend)
        self.organizer_page = OrganizerPanel(self.backend)
        self.import_page = ImportPanel(self.backend)
        for page in [
            self.review_page,
            self.organizer_page,
            self.import_page,
        ]:
            page.setAcceptDrops(True)
        self.import_page.ingested.connect(self._on_ingest_completed)  # type: ignore[attr-defined]
        self.import_page.upload_error.connect(self._on_upload_error)  # type: ignore[attr-defined]
        self.import_page.upload_finished.connect(self._on_upload_finished)  # type: ignore[attr-defined]
        self.tasks_page = _simple_page("Tarefas", "Monitoramento das filas de processamento.")
        self.metrics_page = _simple_page("Métricas", "Indicadores-chave do pipeline.")
        self.settings_page = _simple_page("Configurações", "Preferências locais e provedores.")
        for page in [self.tasks_page, self.metrics_page, self.settings_page]:
            page.setAcceptDrops(True)

        for page in [
            self.review_page,
            self.organizer_page,
            self.import_page,
            self.tasks_page,
            self.metrics_page,
            self.settings_page,
        ]:
            self.stack.addWidget(page)

        self._build_collections_dock()
        self._build_detail_dock()
        self._build_toolbar()

    def _build_collections_dock(self) -> None:
        dock = QDockWidget("Biblioteca", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.collection_tree = CollectionTree(self.collection_service)
        self.collection_tree.setAcceptDrops(True)
        self.collection_tree.filter_changed.connect(self._on_collection_filter_changed)  # type: ignore[attr-defined]
        dock.setWidget(self.collection_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_detail_dock(self) -> None:
        dock = QDockWidget("Detalhes", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.detail_panel = DetailPanel()
        self.detail_panel.setAcceptDrops(True)
        self.detail_panel.bind_save(self._save_detail)
        self.detail_panel.bind_fetch(self._fetch_detail)
        dock.setWidget(self.detail_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        table = self.library_page.table
        table.selectionModel().selectionChanged.connect(self._update_detail)  # type: ignore[attr-defined]
        table.selectionModel().selectionChanged.connect(self._update_collection_actions)  # type: ignore[attr-defined]

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("MAI", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def nav(title: str, page) -> QAction:
            action = QAction(title, self)
            action.triggered.connect(lambda: self.stack.setCurrentWidget(page))  # type: ignore[attr-defined]
            toolbar.addAction(action)
            return action

        nav("Biblioteca", self.library_page)
        nav("Revisão", self.review_page)
        nav("Organizer", self.organizer_page)
        nav("Importar", self.import_page)
        nav("Tarefas", self.tasks_page)
        nav("Métricas", self.metrics_page)
        nav("Config", self.settings_page)

        toolbar.addSeparator()

        self.action_new_collection = QAction("Nova coleção", self)
        self.action_new_collection.triggered.connect(lambda: self.collection_tree.prompt_new_collection())  # type: ignore[attr-defined]
        toolbar.addAction(self.action_new_collection)

        self.action_add_to_collection = QAction("Adicionar selecionados", self)
        self.action_add_to_collection.triggered.connect(self._add_selected_to_collection)  # type: ignore[attr-defined]
        toolbar.addAction(self.action_add_to_collection)

        self.action_remove_from_collection = QAction("Remover selecionados", self)
        self.action_remove_from_collection.triggered.connect(self._remove_selected_from_collection)  # type: ignore[attr-defined]
        toolbar.addAction(self.action_remove_from_collection)

        self.action_delete_selected = QAction("Excluir selecionados", self)
        self.action_delete_selected.triggered.connect(self._delete_selected)  # type: ignore[attr-defined]
        toolbar.addAction(self.action_delete_selected)

        toolbar.addSeparator()

        refresh_action = QAction("Recarregar", self)
        refresh_action.triggered.connect(self._refresh_all)  # type: ignore[attr-defined]
        toolbar.addAction(refresh_action)

        self._update_collection_actions()

    def _install_global_drop_filter(self) -> None:  # pragma: no cover - GUI
        app = QApplication.instance()
        if not app:
            return
        self._drop_filter = _GlobalFileDropFilter(self)
        app.installEventFilter(self._drop_filter)

    def _refresh_all(self) -> None:
        self.collection_tree.refresh()
        self.library_page.refresh()

    def _show_drop_overlay(self, count: int) -> None:  # pragma: no cover - GUI
        self._drop_overlay.set_count(count)
        self._drop_overlay.setGeometry(self.rect())
        self._drop_overlay.raise_()
        self._drop_overlay.show()

    def _hide_drop_overlay(self) -> None:  # pragma: no cover - GUI
        self._drop_overlay.hide()

    def _on_ingest_completed(self, edition_id: int) -> None:
        on_library = self.stack.currentWidget() == self.library_page
        self._refresh_all()
        if on_library:
            self.library_page.select_edition(edition_id)
        self.statusBar().showMessage(f"Ingestão concluída (edition_id={edition_id}).", 8000)

    def _drop_paths_from_event(self, event) -> list[str]:  # pragma: no cover - GUI
        mime = event.mimeData()
        raw_paths: list[str] = []

        def _add(path: str) -> None:
            value = (path or "").strip()
            if not value:
                return
            if Path(value).suffix.lower() not in _SUPPORTED_DROP_EXTENSIONS:
                return
            raw_paths.append(value)

        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    _add(url.toLocalFile())
                else:
                    _add(url.toString())

        for fmt in ("text/uri-list", "x-special/gnome-copied-files"):
            if not mime.hasFormat(fmt):
                continue
            data = bytes(mime.data(fmt)).decode("utf-8", errors="ignore")
            for idx, raw in enumerate(data.splitlines()):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if fmt == "x-special/gnome-copied-files" and idx == 0 and line.lower() in {"copy", "cut"}:
                    continue
                if line.startswith("file://"):
                    _add(QUrl(line).toLocalFile())
                else:
                    _add(line)

        for fmt in (
            'application/x-qt-windows-mime;value="FileNameW"',
            'application/x-qt-windows-mime;value="FileName"',
        ):
            if not mime.hasFormat(fmt):
                continue
            raw = bytes(mime.data(fmt))
            if "FileNameW" in fmt:
                text = raw.decode("utf-16le", errors="ignore")
            else:
                text = raw.decode("utf-8", errors="ignore")
            for part in text.split("\x00"):
                _add(part)

        if mime.hasText():
            text = (mime.text() or "").strip()
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("file://"):
                    _add(QUrl(line).toLocalFile())
                else:
                    _add(line)

        if os.getenv("MAI_QT_DND_DEBUG"):
            print(
                "DnD mime formats:",
                mime.formats(),
                "urls:",
                len(mime.urls()) if mime.hasUrls() else 0,
                "text_len:",
                len(mime.text() or "") if mime.hasText() else 0,
                "paths:",
                raw_paths[:3],
            )

        seen: set[str] = set()
        paths: list[str] = []
        for item in raw_paths:
            if item in seen:
                continue
            seen.add(item)
            paths.append(item)
        return paths

    def _accept_drag_event(self, event) -> bool:  # pragma: no cover - GUI
        paths = self._drop_paths_from_event(event)
        if paths:
            self._show_drop_overlay(len(paths))
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            return True
        self._hide_drop_overlay()
        return False

    def _handle_drop_event(self, event) -> bool:  # pragma: no cover - GUI
        paths = self._drop_paths_from_event(event)
        if not paths:
            self._hide_drop_overlay()
            return False
        self._hide_drop_overlay()

        existing = [p for p in paths if Path(p).is_file()]
        missing = [p for p in paths if p not in existing]

        if not existing:
            first = missing[0] if missing else ""
            msg = (
                "Não consegui acessar o arquivo dentro do ambiente atual.\n\n"
                f"Exemplo: {first}\n\n"
                "Se estiver rodando o Qt via Docker:\n"
                "- Garanta que você rodou `make qt` (sem sudo), para montar seu $HOME no container.\n"
                "- Ou mova o arquivo para um diretório montado (ex.: seu $HOME).\n"
            )
            QMessageBox.information(self, "Upload (drag-and-drop)", msg)
            self.statusBar().showMessage("Arquivo não acessível dentro do container.", 12000)
            event.ignore()
            return True

        if missing:
            self.statusBar().showMessage(
                f"{len(missing)} arquivo(s) não acessíveis; enviando {len(existing)} arquivo(s)…",
                8000,
            )

        self.statusBar().showMessage(f"Enviando {len(existing)} arquivo(s) para ingestão…")
        self.import_page.upload_files(existing)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.acceptProposedAction()
        return True

    def _on_upload_error(self, message: str) -> None:
        self.statusBar().showMessage("Falha no upload. Abra a aba Importar para ver detalhes.", 12000)

    def _on_upload_finished(self, ok: int, failed: int) -> None:
        if ok == 0 and failed == 0:
            return
        self.statusBar().showMessage(f"Upload finalizado: {ok} ok, {failed} falha(s).", 12000)

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._accept_drag_event(event):
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._accept_drag_event(event):
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # pragma: no cover - GUI
        self._hide_drop_overlay()
        event.accept()

    def dropEvent(self, event) -> None:  # pragma: no cover - GUI
        if self._handle_drop_event(event):
            return
        event.ignore()

    def resizeEvent(self, event) -> None:  # pragma: no cover - GUI
        super().resizeEvent(event)
        if hasattr(self, "_drop_overlay"):
            self._drop_overlay.setGeometry(self.rect())

    def _update_detail(self) -> None:
        selection = self.library_page.table.selectionModel().selectedRows()
        if not selection:
            self._populate_detail(None)
            return
        index = selection[0]
        book = self.library_page.model.book_at(index.row())
        self._populate_detail(book)

    def _populate_detail(self, book):
        if not book:
            self.current_detail = None
            self.detail_panel.set_detail(None)
            return
        detail = self.library_service.get_detail(book.edition_id)
        self.current_detail = detail
        self.detail_panel.set_detail(detail)

    def _save_detail(self, detail: EditionDetail) -> None:
        try:
            self.library_service.save_detail(detail)
        except Exception as exc:
            QMessageBox.critical(self, "Erro ao salvar", str(exc))
            self.detail_panel.update_status("Erro ao salvar metadados.")
            return
        self.detail_panel.update_status("Metadados salvos.")
        self.library_page.refresh()

    def _fetch_detail(self) -> None:
        if not self.current_detail:
            QMessageBox.information(self, "Enriquecimento", "Selecione um item antes de buscar metadados.")
            return
        edition_id = self.current_detail.edition_id
        try:
            result = self.backend.fetch_providers(edition_id)
        except Exception as exc:
            QMessageBox.critical(self, "Enriquecimento", f"Falha ao consultar provedores: {exc}")
            self.detail_panel.update_status("Erro ao consultar provedores.")
            return
        top = result.get("top_score") or 0.0
        auto = result.get("auto_applied")
        QMessageBox.information(
            self,
            "Enriquecimento",
            f"Consulta concluída. Top score: {top:.2f} — {'Aplicado' if auto else 'Disponível para revisão'}.",
        )
        self.library_page.refresh()
        detail = self.library_service.get_detail(edition_id)
        self.detail_panel.set_detail(detail)

    def _on_collection_filter_changed(self, collection_id: int | None, unfiled_only: bool) -> None:
        self.library_page.set_collection_filter(collection_id=collection_id, unfiled_only=unfiled_only)
        self._update_collection_actions()

    def _update_collection_actions(self) -> None:
        if not hasattr(self, "action_add_to_collection"):
            return
        collection_id, unfiled = self.collection_tree.current_filter()
        has_collection_target = collection_id is not None and not unfiled
        has_selection = bool(self.library_page.selected_edition_ids())
        self.action_add_to_collection.setEnabled(has_collection_target and has_selection)
        self.action_remove_from_collection.setEnabled(has_collection_target and has_selection)
        if hasattr(self, "action_delete_selected"):
            self.action_delete_selected.setEnabled(has_selection)

    def _add_selected_to_collection(self) -> None:
        collection_id, unfiled = self.collection_tree.current_filter()
        if collection_id is None or unfiled:
            QMessageBox.information(self, "Coleções", "Selecione uma coleção para adicionar itens.")
            return
        edition_ids = self.library_page.selected_edition_ids()
        if not edition_ids:
            QMessageBox.information(self, "Coleções", "Selecione um ou mais itens na tabela.")
            return
        try:
            self.collection_service.add_editions(collection_id, edition_ids)
        except Exception as exc:
            QMessageBox.critical(self, "Coleções", str(exc))
            return
        self.collection_tree.refresh(select_collection_id=collection_id)
        self.library_page.refresh()

    def _remove_selected_from_collection(self) -> None:
        collection_id, unfiled = self.collection_tree.current_filter()
        if collection_id is None or unfiled:
            QMessageBox.information(self, "Coleções", "Selecione uma coleção para remover itens.")
            return
        edition_ids = self.library_page.selected_edition_ids()
        if not edition_ids:
            QMessageBox.information(self, "Coleções", "Selecione um ou mais itens na tabela.")
            return
        try:
            self.collection_service.remove_editions(collection_id, edition_ids)
        except Exception as exc:
            QMessageBox.critical(self, "Coleções", str(exc))
            return
        self.collection_tree.refresh(select_collection_id=collection_id)
        self.library_page.refresh()

    def _delete_selected(self) -> None:
        edition_ids = self.library_page.selected_edition_ids()
        if not edition_ids:
            QMessageBox.information(self, "Excluir", "Selecione um ou mais itens na tabela.")
            return

        resp = QMessageBox.question(
            self,
            "Excluir do catálogo",
            f"Excluir {len(edition_ids)} item(ns) do catálogo?\n\n"
            "Isso remove a edição e os registros de arquivos associados (os arquivos no disco não serão apagados).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self.library_service.delete_editions(edition_ids, delete_disk=False)
        except Exception as exc:
            QMessageBox.critical(self, "Excluir", str(exc))
            return

        deleted = int(result.get("deleted") or 0)
        deleted_files = int(result.get("deleted_files") or 0)
        errors = result.get("disk_errors") or []
        if errors:
            QMessageBox.warning(self, "Excluir", f"Concluído com avisos.\n\n{errors[0]}")
        else:
            QMessageBox.information(
                self,
                "Excluir",
                f"Exclusão concluída: {deleted} item(ns), {deleted_files} arquivo(s) removido(s) do catálogo.",
            )

        self.library_page.refresh()
        self.collection_tree.refresh()
        self._populate_detail(None)
