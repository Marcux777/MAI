from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class SettingsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)

        self.nav = QListWidget()
        self.nav.setFixedWidth(200)
        self.nav.setSpacing(4)
        layout.addWidget(self.nav)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        sections = [
            ("Geral", self._section_general()),
            ("Biblioteca", self._section_library()),
            ("Metadados", self._section_metadata()),
            ("OCR", self._section_ocr()),
            ("Organizador", self._section_organizer()),
            ("Interface", self._section_ui()),
            ("API/OPDS", self._section_api()),
            ("Backup", self._section_backup()),
        ]

        for title, widget in sections:
            self.nav.addItem(title)
            self.stack.addWidget(widget)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)  # type: ignore[attr-defined]
        if self.nav.count() > 0:
            self.nav.setCurrentRow(0)

    def _section_general(self) -> QWidget:
        return self._build_form_section(
            "Preferencias gerais",
            "Ajustes basicos do aplicativo.",
            [
                ("Idioma", self._disabled_input("pt-BR")),
                ("Tema", self._disabled_input("dark_teal")),
                ("Iniciar com o sistema", self._disabled_checkbox(False)),
            ],
        )

    def _section_library(self) -> QWidget:
        return self._build_form_section(
            "Biblioteca",
            "Pastas monitoradas e comportamento do watcher.",
            [
                ("Pastas", self._disabled_input("/caminho/para/livros")),
                ("Watcher", self._disabled_checkbox(True)),
            ],
        )

    def _section_metadata(self) -> QWidget:
        return self._build_form_section(
            "Metadados",
            "Preferencias de provedores e enriquecimento.",
            [
                ("Providers", self._disabled_input("Open Library, Google Books")),
                ("Timeout (s)", self._disabled_input("15")),
            ],
        )

    def _section_ocr(self) -> QWidget:
        return self._build_form_section(
            "OCR",
            "Extracao de texto para PDFs escaneados.",
            [
                ("Ativo", self._disabled_checkbox(False)),
                ("Idioma", self._disabled_input("eng")),
                ("Max paginas", self._disabled_input("3")),
            ],
        )

    def _section_organizer(self) -> QWidget:
        return self._build_form_section(
            "Organizador",
            "Template e destino para reorganizacao dos arquivos.",
            [
                ("Template", self._disabled_input("{author_last}/{title}.{ext}")),
                ("Destino", self._disabled_input("/caminho/para/biblioteca")),
            ],
        )

    def _section_ui(self) -> QWidget:
        return self._build_form_section(
            "Interface",
            "Aparencia e densidade de informacao.",
            [
                ("Modo compactado", self._disabled_checkbox(False)),
                ("Tamanho de capa", self._disabled_input("medio")),
            ],
        )

    def _section_api(self) -> QWidget:
        return self._build_form_section(
            "API/OPDS",
            "Configuracoes de acesso local e feeds.",
            [
                ("API local", self._disabled_checkbox(True)),
                ("Porta", self._disabled_input("8000")),
                ("OPDS", self._disabled_checkbox(False)),
            ],
        )

    def _section_backup(self) -> QWidget:
        return self._build_form_section(
            "Backup",
            "Exportacao e copias de seguranca.",
            [
                ("Backup automatico", self._disabled_checkbox(False)),
                ("Destino", self._disabled_input("/caminho/para/backup")),
            ],
        )

    def _build_form_section(
        self,
        title: str,
        subtitle: str,
        fields: list[tuple[str, QWidget]],
    ) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QLabel(f"<h2>{title}</h2><p>{subtitle}</p>")
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        form_box = QGroupBox("Configuracoes")
        form_layout = QFormLayout(form_box)
        for label, field in fields:
            form_layout.addRow(label, field)
        layout.addWidget(form_box)

        note = QLabel("Edicao ainda nao disponivel. Estas opcoes serao ativadas em breve.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return widget

    @staticmethod
    def _disabled_input(text: str) -> QLineEdit:
        field = QLineEdit(text)
        field.setReadOnly(True)
        field.setEnabled(False)
        return field

    @staticmethod
    def _disabled_checkbox(checked: bool) -> QCheckBox:
        field = QCheckBox()
        field.setChecked(checked)
        field.setEnabled(False)
        return field
