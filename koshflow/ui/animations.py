"""Reusable, restrained motion utilities for the PySide6 interface.

Purpose: Add smooth fade transitions and animated card hover elevation.
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Changelog: v0.1.0 — Added 180–220 ms transitions and reduced-motion override.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


def fade_in(widget: QWidget, duration: int = 200) -> None:
    """Fade a page in without retaining a stale animation object."""
    if getattr(widget, "_koshflow_reduce_motion", False):
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    widget._koshflow_fade_animation = animation
    animation.start()

