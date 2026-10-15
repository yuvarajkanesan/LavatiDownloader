"""The Add torrent sheet: shows what is in a torrent, lets you tick the files you want, and starts it."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from idm.core.torrent import TorrentBackend, TorrentPreview
from idm.gui import theme
from idm.gui.add_download_dialog import _hline
from idm.gui.downloads_model import format_bytes
from idm.gui.material_icons import get_icon
from idm.gui.widgets import ElidedLabel, SegmentedControl, field_label, muted

GIVE_UP_AFTER_MS = 120_000  # a magnet link that finds no file list in two minutes is reported, not waited on forever


class AddTorrentDialog(QDialog):
    """`preview_id` comes from backend.preview_magnet / preview_file. Accepting commits the torrent; closing any other
    way cancels it, so nothing is left half-added."""

    def __init__(self, backend: TorrentBackend, preview_id: str, save_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add torrent")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("AddTorrentDialog { background: transparent; }")
        self.setFixedWidth(690)
        self._backend = backend
        self._preview_id = preview_id
        self._preview: TorrentPreview | None = None
        self._finished = False
        self._drag_offset = None
        self._elapsed_ms = 0
        self._dest_dirty = False
        self._build(save_dir)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()
        self._poll()

    # -- construction ----------------------------------------------------------------

    def _build(self, save_dir: str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 22)
        self._frame = QFrame()
        self._frame.setObjectName("dialogCard")
        self._frame.setStyleSheet(f"QFrame#dialogCard {{ background: {theme.BACKGROUND}; border-radius: 18px; }}")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(20, 28, 50, 70))
        self._frame.setGraphicsEffect(shadow)
        outer.addWidget(self._frame)
        root = QVBoxLayout(self._frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget()
        head = QHBoxLayout(self._header)
        head.setContentsMargins(26, 18, 18, 14)
        title = QLabel("Add torrent")
        title.setStyleSheet("font-size: 17px; font-weight: 700;")
        close = QPushButton()
        close.setObjectName("closeButton")
        close.setIcon(get_icon("close", color=theme.TEXT, size=14))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        root.addWidget(self._header)
        root.addWidget(_hline())

        body = QVBoxLayout()
        body.setContentsMargins(26, 18, 26, 14)
        body.setSpacing(12)
        root.addLayout(body)

        self._name = ElidedLabel("Fetching torrent info...")
        self._name.setStyleSheet("font-size: 15px; font-weight: 700;")
        self._summary = muted("Looking for peers that have the file list. This can take a little while.")
        body.addWidget(self._name)
        body.addWidget(self._summary)

        self._files = QTableWidget(0, 2)
        self._files.setHorizontalHeaderLabels(["Files", "Size"])
        self._files.verticalHeader().setVisible(False)
        self._files.setShowGrid(False)
        self._files.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._files.setSelectionMode(QAbstractItemView.NoSelection)
        self._files.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._files.setColumnWidth(1, 100)
        self._files.setMinimumHeight(190)
        self._files.setMaximumHeight(240)
        self._files.itemChanged.connect(self._on_toggle)
        body.addWidget(self._files)

        select_row = QHBoxLayout()
        all_button = QPushButton("Select all")
        none_button = QPushButton("Select none")
        for button, value in ((all_button, True), (none_button, False)):
            button.setFixedHeight(30)
            button.clicked.connect(lambda _=False, v=value: self._set_all(v))
            select_row.addWidget(button)
        select_row.addStretch(1)
        self._total = QLabel("")
        self._total.setObjectName("mono")
        select_row.addWidget(self._total)
        body.addLayout(select_row)

        body.addWidget(field_label("When added"))
        self._mode = SegmentedControl([("now", "Start immediately"), ("order", "Download in order")])
        body.addWidget(self._mode)

        body.addWidget(field_label("Save to"))
        dest = QHBoxLayout()
        self._dest = QLineEdit(save_dir)
        self._dest.setObjectName("mono")
        self._dest.textEdited.connect(lambda _t: setattr(self, "_dest_dirty", True))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        dest.addWidget(self._dest, 1)
        dest.addWidget(browse)
        body.addLayout(dest)

        root.addWidget(_hline())
        footer = QHBoxLayout()
        footer.setContentsMargins(26, 14, 26, 18)
        footer.setSpacing(10)
        note = ElidedLabel("Torrents share your connection with other people while they download and seed.")
        note.setObjectName("muted")
        note.setStyleSheet("font-size: 12px;")
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._add = QPushButton("Add")
        self._add.setObjectName("primary")
        self._add.setDefault(True)
        self._add.setEnabled(False)
        self._add.clicked.connect(self.accept)
        footer.addWidget(note, 1)
        footer.addWidget(cancel)
        footer.addWidget(self._add)
        root.addLayout(footer)

    # -- state ------------------------------------------------------------------------------

    def _poll(self) -> None:
        if self._preview is not None and self._preview.ready:
            return
        self._elapsed_ms += self._poll_timer.interval() if hasattr(self, "_poll_timer") else 0
        preview = self._backend.preview(self._preview_id)
        if preview is None:
            self._show_error("This torrent is no longer available.")
            return
        if preview.ready:
            self._poll_timer.stop()
            self._show_files(preview)
        elif self._elapsed_ms >= GIVE_UP_AFTER_MS:
            self._poll_timer.stop()
            self._show_error("No peers sent the file list. Check the magnet link, or try again later.")
        elif preview.name:
            self._name.setText(preview.name)

    def _show_error(self, message: str) -> None:
        self._summary.setText(message)
        self._summary.setStyleSheet(f"color: {theme.ERROR};")

    def _show_files(self, preview: TorrentPreview) -> None:
        self._preview = preview
        self._name.setText(preview.name or "Torrent")
        self._summary.setText(f"{len(preview.files)} file{'s' if len(preview.files) != 1 else ''}  ·  "
                              f"{format_bytes(preview.total_size)}")
        self._files.blockSignals(True)
        self._files.setRowCount(len(preview.files))
        for row, f in enumerate(preview.files):
            name = QTableWidgetItem(f.path.replace("\\", "/"))
            name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.Checked)
            name.setData(Qt.UserRole, f.index)
            size = QTableWidgetItem(format_bytes(f.size))
            size.setFlags(Qt.ItemIsEnabled)
            size.setData(Qt.UserRole, f.size)
            self._files.setItem(row, 0, name)
            self._files.setItem(row, 1, size)
        self._files.blockSignals(False)
        self._refresh_total()

    def _selected(self) -> list[int]:
        return [self._files.item(r, 0).data(Qt.UserRole) for r in range(self._files.rowCount())
                if self._files.item(r, 0).checkState() == Qt.Checked]

    def _selected_size(self) -> int:
        return sum(self._files.item(r, 1).data(Qt.UserRole) for r in range(self._files.rowCount())
                   if self._files.item(r, 0).checkState() == Qt.Checked)

    def _on_toggle(self, _item) -> None:
        self._refresh_total()

    def _set_all(self, checked: bool) -> None:
        self._files.blockSignals(True)
        for r in range(self._files.rowCount()):
            self._files.item(r, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._files.blockSignals(False)
        self._refresh_total()

    def _refresh_total(self) -> None:
        selected = self._selected()
        size = self._selected_size()
        self._total.setText(f"{len(selected)} selected  ·  {format_bytes(size)}")
        self._add.setEnabled(bool(selected))
        self._add.setText(f"Add · {format_bytes(size)}" if selected else "Add")

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose folder", self._dest.text())
        if chosen:
            self._dest.setText(chosen)
            self._dest_dirty = True

    # -- result -----------------------------------------------------------------------------

    def accept(self) -> None:
        if self._preview is None or not self._selected():
            return
        try:
            self._backend.commit_preview(self._preview_id, self._selected(), self._mode.value() == "order",
                                         self._dest.text().strip())
        except Exception as exc:  # noqa: BLE001 - show it rather than losing the sheet
            self._show_error(str(exc))
            return
        self._finished = True
        self._poll_timer.stop()
        super().accept()

    def done(self, result: int) -> None:
        if not self._finished:
            self._backend.cancel_preview(self._preview_id)  # closed without adding: forget the torrent
        self._poll_timer.stop()
        super().done(result)

    # -- frameless window: drag by the header -----------------------------------------------------

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
