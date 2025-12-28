from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from mai.core.config import get_settings
from mai.core.logging import configure_logging, logger
from mai.db.init import apply_schema

from .widgets.main_window import MainWindow


def _apply_material_theme(app: QApplication, theme: str | None) -> None:
    if not theme:
        return
    if str(theme).strip().lower() in {"none", "off", "false", "0"}:
        return
    try:
        from qt_material import apply_stylesheet  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional pkg
        logger.warning("Qt-Material não disponível (%s). Usando tema padrão.", exc)
        return
    try:
        apply_stylesheet(app, theme=theme)
    except Exception as exc:  # pragma: no cover - runtime theme failure
        logger.warning("Falha ao aplicar tema Qt-Material (%s).", exc)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.debug)
    apply_schema()
    app = QApplication(sys.argv)
    _apply_material_theme(app, settings.qt_theme)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
