"""Shared color palette and stylesheet. One place to keep the look coherent
across the header, sidebar, table, dialogs and settings."""

from __future__ import annotations

PRIMARY = "#2F5BEA"
PRIMARY_DARK = "#2347C8"
ON_PRIMARY = "#FFFFFF"

SUCCESS = "#1E8E3E"
SUCCESS_BG = "#E6F4EA"
WARNING = "#F29900"
WARNING_BG = "#FEF3E0"
ERROR = "#D93025"
ERROR_BG = "#FCE8E6"
NEUTRAL = "#5F6368"
NEUTRAL_LIGHT = "#9AA0A6"

BACKGROUND = "#FFFFFF"
APP_BG = "#F5F6F8"
SURFACE = "#F8F9FB"
BORDER = "#E3E6EC"
BORDER_STRONG = "#D2D6DE"
TEXT = "#1B1F2A"
TEXT_MUTED = "#6B7280"
SELECTED_BG = "#EEF2FF"
SELECTED_TEXT = "#2F5BEA"
HOVER_BG = "#F1F3F6"
TRACK = "#E7EAF0"

FONT_SANS = '"Inter", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", Consolas, monospace'

STATUS_COLORS = {
    "queued": NEUTRAL_LIGHT,
    "downloading": PRIMARY,
    "paused": WARNING,
    "completed": SUCCESS,
    "failed": ERROR,
    "canceled": NEUTRAL_LIGHT,
    "scheduled": "#8430CE",
}
# (text color, pill background) for the status pill under each file name
STATUS_PILLS = {
    "queued": (TEXT_MUTED, "#EEF0F4"),
    "downloading": (PRIMARY, "#E6EDFF"),
    "paused": ("#B06000", WARNING_BG),
    "completed": (SUCCESS, SUCCESS_BG),
    "failed": (ERROR, ERROR_BG),
    "canceled": (TEXT_MUTED, "#EEF0F4"),
    "scheduled": ("#7A29B8", "#F3E8FD"),
}
# the dot in front of the source name
SOURCE_COLORS = {
    "YouTube": "#E5322D",
    "Instagram": "#D6249F",
    "Facebook": "#1877F2",
    "TikTok": "#111111",
    "X": "#111111",
    "Direct link": NEUTRAL_LIGHT,
}

STYLESHEET = f"""
* {{
    font-family: {FONT_SANS};
    font-size: 13px;
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background: {APP_BG};
}}

QToolTip {{
    background: {TEXT};
    color: white;
    border: none;
    padding: 4px 8px;
}}

/* ---- header ---- */
#header {{
    background: {BACKGROUND};
    border-bottom: 1px solid {BORDER};
}}
#appTitle {{
    font-size: 15px;
    font-weight: 700;
}}
#linkBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#linkBar QLineEdit {{
    border: none;
    background: transparent;
    padding: 8px 4px;
}}

/* ---- sidebar ---- */
#sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
#sectionLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 6px 8px 2px 8px;
}}
QPushButton#navItem {{
    border: none;
    border-radius: 9px;
    text-align: left;
    padding: 9px 12px;
    background: transparent;
}}
QPushButton#navItem:hover {{
    background: {HOVER_BG};
}}
QPushButton#navItem:checked {{
    background: {SELECTED_BG};
    color: {SELECTED_TEXT};
    font-weight: 600;
}}
#navCount {{
    color: {TEXT_MUTED};
    font-family: {FONT_MONO};
    font-size: 11px;
}}
#siteBox {{
    background: {APP_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#siteBoxTitle {{
    font-weight: 600;
}}
#chip {{
    background: {BACKGROUND};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 3px 6px;
    font-size: 12px;
}}

/* ---- cards and page titles ---- */
#card {{
    background: {BACKGROUND};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
#pageTitle {{
    font-size: 21px;
    font-weight: 700;
}}
#cardTitle {{
    font-size: 15px;
    font-weight: 700;
}}
#muted {{
    color: {TEXT_MUTED};
}}
#fieldLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}
#mono {{
    font-family: {FONT_MONO};
    font-size: 12px;
}}

/* ---- table ---- */
QTableView {{
    background: transparent;
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: transparent;
}}
QTableView::item {{
    border-bottom: 1px solid {BORDER};
}}
QHeaderView {{
    background: transparent;
}}
QHeaderView::section {{
    background: transparent;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 12px 8px;
    font-size: 12px;
    font-weight: 600;
}}

/* ---- inputs and buttons ---- */
QLineEdit, QSpinBox, QComboBox, QTimeEdit, QDateTimeEdit {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 7px 10px;
    background: {BACKGROUND};
    selection-background-color: {SELECTED_BG};
    selection-color: {TEXT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border: 1px solid {PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow, QAbstractSpinBox::down-arrow {{
    image: url(__CHEVRON__);
    width: 12px;
    height: 12px;
}}
QAbstractSpinBox::up-arrow {{
    image: url(__CHEVRON_UP__);
    width: 12px;
    height: 12px;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    border: none;
    background: transparent;
    width: 22px;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QDateTimeEdit::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background: {BACKGROUND};
    border: 1px solid {BORDER};
    selection-background-color: {SELECTED_BG};
    selection-color: {SELECTED_TEXT};
    outline: none;
}}
QPushButton {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 7px 14px;
    background: {BACKGROUND};
}}
QPushButton:hover {{
    background: {HOVER_BG};
}}
QPushButton:disabled {{
    color: {NEUTRAL_LIGHT};
}}
QPushButton#primary {{
    background: {PRIMARY};
    color: {ON_PRIMARY};
    border: none;
    font-weight: 600;
    padding: 8px 16px;
}}
QPushButton#primary:hover {{
    background: {PRIMARY_DARK};
}}
QPushButton#primary:disabled {{
    background: #A9B8F0;
    color: white;
}}
QPushButton#iconButton {{
    padding: 6px;
    min-width: 18px;
}}
QPushButton#closeButton {{
    background: {APP_BG};
    border: none;
    border-radius: 10px;
    padding: 8px;
}}
QPushButton#closeButton:hover {{
    background: {BORDER};
}}

QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {BACKGROUND};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
    image: url(__CHECK__);
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {TRACK};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {PRIMARY};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: white;
    border: 2px solid {PRIMARY};
    width: 12px;
    height: 12px;
    margin: -6px 0;
    border-radius: 8px;
}}

QPushButton#pill {{
    border: 1px solid {BORDER_STRONG};
    border-radius: 14px;
    padding: 4px 12px;
}}
QPushButton#pill:checked {{
    background: {SELECTED_BG};
    border-color: {PRIMARY};
    color: {SELECTED_TEXT};
}}

QPushButton#segment {{
    border: none;
    border-radius: 8px;
    padding: 7px 18px;
    background: transparent;
    color: {TEXT_MUTED};
    font-weight: 600;
}}
QPushButton#segment:checked {{
    background: {BACKGROUND};
    color: {TEXT};
}}
#segmentTrack {{
    background: {APP_BG};
    border-radius: 11px;
}}

QPushButton#quality {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    text-align: left;
    padding: 8px 12px;
    background: {BACKGROUND};
}}
QPushButton#quality:hover {{
    border-color: {BORDER_STRONG};
}}
QPushButton#quality:checked {{
    border: 1px solid {PRIMARY};
    background: {SELECTED_BG};
}}

/* ---- settings nav ---- */
QPushButton#settingsNav {{
    border: none;
    border-radius: 8px;
    text-align: left;
    padding: 8px 12px;
    background: transparent;
    font-weight: 500;
}}
QPushButton#settingsNav:hover {{
    background: {HOVER_BG};
}}
QPushButton#settingsNav:checked {{
    background: {SELECTED_BG};
    color: {SELECTED_TEXT};
    font-weight: 600;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}

QStatusBar {{
    background: {BACKGROUND};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QStatusBar::item {{
    border: none;
}}

QMenu {{
    background: {BACKGROUND};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {SELECTED_BG};
    color: {SELECTED_TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 6px;
}}
"""


def stylesheet() -> str:
    """STYLESHEET with the checkbox tick rendered to a small PNG (Qt style sheets can't draw it)."""
    import os
    import tempfile

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    path = os.path.join(tempfile.gettempdir(), "idm-downloader-check.png")
    image = QImage(32, 32, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("white"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPolyline([QPointF(8, 17), QPointF(14, 23), QPointF(24, 10)])
    painter.end()
    image.save(path)

    chevron = os.path.join(tempfile.gettempdir(), "idm-downloader-chevron.png")
    image = QImage(32, 32, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(TEXT_MUTED), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPolyline([QPointF(8, 12), QPointF(16, 20), QPointF(24, 12)])
    painter.end()
    image.save(chevron)
    up = os.path.join(tempfile.gettempdir(), "idm-downloader-chevron-up.png")
    image.mirrored(False, True).save(up)
    return (STYLESHEET.replace("__CHECK__", path.replace("\\", "/"))
            .replace("__CHEVRON_UP__", up.replace("\\", "/"))
            .replace("__CHEVRON__", chevron.replace("\\", "/")))
