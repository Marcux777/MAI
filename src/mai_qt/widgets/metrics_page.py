from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..services import CountStat, LibraryService, LibraryStats, YearStat


class MetricsPage(QWidget):
    def __init__(self, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header = QLabel(
            "<h2>Métricas da biblioteca</h2>"
            "<p>Perfil do acervo local com contagens e distribuições.</p>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        header_layout.addWidget(header, 1)

        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh)  # type: ignore[attr-defined]
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)

        container = QWidget()
        self.scroll.setWidget(container)
        body = QVBoxLayout(container)

        self.summary_box = QGroupBox("Resumo")
        summary_layout = QFormLayout(self.summary_box)
        self.work_count = QLabel("0")
        self.edition_count = QLabel("0")
        self.file_count = QLabel("0")
        self.author_count = QLabel("0")
        self.format_count = QLabel("0")
        summary_layout.addRow("Obras", self.work_count)
        summary_layout.addRow("Edições (formatos)", self.edition_count)
        summary_layout.addRow("Arquivos físicos", self.file_count)
        summary_layout.addRow("Autores únicos", self.author_count)
        summary_layout.addRow("Formatos distintos", self.format_count)
        body.addWidget(self.summary_box)

        self.format_box = QGroupBox("Distribuição por formato")
        self.format_layout = QVBoxLayout(self.format_box)
        body.addWidget(self.format_box)

        self.tag_box = QGroupBox("Livros por tag")
        self.tag_layout = QVBoxLayout(self.tag_box)
        self.tag_note = QLabel(
            "Percentuais baseados no total de edições. Tags podem se sobrepor."
        )
        self.tag_note.setWordWrap(True)
        self.tag_layout.addWidget(self.tag_note)
        body.addWidget(self.tag_box)

        self.year_box = QGroupBox("Publicação por década")
        self.year_layout = QVBoxLayout(self.year_box)
        body.addWidget(self.year_box)

        body.addStretch(1)

    def refresh(self) -> None:
        stats = self.service.get_library_stats()
        self._populate_summary(stats)
        self._populate_formats(stats)
        self._populate_tags(stats)
        self._populate_years(stats)

    def _populate_summary(self, stats: LibraryStats) -> None:
        self.work_count.setText(str(stats.work_count))
        self.edition_count.setText(str(stats.edition_count))
        self.file_count.setText(str(stats.file_count))
        self.author_count.setText(str(stats.author_count))
        self.format_count.setText(str(stats.format_count))

    def _populate_formats(self, stats: LibraryStats) -> None:
        self._clear_layout(self.format_layout)
        total = stats.edition_count
        if not stats.format_counts:
            self.format_layout.addWidget(QLabel("Sem dados de formato."))
            return

        items = self._limit_items(stats.format_counts, limit=8)
        for item in items:
            percent = _percent(item.count, total)
            row = _bar_row(item.label, item.count, percent)
            self.format_layout.addWidget(row)

    def _populate_tags(self, stats: LibraryStats) -> None:
        self._clear_layout(self.tag_layout, keep_first=True)
        total = stats.edition_count
        if not stats.tag_counts:
            self.tag_layout.addWidget(QLabel("Sem tags cadastradas."))
            return

        items = self._limit_items(stats.tag_counts, limit=12)
        for item in items:
            percent = _percent(item.count, total)
            row = _bar_row(item.label, item.count, percent)
            self.tag_layout.addWidget(row)

    def _populate_years(self, stats: LibraryStats) -> None:
        self._clear_layout(self.year_layout)
        total = stats.edition_count
        if not stats.year_counts and stats.missing_year_count == 0:
            self.year_layout.addWidget(QLabel("Sem dados de publicação."))
            return

        if len(stats.year_counts) <= 12:
            self.year_box.setTitle("Publicação por ano")
            year_items = [CountStat(label=str(y.year), count=y.count) for y in stats.year_counts]
        else:
            self.year_box.setTitle("Publicação por década")
            year_items = self._build_decade_items(stats.year_counts)

        for item in year_items:
            percent = _percent(item.count, total)
            row = _bar_row(item.label, item.count, percent)
            self.year_layout.addWidget(row)

        if stats.missing_year_count:
            percent = _percent(stats.missing_year_count, total)
            row = _bar_row("Sem ano", stats.missing_year_count, percent)
            self.year_layout.addWidget(row)

    @staticmethod
    def _build_decade_items(years: list[YearStat]) -> list[CountStat]:
        buckets: dict[int, int] = defaultdict(int)
        for item in years:
            decade = (item.year // 10) * 10
            buckets[decade] += item.count
        decade_items = [
            CountStat(label=f"{decade}-{decade + 9}", count=count)
            for decade, count in sorted(buckets.items())
        ]
        return decade_items

    @staticmethod
    def _limit_items(items: list[CountStat], limit: int) -> list[CountStat]:
        if limit <= 0 or len(items) <= limit:
            return list(items)
        head = items[:limit]
        tail = items[limit:]
        remainder = sum(item.count for item in tail)
        if remainder:
            head.append(CountStat(label="Outros", count=remainder))
        return head

    @staticmethod
    def _clear_layout(layout: QVBoxLayout, keep_first: bool = False) -> None:
        index = 1 if keep_first else 0
        while layout.count() > index:
            item = layout.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                MetricsPage._clear_layout(item.layout())  # type: ignore[arg-type]


def _percent(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (value / total) * 100.0


def _bar_row(label: str, count: int, percent: float) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)

    name_label = QLabel(label)
    name_label.setMinimumWidth(140)
    value_label = QLabel(f"{count} ({percent:.0f}%)")
    value_label.setMinimumWidth(90)

    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(int(round(percent)))
    bar.setTextVisible(False)

    layout.addWidget(name_label)
    layout.addWidget(bar, 1)
    layout.addWidget(value_label)
    return row
