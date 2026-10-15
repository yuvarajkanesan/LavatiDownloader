from __future__ import annotations

import os
from datetime import time as dtime

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSlider, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from idm import browser_integration
from idm.core import ffmpeg_tool
from idm.core.schedule import ALL_DAYS, FINISH_ACTIONS, parse_hhmm
from idm.core.video import QUALITY_TIERS, VideoOptions
from idm.gui import autostart, theme
from idm.gui.ffmpeg_prompt import download_with_progress
from idm.gui.material_icons import get_icon
from idm.gui.widgets import card, field_label, muted
from idm.storage.repository import DownloadRepository

# Settings keys and their defaults live here, next to the widgets that own them, so the two can't drift apart.
DEFAULTS = {
    "default_download_root": "",
    "max_connections_per_download": "8",
    "max_concurrent_downloads": "3",
    "global_speed_limit_kbps": "0",  # 0 = unlimited
    "start_on_boot": "0",
    "video_quality": "1080",
    "video_format": "mp4",
    "clipboard_monitor": "1",
    "join_streams": "1",
    "video_subtitles": "0",
    "video_name_uploader": "0",
    "schedule_enabled": "0",
    "schedule_start": "23:00",
    "schedule_stop": "06:00",
    "schedule_days": "0,1,2,3,4",
    "schedule_finish": "nothing",
    "browser_video_button": "1",
    "browser_capture": "1",
}

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FINISH_LABELS = {"nothing": "Do nothing", "exit": "Exit the app", "sleep": "Put the PC to sleep", "shutdown": "Shut down the PC"}
SECTIONS = ("General", "Video and social", "Speed and connections", "Scheduler", "Browser integration")


def get_setting(repo: DownloadRepository, key: str) -> str:
    return repo.get_setting(key, DEFAULTS[key])


def video_defaults(repo: DownloadRepository) -> VideoOptions:
    return VideoOptions(
        format=get_setting(repo, "video_format"),
        height=int(get_setting(repo, "video_quality")),
        subtitles=get_setting(repo, "video_subtitles") == "1",
        name_with_uploader=get_setting(repo, "video_name_uploader") == "1",
        join_streams=get_setting(repo, "join_streams") == "1",
    )


class SettingsPage(QWidget):
    """Every control saves as soon as it changes; `changed(key)` tells the main window to apply it."""

    changed = Signal(str)
    back_requested = Signal()

    def __init__(self, repo: DownloadRepository, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._loading = True
        self._cards: list[QWidget] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        nav = QVBoxLayout()
        nav.setSpacing(2)
        back = QPushButton(" Downloads")
        back.setObjectName("settingsNav")
        back.setIcon(get_icon("grid", color=theme.NEUTRAL, size=16))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        nav.addWidget(back)
        nav.addSpacing(10)
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        nav.addWidget(title)
        nav.addSpacing(8)
        self._nav_buttons: list[QPushButton] = []
        for i, name in enumerate(SECTIONS):
            button = QPushButton(name)
            button.setObjectName("settingsNav")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, idx=i: self._scroll_to(idx))
            nav.addWidget(button)
            self._nav_buttons.append(button)
        nav.addStretch(1)
        nav_host = QWidget()
        nav_host.setLayout(nav)
        nav_host.setFixedWidth(200)
        root.addWidget(nav_host)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 8, 20)
        self._content.setSpacing(16)
        self._scroll.setWidget(content)
        self._scroll.verticalScrollBar().valueChanged.connect(self._sync_nav)
        root.addWidget(self._scroll, 1)

        self._build_general()
        self._build_video()
        self._build_speed()
        self._build_scheduler()
        self._build_browser()
        self._content.addStretch(1)
        self._nav_buttons[0].setChecked(True)
        self._load()
        self._loading = False

    # -- helpers -----------------------------------------------------------------

    def _section(self, title: str, subtitle: str) -> QVBoxLayout:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        layout.addWidget(muted(subtitle))
        self._content.addWidget(frame)
        self._cards.append(frame)
        return layout

    def _check(self, text: str, key: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setProperty("key", key)
        box.toggled.connect(lambda on, k=key: self._save(k, "1" if on else "0"))
        return box

    def _save(self, key: str, value: str) -> None:
        if self._loading:
            return
        self._repo.set_setting(key, value)
        self.changed.emit(key)

    def _labeled(self, label: str, widget: QWidget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(field_label(label))
        box.addWidget(widget)
        return box

    def _scroll_to(self, index: int) -> None:
        self._scroll.verticalScrollBar().setValue(self._cards[index].y())
        self._set_nav(index)

    def _set_nav(self, index: int) -> None:
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)

    def _sync_nav(self, value: int) -> None:
        bar = self._scroll.verticalScrollBar()
        if bar.maximum() and value >= bar.maximum() - 4:
            self._set_nav(len(self._cards) - 1)
            return
        current = 0
        for i, frame in enumerate(self._cards):
            if frame.y() <= value + 40:
                current = i
        self._set_nav(current)

    # -- sections ------------------------------------------------------------------

    def _build_general(self) -> None:
        layout = self._section("General", "Where downloads go and how the app starts.")
        self._root_edit = QLineEdit()
        self._root_edit.setObjectName("mono")
        self._root_edit.editingFinished.connect(lambda: self._save("default_download_root", self._root_edit.text().strip()))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_root)
        row = QHBoxLayout()
        row.addWidget(self._root_edit, 1)
        row.addWidget(browse)
        layout.addWidget(field_label("Default download folder"))
        layout.addLayout(row)
        layout.addWidget(muted("Videos, Documents, Music and other category folders are created inside it."))
        self._autostart = self._check("Start Lavati Downloader when I sign in", "start_on_boot")
        if not autostart.is_supported():
            self._autostart.setEnabled(False)
            self._autostart.setText(self._autostart.text() + " (not supported on this OS yet)")
        layout.addWidget(self._autostart)

    def _build_video(self) -> None:
        layout = self._section("Video and social", "Defaults for links from YouTube, Instagram, Facebook, TikTok and X.")
        self._quality = QComboBox()
        for height, _tier in QUALITY_TIERS:
            self._quality.addItem(f"Best up to {height}p", str(height))
        self._quality.currentIndexChanged.connect(lambda _i: self._save("video_quality", self._quality.currentData()))
        self._format = QComboBox()
        self._format.addItem("MP4", "mp4")
        self._format.addItem("MP3 (audio only)", "mp3")
        self._format.currentIndexChanged.connect(lambda _i: self._save("video_format", self._format.currentData()))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self._labeled("Default quality", self._quality), 1)
        row.addLayout(self._labeled("Preferred format", self._format), 1)
        layout.addLayout(row)
        self._clipboard = self._check("Detect video links copied to the clipboard", "clipboard_monitor")
        self._join = self._check("Join separate audio and video streams automatically", "join_streams")
        self._subs = self._check("Always download subtitles", "video_subtitles")
        self._uploader = self._check("Name files with the uploader and title", "video_name_uploader")
        for box in (self._clipboard, self._join, self._subs, self._uploader):
            layout.addWidget(box)
        layout.addSpacing(4)
        layout.addWidget(field_label("Video tool (ffmpeg)"))
        tool_row = QHBoxLayout()
        self._tool_status = QLabel()
        self._tool_button = QPushButton("Download")
        self._tool_button.setCursor(Qt.PointingHandCursor)
        self._tool_button.clicked.connect(self._download_tool)
        tool_row.addWidget(self._tool_status, 1)
        tool_row.addWidget(self._tool_button)
        layout.addLayout(tool_row)
        layout.addWidget(muted("Joins separate video and audio (needed for YouTube and any high quality) and makes MP3s. "
                               "Downloaded once and kept on this PC."))
        self._refresh_tool()

    def _build_speed(self) -> None:
        layout = self._section("Speed and connections", "Each file is split into segments that download in parallel.")
        self._conn_slider = QSlider(Qt.Horizontal)
        self._conn_slider.setRange(1, 32)
        self._conn_label = QLabel()
        self._conn_label.setObjectName("mono")
        self._conn_slider.valueChanged.connect(self._on_connections)
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(field_label("Connections per file"))
        left.addWidget(self._conn_slider)
        left.addWidget(self._conn_label)
        self._concurrent = QComboBox()
        for n in range(1, 11):
            self._concurrent.addItem(str(n), str(n))
        self._concurrent.currentIndexChanged.connect(
            lambda _i: self._save("max_concurrent_downloads", self._concurrent.currentData()))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(left, 1)
        row.addLayout(self._labeled("Simultaneous downloads", self._concurrent), 1)
        layout.addLayout(row)
        self._limit_check = QCheckBox("Limit total speed")
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(1, 1_000_000)
        self._limit_spin.setValue(1024)
        self._limit_spin.setSuffix(" KB/s")
        self._limit_check.toggled.connect(self._on_limit)
        self._limit_spin.valueChanged.connect(self._on_limit)
        limit_row = QHBoxLayout()
        limit_row.addWidget(self._limit_check)
        limit_row.addWidget(self._limit_spin)
        limit_row.addStretch(1)
        layout.addLayout(limit_row)

    def _build_scheduler(self) -> None:
        layout = self._section("Scheduler", "Run the queue at set times, for example overnight.")
        self._sched_on = self._check("Start the queue automatically", "schedule_enabled")
        layout.addWidget(self._sched_on)
        self._start_time = QTimeEdit()
        self._stop_time = QTimeEdit()
        for edit, key in ((self._start_time, "schedule_start"), (self._stop_time, "schedule_stop")):
            edit.setDisplayFormat("hh:mm")
            edit.timeChanged.connect(lambda t, k=key: self._save(k, t.toString("HH:mm")))
        self._finish = QComboBox()
        for action in FINISH_ACTIONS:
            self._finish.addItem(FINISH_LABELS[action], action)
        self._finish.currentIndexChanged.connect(lambda _i: self._save("schedule_finish", self._finish.currentData()))
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self._labeled("Start at", self._start_time), 1)
        row.addLayout(self._labeled("Stop at", self._stop_time), 1)
        row.addLayout(self._labeled("When finished", self._finish), 1)
        layout.addLayout(row)
        days = QHBoxLayout()
        days.setSpacing(8)
        self._day_buttons: list[QPushButton] = []
        for i, name in enumerate(DAY_NAMES):
            button = QPushButton(name)
            button.setObjectName("pill")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.toggled.connect(self._on_days)
            days.addWidget(button)
            self._day_buttons.append(button)
        days.addStretch(1)
        layout.addLayout(days)
        self._sched_note = muted("")
        layout.addWidget(self._sched_note)

    def _build_browser(self) -> None:
        layout = self._section("Browser integration", "Send links from your browser straight to the downloader.")
        self._video_button = self._check("Show a Download button on videos", "browser_video_button")
        self._capture = self._check("Capture file downloads started in the browser", "browser_capture")
        layout.addWidget(self._video_button)
        layout.addWidget(self._capture)
        folder = browser_integration.extension_dir()
        self._ext_hint = muted(
            "Chrome and Edge: open the extensions page, switch on Developer mode, choose Load unpacked and pick the "
            "extension folder." if folder else "The browser extension is not part of this build.")
        self._ext_hint.setWordWrap(True)
        layout.addWidget(self._ext_hint)
        buttons = QHBoxLayout()
        open_folder = QPushButton("Open extension folder")
        open_folder.setEnabled(folder is not None)
        open_folder.clicked.connect(lambda: folder and os.startfile(str(folder)) if os.name == "nt" else None)
        repair = QPushButton("Repair browser link")
        repair.setToolTip("Registers the app with Chrome and Edge again")
        repair.clicked.connect(self._repair_browser)
        self._browser_status = muted("")
        buttons.addWidget(open_folder)
        buttons.addWidget(repair)
        buttons.addWidget(self._browser_status, 1)
        layout.addLayout(buttons)

    # -- handlers ---------------------------------------------------------------------

    def _refresh_tool(self) -> None:
        installed = ffmpeg_tool.ffmpeg_path()
        self._tool_status.setText("Installed" if installed else "Not installed")
        self._tool_status.setStyleSheet(f"color: {theme.SUCCESS if installed else '#B06000'}; font-weight: 600;")
        self._tool_button.setEnabled(not installed)  # the button is live exactly when the tool is missing
        self._tool_button.setText("Installed" if installed else "Download")

    def _download_tool(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        error = download_with_progress(self)
        if error and error != "cancelled":
            QMessageBox.warning(self, "Video tool", error)
        self._refresh_tool()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_tool()

    def _browse_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose folder", self._root_edit.text())
        if chosen:
            self._root_edit.setText(chosen)
            self._save("default_download_root", chosen)

    def _on_connections(self, value: int) -> None:
        self._conn_label.setText(f"{value} segments")
        self._save("max_connections_per_download", str(value))

    def _on_limit(self, *_args) -> None:
        self._limit_spin.setEnabled(self._limit_check.isChecked())
        self._save("global_speed_limit_kbps", str(self._limit_spin.value()) if self._limit_check.isChecked() else "0")

    def _on_days(self, *_args) -> None:
        days = [str(i) for i, b in enumerate(self._day_buttons) if b.isChecked()]
        self._save("schedule_days", ",".join(days))
        self._update_note()

    def _update_note(self) -> None:
        if not any(b.isChecked() for b in self._day_buttons):
            self._sched_note.setText("No days selected: the schedule will never run.")
        else:
            self._sched_note.setText("")

    def _repair_browser(self) -> None:
        from idm.storage.paths import default_database_path
        try:
            browser_integration.register(default_database_path().parent)
            self._browser_status.setText("Registered with Chrome and Edge.")
        except OSError as exc:
            self._browser_status.setText(f"Failed: {exc}")

    # -- load -------------------------------------------------------------------------

    def _load(self) -> None:
        g = lambda key: get_setting(self._repo, key)  # noqa: E731
        self._root_edit.setText(g("default_download_root"))
        self._autostart.setChecked(autostart.is_enabled() if autostart.is_supported() else g("start_on_boot") == "1")
        self._quality.setCurrentIndex(max(0, self._quality.findData(g("video_quality"))))
        self._format.setCurrentIndex(max(0, self._format.findData(g("video_format"))))
        for box, key in ((self._clipboard, "clipboard_monitor"), (self._join, "join_streams"),
                         (self._subs, "video_subtitles"), (self._uploader, "video_name_uploader"),
                         (self._sched_on, "schedule_enabled"), (self._video_button, "browser_video_button"),
                         (self._capture, "browser_capture")):
            box.setChecked(g(key) == "1")
        connections = int(g("max_connections_per_download"))
        self._conn_slider.setValue(connections)
        self._conn_label.setText(f"{connections} segments")
        self._concurrent.setCurrentIndex(max(0, self._concurrent.findData(g("max_concurrent_downloads"))))
        limit = int(g("global_speed_limit_kbps"))
        self._limit_check.setChecked(limit > 0)
        if limit > 0:
            self._limit_spin.setValue(limit)
        self._limit_spin.setEnabled(limit > 0)
        for edit, key, default in ((self._start_time, "schedule_start", dtime(23, 0)),
                                   (self._stop_time, "schedule_stop", dtime(6, 0))):
            t = parse_hhmm(g(key), default)
            edit.setTime(QTime(t.hour, t.minute))
        self._finish.setCurrentIndex(max(0, self._finish.findData(g("schedule_finish"))))
        days = {int(d) for d in g("schedule_days").split(",") if d.strip().isdigit()}
        for i, button in enumerate(self._day_buttons):
            button.setChecked(i in days and i in ALL_DAYS)
        self._update_note()
