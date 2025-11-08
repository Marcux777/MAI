from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QWidget,
    QMessageBox,
)

from ..services import LibraryService, EditionDetail, BackendClient
from ..widgets.library_page import LibraryPage
from ..widgets.detail_panel import DetailPanel
from ..widgets.organizer_panel import OrganizerPanel
from ..widgets.review_page import ReviewPage
from ..widgets.import_panel import ImportPanel
from ..pages.simple_pages import _simple_page


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MAI — Biblioteca Local")
        self.resize(1400, 900)
        self.library_service = LibraryService()
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

        self._build_sidebar()
        self._build_detail_dock()
        self._build_menu()

    def _build_sidebar(self) -> None:
        dock = QDockWidget("Módulos", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        menu = QListWidget()
        items = [
            ("Biblioteca", self.library_page),
            ("Revisão", self.review_page),
            ("Organizer", self.organizer_page),
            ("Importar", self.import_page),
            ("Tarefas", self.tasks_page),
            ("Métricas", self.metrics_page),
            ("Config", self.settings_page),
        ]
        for title, page in items:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, page)
            menu.addItem(item)
        menu.currentRowChanged.connect(lambda idx: self.stack.setCurrentIndex(idx))  # type: ignore[attr-defined]
        menu.setCurrentRow(0)
        dock.setWidget(menu)
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

    def _build_menu(self) -> None:
        refresh_action = QAction("Recarregar", self)
        refresh_action.triggered.connect(self.library_page.refresh)  # type: ignore[attr-defined]
        self.menuBar().addAction(refresh_action)

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
