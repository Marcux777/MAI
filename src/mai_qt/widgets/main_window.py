from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QStackedWidget,
    QMessageBox,
    QToolBar,
)

from ..services import BackendClient, CollectionService, EditionDetail, LibraryService
from ..widgets.library_page import LibraryPage
from ..widgets.detail_panel import DetailPanel
from ..widgets.collection_tree import CollectionTree
from ..widgets.organizer_panel import OrganizerPanel
from ..widgets.review_page import ReviewPage
from ..widgets.import_panel import ImportPanel
from ..pages.simple_pages import _simple_page


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

    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.library_page = LibraryPage(self.library_service)
        self.stack.addWidget(self.library_page)

        self.review_page = ReviewPage(self.backend)
        self.organizer_page = OrganizerPanel(self.backend)
        self.import_page = ImportPanel(self.backend)
        self.import_page.ingested.connect(self._on_ingest_completed)  # type: ignore[attr-defined]
        self.tasks_page = _simple_page("Tarefas", "Monitoramento das filas de processamento.")
        self.metrics_page = _simple_page("Métricas", "Indicadores-chave do pipeline.")
        self.settings_page = _simple_page("Configurações", "Preferências locais e provedores.")

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
        self.collection_tree.filter_changed.connect(self._on_collection_filter_changed)  # type: ignore[attr-defined]
        dock.setWidget(self.collection_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_detail_dock(self) -> None:
        dock = QDockWidget("Detalhes", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea)
        self.detail_panel = DetailPanel()
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

    def _refresh_all(self) -> None:
        self.collection_tree.refresh()
        self.library_page.refresh()

    def _on_ingest_completed(self, edition_id: int) -> None:
        self._refresh_all()

    def dragEnterEvent(self, event) -> None:  # pragma: no cover - GUI
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).is_file():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # pragma: no cover - GUI
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            event.ignore()
            return
        self.stack.setCurrentWidget(self.import_page)
        self.import_page.upload_files(paths)
        event.acceptProposedAction()

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
