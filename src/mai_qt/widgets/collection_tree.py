from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from ..services import CollectionRow, CollectionService


class CollectionTree(QTreeWidget):
    filter_changed = Signal(object, bool)  # collection_id (or None), unfiled_only

    _ROLE_KIND = Qt.ItemDataRole.UserRole + 1
    _ROLE_COLLECTION_ID = Qt.ItemDataRole.UserRole + 2

    _KIND_ALL = "all"
    _KIND_UNFILED = "unfiled"
    _KIND_GROUP = "group"
    _KIND_COLLECTION = "collection"

    def __init__(self, service: CollectionService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_context_menu)  # type: ignore[attr-defined]
        self.itemSelectionChanged.connect(self._emit_filter)  # type: ignore[attr-defined]
        self.refresh()

    def current_filter(self) -> tuple[int | None, bool]:
        item = self.currentItem()
        if not item:
            return None, False
        kind = item.data(0, self._ROLE_KIND)
        if kind == self._KIND_UNFILED:
            return None, True
        if kind == self._KIND_COLLECTION:
            return int(item.data(0, self._ROLE_COLLECTION_ID)), False
        return None, False

    def refresh(self, select_collection_id: int | None = None) -> None:
        self.clear()

        total = self.service.total_editions()
        unfiled = self.service.unfiled_count()
        collections = self.service.list_collections()

        root = QTreeWidgetItem(["Biblioteca"])
        root.setData(0, self._ROLE_KIND, self._KIND_GROUP)
        self.addTopLevelItem(root)
        root.setExpanded(True)

        all_item = QTreeWidgetItem([f"Todos os itens ({total})"])
        all_item.setData(0, self._ROLE_KIND, self._KIND_ALL)
        root.addChild(all_item)

        unfiled_item = QTreeWidgetItem([f"Sem coleção ({unfiled})"])
        unfiled_item.setData(0, self._ROLE_KIND, self._KIND_UNFILED)
        root.addChild(unfiled_item)

        group = QTreeWidgetItem(["Coleções"])
        group.setData(0, self._ROLE_KIND, self._KIND_GROUP)
        root.addChild(group)
        group.setExpanded(True)

        items_by_parent: Dict[int | None, List[CollectionRow]] = defaultdict(list)
        for row in collections:
            items_by_parent[row.parent_id].append(row)
        for parent_id in items_by_parent:
            items_by_parent[parent_id].sort(key=lambda r: r.name.casefold())

        def add_children(parent_item: QTreeWidgetItem, parent_id: int | None) -> None:
            for row in items_by_parent.get(parent_id, []):
                label = f"{row.name} ({row.item_count})" if row.item_count else row.name
                node = QTreeWidgetItem([label])
                node.setData(0, self._ROLE_KIND, self._KIND_COLLECTION)
                node.setData(0, self._ROLE_COLLECTION_ID, int(row.id))
                parent_item.addChild(node)
                add_children(node, row.id)

        add_children(group, None)

        if select_collection_id is not None:
            if self.select_collection(select_collection_id):
                return
        self.setCurrentItem(all_item)

    def prompt_new_collection(self) -> None:
        self._create_collection(parent_item=None)

    def select_collection(self, collection_id: int) -> bool:
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, self._ROLE_KIND) == self._KIND_COLLECTION and int(
                item.data(0, self._ROLE_COLLECTION_ID)
            ) == int(collection_id):
                return item
            for idx in range(item.childCount()):
                found = walk(item.child(idx))
                if found:
                    return found
            return None

        for top_idx in range(self.topLevelItemCount()):
            found = walk(self.topLevelItem(top_idx))
            if found:
                self.setCurrentItem(found)
                return True
        return False

    def _emit_filter(self) -> None:
        collection_id, unfiled = self.current_filter()
        self.filter_changed.emit(collection_id, unfiled)

    def _open_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        kind = item.data(0, self._ROLE_KIND) if item else None
        menu = QMenu(self)

        if kind in (self._KIND_GROUP, None, self._KIND_ALL, self._KIND_UNFILED):
            action_new = menu.addAction("Nova coleção…")
            action_new.triggered.connect(lambda: self._create_collection(parent_item=None))  # type: ignore[attr-defined]
        elif kind == self._KIND_COLLECTION:
            collection_id = int(item.data(0, self._ROLE_COLLECTION_ID))
            action_new = menu.addAction("Nova subcoleção…")
            action_new.triggered.connect(lambda: self._create_collection(parent_item=item))  # type: ignore[attr-defined]
            menu.addSeparator()
            action_rename = menu.addAction("Renomear…")
            action_rename.triggered.connect(lambda: self._rename_collection(item, collection_id))  # type: ignore[attr-defined]
            action_delete = menu.addAction("Excluir…")
            action_delete.triggered.connect(lambda: self._delete_collection(item, collection_id))  # type: ignore[attr-defined]

        menu.addSeparator()
        action_refresh = menu.addAction("Atualizar")
        action_refresh.triggered.connect(self.refresh)  # type: ignore[attr-defined]

        if not menu.actions():
            return
        menu.exec(self.viewport().mapToGlobal(pos))

    def _create_collection(self, parent_item: QTreeWidgetItem | None) -> None:
        parent_id: int | None = None
        if parent_item and parent_item.data(0, self._ROLE_KIND) == self._KIND_COLLECTION:
            parent_id = int(parent_item.data(0, self._ROLE_COLLECTION_ID))
        name, ok = QInputDialog.getText(self, "Nova coleção", "Nome da coleção:")
        if not ok:
            return
        try:
            new_id = self.service.create_collection(name, parent_id=parent_id)
        except Exception as exc:
            QMessageBox.critical(self, "Coleções", str(exc))
            return
        self.refresh(select_collection_id=new_id)

    def _rename_collection(self, item: QTreeWidgetItem, collection_id: int) -> None:
        current_label = item.text(0).split(" (", 1)[0]
        name, ok = QInputDialog.getText(self, "Renomear coleção", "Novo nome:", text=current_label)
        if not ok:
            return
        try:
            self.service.rename_collection(collection_id, name)
        except Exception as exc:
            QMessageBox.critical(self, "Coleções", str(exc))
            return
        self.refresh(select_collection_id=collection_id)

    def _delete_collection(self, item: QTreeWidgetItem, collection_id: int) -> None:
        label = item.text(0).split(" (", 1)[0]
        result = QMessageBox.question(
            self,
            "Excluir coleção",
            f"Excluir a coleção “{label}” e suas subcoleções?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_collection(collection_id)
        except Exception as exc:
            QMessageBox.critical(self, "Coleções", str(exc))
            return
        self.refresh()
