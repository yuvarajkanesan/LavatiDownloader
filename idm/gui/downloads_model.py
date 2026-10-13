from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from idm.core.events import DownloadEvent
from idm.storage.models import DownloadRecord, DownloadStatus

COL_FILENAME = 0
COL_SIZE = 1
COL_PROGRESS = 2
COL_SPEED = 3
COL_ETA = 4
COL_ACTIONS = 5
HEADERS = ["Name", "Size", "Progress", "Speed", "ETA", "Actions"]

ROLE_ROW = Qt.UserRole + 1  # the DownloadRow (record plus live speed/eta)

STATUS_LABELS = {
    DownloadStatus.QUEUED: "Queued",
    DownloadStatus.DOWNLOADING: "Downloading",
    DownloadStatus.PAUSED: "Paused",
    DownloadStatus.COMPLETED: "Completed",
    DownloadStatus.FAILED: "Failed",
    DownloadStatus.CANCELED: "Canceled",
    DownloadStatus.SCHEDULED: "Scheduled",
}


def format_bytes(n: int) -> str:
    if n is None or n < 0:
        return "--"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.0f} {unit}" if size >= 100 else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}:{s:02d}"


@dataclass
class DownloadRow:
    record: DownloadRecord
    speed_bytes_per_sec: float = 0.0
    eta_seconds: float | None = None

    @property
    def id(self) -> int:
        return self.record.id


class DownloadsTableModel(QAbstractTableModel):
    """One row per download; updated from DownloadEvents via the EngineBridge, and by direct calls when the
    queue changes structurally (add/remove). Rendering of the Name, Progress and Actions columns is done by
    delegates, so DisplayRole here is the plain-text value (used for sorting, tooltips and tests)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[DownloadRow] = []
        self._index_by_id: dict[int, int] = {}

    # -- Qt model interface -------------------------------------------------

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

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            return self._display_value(row, col)
        if role == Qt.UserRole:
            return row.record
        if role == ROLE_ROW:
            return row
        if role == Qt.ToolTipRole and col == COL_FILENAME:
            tip = f"{row.record.filename}\n{row.record.url}"
            if row.record.error_message:
                tip += f"\n{row.record.error_message}"
            return tip
        if role == Qt.TextAlignmentRole and col in (COL_SPEED, COL_ETA):
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def _display_value(self, row: DownloadRow, col: int):
        r = row.record
        if col == COL_FILENAME:
            return r.filename
        if col == COL_SIZE:
            return format_bytes(r.total_size)
        if col == COL_PROGRESS:
            if r.total_size and r.total_size > 0:
                return f"{min(100.0, 100.0 * r.downloaded_bytes / r.total_size):.0f}%"
            return format_bytes(r.downloaded_bytes) if r.downloaded_bytes else "--"
        if col == COL_SPEED:
            if r.status == DownloadStatus.DOWNLOADING and row.speed_bytes_per_sec > 0:
                return f"{format_bytes(int(row.speed_bytes_per_sec))}/s"
            return "-"
        if col == COL_ETA:
            if r.status == DownloadStatus.DOWNLOADING and row.eta_seconds is not None:
                return format_eta(row.eta_seconds)
            return "-"
        return None

    # -- mutation ------------------------------------------------------------

    def set_records(self, records: list[DownloadRecord]) -> None:
        self.beginResetModel()
        self._rows = [DownloadRow(record=r) for r in records]
        self._index_by_id = {row.id: i for i, row in enumerate(self._rows)}
        self.endResetModel()

    def add_record(self, record: DownloadRecord) -> None:
        row_index = len(self._rows)
        self.beginInsertRows(QModelIndex(), row_index, row_index)
        self._rows.append(DownloadRow(record=record))
        self._index_by_id[record.id] = row_index
        self.endInsertRows()

    def remove_download(self, download_id: int) -> None:
        row_index = self._index_by_id.get(download_id)
        if row_index is None:
            return
        self.beginRemoveRows(QModelIndex(), row_index, row_index)
        del self._rows[row_index]
        self.endRemoveRows()
        self._reindex()

    def _reindex(self) -> None:
        self._index_by_id = {row.id: i for i, row in enumerate(self._rows)}

    def apply_event(self, event: DownloadEvent) -> None:
        row_index = self._index_by_id.get(event.download_id)
        if row_index is None:
            return
        row = self._rows[row_index]
        row.record.status = event.status
        row.record.downloaded_bytes = event.downloaded_bytes
        if event.total_size and event.total_size > 0:
            row.record.total_size = event.total_size
        if event.error_message:
            row.record.error_message = event.error_message
        row.speed_bytes_per_sec = event.speed_bytes_per_sec
        row.eta_seconds = event.eta_seconds
        self.dataChanged.emit(self.index(row_index, 0), self.index(row_index, len(HEADERS) - 1))

    def refresh_record(self, record: DownloadRecord) -> None:
        """A task changed the file name/path/category behind the model's back (video downloads finish with
        their real name); copy the stored values over."""
        row_index = self._index_by_id.get(record.id)
        if row_index is None:
            return
        mine = self._rows[row_index].record
        mine.filename, mine.destination_path, mine.category = record.filename, record.destination_path, record.category
        self.dataChanged.emit(self.index(row_index, 0), self.index(row_index, len(HEADERS) - 1))

    def row_at(self, index: QModelIndex) -> DownloadRow | None:
        if not index.isValid():
            return None
        return self._rows[index.row()]

    def get_record(self, download_id: int) -> DownloadRecord | None:
        row_index = self._index_by_id.get(download_id)
        return self._rows[row_index].record if row_index is not None else None

    def records(self) -> list[DownloadRecord]:
        return [row.record for row in self._rows]
