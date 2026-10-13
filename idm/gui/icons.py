"""Programmatically drawn app icon -- avoids shipping a binary asset file."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QPolygonF

from idm.gui import theme

_APP_ICON_CACHE: dict[int, QIcon] = {}


def make_app_icon(size: int = 64) -> QIcon:
    cached = _APP_ICON_CACHE.get(size)
    if cached is not None:
        return cached

    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(theme.PRIMARY))
    corner = size * 0.22
    painter.drawRoundedRect(0, 0, size, size, corner, corner)

    painter.setBrush(QColor("white"))
    cx = size / 2
    stem_w = size * 0.14
    stem_top = size * 0.20
    stem_bottom = size * 0.52
    painter.drawRoundedRect(
        int(cx - stem_w / 2), int(stem_top), int(stem_w), int(stem_bottom - stem_top),
        stem_w / 2, stem_w / 2,
    )
    arrow = QPolygonF([
        QPointF(cx - size * 0.20, stem_bottom),
        QPointF(cx + size * 0.20, stem_bottom),
        QPointF(cx, size * 0.72),
    ])
    painter.drawPolygon(arrow)

    bar_h = size * 0.075
    painter.drawRoundedRect(
        int(size * 0.24), int(size * 0.80), int(size * 0.52), int(bar_h),
        bar_h / 2, bar_h / 2,
    )

    painter.end()
    icon = QIcon(QPixmap.fromImage(image))
    _APP_ICON_CACHE[size] = icon
    return icon
