from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QDateTime, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from idm.core.clipboard_detect import extract_first_url
from idm.core.http import filename_for
from idm.core.video import QUALITY_TIERS, VideoInfo, VideoOptions, detect_site, display_name
from idm.gui import theme
from idm.gui.downloads_model import format_bytes
from idm.gui.material_icons import get_icon
from idm.gui.probe_worker import ProbeWorker, VideoInfoWorker
from idm.gui.widgets import ElidedLabel, SegmentedControl, field_label, muted
from idm.storage.paths import CATEGORY_SUBFOLDERS, category_for_extension, category_folder


@dataclass
class AddDownloadResult:
    url: str
    filename: str
    destination_dir: str
    category: str
    connections: int
    start_immediately: bool
    scheduled_at: str | None
    kind: str = "file"  # "file" or "video"
    source: str = "Direct link"
    options: str | None = None  # VideoOptions JSON for videos


class _Thumb(QLabel):
    """Dark placeholder with a play triangle; shows the real thumbnail once it arrives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(118, 66)
        self._pixmap: QPixmap | None = None

    def set_image(self, data: bytes | None) -> None:
        pixmap = QPixmap()
        self._pixmap = pixmap if data and pixmap.loadFromData(data) else None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#161A22"))
        painter.drawRoundedRect(rect, 10, 10)
        if self._pixmap:
            scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            clip = QPainterPath()
            clip.addRoundedRect(rect, 10, 10)
            painter.setClipPath(clip)
            painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
            painter.setClipping(False)
        c = rect.center()
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPolygon(QPolygonF([QPointF(c.x() - 7, c.y() - 10), QPointF(c.x() - 7, c.y() + 10),
                                       QPointF(c.x() + 11, c.y())]))


class AddDownloadDialog(QDialog):
    def __init__(self, downloads_root, default_connections: int = 8, initial_url: str = "",
                 video_defaults: VideoOptions | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add download")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("AddDownloadDialog { background: transparent; }")
        self.setFixedWidth(690)
        self._downloads_root = downloads_root
        self._video_defaults = video_defaults or VideoOptions()
        self._drag_offset = None
        self._info: VideoInfo | None = None
        self._site: str | None = None
        self._dest_dirty = False
        self._quality_buttons: dict[int, QPushButton] = {}
        self._chosen_height = self._video_defaults.height
        self._file_size = -1

        self._probe_worker = ProbeWorker()
        self._probe_worker.succeeded.connect(self._on_probe_succeeded)
        self._probe_worker.failed.connect(self._on_probe_failed)
        self._video_worker = VideoInfoWorker(self)
        self._video_worker.succeeded.connect(self._on_video_info)
        self._video_worker.failed.connect(self._on_video_failed)
        self._current_ticket = 0

        # one probe a moment after the user stops typing / pasting
        self._probe_timer = QTimer(self)
        self._probe_timer.setSingleShot(True)
        self._probe_timer.setInterval(450)
        self._probe_timer.timeout.connect(self._probe)

        self._build(initial_url, default_connections)
        self._apply_site()
        if initial_url:
            self._probe()

    # -- construction ----------------------------------------------------------

    def _build(self, initial_url: str, default_connections: int) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)
        self._frame = QFrame()
        self._frame.setStyleSheet(
            f"QFrame#dialogCard {{ background: {theme.BACKGROUND}; border-radius: 18px; }}")
        self._frame.setObjectName("dialogCard")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 28, 50, 70))
        self._frame.setGraphicsEffect(shadow)
        outer.addWidget(self._frame)

        root = QVBoxLayout(self._frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        self._header = QWidget()
        header = QHBoxLayout(self._header)
        header.setContentsMargins(26, 18, 18, 14)
        title = QLabel("Add download")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        close = QPushButton()
        close.setObjectName("closeButton")
        close.setIcon(get_icon("close", color=theme.TEXT, size=14))
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Close")
        close.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close)
        root.addWidget(self._header)
        root.addWidget(_hline())

        body = QVBoxLayout()
        body.setContentsMargins(26, 18, 26, 14)
        body.setSpacing(14)
        root.addLayout(body)

        # url + site pill
        url_row = QFrame()
        url_row.setStyleSheet(f"QFrame#urlRow {{ border: 1px solid {theme.BORDER_STRONG}; border-radius: 10px; }}"
                              f"QFrame#urlRow:focus-within {{ border-color: {theme.PRIMARY}; }}")
        url_row.setObjectName("urlRow")
        url_layout = QHBoxLayout(url_row)
        url_layout.setContentsMargins(4, 2, 8, 2)
        self._url_edit = QLineEdit(initial_url)
        self._url_edit.setPlaceholderText("Paste a link to a file, video or playlist")
        self._url_edit.setStyleSheet("border: none; background: transparent; padding: 8px 8px;")
        self._url_edit.textChanged.connect(self._on_url_changed)
        self._url_edit.editingFinished.connect(self._probe_timer.start)
        self._site_pill = QLabel()
        url_layout.addWidget(self._url_edit, 1)
        url_layout.addWidget(self._site_pill)
        body.addWidget(url_row)

        # stacked: video options / file options
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_video_page())
        self._stack.addWidget(self._build_file_page(default_connections))
        body.addWidget(self._stack)

        # save to
        body.addWidget(field_label("Save to"))
        dest_row = QHBoxLayout()
        self._dest_edit = QLineEdit()
        self._dest_edit.setObjectName("mono")
        self._dest_edit.textEdited.connect(lambda _t: setattr(self, "_dest_dirty", True))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_destination)
        dest_row.addWidget(self._dest_edit, 1)
        dest_row.addWidget(browse)
        body.addLayout(dest_row)

        # footer
        root.addWidget(_hline())
        footer = QHBoxLayout()
        footer.setContentsMargins(26, 14, 26, 18)
        footer.setSpacing(10)
        self._note = ElidedLabel("Only download content you own or have permission to save.")
        self._note.setObjectName("muted")
        self._note.setStyleSheet("font-size: 12px;")
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._download_button = QPushButton("Download")
        self._download_button.setObjectName("primary")
        self._download_button.setDefault(True)
        self._download_button.clicked.connect(self.accept)
        footer.addWidget(self._note, 1)
        footer.addWidget(cancel)
        footer.addWidget(self._download_button)
        root.addLayout(footer)

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(16)
        self._thumb = _Thumb()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        self._found_label = QLabel("Video found")
        self._found_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        self._found_sub = ElidedLabel("Choose a format and quality below.")
        self._found_sub.setObjectName("muted")
        text.addWidget(self._found_label)
        text.addWidget(self._found_sub)
        text.addStretch(1)
        top.addWidget(self._thumb)
        top.addLayout(text, 1)
        layout.addLayout(top)

        layout.addWidget(field_label("Format"))
        self._format = SegmentedControl([("mp4", "Video (MP4)"), ("mp3", "Audio only (MP3)")])
        self._format.changed.connect(self._on_format_changed)
        layout.addWidget(self._format)

        self._quality_label = field_label("Quality")
        layout.addWidget(self._quality_label)
        self._quality_host = QWidget()
        self._quality_grid = QGridLayout(self._quality_host)
        self._quality_grid.setContentsMargins(0, 0, 0, 0)
        self._quality_grid.setSpacing(8)
        layout.addWidget(self._quality_host)

        checks = QHBoxLayout()
        checks.setSpacing(24)
        self._subtitles = QCheckBox("Download subtitles")
        self._playlist = QCheckBox("Whole playlist, if the link has one")
        checks.addWidget(self._subtitles)
        checks.addWidget(self._playlist)
        checks.addStretch(1)
        layout.addLayout(checks)

        self._format.set_value(self._video_defaults.format)
        self._subtitles.setChecked(self._video_defaults.subtitles)
        self._set_qualities(None)
        return page

    def _build_file_page(self, default_connections: int) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(12)
        tile = QLabel()
        tile.setFixedSize(44, 44)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet("background: #F1F3F7; border-radius: 11px;")
        tile.setPixmap(get_icon("description", color=theme.TEXT_MUTED, size=20).pixmap(20, 20))
        info = QVBoxLayout()
        info.setSpacing(2)
        self._filename_edit = QLineEdit()
        self._filename_edit.setPlaceholderText("File name")
        self._file_meta = muted("Detecting file info...")
        info.addWidget(self._filename_edit)
        info.addWidget(self._file_meta)
        card_layout.addWidget(tile)
        card_layout.addLayout(info, 1)
        layout.addWidget(card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self._category_combo = QComboBox()
        self._category_combo.addItems(list(CATEGORY_SUBFOLDERS.keys()))
        self._category_combo.currentTextChanged.connect(self._update_destination_preview)
        self._connections_spin = QSpinBox()
        self._connections_spin.setRange(1, 32)
        self._connections_spin.setValue(default_connections)
        grid.addWidget(field_label("Category"), 0, 0)
        grid.addWidget(field_label("Connections"), 0, 1)
        grid.addWidget(self._category_combo, 1, 0)
        grid.addWidget(self._connections_spin, 1, 1)
        layout.addLayout(grid)

        schedule = QHBoxLayout()
        self._start_now_check = QCheckBox("Start immediately")
        self._start_now_check.setChecked(True)
        self._schedule_check = QCheckBox("Schedule start time")
        self._schedule_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self._schedule_edit.setCalendarPopup(True)
        self._schedule_edit.setEnabled(False)
        self._schedule_check.toggled.connect(self._schedule_edit.setEnabled)
        self._schedule_check.toggled.connect(lambda on: self._start_now_check.setEnabled(not on))
        schedule.addWidget(self._start_now_check)
        schedule.addSpacing(16)
        schedule.addWidget(self._schedule_check)
        schedule.addWidget(self._schedule_edit)
        schedule.addStretch(1)
        layout.addLayout(schedule)
        return page

    # -- url handling ------------------------------------------------------------

    def _resolved_url(self) -> str:
        text = self._url_edit.text().strip()
        return extract_first_url(text) or text

    def _on_url_changed(self, _text: str) -> None:
        self._apply_site()
        self._probe_timer.start()

    def _apply_site(self) -> None:
        url = self._resolved_url()
        site = detect_site(url)
        self._site = site
        if site:
            color = theme.SOURCE_COLORS.get(site, theme.NEUTRAL_LIGHT)
            self._site_pill.setText(f'<span style="color:{color}">●</span>&nbsp;{site}')
            self._site_pill.setStyleSheet(
                f"background: {theme.APP_BG}; border-radius: 10px; padding: 4px 10px; font-weight: 600; font-size: 12px;")
            self._site_pill.setTextFormat(Qt.RichText)
            self._site_pill.show()
            self._found_label.setText(f"Video found on {site}")
            self._stack.setCurrentIndex(0)
        else:
            self._site_pill.hide()
            self._stack.setCurrentIndex(1)
        for i in range(self._stack.count()):  # size the stack to the visible page only
            self._stack.widget(i).setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred if i == self._stack.currentIndex() else QSizePolicy.Ignored)
        self._update_destination_preview()
        self._update_download_button()
        QTimer.singleShot(0, self.adjustSize)

    def _probe(self) -> None:
        url = self._resolved_url()
        if not url.lower().startswith(("http://", "https://")):
            return
        if self._site:
            self._info = None
            self._found_sub.setText("Reading video details...")
            self._current_ticket = self._video_worker.start(url)
        else:
            self._file_meta.setText("Detecting file info...")
            self._probe_worker.start(url)

    # -- file mode ---------------------------------------------------------------

    def _on_probe_succeeded(self, result) -> None:
        if self._site:
            return
        self._filename_edit.setText(result.filename)
        size = "Unknown size" if result.total_size < 0 else format_bytes(result.total_size)
        category = category_for_extension(result.filename)
        self._category_combo.setCurrentText(category)
        meta = f"{size}  ·  {category}"
        if not result.supports_ranges:
            meta += "  ·  single connection (server limit)"
        self._file_meta.setText(meta)
        self._file_size = result.total_size
        self._update_destination_preview()
        self._update_download_button()

    def _on_probe_failed(self, message: str) -> None:
        if self._site:
            return
        self._file_meta.setText(f"Could not detect file info: {message[:90]}")
        if not self._filename_edit.text():
            self._filename_edit.setText(filename_for(self._resolved_url(), None))
        self._update_destination_preview()

    # -- video mode --------------------------------------------------------------

    def _on_video_info(self, ticket: int, info: VideoInfo, thumb) -> None:
        if ticket != self._current_ticket:
            return
        self._info = info
        self._thumb.set_image(thumb)
        who = f" · {info.uploader}" if info.uploader else ""
        self._found_sub.setText(f"{info.title}{who}")
        if info.is_playlist and info.playlist_count:
            self._playlist.setText(f"Whole playlist ({info.playlist_count} videos)")
            self._playlist.setChecked(True)
        else:
            self._playlist.setText("Whole playlist, if the link has one")
        self._set_qualities(info)

    def _on_video_failed(self, ticket: int, message: str) -> None:
        if ticket != self._current_ticket:
            return
        self._found_sub.setText(f"Couldn't read this link ({message}). You can still try the download.")

    def _set_qualities(self, info: VideoInfo | None) -> None:
        while self._quality_grid.count():
            item = self._quality_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._quality_buttons.clear()
        if info is not None and info.qualities:
            options = [(q.height, q.tier, q.size_bytes) for q in info.qualities]
        else:
            options = [(h, t, None) for h, t in QUALITY_TIERS]
        heights = [h for h, _t, _s in options]
        # keep the user's choice, else the tallest not above the saved default, else the best offered
        if self._chosen_height not in heights:
            below = [h for h in heights if h <= self._video_defaults.height]
            self._chosen_height = max(below) if below else max(heights)
        for i, (height, tier, size) in enumerate(options):
            sub = tier if size is None else f"{tier} · {format_bytes(size)}"
            button = _QualityButton(f"{height}p", sub)
            button.setChecked(height == self._chosen_height)
            button.clicked.connect(lambda _=False, h=height: self._choose_height(h))
            self._quality_buttons[height] = button
            self._quality_grid.addWidget(button, i // 3, i % 3)
        for col in range(3):
            self._quality_grid.setColumnStretch(col, 1)
        self._update_download_button()

    def _choose_height(self, height: int) -> None:
        self._chosen_height = height
        for h, button in self._quality_buttons.items():
            button.setChecked(h == height)
        self._update_download_button()

    def _on_format_changed(self, _key: str) -> None:
        audio = self._format.value() == "mp3"
        self._quality_label.setVisible(not audio)
        self._quality_host.setVisible(not audio)
        self._update_destination_preview()
        self._update_download_button()

    def _selected_size(self) -> int | None:
        if self._site is None:
            size = self._file_size
            return size if size and size > 0 else None
        if self._info is None:
            return None
        if self._format.value() == "mp3":
            return self._info.audio_size_bytes
        for q in self._info.qualities:
            if q.height == self._chosen_height:
                return q.size_bytes
        return None

    def _update_download_button(self) -> None:
        if not hasattr(self, "_download_button"):
            return  # still building the pages
        size = self._selected_size()
        self._download_button.setText(f"Download · {format_bytes(size)}" if size else "Download")

    # -- destination -----------------------------------------------------------

    def _category_for_destination(self) -> str:
        if self._site:
            return "Music" if self._format.value() == "mp3" else "Video"
        return self._category_combo.currentText()

    def _update_destination_preview(self, *_args) -> None:
        if self._dest_dirty:
            return
        self._dest_edit.setText(str(category_folder(self._downloads_root, self._category_for_destination())))

    def _browse_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose folder", self._dest_edit.text())
        if chosen:
            self._dest_edit.setText(chosen)
            self._dest_dirty = True

    # -- result ----------------------------------------------------------------

    def video_options(self) -> VideoOptions:
        return VideoOptions(
            format=self._format.value(), height=self._chosen_height,
            subtitles=self._subtitles.isChecked(), playlist=self._playlist.isChecked(),
            name_with_uploader=self._video_defaults.name_with_uploader,
            join_streams=self._video_defaults.join_streams,
        )

    def result_data(self) -> AddDownloadResult:
        url = self._resolved_url()
        if self._site:
            options = self.video_options()
            title = self._info.title if self._info else "video"
            return AddDownloadResult(
                url=url, filename=display_name(title, options),
                destination_dir=self._dest_edit.text().strip(), category=self._category_for_destination(),
                connections=8, start_immediately=True, scheduled_at=None,
                kind="video", source=self._site, options=options.to_json(),
            )
        filename = self._filename_edit.text().strip() or filename_for(url, None)
        scheduled_at = None
        if self._schedule_check.isChecked():
            scheduled_at = self._schedule_edit.dateTime().toUTC().toString(Qt.ISODate)
        return AddDownloadResult(
            url=url, filename=filename, destination_dir=self._dest_edit.text().strip(),
            category=self._category_combo.currentText(), connections=self._connections_spin.value(),
            start_immediately=self._start_now_check.isChecked() and not scheduled_at,
            scheduled_at=scheduled_at,
        )

    # -- frameless window: drag by the header --------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._header.geometry().translated(
                self._frame.pos()).contains(event.position().toPoint()):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _QualityButton(QPushButton):
    """A selectable card: bold resolution over a muted 'tier · size' line."""

    def __init__(self, title: str, sub: str, parent=None):
        super().__init__(parent)
        self.setObjectName("quality")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(0)
        top = QLabel(title)
        top.setStyleSheet("font-weight: 700; font-size: 13px; background: transparent;")
        bottom = QLabel(sub)
        bottom.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;")
        for label in (top, bottom):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(label)


def _hline() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line
