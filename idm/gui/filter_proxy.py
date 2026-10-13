from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt

from idm.storage.models import DownloadStatus

ACTIVE_STATUSES = {DownloadStatus.DOWNLOADING}
WAITING_STATUSES = {DownloadStatus.QUEUED, DownloadStatus.PAUSED, DownloadStatus.SCHEDULED}
COMPLETED_STATUSES = {DownloadStatus.COMPLETED}

STATUS_GROUPS = {
    "active": ACTIVE_STATUSES,
    "waiting": WAITING_STATUSES,  # "Queued and paused"
    "completed": COMPLETED_STATUSES,
}


def group_of(status: DownloadStatus) -> str | None:
    for name, statuses in STATUS_GROUPS.items():
        if status in statuses:
            return name
    return None


class DownloadsFilterProxy(QSortFilterProxyModel):
    """Sidebar selection (a status group, or a file type) combined with the free-text search box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._category: str | None = None
        self._status_group: str | None = None  # None | "active" | "waiting" | "completed"
        self._search_text = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def set_category(self, category: str | None) -> None:
        self._category = category
        self.invalidateFilter()

    def set_status_group(self, group: str | None) -> None:
        self._status_group = group
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        self._search_text = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        index = self.sourceModel().index(source_row, 0, source_parent)
        record = self.sourceModel().data(index, Qt.UserRole)
        if record is None:
            return False

        if self._category is not None and record.category != self._category:
            return False

        if self._status_group is not None and record.status not in STATUS_GROUPS[self._status_group]:
            return False

        if self._search_text and self._search_text not in record.filename.lower() \
                and self._search_text not in record.url.lower():
            return False

        return True
