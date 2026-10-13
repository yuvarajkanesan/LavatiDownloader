"""Cell painters for the downloads table: file name with source and status pill, progress bar, action buttons."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from idm.gui import theme
from idm.gui.downloads_model import ROLE_ROW, STATUS_LABELS
from idm.gui.material_icons import get_icon
from idm.storage.models import DownloadStatus

ROW_HEIGHT = 56
CATEGORY_ICON = {
    "Documents": "description", "Video": "movie", "Music": "music",
    "Compressed": "archive", "Programs": "apps", "Other": "description",
}
BUTTON = 30
BUTTON_GAP = 6


def _mono(size: int = 12) -> QFont:
    font = QFont()
    font.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas"])
    font.setPixelSize(size)
    return font


def _paint_background(painter: QPainter, option) -> None:
    if option.state & QStyle.State_Selected:
        painter.fillRect(option.rect, QColor("#EEF2FB"))


def actions_for(status: DownloadStatus) -> list[str]:
    """Action names for the buttons shown at the right of a row, left to right."""
    if status == DownloadStatus.DOWNLOADING:
        return ["pause", "remove"]
    if status in (DownloadStatus.QUEUED, DownloadStatus.PAUSED, DownloadStatus.SCHEDULED):
        return ["resume", "remove"]
    if status in (DownloadStatus.FAILED, DownloadStatus.CANCELED):
        return ["retry", "remove"]
    return ["remove"]


_ACTION_ICON = {"pause": "pause", "resume": "play", "retry": "refresh", "remove": "close"}
_ACTION_COLOR = {"remove": theme.ERROR}
_ACTION_TIP = {"pause": "Pause", "resume": "Resume", "retry": "Retry", "remove": "Remove from list"}


def button_rects(cell: QRect, count: int) -> list[QRect]:
    """Rects of `count` square buttons packed against the right edge of the cell, in left-to-right order."""
    top = cell.top() + (cell.height() - BUTTON) // 2
    right = cell.right() - 12
    rects = []
    for i in range(count):
        left = right - BUTTON + 1 - (count - 1 - i) * (BUTTON + BUTTON_GAP)
        rects.append(QRect(left, top, BUTTON, BUTTON))
    return rects


class TextDelegate(QStyledItemDelegate):
    """Plain cells (size, speed, ETA) in the mono font, with the shared selection background."""

    def paint(self, painter, option, index) -> None:
        painter.save()
        _paint_background(painter, option)
        painter.setFont(_mono(12))
        painter.setPen(QColor(theme.TEXT))
        text = index.data(Qt.DisplayRole) or ""
        painter.drawText(option.rect.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(80, ROW_HEIGHT)


class NameDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        row = index.data(ROLE_ROW)
        if row is None:
            return
        rec = row.record
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        _paint_background(painter, option)
        rect = option.rect

        # icon tile
        tile = QRectF(rect.left() + 14, rect.top() + (rect.height() - 36) / 2, 36, 36)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F1F3F7"))
        painter.drawRoundedRect(tile, 9, 9)
        icon = get_icon(CATEGORY_ICON.get(rec.category, "description"), color=theme.TEXT_MUTED, size=16)
        icon.paint(painter, QRect(int(tile.left()) + 10, int(tile.top()) + 10, 16, 16))

        text_left = int(tile.right()) + 12
        text_width = rect.right() - text_left - 8

        # file name
        name_font = QFont(option.font)
        name_font.setPixelSize(13)
        name_font.setWeight(QFont.DemiBold)
        painter.setFont(name_font)
        painter.setPen(QColor(theme.TEXT))
        name = QFontMetrics(name_font).elidedText(rec.filename, Qt.ElideMiddle, text_width)
        painter.drawText(QRect(text_left, rect.top() + 9, text_width, 18), Qt.AlignLeft | Qt.AlignVCenter, name)

        # source dot + source name + status pill
        small = QFont(option.font)
        small.setPixelSize(11)
        painter.setFont(small)
        fm = QFontMetrics(small)
        y = rect.top() + 30
        x = text_left
        painter.setBrush(QColor(theme.SOURCE_COLORS.get(rec.source, theme.NEUTRAL_LIGHT)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(x + 3, y + 8), 3, 3)
        x += 12
        painter.setPen(QColor(theme.TEXT_MUTED))
        source_w = fm.horizontalAdvance(rec.source)
        painter.drawText(QRect(x, y, source_w + 2, 16), Qt.AlignLeft | Qt.AlignVCenter, rec.source)
        x += source_w + 10

        label = STATUS_LABELS.get(rec.status, rec.status.value)
        fg, bg = theme.STATUS_PILLS.get(rec.status.value, (theme.TEXT_MUTED, "#EEF0F4"))
        pill_w = fm.horizontalAdvance(label) + 16
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(x, y, pill_w, 17), 8.5, 8.5)
        painter.setPen(QColor(fg))
        painter.drawText(QRect(x, y, pill_w, 17), Qt.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(260, ROW_HEIGHT)


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        row = index.data(ROLE_ROW)
        if row is None:
            return
        rec = row.record
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        _paint_background(painter, option)

        fraction = None
        if rec.total_size and rec.total_size > 0:
            fraction = min(1.0, rec.downloaded_bytes / rec.total_size)
        elif rec.status == DownloadStatus.COMPLETED:
            fraction = 1.0
        label_w = 52
        rect = option.rect
        track = QRectF(rect.left() + 8, rect.center().y() - 4, max(20, rect.width() - label_w - 22), 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.TRACK))
        painter.drawRoundedRect(track, 4, 4)
        color = QColor(theme.STATUS_COLORS.get(rec.status.value, theme.NEUTRAL_LIGHT))
        if fraction is not None and fraction > 0:
            fill = QRectF(track)
            fill.setWidth(max(8.0, track.width() * fraction))
            painter.setBrush(color)
            painter.drawRoundedRect(fill, 4, 4)
        elif fraction is None and rec.status == DownloadStatus.DOWNLOADING:
            painter.setBrush(color)
            painter.drawRoundedRect(track, 4, 4)  # unknown size: full bar rather than frozen at 0

        painter.setFont(_mono(12))
        painter.setPen(QColor(theme.TEXT))
        text = f"{(fraction or 0) * 100:.0f}%" if fraction is not None else "--"
        painter.drawText(QRect(int(track.right()) + 6, rect.top(), label_w, rect.height()),
                         Qt.AlignRight | Qt.AlignVCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, ROW_HEIGHT)


class ActionsDelegate(QStyledItemDelegate):
    """Square icon buttons at the right of each row. Clicks are reported through `triggered`."""

    triggered = Signal(int, str)  # download id, action name

    def paint(self, painter, option, index) -> None:
        row = index.data(ROLE_ROW)
        if row is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        _paint_background(painter, option)
        names = actions_for(row.record.status)
        for name, rect in zip(names, button_rects(option.rect, len(names))):
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.setBrush(QColor(theme.BACKGROUND))
            painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            color = _ACTION_COLOR.get(name, theme.TEXT)
            size = 14
            get_icon(_ACTION_ICON[name], color=color, size=size).paint(
                painter, QRect(rect.left() + (BUTTON - size) // 2, rect.top() + (BUTTON - size) // 2, size, size))
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(100, ROW_HEIGHT)

    def _hit(self, option, index, pos) -> str | None:
        row = index.data(ROLE_ROW)
        if row is None:
            return None
        names = actions_for(row.record.status)
        for name, rect in zip(names, button_rects(option.rect, len(names))):
            if rect.contains(pos):
                return name
        return None

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            name = self._hit(option, index, event.position().toPoint())
            if name:
                self.triggered.emit(index.data(ROLE_ROW).id, name)
                return True
        return False

    def helpEvent(self, event, view, option, index) -> bool:
        from PySide6.QtWidgets import QToolTip
        name = self._hit(option, index, event.pos())
        if name:
            QToolTip.showText(event.globalPos(), _ACTION_TIP[name], view)
            return True
        QToolTip.hideText()
        return True
