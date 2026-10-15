"""Reusable UI controls for KoshFlow v0.5.1.

Purpose: Provide polished card surfaces, smooth hover tooltips, icon-only actions,
         and consistent form helpers for the desktop application.
Project: KoshFlow | Version: 0.5.1
Canonical path: koshflow/ui/components.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Import controls into desktop pages; keep popup and motion lifetimes owned.
Changelog: v0.5.1 — Removed geometry-based hover movement from layout-managed controls to prevent dock/card overlap.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGraphicsOpacityEffect, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)


class CardFrame(QFrame):
    """Crisp card surface. Never animates geometry managed by a Qt layout."""

    def __init__(self, object_name: str = "contentCard", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)


class TooltipIconButton(QPushButton):
    """Circular icon button with a fade tooltip and layout-safe hover feedback."""

    def __init__(self, tooltip_text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.tooltip_text = tooltip_text
        self.setObjectName("circleIconButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 42)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("")
        self._tooltip: QLabel | None = None
        self._tooltip_effect: QGraphicsOpacityEffect | None = None
        self._tooltip_animation: QPropertyAnimation | None = None
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(250)
        self._show_timer.timeout.connect(self._show_tooltip)

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self._show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._show_timer.stop()
        self._hide_tooltip()
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)

    def _show_tooltip(self) -> None:
        if not self.tooltip_text or not self.isVisible():
            return
        if self._tooltip is None:
            self._tooltip = QLabel(self.tooltip_text, self.window(), Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self._tooltip.setObjectName("customTooltip")
            self._tooltip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._tooltip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tooltip.setMargin(0)
            self._tooltip.adjustSize()
            self._tooltip_effect = QGraphicsOpacityEffect(self._tooltip)
            self._tooltip_effect.setOpacity(0.0)
            self._tooltip.setGraphicsEffect(self._tooltip_effect)
        self._tooltip.setText(self.tooltip_text)
        self._tooltip.adjustSize()
        anchor = self.mapToGlobal(QPoint(self.width() // 2, 0))
        position = QPoint(anchor.x() - self._tooltip.width() // 2, anchor.y() - self._tooltip.height() - 9)
        screen = self.screen().availableGeometry() if self.screen() else None
        if screen:
            if position.x() < screen.left() + 6:
                position.setX(screen.left() + 6)
            if position.x() + self._tooltip.width() > screen.right() - 6:
                position.setX(screen.right() - self._tooltip.width() - 6)
            if position.y() < screen.top() + 6:
                position.setY(anchor.y() + self.height() + 7)
        self._tooltip.move(position)
        self._tooltip.show()
        if self._tooltip_animation:
            self._tooltip_animation.stop()
        self._tooltip_animation = QPropertyAnimation(self._tooltip_effect, b"opacity", self._tooltip)
        self._tooltip_animation.setDuration(135)
        self._tooltip_animation.setStartValue(self._tooltip_effect.opacity())
        self._tooltip_animation.setEndValue(1.0)
        self._tooltip_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tooltip_animation.start()

    def _hide_tooltip(self) -> None:
        if not self._tooltip or not self._tooltip.isVisible() or not self._tooltip_effect:
            return
        if self._tooltip_animation:
            self._tooltip_animation.stop()
        self._tooltip_animation = QPropertyAnimation(self._tooltip_effect, b"opacity", self._tooltip)
        self._tooltip_animation.setDuration(90)
        self._tooltip_animation.setStartValue(self._tooltip_effect.opacity())
        self._tooltip_animation.setEndValue(0.0)
        self._tooltip_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tooltip_animation.finished.connect(self._tooltip.hide)
        self._tooltip_animation.start()


class HoverButton(QPushButton):
    """Action button with crisp style-based hover feedback; geometry stays layout-owned."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)


def section_label(text: str, object_name: str = "sectionTitle") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    return label


def muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def make_line_edit(placeholder: str = "", password: bool = False) -> QLineEdit:
    field = QLineEdit()
    field.setPlaceholderText(placeholder)
    if password:
        field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setClearButtonEnabled(not password)
    return field


def make_combo(items: list[str], placeholder: str = "Select an option") -> QComboBox:
    combo = QComboBox()
    combo.addItems(items)
    # Height is governed by the app-wide density setting so Compact / Roomy
    # preferences work consistently on every page.
    combo.setToolTip(placeholder)
    return combo


def labeled_field(label_text: str, widget: QWidget, hint: str | None = None) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel(label_text)
    label.setStyleSheet("font-weight: 650; font-size: 11px;")
    layout.addWidget(label)
    layout.addWidget(widget)
    if hint:
        help_label = QLabel(hint)
        help_label.setObjectName("muted")
        help_label.setStyleSheet("font-size: 10px;")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
    return wrapper


class CommandSearch(QLineEdit):
    """Read-only search-shaped control that opens the command palette."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)
