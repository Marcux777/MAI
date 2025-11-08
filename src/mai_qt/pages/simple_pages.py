from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget


def _simple_page(title: str, description: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    header = QLabel(f"<h2>{title}</h2><p>{description}</p>")
    header.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(header)
    log = QTextEdit()
    log.setPlainText("Área em desenvolvimento. Este painel será preenchido conforme o roadmap Qt.")
    log.setReadOnly(True)
    layout.addWidget(log)
    return widget
