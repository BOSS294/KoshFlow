"""Branded animated loading screen for bill-related transitions.

Purpose: Keep the KoshFlow identity visible while bill and PDF pages are prepared.
Canonical path: koshflow/ui/pages/branded_loading_page.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Add BrandedLoadingPage(mark_path, theme) to the main QStackedWidget.
Changelog: v0.3.1 — Added a high-DPI logo with a smoothly rotating circular progress ring.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class CircularLoader(QWidget):
    """Anti-aliased rotating ring whose animation remains light on the UI thread."""

    def __init__(self, diameter: int = 110, parent=None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._angle = (self._angle + 5) % 360
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt event override
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt event override
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt event override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = self.rect().center()
        diameter = min(self.width(), self.height())
        ring_rect = self.rect().adjusted(7, 7, -7, -7)
        track_pen = QPen(QColor("#E4E8DC"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(ring_rect, 0, 360 * 16)
        progress_pen = QPen(QColor("#91AD3D"), 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        painter.drawArc(ring_rect, -self._angle * 16, -105 * 16)
        painter.end()


class BrandedLoadingPage(QWidget):
    """Centered application mark and spinner shown during bill/PDF transitions."""

    def __init__(self, mark_path: str | Path, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("brandedLoadingPage")
        self._theme = theme
        dark = theme == "dark"
        page_bg = "#171916" if dark else "#F5F6F1"
        text = "#F1F3EB" if dark else "#20231C"
        muted = "#B8BDB0" if dark else "#6C7166"
        self.setStyleSheet(f"QWidget#brandedLoadingPage{{background:{page_bg};}}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addStretch(1)

        center = QVBoxLayout()
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center.setSpacing(14)
        self.loader = CircularLoader(112)
        self.loader.setToolTip("Preparing the selected bill")
        logo = QLabel()
        logo.setFixedSize(58, 58)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(mark_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo.setPixmap(pixmap)
        logo_row = QHBoxLayout()
        logo_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo_row.addWidget(logo)
        center.addWidget(self.loader, 0, Qt.AlignmentFlag.AlignHCenter)
        logo.setParent(self.loader)
        logo.move((self.loader.width() - logo.width()) // 2, (self.loader.height() - logo.height()) // 2)
        logo.raise_()

        brand = QLabel("KoshFlow")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet(f"color:{text};font-size:18px;font-weight:750;background:transparent;")
        message = QLabel("Preparing your bill…")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet(f"color:{muted};font-size:11px;background:transparent;")
        center.addWidget(brand)
        center.addWidget(message)
        outer.addLayout(center)
        outer.addStretch(1)
