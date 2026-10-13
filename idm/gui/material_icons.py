"""A small Material-Design-flavored icon set, drawn programmatically with
QPainter. Keeping icons as code (instead of bundled image/font files) means
the app stays a self-contained, packaging-friendly Python tree -- no asset
paths to resolve after a PyInstaller freeze, no font licensing to track.

Icons are drawn filled, flat, on a 24x24 logical grid, and recolored/cached
per (name, color, size) via get_icon().
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)

GRID = 24.0
_CACHE: dict[tuple[str, str, int], QIcon] = {}


def get_icon(name: str, color: str = "#3C4043", size: int = 20) -> QIcon:
    key = (name, color, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    drawer = _DRAWERS.get(name)
    if drawer is None:
        raise KeyError(f"unknown icon: {name}")

    # QImage with an explicit alpha-channel format guarantees the
    # CompositionMode_Clear "cutout" trick used by a few icons actually
    # punches transparent holes, regardless of platform pixmap defaults.
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = size / GRID
    painter.scale(scale, scale)
    drawer(painter, QColor(color))
    painter.end()

    icon = QIcon(QPixmap.fromImage(image))
    _CACHE[key] = icon
    return icon


def colored_dot(color: str, size: int = 10) -> QIcon:
    return get_icon("dot", color=color, size=size)


# -- drawing helpers --------------------------------------------------------

def _fill(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)


def _stroke(painter: QPainter, color: QColor, width: float = 2.0) -> QPen:
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pen


# -- icon drawers (each receives a painter already scaled to a 24x24 grid) --

def _draw_dot(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawEllipse(QRectF(4, 4, 16, 16))


def _draw_add(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(10.5, 4, 3, 16), 1.5, 1.5)
    p.drawRoundedRect(QRectF(4, 10.5, 16, 3), 1.5, 1.5)


def _draw_play(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(6, 4), QPointF(6, 20), QPointF(20, 12)]))


def _draw_pause(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(6, 4, 4.5, 16), 1.5, 1.5)
    p.drawRoundedRect(QRectF(13.5, 4, 4.5, 16), 1.5, 1.5)


def _draw_stop(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(5, 5, 14, 14), 2.5, 2.5)


def _draw_close(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def _draw_refresh(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    rect = QRectF(4.5, 4.5, 15, 15)
    p.drawArc(rect, 40 * 16, 260 * 16)
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(17.5, 3.5), QPointF(20.5, 8), QPointF(14.7, 8.4)]))


def _draw_delete(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(6.5, 8, 11, 12), 1.5, 1.5)
    p.drawRoundedRect(QRectF(4, 5.5, 16, 2.2), 1.1, 1.1)
    p.drawRoundedRect(QRectF(9.5, 3, 5, 2.2), 1.1, 1.1)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawRoundedRect(QRectF(9.3, 10, 1.6, 7), 0.8, 0.8)
    p.drawRoundedRect(QRectF(13.1, 10, 1.6, 7), 0.8, 0.8)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_settings(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    cx, cy, r = 12.0, 12.0, 7.6
    for i in range(8):
        angle = math.radians(i * 45)
        tx = cx + r * 0.82 * math.cos(angle)
        ty = cy + r * 0.82 * math.sin(angle)
        p.save()
        p.translate(tx, ty)
        p.rotate(i * 45)
        p.drawRoundedRect(QRectF(-1.3, -2.6, 2.6, 3.6), 0.8, 0.8)
        p.restore()
    p.drawEllipse(QPointF(cx, cy), 5.6, 5.6)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawEllipse(QPointF(cx, cy), 2.6, 2.6)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_folder(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    path = QPainterPath()
    path.moveTo(3.5, 6.5)
    path.lineTo(9.5, 6.5)
    path.lineTo(11, 8.5)
    path.lineTo(20.5, 8.5)
    path.lineTo(20.5, 18.5)
    path.lineTo(3.5, 18.5)
    path.closeSubpath()
    p.drawPath(path)


def _draw_description(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    path = QPainterPath()
    path.moveTo(6, 3)
    path.lineTo(14.5, 3)
    path.lineTo(18.5, 7)
    path.lineTo(18.5, 21)
    path.lineTo(6, 21)
    path.closeSubpath()
    p.drawPath(path)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    for y in (11, 14, 17):
        p.drawRoundedRect(QRectF(8.3, y, 8, 1.4), 0.6, 0.6)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_copy(p: QPainter, c: QColor) -> None:
    back = QColor(c)
    back.setAlpha(120)
    _fill(p, back)
    p.drawRoundedRect(QRectF(3.5, 3.5, 13, 13), 2, 2)
    _fill(p, c)
    p.drawRoundedRect(QRectF(7.5, 7.5, 13, 13), 2, 2)


def _draw_info(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawEllipse(QRectF(3, 3, 18, 18))
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawEllipse(QRectF(10.7, 6.5, 2.6, 2.6))
    p.drawRoundedRect(QRectF(10.7, 10.5, 2.6, 7), 1, 1)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_search(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.1)
    p.drawEllipse(QRectF(3.5, 3.5, 11, 11))
    p.drawLine(QPointF(13.2, 13.2), QPointF(20, 20))


def _draw_download(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(12, 3), QPointF(12, 14))
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(6.5, 12.5), QPointF(17.5, 12.5), QPointF(12, 18.5)]))
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(5, 21), QPointF(19, 21))


def _draw_upload(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(12, 21), QPointF(12, 10))
    _fill(p, c)
    p.drawPolygon(QPolygonF([QPointF(6.5, 11.5), QPointF(17.5, 11.5), QPointF(12, 5.5)]))
    _stroke(p, c, 2.2)
    p.drawLine(QPointF(5, 3), QPointF(19, 3))


def _draw_history(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.0)
    p.drawEllipse(QRectF(3.5, 3.5, 16, 16))
    p.drawLine(QPointF(11.5, 8), QPointF(11.5, 12))
    p.drawLine(QPointF(11.5, 12), QPointF(15, 14))


def _draw_bolt(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawPolygon(QPolygonF([
        QPointF(13, 2), QPointF(5, 14), QPointF(11, 14),
        QPointF(9.5, 22), QPointF(19, 9.5), QPointF(12.5, 9.5),
    ]))


def _draw_link(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.0)
    p.save()
    p.translate(12, 12)
    p.rotate(-45)
    p.drawRoundedRect(QRectF(-9, -3.6, 10, 7.2), 3.6, 3.6)
    p.drawRoundedRect(QRectF(-1, -3.6, 10, 7.2), 3.6, 3.6)
    p.restore()


def _draw_check(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.4)
    p.drawPolyline([QPointF(5, 12.5), QPointF(10, 17.5), QPointF(19, 7)])


def _draw_clock(p: QPainter, c: QColor) -> None:
    _stroke(p, c, 2.0)
    p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
    p.drawPolyline([QPointF(12, 7.5), QPointF(12, 12), QPointF(15.5, 14)])


def _draw_grid(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    for x in (4, 13.5):
        for y in (4, 13.5):
            p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1.5, 1.5)


def _draw_movie(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
    _fill(p, QColor(255, 255, 255, 235))
    p.drawPolygon(QPolygonF([QPointF(10, 9), QPointF(10, 15), QPointF(15.5, 12)]))


def _draw_music(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawEllipse(QRectF(4, 15, 6, 6))
    p.drawEllipse(QRectF(13, 12.5, 6, 6))
    p.drawRoundedRect(QRectF(9.5, 3, 2, 15.5), 1, 1)
    p.drawRoundedRect(QRectF(9.5, 3, 9.5, 5), 1, 1)


def _draw_archive(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    p.drawRoundedRect(QRectF(3.5, 4, 17, 5), 1.5, 1.5)
    p.drawRoundedRect(QRectF(4.5, 9.5, 15, 10.5), 1.5, 1.5)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.drawRoundedRect(QRectF(9.5, 12.5, 5, 3.5), 1, 1)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_apps(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    for x in (4.5, 10.5, 16.5):
        for y in (4.5, 10.5, 16.5):
            p.drawEllipse(QRectF(x, y, 3.6, 3.6))


def _draw_other(p: QPainter, c: QColor) -> None:
    _draw_folder(p, c)


_DRAWERS: dict[str, Callable[[QPainter, QColor], None]] = {
    "dot": _draw_dot,
    "link": _draw_link,
    "check": _draw_check,
    "clock": _draw_clock,
    "add": _draw_add,
    "play": _draw_play,
    "pause": _draw_pause,
    "stop": _draw_stop,
    "close": _draw_close,
    "refresh": _draw_refresh,
    "delete": _draw_delete,
    "settings": _draw_settings,
    "folder": _draw_folder,
    "description": _draw_description,
    "copy": _draw_copy,
    "info": _draw_info,
    "search": _draw_search,
    "download": _draw_download,
    "upload": _draw_upload,
    "history": _draw_history,
    "bolt": _draw_bolt,
    "grid": _draw_grid,
    "movie": _draw_movie,
    "music": _draw_music,
    "archive": _draw_archive,
    "apps": _draw_apps,
    "other": _draw_other,
}
