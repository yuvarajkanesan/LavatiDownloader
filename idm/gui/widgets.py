"""Small reusable pieces of the redesigned UI."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget,
)

from idm.gui import theme
from idm.gui.material_icons import get_icon


def card(parent=None) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName("card")
    return frame


def muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    return label


def field_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("fieldLabel")
    return label


def chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("chip")
    return label


class NavButton(QPushButton):
    """Sidebar row: icon, label, and a count at the right."""

    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("navItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._icon_name = icon_name
        self.setText(text)
        self.setIconSize(QSize(16, 16))
        self._count = QLabel("", self)
        self._count.setObjectName("navCount")
        self._count.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.toggled.connect(self._refresh_icon)
        self._refresh_icon(False)
        self.setMinimumHeight(36)

    def _refresh_icon(self, checked: bool) -> None:
        color = theme.SELECTED_TEXT if checked else theme.NEUTRAL
        self.setIcon(get_icon(self._icon_name, color=color, size=16))

    def set_count(self, value: int) -> None:
        self._count.setText(str(value))
        self._count.adjustSize()
        self._place_count()

    def _place_count(self) -> None:
        self._count.move(self.width() - self._count.width() - 12, (self.height() - self._count.height()) // 2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_count()


class SegmentedControl(QWidget):
    """Two or more mutually exclusive text buttons on a pale track (Video (MP4) | Audio only (MP3))."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("segmentTrack")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in options:
            button = QPushButton(text)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)
            button.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        next(iter(self._buttons.values())).setChecked(True)

    def value(self) -> str:
        return next(k for k, b in self._buttons.items() if b.isChecked())

    def set_value(self, key: str) -> None:
        self._buttons[key].setChecked(True)


class SegmentBar(QWidget):
    """The IDM-style strip: one rounded piece per connection, each filled by how far that connection got."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fractions: list[float] = []
        self._color = QColor(theme.PRIMARY)
        self.setFixedHeight(10)

    def set_progress(self, fractions: list[float], color: str = theme.PRIMARY) -> None:
        self._fractions = fractions
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        if not self._fractions:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        n = len(self._fractions)
        gap = 6.0
        width = (self.width() - gap * (n - 1)) / n
        for i, fraction in enumerate(self._fractions):
            left = i * (width + gap)
            track = QRectF(left, 0, width, self.height())
            painter.setBrush(QColor(theme.TRACK))
            painter.drawRoundedRect(track, 5, 5)
            if fraction > 0:
                fill = QRectF(left, 0, max(self.height(), width * min(1.0, fraction)), self.height())
                painter.setBrush(self._color)
                painter.drawRoundedRect(fill, 5, 5)


class ElidedLabel(QLabel):
    """A label that shortens its text with an ellipsis instead of forcing the layout wider."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._apply()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text
        self._apply()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, self.width()))
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")
