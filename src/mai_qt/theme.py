from __future__ import annotations

from PySide6.QtGui import QPalette, QColor


def apply_theme(app, mode: str = "dark") -> None:
    palette = QPalette()
    if mode == "dark":
        palette.setColor(QPalette.Window, QColor(14, 22, 36))
        palette.setColor(QPalette.WindowText, QColor(230, 236, 245))
        palette.setColor(QPalette.Base, QColor(18, 26, 40))
        palette.setColor(QPalette.AlternateBase, QColor(24, 34, 52))
        palette.setColor(QPalette.ToolTipBase, QColor(230, 236, 245))
        palette.setColor(QPalette.ToolTipText, QColor(14, 22, 36))
        palette.setColor(QPalette.Text, QColor(230, 236, 245))
        palette.setColor(QPalette.Button, QColor(22, 32, 50))
        palette.setColor(QPalette.ButtonText, QColor(230, 236, 245))
        palette.setColor(QPalette.Highlight, QColor(37, 99, 235))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    else:
        palette = QPalette()
    app.setPalette(palette)
