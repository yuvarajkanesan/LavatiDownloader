from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget, QTableView, QVBoxLayout, QWidget,
)

from idm.core.clipboard_detect import extract_first_url
from idm.core.errors import DuplicateDownloadError
from idm.core.events import DownloadEvent
from idm.core.queue_manager import DownloadManager
from idm.core.scheduler import DownloadScheduler
from idm.core.schedule import QueueScheduler, ScheduleConfig, perform_finish_action
from idm.core.torrent import is_magnet, load_backend
from idm.core.video import SITES, VideoOptions
from idm.gui import autostart, theme
from idm.gui.add_download_dialog import AddDownloadDialog
from idm.gui.bridge import EngineBridge
from idm.gui.clipboard_monitor import ClipboardMonitor
from idm.gui.ffmpeg_prompt import ensure_ffmpeg
from idm.gui.delegates import ROW_HEIGHT, ActionsDelegate, NameDelegate, ProgressDelegate, TextDelegate
from idm.gui.downloads_model import (
    COL_ACTIONS, COL_ETA, COL_FILENAME, COL_PROGRESS, COL_SIZE, COL_SPEED, STATUS_LABELS, DownloadsTableModel,
    format_bytes,
)
from idm.gui.filter_proxy import DownloadsFilterProxy, group_of
from idm.gui.icons import make_app_icon
from idm.gui.ipc_server import IpcServer
from idm.gui.material_icons import get_icon
from idm.gui.settings_page import SettingsPage, get_setting, video_defaults
from idm.gui.torrents_page import GROUPS, TorrentsPage
from idm.gui.tray import TrayController
from idm.gui.widgets import ElidedLabel, NavButton, SegmentBar, SegmentedControl, card, chip, muted
from idm.storage.models import DownloadRecord, DownloadStatus
from idm.storage.paths import default_downloads_root
from idm.storage.repository import DownloadRepository

TERMINAL_STATUSES = (DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELED)

# (label, icon, status group, file type)
LIBRARY_ITEMS = [
    ("All downloads", "grid", None, None),
    ("Active", "bolt", "active", None),
    ("Queued and paused", "clock", "waiting", None),
    ("Completed", "check", "completed", None),
]
TYPE_ITEMS = [
    ("Videos", "movie", None, "Video"),
    ("Documents", "description", None, "Documents"),
    ("Music", "music", None, "Music"),
    ("Compressed", "archive", None, "Compressed"),
    ("Programs", "apps", None, "Programs"),
]
NAV_ITEMS = LIBRARY_ITEMS + TYPE_ITEMS
TORRENT_ITEMS = [
    ("All torrents", "grid", None),
    ("Downloading", "download", "downloading"),
    ("Seeding", "upload", "seeding"),
    ("Paused", "pause", "paused"),
]
PAGE_DOWNLOADS, PAGE_SETTINGS, PAGE_TORRENTS = 0, 1, 2


class _Notifier(QObject):
    """Lets the scheduler thread ask the GUI thread to act (exit the app, announce a power action)."""

    finished = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, repo: DownloadRepository):
        super().__init__()
        self.setWindowTitle("Lavati Downloader")
        self.setWindowIcon(make_app_icon())
        self.resize(1240, 760)
        self.setMinimumSize(900, 560)

        self._repo = repo
        self._downloads_root = self._resolve_downloads_root()
        self._manager = DownloadManager(
            repo, downloads_root=self._downloads_root,
            max_concurrent=int(get_setting(repo, "max_concurrent_downloads")),
            global_speed_limit_bytes=self._speed_limit_bytes_from_settings(),
        )
        self._scheduler = DownloadScheduler(repo, on_due=self._manager.start_queue)
        self._notifier = _Notifier()
        self._notifier.finished.connect(self._on_schedule_finished)
        self._queue_schedule = QueueScheduler(
            repo=repo,
            get_config=lambda: ScheduleConfig.from_settings(repo.get_setting),
            start_queue=self._manager.start_queue,
            stop_queue=self._manager.stop_queue,
            pause_active=self._pause_all_active,
            on_finished=self._notifier.finished.emit,
        )
        # Control calls (pause/resume/cancel/...) can briefly block on
        # in-flight I/O; run them off the GUI thread so the UI never freezes.
        self._control_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="idm-gui-ctrl")

        self._bridge = EngineBridge()
        self._bridge.event_received.connect(self._on_engine_event)
        self._manager.add_listener(self._bridge.listener)

        self._torrents = load_backend()
        self._mode = "downloads"
        self._torrent_totals = (0, 0, 0)
        self._model = DownloadsTableModel(self)
        self._proxy = DownloadsFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._build_ui()
        self._tray = TrayController(self, on_quit=self._quit_application)
        self._clipboard_monitor = ClipboardMonitor(self)
        self._clipboard_monitor.download_url_detected.connect(self._on_clipboard_url)
        self._clipboard_monitor.detect_video_links = get_setting(repo, "clipboard_monitor") == "1"
        self._ipc = IpcServer(self._handle_ipc, self)

        self._load_existing_downloads()
        self._manager.load_persisted_queue()
        self._scheduler.start()
        self._queue_schedule.start()
        self._clipboard_monitor.start()
        self._ipc.start()
        self._torrent_timer = QTimer(self)
        self._torrent_timer.setInterval(1000)
        self._torrent_timer.timeout.connect(self._refresh_torrents)
        self._torrent_timer.start()
        self._refresh_all()
        self._refresh_torrents()

        self._notified_first_tray_hide = False

    # -- UI construction -------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._sidebar_stack = QStackedWidget()
        self._sidebar_stack.setFixedWidth(224)
        self._sidebar = self._build_sidebar()
        self._sidebar_stack.addWidget(self._sidebar)
        self._sidebar_stack.addWidget(self._build_torrent_sidebar())
        body.addWidget(self._sidebar_stack)
        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_downloads_page())
        self._settings_page = SettingsPage(self._repo)
        self._settings_page.changed.connect(self._on_setting_changed)
        self._settings_page.back_requested.connect(self._show_downloads)
        self._pages.addWidget(self._settings_page)
        self._torrents_page = TorrentsPage()
        self._torrents_page.action_requested.connect(self._on_torrent_action)
        self._torrents_page.resume_all.connect(lambda: self._torrent_bulk("resume"))
        self._torrents_page.pause_all.connect(lambda: self._torrent_bulk("pause"))
        self._pages.addWidget(self._torrents_page)
        body.addWidget(self._pages, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self._build_status_bar()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(66)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(make_app_icon(64).pixmap(34, 34))
        title = QLabel("Lavati Downloader")
        title.setObjectName("appTitle")
        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addSpacing(14)
        self._mode_tabs = SegmentedControl([("downloads", "Downloads"), ("torrents", "Torrents")])
        self._mode_tabs.changed.connect(self._set_mode)
        layout.addWidget(self._mode_tabs)

        link_bar = QFrame()
        link_bar.setObjectName("linkBar")
        link_bar.setFixedHeight(42)
        link_layout = QHBoxLayout(link_bar)
        link_layout.setContentsMargins(12, 0, 6, 0)
        link_layout.setSpacing(6)
        link_icon = QLabel()
        link_icon.setPixmap(get_icon("link", color=theme.NEUTRAL_LIGHT, size=16).pixmap(16, 16))
        self._link_edit = QLineEdit()
        self._link_edit.setPlaceholderText("Paste a link to a file, video or playlist")
        self._link_edit.returnPressed.connect(self._add_from_link_bar)
        self._add_button = QPushButton(" Add")
        self._add_button.setObjectName("primary")
        self._add_button.setIcon(get_icon("add", color="white", size=14))
        self._add_button.setCursor(Qt.PointingHandCursor)
        self._add_button.clicked.connect(lambda checked=False: self._add_from_link_bar())
        link_layout.addWidget(link_icon)
        link_layout.addWidget(self._link_edit, 1)
        link_layout.addWidget(self._add_button)
        layout.addWidget(link_bar, 1)

        settings = QPushButton(" Settings")
        settings.setIcon(get_icon("settings", color=theme.TEXT, size=16))
        settings.setCursor(Qt.PointingHandCursor)
        settings.setFixedHeight(40)
        settings.clicked.connect(lambda checked=False: self._open_settings())
        self._settings_button = settings
        layout.addWidget(settings)
        self._open_torrent_button = QPushButton(" Open .torrent file")
        self._open_torrent_button.setIcon(get_icon("description", color=theme.TEXT, size=16))
        self._open_torrent_button.setCursor(Qt.PointingHandCursor)
        self._open_torrent_button.setFixedHeight(40)
        self._open_torrent_button.clicked.connect(lambda checked=False: self._open_torrent_file())
        self._open_torrent_button.hide()
        layout.addWidget(self._open_torrent_button)
        return header

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(224)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(2)

        self._nav_group = QButtonGroup(self)
        self._nav_buttons: list[NavButton] = []

        def section(title: str, items) -> None:
            label = QLabel(title)
            label.setObjectName("sectionLabel")
            layout.addWidget(label)
            for text, icon, _group, _type in items:
                button = NavButton(icon, text)
                self._nav_group.addButton(button, len(self._nav_buttons))
                self._nav_buttons.append(button)
                layout.addWidget(button)

        section("LIBRARY", LIBRARY_ITEMS)
        layout.addSpacing(14)
        section("FILE TYPES", TYPE_ITEMS)
        layout.addSpacing(14)
        p2p = QLabel("PEER TO PEER")
        p2p.setObjectName("sectionLabel")
        layout.addWidget(p2p)
        self._torrents_nav = NavButton("upload", "Torrents")
        self._torrents_nav.clicked.connect(lambda checked=False: self._set_mode("torrents"))
        layout.addWidget(self._torrents_nav)
        layout.addStretch(1)
        self._nav_buttons[0].setChecked(True)
        self._nav_group.idClicked.connect(self._on_nav_clicked)

        box = QFrame()
        box.setObjectName("siteBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 14)
        box_layout.setSpacing(8)
        heading = QLabel("Video sites")
        heading.setObjectName("siteBoxTitle")
        box_layout.addWidget(heading)
        names = list(SITES)
        for chunk in (names[:2], names[2:]):  # two rows, like the design
            row = QHBoxLayout()
            row.setSpacing(6)
            for name in chunk:
                row.addWidget(chip(name))
            row.addStretch(1)
            box_layout.addLayout(row)
        layout.addWidget(box)
        return side

    def _build_torrent_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(2)
        label = QLabel("TORRENTS")
        label.setObjectName("sectionLabel")
        layout.addWidget(label)
        self._tor_group = QButtonGroup(self)
        self._tor_buttons: list[NavButton] = []
        for text, icon, _group in TORRENT_ITEMS:
            button = NavButton(icon, text)
            self._tor_group.addButton(button, len(self._tor_buttons))
            self._tor_buttons.append(button)
            layout.addWidget(button)
        self._tor_buttons[0].setChecked(True)
        self._tor_group.idClicked.connect(self._on_torrent_nav)
        layout.addStretch(1)

        box = QFrame()
        box.setObjectName("siteBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        box_layout.setSpacing(6)
        self._tor_speed_labels = {}
        for key, text, icon, color in (("down", "Download", "download", theme.PRIMARY), ("up", "Upload", "upload", "#0F9D8A")):
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(get_icon(icon, color=color, size=14).pixmap(14, 14))
            value = QLabel("0.0 MB/s")
            value.setObjectName("mono")
            row.addWidget(icon_label)
            row.addWidget(QLabel(text))
            row.addStretch(1)
            row.addWidget(value)
            self._tor_speed_labels[key] = value
            box_layout.addLayout(row)
        layout.addWidget(box)
        return side

    def _build_downloads_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(8)
        self._title = QLabel("All downloads")
        self._title.setObjectName("pageTitle")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search downloads")
        self._search_edit.addAction(get_icon("search", color=theme.NEUTRAL_LIGHT, size=16), QLineEdit.LeadingPosition)
        self._search_edit.setFixedWidth(300)
        self._search_edit.setFixedHeight(38)
        self._search_edit.textChanged.connect(self._proxy.set_search_text)
        top.addWidget(self._title)
        top.addStretch(1)
        top.addWidget(self._search_edit)
        for text, icon, slot in (("Resume all", "play", self._resume_all), ("Pause all", "pause", self._pause_all),
                                 ("Clear completed", "delete", self._clear_completed)):
            button = QPushButton(" " + text)
            button.setIcon(get_icon(icon, color=theme.TEXT, size=14))
            button.setFixedHeight(38)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, s=slot: s())
            top.addWidget(button)
        layout.addLayout(top)

        table_card = card()
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.setMouseTracking(True)
        header = self._table.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setSectionResizeMode(COL_FILENAME, QHeaderView.Stretch)
        for col, width in ((COL_SIZE, 90), (COL_PROGRESS, 200), (COL_SPEED, 100), (COL_ETA, 70), (COL_ACTIONS, 110)):
            self._table.setColumnWidth(col, width)
        header.setStretchLastSection(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self._actions_delegate = ActionsDelegate(self._table)
        self._actions_delegate.triggered.connect(self._on_row_action)
        text_delegate = TextDelegate(self._table)
        self._table.setItemDelegateForColumn(COL_FILENAME, NameDelegate(self._table))
        self._table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self._table))
        self._table.setItemDelegateForColumn(COL_ACTIONS, self._actions_delegate)
        for col in (COL_SIZE, COL_SPEED, COL_ETA):
            self._table.setItemDelegateForColumn(col, text_delegate)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.doubleClicked.connect(lambda _index: self._open_selected_file())
        self._table.selectionModel().selectionChanged.connect(lambda *_: self._refresh_detail())
        self._empty = muted("No downloads here yet. Paste a link above to start one.")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setMinimumHeight(120)
        card_layout.addWidget(self._table)
        card_layout.addWidget(self._empty)
        layout.addWidget(table_card, 1)

        self._detail = card()
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(20, 14, 20, 16)
        detail_layout.setSpacing(10)
        head = QHBoxLayout()
        self._detail_name = QLabel()
        self._detail_name.setStyleSheet("font-size: 14px; font-weight: 700;")
        self._detail_meta = ElidedLabel()
        self._detail_meta.setObjectName("muted")
        self._detail_meta.setStyleSheet("font-size: 12px;")
        self._detail_connections = muted()
        self._detail_connections.setStyleSheet("font-size: 12px;")
        head.addWidget(self._detail_name)
        head.addWidget(self._detail_meta, 1)
        head.addWidget(self._detail_connections)
        self._segments = SegmentBar()
        detail_layout.addLayout(head)
        detail_layout.addWidget(self._segments)
        layout.addWidget(self._detail)
        self._detail.hide()
        return page

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_active = QLabel("0 active")
        self._status_speed = QLabel("")
        self._status_speed.setObjectName("mono")
        self._status_speed.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        holder = QWidget()
        holder.setMinimumWidth(380)
        row = QHBoxLayout(holder)
        row.setContentsMargins(14, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._status_dot)
        row.addWidget(self._status_active)
        row.addWidget(self._status_speed)
        bar.addWidget(holder)
        self._status_message = QLabel("Ready")
        self._status_message.setStyleSheet(f"color: {theme.TEXT_MUTED}; padding-right: 14px;")
        bar.addPermanentWidget(self._status_message)

    # -- data loading ------------------------------------------------------

    def _resolve_downloads_root(self):
        configured = get_setting(self._repo, "default_download_root")
        return Path(configured) if configured else default_downloads_root()

    def _speed_limit_bytes_from_settings(self) -> int | None:
        kbps = int(get_setting(self._repo, "global_speed_limit_kbps"))
        return kbps * 1024 if kbps > 0 else None

    def _load_existing_downloads(self) -> None:
        self._model.set_records(self._repo.list_downloads())

    # -- navigation ----------------------------------------------------------

    def _on_nav_clicked(self, index: int) -> None:
        label, _icon, group, file_type = NAV_ITEMS[index]
        self._proxy.set_status_group(group)
        self._proxy.set_category(file_type)
        self._title.setText(label)
        self._pages.setCurrentIndex(PAGE_DOWNLOADS)
        self._refresh_empty_state()

    def _open_settings(self) -> None:
        self._pages.setCurrentIndex(PAGE_SETTINGS)
        self._sidebar_stack.hide()

    def _show_downloads(self) -> None:
        self._set_mode(self._mode)

    # -- modes: downloads / torrents ----------------------------------------------

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        torrents = mode == "torrents"
        if self._mode_tabs.value() != mode:
            self._mode_tabs.set_value(mode)
        self._pages.setCurrentIndex(PAGE_TORRENTS if torrents else PAGE_DOWNLOADS)
        self._sidebar_stack.show()
        self._sidebar_stack.setCurrentIndex(1 if torrents else 0)
        self._link_edit.setPlaceholderText("Paste a magnet link" if torrents else "Paste a link to a file, video or playlist")
        self._add_button.setText("Add" if torrents else " Add")
        self._add_button.setIcon(QIcon() if torrents else get_icon("add", color="white", size=14))
        self._settings_button.setVisible(not torrents)
        self._open_torrent_button.setVisible(torrents)
        self._refresh_status_bar()

    def _on_torrent_nav(self, index: int) -> None:
        label, _icon, group = TORRENT_ITEMS[index]
        self._torrents_page.set_group(group, label)

    def _refresh_torrents(self) -> None:
        records = self._torrents.snapshot()
        self._torrents_page.set_records(records)
        for button, (_label, _icon, group) in zip(self._tor_buttons, TORRENT_ITEMS):
            button.set_count(len(records) if group is None else sum(1 for r in records if r.state in GROUPS[group]))
        down = sum(r.down_speed for r in records)
        up = sum(r.up_speed for r in records)
        self._tor_speed_labels["down"].setText(f"{format_bytes(down)}/s" if down else "0.0 MB/s")
        self._tor_speed_labels["up"].setText(f"{format_bytes(up)}/s" if up else "0.0 MB/s")
        self._torrent_totals = (sum(1 for r in records if r.state.value == "downloading"), down, up)
        self._torrents_page.set_empty_message(
            "No torrents here yet. Paste a magnet link above to start one." if self._torrents.available
            else self._torrents.unavailable_reason)
        self._torrents_page.update_empty_state()
        if self._mode == "torrents":
            self._refresh_status_bar()

    def _torrents_unavailable(self) -> bool:
        if self._torrents.available:
            return False
        QMessageBox.information(self, "Torrents", self._torrents.unavailable_reason)
        return True

    def _add_magnet(self) -> None:
        if self._torrents_unavailable():
            return
        text = self._link_edit.text().strip()
        if not is_magnet(text):
            QMessageBox.information(self, "Magnet link needed", "Paste a magnet link (it starts with magnet:?).")
            return
        self._link_edit.clear()
        self._torrents.add_magnet(text, str(self._downloads_root / "Torrents"))
        self._refresh_torrents()

    def _open_torrent_file(self) -> None:
        if self._torrents_unavailable():
            return
        path, _filter = QFileDialog.getOpenFileName(self, "Open .torrent file", "", "Torrent files (*.torrent)")
        if path:
            self._torrents.add_file(path, str(self._downloads_root / "Torrents"))
            self._refresh_torrents()

    def _on_torrent_action(self, torrent_id: str, action: str) -> None:
        getattr(self._torrents, action)(torrent_id)
        self._refresh_torrents()

    def _torrent_bulk(self, action: str) -> None:
        for record in self._torrents.snapshot():
            getattr(self._torrents, action)(record.id)
        self._refresh_torrents()

    # -- counts, status bar, detail card -----------------------------------------

    def _refresh_all(self) -> None:
        self._refresh_counts()
        self._refresh_status_bar()
        self._refresh_detail()
        self._refresh_empty_state()

    def _refresh_counts(self) -> None:
        records = self._model.records()
        for button, (_label, _icon, group, file_type) in zip(self._nav_buttons, NAV_ITEMS):
            count = sum(1 for r in records
                        if (group is None or group_of(r.status) == group)
                        and (file_type is None or r.category == file_type))
            button.set_count(count)

    def _refresh_status_bar(self) -> None:
        if self._mode == "torrents":
            count, down, up = self._torrent_totals
            self._status_dot.setStyleSheet(
                f"background: {theme.SUCCESS if count else theme.NEUTRAL_LIGHT}; border-radius: 4px;")
            self._status_active.setText(f"{count} downloading")
            self._status_speed.setText(f"{format_bytes(down) if down else '0.0 MB'}/s down · "
                                       f"{format_bytes(up) if up else '0.0 MB'}/s up")
            return
        rows = [self._model.row_at(self._model.index(i, 0)) for i in range(self._model.rowCount())]
        active = [r for r in rows if r.record.status == DownloadStatus.DOWNLOADING]
        speed = sum(r.speed_bytes_per_sec for r in active)
        color = theme.SUCCESS if active else theme.NEUTRAL_LIGHT
        self._status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self._status_active.setText(f"{len(active)} active")
        self._status_speed.setText(f"{format_bytes(int(speed))}/s" if active else "")

    def _refresh_empty_state(self) -> None:
        empty = self._proxy.rowCount() == 0
        self._empty.setVisible(empty)
        self._table.setVisible(not empty)

    def _selected_download_ids(self) -> list[int]:
        ids = []
        for index in self._table.selectionModel().selectedRows():
            record = self._model.data(self._proxy.mapToSource(index), Qt.UserRole)
            if record is not None:
                ids.append(record.id)
        return ids

    def _refresh_detail(self) -> None:
        ids = self._selected_download_ids()
        record = self._model.get_record(ids[0]) if ids else None
        if record is None:
            self._detail.hide()
            return
        self._detail.show()
        self._detail_name.setText(record.filename)
        self._detail_meta.setText(f"{record.source}  ·  saves to {Path(record.destination_path).parent.name or 'Downloads'}")
        fractions = self._segment_fractions(record)
        self._detail_connections.setText(f"{len(fractions)} connections")
        color = theme.STATUS_COLORS.get(record.status.value, theme.PRIMARY)
        self._segments.set_progress(fractions, color if record.status != DownloadStatus.COMPLETED else theme.PRIMARY)

    def _segment_fractions(self, record: DownloadRecord) -> list[float]:
        count = max(1, record.connections if record.supports_ranges else 1)
        if record.status == DownloadStatus.COMPLETED:
            return [1.0] * count
        if record.kind == "file":
            segments = self._repo.get_segments(record.id)
            if segments:
                return [min(1.0, s.downloaded_bytes / (s.end_byte - s.start_byte + 1)) if s.end_byte >= s.start_byte else 0.0
                        for s in segments]
            return [0.0] * count
        total = record.total_size if record.total_size > 0 else 0
        overall = record.downloaded_bytes / total if total else 0.0
        return [max(0.0, min(1.0, overall * count - i)) for i in range(count)]

    # -- add download --------------------------------------------------------

    def _add_from_link_bar(self) -> None:
        if self._mode == "torrents":
            self._add_magnet()
            return
        text = self._link_edit.text().strip()
        self._link_edit.clear()
        self._open_add_dialog(initial_url=extract_first_url(text) or text)

    def _open_add_dialog(self, initial_url: str = "") -> None:
        self._show_downloads()
        dialog = AddDownloadDialog(
            self._downloads_root,
            default_connections=int(get_setting(self._repo, "max_connections_per_download")),
            initial_url=initial_url, video_defaults=video_defaults(self._repo), parent=self,
        )
        if dialog.exec() != AddDownloadDialog.Accepted:
            return
        result = dialog.result_data()
        if not result.url:
            return
        if result.kind == "video" and not ensure_ffmpeg(self, VideoOptions.from_json(result.options)):
            return
        try:
            record = self._manager.add_download(
                url=result.url, destination_dir=result.destination_dir,
                filename=result.filename, category=result.category,
                connections=result.connections, start_immediately=result.start_immediately,
                scheduled_at=result.scheduled_at, kind=result.kind, source=result.source, options=result.options,
            )
        except DuplicateDownloadError as exc:
            QMessageBox.information(
                self, "Already queued",
                f"\"{exc.existing.filename}\" is already in the queue "
                f"({STATUS_LABELS.get(exc.existing.status, exc.existing.status.value)}).\n\n"
                "Pause or remove it first if you want to start a fresh copy.",
            )
            return
        self._model.add_record(record)
        self._refresh_all()

    def _on_clipboard_url(self, text: str) -> None:
        url = extract_first_url(text)
        if not url:
            return
        answer = QMessageBox.question(
            self, "Download detected",
            f"Clipboard contains a downloadable link:\n{url}\n\nAdd it?",
        )
        if answer == QMessageBox.Yes:
            self._open_add_dialog(initial_url=url)

    # -- row and bulk actions -----------------------------------------------------

    def _on_row_action(self, download_id: int, action: str) -> None:
        if action == "remove":
            self._remove_ids([download_id], confirm=False)
            return
        method = {"pause": self._manager.pause, "resume": self._manager.resume, "retry": self._manager.retry}[action]
        self._control_executor.submit(method, download_id)

    def _act_on_selection(self, manager_method) -> None:
        for download_id in self._selected_download_ids():
            self._control_executor.submit(manager_method, download_id)

    def _remove_ids(self, ids: list[int], confirm: bool = True) -> None:
        if not ids:
            return
        if confirm:
            answer = QMessageBox.question(
                self, "Remove downloads",
                f"Remove {len(ids)} download(s) from the list? In-progress downloads will be canceled.",
            )
            if answer != QMessageBox.Yes:
                return
        for download_id in ids:
            self._control_executor.submit(self._manager.remove, download_id)
            self._model.remove_download(download_id)
        self._refresh_all()

    def _remove_selected(self) -> None:
        self._remove_ids(self._selected_download_ids())

    def _pause_all_active(self) -> None:
        for record in self._repo.list_downloads([DownloadStatus.DOWNLOADING]):
            self._control_executor.submit(self._manager.pause, record.id)

    def _pause_all(self) -> None:
        for record in self._model.records():
            if record.status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED):
                self._control_executor.submit(self._manager.pause, record.id)
        self._status_message.setText("Paused all")

    def _resume_all(self) -> None:
        self._manager.start_queue()
        for record in self._model.records():
            if record.status == DownloadStatus.PAUSED:
                self._control_executor.submit(self._manager.resume, record.id)
        self._status_message.setText("Queue started")

    def _clear_completed(self) -> None:
        ids = [r.id for r in self._model.records() if r.status == DownloadStatus.COMPLETED]
        self._remove_ids(ids, confirm=False)

    # -- context menu --------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        if not self._table.selectionModel().isSelected(index):
            self._table.selectRow(index.row())
        menu = QMenu(self)
        menu.addAction(get_icon("description", color=theme.NEUTRAL), "Open file", self._open_selected_file)
        menu.addAction(get_icon("folder", color=theme.NEUTRAL), "Open containing folder", self._open_selected_folder)
        menu.addAction(get_icon("copy", color=theme.NEUTRAL), "Copy link", self._copy_selected_url)
        menu.addAction(get_icon("info", color=theme.NEUTRAL), "Show details", self._show_details)
        menu.addSeparator()
        menu.addAction(get_icon("pause", color=theme.NEUTRAL), "Pause", lambda: self._act_on_selection(self._manager.pause))
        menu.addAction(get_icon("play", color=theme.NEUTRAL), "Resume", lambda: self._act_on_selection(self._manager.resume))
        menu.addAction(get_icon("close", color=theme.NEUTRAL), "Cancel", lambda: self._act_on_selection(self._manager.cancel))
        menu.addAction(get_icon("refresh", color=theme.NEUTRAL), "Retry", lambda: self._act_on_selection(self._manager.retry))
        menu.addAction(get_icon("delete", color=theme.NEUTRAL), "Remove from list", self._remove_selected)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _selected_single_record(self):
        ids = self._selected_download_ids()
        return self._model.get_record(ids[0]) if ids else None

    def _show_details(self) -> None:
        record = self._selected_single_record()
        if record is None:
            return
        text = (
            f"File: {record.filename}\n"
            f"Link: {record.url}\n"
            f"Location: {record.destination_path}\n"
            f"Size: {record.total_size if record.total_size >= 0 else 'unknown'} bytes\n"
            f"Source: {record.source}\n"
            f"Category: {record.category}\n"
            f"Status: {record.status.value}\n"
            f"Added: {record.created_at}\n"
            f"Completed: {record.completed_at or '--'}\n"
        )
        if record.error_message:
            text += f"Error: {record.error_message}\n"
        QMessageBox.information(self, "Download details", text)

    def _open_selected_file(self) -> None:
        record = self._selected_single_record()
        if record is None or not os.path.exists(record.destination_path):
            QMessageBox.warning(self, "File not found", "The file doesn't exist on disk yet.")
            return
        _open_path(record.destination_path)

    def _open_selected_folder(self) -> None:
        record = self._selected_single_record()
        if record is None:
            return
        folder = record.destination_path if os.path.isdir(record.destination_path) else os.path.dirname(record.destination_path)
        if os.path.exists(folder):
            _open_path(folder)

    def _copy_selected_url(self) -> None:
        record = self._selected_single_record()
        if record is not None:
            QGuiApplication.clipboard().setText(record.url)

    # -- settings --------------------------------------------------------------

    def _on_setting_changed(self, key: str) -> None:
        if key == "max_concurrent_downloads":
            self._manager.set_max_concurrent(int(get_setting(self._repo, key)))
        elif key == "global_speed_limit_kbps":
            self._manager.set_global_speed_limit(self._speed_limit_bytes_from_settings())
        elif key == "default_download_root":
            self._downloads_root = self._resolve_downloads_root()
            self._manager._downloads_root = self._downloads_root
        elif key == "start_on_boot" and autostart.is_supported():
            autostart.set_enabled(get_setting(self._repo, key) == "1")
        elif key == "clipboard_monitor":
            self._clipboard_monitor.detect_video_links = get_setting(self._repo, key) == "1"
        elif key.startswith("schedule_"):
            if key == "schedule_enabled" and get_setting(self._repo, key) != "1":
                self._manager.start_queue()  # a schedule that was holding the queue is switched off
            QTimer.singleShot(0, self._queue_schedule.tick)

    def _on_schedule_finished(self, action: str) -> None:
        self._status_message.setText("Scheduled downloads finished")
        if action == "exit":
            self._quit_application()
            return
        self._tray.notify("Downloads finished",
                          "Shutting down in 60 seconds. Run 'shutdown /a' to cancel." if action == "shutdown"
                          else "Putting the PC to sleep.")
        perform_finish_action(action)

    # -- browser / second launch ----------------------------------------------------

    def _handle_ipc(self, message: dict) -> dict:
        kind = message.get("type")
        if kind == "config":
            return {
                "videoButton": get_setting(self._repo, "browser_video_button") == "1",
                "captureDownloads": get_setting(self._repo, "browser_capture") == "1",
            }
        if kind == "show":
            QTimer.singleShot(0, self.bring_to_front)
            return {}
        if kind == "add":
            url = str(message.get("url", "")).strip()
            if not url.lower().startswith(("http://", "https://")):
                return {"ok": False, "error": "not a web link"}
            # reply first: the dialog is modal and the browser should not wait for the user
            QTimer.singleShot(0, lambda: (self.bring_to_front(), self._open_add_dialog(initial_url=url)))
            return {}
        return {"ok": False, "error": f"unknown request {kind!r}"}

    def center_on_screen(self) -> None:
        """Put the window in the middle of the screen it will open on (the one under the mouse)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(area.center())
        self.move(frame.topLeft())

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # -- engine events ------------------------------------------------------

    def _on_engine_event(self, event: DownloadEvent) -> None:
        record = self._find_record(event.download_id)
        previous = record.status if record else None
        self._model.apply_event(event)
        if event.status in TERMINAL_STATUSES:
            record = self._find_record(event.download_id)
            if record is not None and event.status == DownloadStatus.COMPLETED and record.kind == "video":
                stored = self._repo.get_download(event.download_id)
                if stored is not None:
                    self._model.refresh_record(stored)  # video tasks learn their real name at the end
            name = record.filename if record else f"Download {event.download_id}"
            if event.status == DownloadStatus.COMPLETED:
                self._tray.notify("Download complete", name)
            elif event.status == DownloadStatus.FAILED:
                self._tray.notify("Download failed", name, is_error=True)
        if previous != event.status:
            self._refresh_counts()
            self._refresh_empty_state()
        self._refresh_status_bar()
        if event.download_id in self._selected_download_ids():
            self._refresh_detail()

    def _find_record(self, download_id: int):
        return self._model.get_record(download_id)

    # -- lifecycle ------------------------------------------------------------

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        if not self._notified_first_tray_hide:
            self._tray.notify(
                "Still running", "Lavati Downloader is still running in the system tray."
            )
            self._notified_first_tray_hide = True

    def _quit_application(self) -> None:
        self._scheduler.stop()
        self._queue_schedule.stop()
        self._ipc.stop()
        self._manager.stop_queue()
        self._control_executor.shutdown(wait=False)
        QApplication.instance().quit()


def _open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - user-initiated, path is our own download location
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
