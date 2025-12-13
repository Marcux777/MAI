from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from mai.core.config import get_settings
from mai.core.logging import configure_logging
from mai.db.init import apply_schema

from .widgets.main_window import MainWindow


def main() -> None:
    settings = get_settings()
    configure_logging(settings.debug)
    apply_schema()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
