"""The Torrents screen: list, filters, and a detail card (overview with pieces grid, files, peers, trackers)."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QStackedWidget,
    QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from idm.core.torrent import PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_SKIP, TorrentRecord, TorrentState
from idm.gui import theme
from idm.gui.delegates import BUTTON, ROW_HEIGHT, TextDelegate, button_rects
from idm.gui.downloads_model import format_bytes, format_eta
from idm.gui.material_icons import get_icon
from idm.gui.widgets import card, field_label, muted

TEAL = "#0F9D8A"
TEAL_BG = "#DDF4EF"
COL_NAME, COL_SIZE, COL_PROGRESS, COL_DOWN, COL_UP, COL_PEERS, COL_RATIO, COL_ACTIONS = range(8)
HEADERS = ["Name", "Size", "Progress", "Down", "Up", "Seeds / peers", "Ratio", "Actions"]
ROLE_TORRENT = Qt.UserRole

STATE_LABEL = {
    TorrentState.METADATA: "Fetching info", TorrentState.DOWNLOADING: "Downloading", TorrentState.SEEDING: "Seeding", TorrentState.PAUSED: "Paused",
    TorrentState.CHECKING: "Checking", TorrentState.ERROR: "Error",
}
STATE_PILL = {
    TorrentState.METADATA: (theme.TEXT_MUTED, "#EEF0F4"),
    TorrentState.DOWNLOADING: (theme.PRIMARY, "#E6EDFF"), TorrentState.SEEDING: (TEAL, TEAL_BG),
    TorrentState.PAUSED: ("#B06000", theme.WARNING_BG), TorrentState.CHECKING: (theme.TEXT_MUTED, "#EEF0F4"),
    TorrentState.ERROR: (theme.ERROR, theme.ERROR_BG),
}
STATE_BAR = {
    TorrentState.METADATA: theme.NEUTRAL_LIGHT,
    TorrentState.DOWNLOADING: theme.PRIMARY, TorrentState.SEEDING: TEAL, TorrentState.PAUSED: theme.WARNING,
    TorrentState.CHECKING: theme.NEUTRAL_LIGHT, TorrentState.ERROR: theme.ERROR,
}
GROUPS = {
    "downloading": {TorrentState.DOWNLOADING, TorrentState.METADATA, TorrentState.CHECKING},
    "seeding": {TorrentState.SEEDING},
    "paused": {TorrentState.PAUSED},
}


def speed_text(bytes_per_sec: int) -> str:
    return f"{format_bytes(bytes_per_sec)}/s" if bytes_per_sec > 0 else "-"


def actions_for(state: TorrentState) -> list[str]:
    return ["pause" if state in (TorrentState.DOWNLOADING, TorrentState.SEEDING, TorrentState.CHECKING) else "resume",
            "remove"]


class TorrentTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[TorrentRecord] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return HEADERS[section]
            if role == Qt.TextAlignmentRole:
                return int((Qt.AlignRight if section == COL_ACTIONS else Qt.AlignLeft) | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self._rows[index.row()]
        if role == ROLE_TORRENT:
            return t
        if role == Qt.DisplayRole:
            col = index.column()
            if col == COL_NAME:
                return t.name
            if col == COL_SIZE:
                return format_bytes(t.total_size)
            if col == COL_PROGRESS:
                return f"{t.progress * 100:.0f}%"
            if col == COL_DOWN:
                return speed_text(t.down_speed)
            if col == COL_UP:
                return speed_text(t.up_speed)
            if col == COL_PEERS:
                return f"{t.seeds} / {t.peers}"
            if col == COL_RATIO:
                return f"{t.ratio:.2f}"
        if role == Qt.ToolTipRole and index.column() == COL_NAME:
            return t.name
        return None

    def set_records(self, records: list[TorrentRecord]) -> None:
        if [r.id for r in records] == [r.id for r in self._rows]:
            self._rows = list(records)  # same torrents: refresh in place so the selection survives
            if self._rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, len(HEADERS) - 1))
            return
        self.beginResetModel()
        self._rows = list(records)
        self.endResetModel()

    def records(self) -> list[TorrentRecord]:
        return list(self._rows)


class TorrentFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._group: str | None = None

    def set_group(self, group: str | None) -> None:
        self._group = group
        self.beginFilterChange()
        self.endFilterChange()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if self._group is None:
            return True
        t = self.sourceModel().data(self.sourceModel().index(source_row, 0, source_parent), ROLE_TORRENT)
        return t is not None and t.state in GROUPS[self._group]


def _selected(option) -> bool:
    from PySide6.QtWidgets import QStyle
    return bool(option.state & QStyle.State_Selected)


class TorrentNameDelegate(TextDelegate):
    def paint(self, painter, option, index) -> None:
        t: TorrentRecord = index.data(ROLE_TORRENT)
        if t is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if _selected(option):
            painter.fillRect(option.rect, QColor("#EEF2FB"))
        rect = option.rect
        tile = QRectF(rect.left() + 14, rect.top() + (rect.height() - 36) / 2, 36, 36)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F1F3F7"))
        painter.drawRoundedRect(tile, 9, 9)
        get_icon("download", color=theme.TEXT_MUTED, size=16).paint(
            painter, QRect(int(tile.left()) + 10, int(tile.top()) + 10, 16, 16))
        left = int(tile.right()) + 12
        width = rect.right() - left - 8
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRect(left, rect.top() + 9, width, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font).elidedText(t.name, Qt.ElideRight, width))
        small = QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        label = STATE_LABEL[t.state]
        fg, bg = STATE_PILL[t.state]
        pill_w = QFontMetrics(small).horizontalAdvance(label) + 16
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(left, rect.top() + 30, pill_w, 17), 8.5, 8.5)
        painter.setPen(QColor(fg))
        painter.drawText(QRect(left, rect.top() + 30, pill_w, 17), Qt.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(240, ROW_HEIGHT)


class TorrentProgressDelegate(TextDelegate):
    def paint(self, painter, option, index) -> None:
        t: TorrentRecord = index.data(ROLE_TORRENT)
        if t is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if _selected(option):
            painter.fillRect(option.rect, QColor("#EEF2FB"))
        rect = option.rect
        label_w = 52
        track = QRectF(rect.left() + 8, rect.center().y() - 4, max(20, rect.width() - label_w - 22), 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.TRACK))
        painter.drawRoundedRect(track, 4, 4)
        if t.progress > 0:
            fill = QRectF(track)
            fill.setWidth(max(8.0, track.width() * t.progress))
            painter.setBrush(QColor(STATE_BAR[t.state]))
            painter.drawRoundedRect(fill, 4, 4)
        mono = QFont()
        mono.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas"])
        mono.setPixelSize(12)
        painter.setFont(mono)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QRect(int(track.right()) + 6, rect.top(), label_w, rect.height()),
                         Qt.AlignRight | Qt.AlignVCenter, f"{t.progress * 100:.0f}%")
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, ROW_HEIGHT)


class TorrentActionsDelegate(TextDelegate):
    triggered = Signal(str, str)  # torrent id, action

    def _names(self, index) -> list[str]:
        t = index.data(ROLE_TORRENT)
        return actions_for(t.state) if t else []

    def paint(self, painter, option, index) -> None:
        names = self._names(index)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if _selected(option):
            painter.fillRect(option.rect, QColor("#EEF2FB"))
        icons = {"pause": "pause", "resume": "play", "remove": "close"}
        for name, rect in zip(names, button_rects(option.rect, len(names))):
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.setBrush(QColor(theme.BACKGROUND))
            painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            color = theme.ERROR if name == "remove" else theme.TEXT
            get_icon(icons[name], color=color, size=14).paint(
                painter, QRect(rect.left() + (BUTTON - 14) // 2, rect.top() + (BUTTON - 14) // 2, 14, 14))
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            names = self._names(index)
            for name, rect in zip(names, button_rects(option.rect, len(names))):
                if rect.contains(event.position().toPoint()):
                    self.triggered.emit(index.data(ROLE_TORRENT).id, name)
                    return True
        return False


class PiecesGrid(QWidget):
    """Rows of small cells, one per piece (or one per group of pieces when there are more pieces than cells)."""

    ROWS, CELL_W, CELL_H, GAP = 3, 16, 8, 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pieces: list[bool] = []
        self._color = QColor(theme.PRIMARY)
        self.setFixedHeight(self.ROWS * (self.CELL_H + self.GAP) - self.GAP)

    def set_pieces(self, pieces: list[bool], color: str = theme.PRIMARY) -> None:
        self._pieces = pieces
        self._color = QColor(color)
        self.update()

    def cells(self) -> list[float]:
        """Fill (0..1) of each drawn cell; the pieces are binned evenly when they outnumber the cells."""
        columns = max(1, (self.width() + self.GAP) // (self.CELL_W + self.GAP))
        capacity = columns * self.ROWS
        n = len(self._pieces)
        if n == 0:
            return [0.0] * capacity
        if n <= capacity:
            return [1.0 if p else 0.0 for p in self._pieces]
        out = []
        for i in range(capacity):
            lo, hi = i * n // capacity, max(i * n // capacity + 1, (i + 1) * n // capacity)
            chunk = self._pieces[lo:hi]
            out.append(sum(chunk) / len(chunk))
        return out

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        columns = max(1, (self.width() + self.GAP) // (self.CELL_W + self.GAP))
        extra = (self.width() + self.GAP) - columns * (self.CELL_W + self.GAP)
        step_x = self.CELL_W + self.GAP + (extra / columns if columns else 0)
        for i, fill in enumerate(self.cells()):
            row, col = divmod(i, columns)
            rect = QRectF(col * step_x, row * (self.CELL_H + self.GAP), step_x - self.GAP, self.CELL_H)
            painter.setBrush(QColor(theme.TRACK))
            painter.drawRoundedRect(rect, 2, 2)
            if fill > 0:
                color = QColor(self._color)
                color.setAlphaF(0.35 + 0.65 * fill if fill < 1 else 1.0)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 2, 2)


class _Tile(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background: {theme.APP_BG}; border-radius: 10px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
        self.value = QLabel("-")
        self.value.setStyleSheet(f"font-family: {theme.FONT_MONO}; font-size: 15px; font-weight: 600; background: transparent;")
        layout.addWidget(heading)
        layout.addWidget(self.value)


class TorrentsPage(QWidget):
    action_requested = Signal(str, str)  # torrent id, "pause" | "resume" | "remove"
    resume_all = Signal()
    pause_all = Signal()
    file_priority_requested = Signal(str, int, int)  # torrent id, file index, priority

    def __init__(self, parent=None):
        super().__init__(parent)
        self.detail_provider = None  # callable(id) -> a fully filled TorrentRecord, set by the owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel("All torrents")
        self.title.setObjectName("pageTitle")
        top.addWidget(self.title)
        top.addStretch(1)
        for text, icon, signal in (("Resume all", "play", self.resume_all), ("Pause all", "pause", self.pause_all)):
            button = QPushButton(" " + text)
            button.setIcon(get_icon(icon, color=theme.TEXT, size=14))
            button.setFixedHeight(38)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, s=signal: s.emit())
            top.addWidget(button)
        layout.addLayout(top)

        self.model = TorrentTableModel(self)
        self.proxy = TorrentFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        table_card = card()
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col, width in ((COL_SIZE, 80), (COL_PROGRESS, 170), (COL_DOWN, 84), (COL_UP, 84), (COL_PEERS, 100),
                           (COL_RATIO, 56), (COL_ACTIONS, 96)):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        mono = TextDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_NAME, TorrentNameDelegate(self.table))
        self.table.setItemDelegateForColumn(COL_PROGRESS, TorrentProgressDelegate(self.table))
        actions = TorrentActionsDelegate(self.table)
        actions.triggered.connect(self.action_requested)
        self.table.setItemDelegateForColumn(COL_ACTIONS, actions)
        for col in (COL_SIZE, COL_DOWN, COL_UP, COL_PEERS, COL_RATIO):
            self.table.setItemDelegateForColumn(col, mono)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.refresh_detail())
        self.empty = muted("")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setMinimumHeight(140)
        card_layout.addWidget(self.table)
        card_layout.addWidget(self.empty)
        layout.addWidget(table_card, 1)

        layout.addWidget(self._build_detail())
        self.set_empty_message("No torrents here yet.")

    # -- detail ------------------------------------------------------------------

    def _build_detail(self) -> QWidget:
        self.detail = card()
        outer = QVBoxLayout(self.detail)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(20, 14, 16, 12)
        self.detail_name = QLabel()
        self.detail_name.setStyleSheet("font-size: 14px; font-weight: 700;")
        head.addWidget(self.detail_name, 1)
        self.tab_buttons: list[QPushButton] = []
        for i, text in enumerate(("Overview", "Files", "Peers", "Trackers")):
            button = QPushButton(text)
            button.setObjectName("settingsNav")
            button.setCheckable(True)
            button.setMinimumWidth(92)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, idx=i: self._select_tab(idx))
            head.addWidget(button)
            self.tab_buttons.append(button)
        outer.addLayout(head)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER};")
        outer.addWidget(line)

        self.tabs = QStackedWidget()
        overview = QWidget()
        ov = QVBoxLayout(overview)
        ov.setContentsMargins(20, 16, 20, 16)
        ov.setSpacing(10)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_downloaded = _Tile("Downloaded")
        self.tile_uploaded = _Tile("Uploaded")
        self.tile_ratio = _Tile("Share ratio")
        self.tile_eta = _Tile("ETA")
        for tile in (self.tile_downloaded, self.tile_uploaded, self.tile_ratio, self.tile_eta):
            tiles.addWidget(tile, 1)
        ov.addLayout(tiles)
        ov.addWidget(field_label("Pieces"))
        self.pieces = PiecesGrid()
        ov.addWidget(self.pieces)
        self.saved_to = QLabel()
        self.saved_to.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        ov.addWidget(self.saved_to)
        self.tabs.addWidget(overview)
        self.files_table = self._simple_table(["File", "Size", "Done", "Priority"])
        self.peers_table = self._simple_table(["Address", "Client", "Done", "Down", "Up"])
        self.trackers_table = self._simple_table(["Tracker", "Status", "Seeds", "Peers"])
        for table in (self.files_table, self.peers_table, self.trackers_table):
            self.tabs.addWidget(table)
        outer.addWidget(self.tabs)
        self.tab_buttons[0].setChecked(True)
        self.detail.hide()
        return self.detail

    @staticmethod
    def _simple_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setShowGrid(False)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setMinimumHeight(150)
        return table

    def _select_tab(self, index: int) -> None:
        for i, button in enumerate(self.tab_buttons):
            button.setChecked(i == index)
        self.tabs.setCurrentIndex(index)

    PRIORITY_CHOICES = (("Skip", PRIORITY_SKIP), ("Normal", PRIORITY_NORMAL), ("High", PRIORITY_HIGH))

    def _fill_files(self, t: TorrentRecord) -> None:
        """Update the files table in place: rebuilding it every second would close an open priority drop-down."""
        table = self.files_table
        same = table.rowCount() == len(t.files) and getattr(self, "_files_for", None) == t.id
        if not same:
            table.setRowCount(len(t.files))
            self._files_for = t.id
        for row, f in enumerate(t.files):
            for col, text in enumerate((f.path.replace("\\", "/"), format_bytes(f.size), f"{f.progress * 100:.0f}%")):
                item = table.item(row, col)
                if item is None:
                    table.setItem(row, col, QTableWidgetItem(text))
                else:
                    item.setText(text)
            combo = table.cellWidget(row, 3)
            if combo is None:
                combo = QComboBox()
                combo.setMaximumWidth(120)
                for label, value in self.PRIORITY_CHOICES:
                    combo.addItem(label, value)
                combo.currentIndexChanged.connect(
                    lambda _i, c=combo, tid=t.id, idx=f.index: self.file_priority_requested.emit(tid, idx, c.currentData()))
                table.setCellWidget(row, 3, combo)
            if not combo.view().isVisible():
                combo.blockSignals(True)
                combo.setCurrentIndex(max(0, combo.findData(f.priority)) if f.priority in (0, 4, 7)
                                      else 1 if f.priority < 7 else 2)
                combo.blockSignals(False)

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))

    def selected(self) -> TorrentRecord | None:
        rows = self.table.selectionModel().selectedRows()
        return self.proxy.data(rows[0], ROLE_TORRENT) if rows else None

    def refresh_detail(self) -> None:
        t = self.selected()
        if t is None:
            self.detail.hide()
            return
        if self.detail_provider is not None:
            t = self.detail_provider(t.id) or t
        self.detail.show()
        self.detail_name.setText(t.name)
        self.tile_downloaded.value.setText(format_bytes(t.downloaded))
        self.tile_uploaded.value.setText(format_bytes(t.uploaded))
        self.tile_ratio.value.setText(f"{t.ratio:.2f}")
        self.tile_eta.value.setText(format_eta(t.eta_seconds) if t.eta_seconds is not None else "-")
        self.pieces.set_pieces(t.pieces, STATE_BAR[t.state] if t.state != TorrentState.SEEDING else theme.PRIMARY)
        self.saved_to.setText(f"Saved to {t.save_path}" if t.save_path else "")
        self._fill_files(t)
        self._fill(self.peers_table, [[p.address, p.client, f"{p.progress * 100:.0f}%", speed_text(p.down_speed),
                                       speed_text(p.up_speed)] for p in t.peer_list])
        self._fill(self.trackers_table, [[k.url, k.status, str(k.seeds), str(k.peers)] for k in t.trackers])

    # -- public --------------------------------------------------------------------

    def set_records(self, records: list[TorrentRecord]) -> None:
        self.model.set_records(records)
        self.update_empty_state()
        self.refresh_detail()

    def set_group(self, group: str | None, title: str) -> None:
        self.proxy.set_group(group)
        self.title.setText(title)
        self.update_empty_state()

    def set_empty_message(self, text: str) -> None:
        self._empty_text = text
        self.empty.setText(text)

    def update_empty_state(self) -> None:
        empty = self.proxy.rowCount() == 0
        self.empty.setVisible(empty)
        self.table.setVisible(not empty)
