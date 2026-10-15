"""Customizable KoshFlow overview dashboard.

Purpose: Show an operational, local-first business overview with actionable empty states,
         configurable analytics sections, and clean export options.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/ui/pages/dashboard_page.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Construct with Session, business profile, Database, and backup manager.
Changelog: v0.6.3 — Removed obsolete status/priority panels, added business identity and animated AI Business Insights, and strengthened live dashboard data diagnostics.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, Property, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
    QGraphicsOpacityEffect, QLayout,
)

from koshflow.config import DEFAULT_TIMEZONE
from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.services.dashboard_service import DashboardService, money_text
from koshflow.services.invoice_profile_service import load_invoice_profile
from koshflow.ui.components import CardFrame, HoverButton, muted_label
from koshflow.ui.icons import svg_icon

ACCENT = "#C9E86A"
PERIODS = ["Today", "Last 7 days", "This month", "This quarter", "Financial year"]
SCOPE_OPTIONS = ["Everything", "Finance", "Sales", "Inventory", "Operations", "Compliance", "Workspace"]

SECTION_META: dict[str, dict[str, str]] = {
    "metrics": {"title": "Business pulse", "category": "Finance", "icon": "chart"},
    "revenue": {"title": "Revenue trend", "category": "Finance", "icon": "trending-up"},
    "cashflow": {"title": "Cash movement", "category": "Finance", "icon": "wallet"},
    "receivables": {"title": "Collections & receivables", "category": "Finance", "icon": "hand-coins"},
    "payables": {"title": "Supplier payables", "category": "Finance", "icon": "landmark"},
    "expenses": {"title": "Expense mix", "category": "Finance", "icon": "chart-pie"},
    "inventory": {"title": "Stock signals", "category": "Inventory", "icon": "package-search"},
    "products": {"title": "Product performance", "category": "Sales", "icon": "trophy"},
    "invoices": {"title": "Recent invoices", "category": "Sales", "icon": "receipt"},
    "purchases": {"title": "Purchase activity", "category": "Operations", "icon": "truck"},
    "deadlines": {"title": "Upcoming dates", "category": "Compliance", "icon": "calendar-clock"},
    "quick_actions": {"title": "Quick actions", "category": "Operations", "icon": "plus"},
    "customers": {"title": "Customer pulse", "category": "Sales", "icon": "users"},
    "tax": {"title": "Tax readiness", "category": "Compliance", "icon": "file-check"},
    "business_profile": {"title": "Business profile", "category": "Workspace", "icon": "building"},
    "activity": {"title": "Recent activity", "category": "Workspace", "icon": "clock"},
    "insights": {"title": "AI Business Insights", "category": "Workspace", "icon": "sparkles"},
}

_DEFAULT_ORDER = list(SECTION_META.keys())
_DEFAULT_SECTIONS = {
    "metrics": {"width": "full", "height": "compact"},
    "revenue": {"width": "full", "height": "tall"},
    "cashflow": {"width": "half", "height": "regular"},
    "receivables": {"width": "half", "height": "regular"},
    "payables": {"width": "half", "height": "regular"},
    "expenses": {"width": "half", "height": "regular"},
    "inventory": {"width": "half", "height": "regular"},
    "products": {"width": "half", "height": "regular"},
    "invoices": {"width": "full", "height": "regular"},
    "purchases": {"width": "half", "height": "regular"},
    "deadlines": {"width": "half", "height": "regular"},
    "quick_actions": {"width": "half", "height": "regular"},
    "customers": {"width": "half", "height": "regular"},
    "tax": {"width": "half", "height": "regular"},
    "business_profile": {"width": "half", "height": "regular"},
    "activity": {"width": "full", "height": "regular"},
    "insights": {"width": "full", "height": "regular"},
}
DEFAULT_LAYOUT = {
    "order": _DEFAULT_ORDER,
    "sections": _DEFAULT_SECTIONS,
    "display": "Grid",
    "period": "Last 7 days",
    "scope": "Everything",
    "sample_mode": False,  # Kept only so older saved preferences migrate cleanly.
    "visible": _DEFAULT_ORDER,
}


class TrendChart(QWidget):
    """Custom anti-aliased curve chart with a small reveal animation."""

    def __init__(self, values: list[float] | None = None, labels: list[str] | None = None,
                 caption: str = "Illustrative values", parent: QWidget | None = None):
        super().__init__(parent)
        self.values = values or []
        self.labels = labels or ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Today"]
        self.caption = caption
        self._progress = 0.0
        self.setMinimumHeight(174)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(560)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_series(self.values, self.labels, self.caption, animate=False)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = min(1.0, max(0.0, value))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def set_series(self, values: list[float], labels: list[str] | None = None,
                   caption: str | None = None, animate: bool = True) -> None:
        self.values = list(values)
        if labels:
            self.labels = list(labels)
        if caption is not None:
            self.caption = caption
        self._animation.stop()
        self._progress = 0.0 if self.values and animate else 1.0
        self.update()
        if self.values and animate:
            self._animation.setStartValue(0.0)
            self._animation.setEndValue(1.0)
            self._animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        palette = self.palette()
        text_color = palette.color(palette.ColorRole.Text)
        muted = palette.color(palette.ColorRole.PlaceholderText)
        border = palette.color(palette.ColorRole.Mid)
        left, right, top, bottom = 11.0, 12.0, 16.0, 29.0
        chart = QRectF(left, top, max(20.0, self.width() - left - right), max(30.0, self.height() - top - bottom))

        painter.setPen(QPen(QColor(border.red(), border.green(), border.blue(), 80), 1, Qt.PenStyle.DashLine))
        for row in range(4):
            y = chart.top() + chart.height() * row / 3
            painter.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))

        if not self.values:
            painter.setPen(muted)
            font = QFont(painter.font())
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(chart.toRect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             "No transactions recorded for this period.\nThe chart will populate from posted records.")
            painter.end()
            return

        maximum = max(self.values) or 1
        points: list[QPoint] = []
        for index, value in enumerate(self.values):
            x = chart.left() + chart.width() * index / max(1, len(self.values) - 1)
            y = chart.bottom() - (value / maximum) * chart.height() * 0.83 - chart.height() * 0.08
            points.append(QPoint(int(x), int(y)))

        reveal_count = max(2, int(len(points) * self._progress))
        revealed = points[:reveal_count]
        if len(revealed) >= 2:
            line_path = QPainterPath()
            line_path.moveTo(revealed[0])
            for index in range(1, len(revealed)):
                previous = revealed[index - 1]
                current = revealed[index]
                mid_x = (previous.x() + current.x()) / 2
                line_path.cubicTo(mid_x, previous.y(), mid_x, current.y(), current.x(), current.y())
            area_path = QPainterPath(line_path)
            area_path.lineTo(revealed[-1].x(), chart.bottom())
            area_path.lineTo(revealed[0].x(), chart.bottom())
            area_path.closeSubpath()
            painter.fillPath(area_path, QColor(201, 232, 106, 34))
            painter.setPen(QPen(QColor(137, 171, 52), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(line_path)
            for point in (revealed[0], revealed[-1]):
                painter.setPen(QPen(QColor(137, 171, 52), 2))
                painter.setBrush(QColor(201, 232, 106))
                painter.drawEllipse(point, 4, 4)

        painter.setPen(muted)
        font = QFont(painter.font())
        font.setPointSize(8)
        painter.setFont(font)
        shown_labels = self.labels if self.labels else [""] * len(points)
        for index in range(min(5, len(shown_labels))):
            sample_index = round(index * (len(shown_labels) - 1) / max(1, min(5, len(shown_labels)) - 1))
            x = chart.left() + chart.width() * sample_index / max(1, len(shown_labels) - 1)
            painter.drawText(int(x - 24), int(chart.bottom() + 17), 48, 12,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                             shown_labels[sample_index])
        painter.end()


class DashboardPage(QWidget):
    """A user-configurable dashboard whose preferences are saved locally."""

    def __init__(self, session: Session, profile: dict[str, str], data_dir: Path,
                 backup_manager, on_navigate, on_create_backup=None,
                 database: Database | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.profile = profile
        self.data_dir = data_dir
        self.backup_manager = backup_manager
        self.on_navigate = on_navigate
        self.on_create_backup = on_create_backup
        self.database = database
        self.dashboard_service = DashboardService(database) if database else None
        self.snapshot_error: str | None = None
        self.layout_state = self._load_layout()
        self.snapshot = self._load_snapshot()
        self.customizing = False
        self._customize_drawer: QFrame | None = None
        self._drawer_animations: list[QPropertyAnimation] = []
        self.drawer_display_combo: QComboBox | None = None
        self.drawer_sections_layout: QVBoxLayout | None = None
        self.drawer_active_count: QLabel | None = None
        self._section_widgets: dict[str, QWidget] = {}
        self._section_bodies: dict[str, QWidget] = {}
        self._section_layout: QLayout | None = None
        self._metrics_columns_used: int | None = None
        self.setObjectName("dashboardPage")
        self._build()
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(60_000)
        self._snapshot_timer.timeout.connect(self._refresh_if_visible)
        self._snapshot_timer.start()

    def _load_layout(self) -> dict[str, Any]:
        stored = None
        if self.database:
            stored = self.database.get_setting("dashboard_layout", None, scope="business", scope_id=self.session.business_id)
        try:
            data = json.loads(stored) if stored else {}
        except (json.JSONDecodeError, TypeError):
            data = {}
        merged = json.loads(json.dumps(DEFAULT_LAYOUT))
        if isinstance(data, dict):
            order = data.get("order")
            if isinstance(order, list):
                valid = [key for key in order if key in SECTION_META]
                merged["order"] = valid + [key for key in merged["order"] if key not in valid]
            if isinstance(data.get("sections"), dict):
                for key, setting in data["sections"].items():
                    if key in merged["sections"] and isinstance(setting, dict):
                        if setting.get("width") in {"full", "half"}:
                            merged["sections"][key]["width"] = setting["width"]
                        if setting.get("height") in {"compact", "regular", "tall"}:
                            merged["sections"][key]["height"] = setting["height"]
            if data.get("display") in {"Grid", "List", "Focus", "Masonry"}:
                merged["display"] = data["display"]
            visible_sections = data.get("visible")
            if isinstance(visible_sections, list):
                merged["visible"] = [key for key in SECTION_META if key in visible_sections]
                saved_sections = data.get("sections", {}) if isinstance(data.get("sections"), dict) else {}
                saved_order = data.get("order", []) if isinstance(data.get("order"), list) else []
                legacy_keys = {"priorities", "priority_radar", "priority-radar", "workspace_health", "workspace_health_card", "workspace-health", "workspace"}
                is_legacy_layout = bool(legacy_keys.intersection(set(saved_order) | set(saved_sections) | set(visible_sections)))
                # Migrate legacy layouts forward. Add the business identity and AI launch
                # sections once, while honoring visibility preferences saved by this version.
                if is_legacy_layout or not saved_sections or any(key not in saved_sections for key in ("business_profile", "insights")):
                    for new_section in ("business_profile", "insights"):
                        if new_section not in saved_sections and new_section not in visible_sections:
                            merged["visible"].append(new_section)
                merged["visible"] = [key for key in SECTION_META if key in merged["visible"]]
            if data.get("period") in PERIODS:
                merged["period"] = data["period"]
            if data.get("scope") in set(SCOPE_OPTIONS):
                merged["scope"] = data["scope"]
            # v0.2.3 intentionally disables fabricated dashboard values from older layouts.
            merged["sample_mode"] = False
        return merged

    def _save_layout(self) -> None:
        if not self.database:
            return
        try:
            self.database.set_setting(
                "dashboard_layout", json.dumps(self.layout_state, separators=(",", ":")),
                scope="business", scope_id=self.session.business_id,
            )
        except Exception:
            # A dashboard preference failure must not block billing or access to the workspace.
            pass

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 17, 22, 17)
        outer.setSpacing(12)
        outer.addWidget(self._build_header())

        self.data_warning = QFrame()
        self.data_warning.setObjectName("dashboardDataWarning")
        warning_layout = QHBoxLayout(self.data_warning)
        warning_layout.setContentsMargins(12, 8, 12, 8)
        warning_layout.setSpacing(8)
        warning_icon = QLabel()
        warning_icon.setPixmap(svg_icon("circle-alert", "#9B6B18", 16).pixmap(16, 16))
        warning_layout.addWidget(warning_icon)
        self.data_warning_label = QLabel("Some dashboard data could not be loaded.")
        self.data_warning_label.setWordWrap(True)
        warning_layout.addWidget(self.data_warning_label, 1)
        self.data_warning.hide()
        outer.addWidget(self.data_warning)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("dashboardScrollArea")
        self.scroll_area.setMinimumHeight(360)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.canvas = QWidget()
        self.canvas.setObjectName("dashboardCanvas")
        self.canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.canvas_layout = QVBoxLayout(self.canvas)
        self.canvas_layout.setContentsMargins(0, 0, 3, 8)
        self.canvas_layout.setSpacing(13)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("dashboardSectionHost")
        self.grid_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.canvas_layout.addWidget(self.grid_host)
        self.canvas_layout.addStretch(1)
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.viewport().setObjectName("dashboardViewport")
        self.scroll_area.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.scroll_area.viewport().setAutoFillBackground(True)
        outer.addWidget(self.scroll_area, 1)
        self._render_sections()
        self._update_data_warning()

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        eyebrow = QLabel("BUSINESS OVERVIEW")
        eyebrow.setObjectName("eyebrow")
        heading = QLabel("Overview")
        heading.setObjectName("pageTitle")
        subtitle = QLabel("The pulse of your business, important work and everyday decisions.")
        subtitle.setObjectName("muted")
        subtitle.setStyleSheet("font-size:11px;")
        title_col.addWidget(eyebrow)
        title_col.addWidget(heading)
        title_col.addWidget(subtitle)
        layout.addLayout(title_col, 1)

        self.period_combo = QComboBox()
        self.period_combo.setMinimumWidth(142)
        self.period_combo.addItems(PERIODS)
        self.period_combo.setCurrentText(self.layout_state["period"])
        self.period_combo.setToolTip("Choose the reporting period")
        self.period_combo.currentTextChanged.connect(self._on_period_changed)
        layout.addWidget(self.period_combo)

        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(132)
        self.scope_combo.addItems(SCOPE_OPTIONS)
        self.scope_combo.setCurrentText(self.layout_state["scope"])
        self.scope_combo.setToolTip("Filter sections by business area")
        self.scope_combo.currentTextChanged.connect(self._on_scope_changed)
        layout.addWidget(self.scope_combo)

        self.customize_button = QPushButton()
        self.customize_button.setObjectName("quietButton")
        self.customize_button.setIcon(svg_icon("sliders", "#758D39", 15))
        self.customize_button.setText("Customize")
        self.customize_button.clicked.connect(self._toggle_customizing)
        layout.addWidget(self.customize_button)

        self.export_button = QPushButton("Export")
        self.export_button.setObjectName("primaryButton")
        self.export_button.setIcon(svg_icon("download", "#171916", 15))
        self.export_button.clicked.connect(self._show_export_menu)
        layout.addWidget(self.export_button)
        return header

    def _load_snapshot(self) -> dict[str, Any]:
        if not self.dashboard_service:
            return {}
        try:
            snapshot = self.dashboard_service.snapshot(self.session.business_id, self.layout_state.get("period", "Last 7 days"))
            self.snapshot_error = None
            return snapshot
        except Exception as exc:
            # Do not disguise schema/data failures as an ordinary empty workspace.
            self.snapshot_error = str(exc)
            return {}

    def _update_data_warning(self) -> None:
        warning = getattr(self, "data_warning", None)
        if warning is None:
            return
        if self.snapshot_error:
            self.data_warning_label.setText(
                "Dashboard data could not be loaded. Check the business database or open Reports."
            )
            self.data_warning.setToolTip(self.snapshot_error[:1200])
            warning.show()
        else:
            warning.hide()

    def refresh(self) -> None:
        """Refresh every card from the current business records, preserving scroll position."""
        self.profile = self.profile or {}
        scroll_value = self.scroll_area.verticalScrollBar().value() if hasattr(self, "scroll_area") else 0
        self.snapshot = self._load_snapshot()
        self._render_sections()
        self._update_data_warning()
        if hasattr(self, "scroll_area"):
            QTimer.singleShot(0, lambda value=scroll_value: self.scroll_area.verticalScrollBar().setValue(value))

    def _refresh_if_visible(self) -> None:
        if self.isVisible():
            self.refresh()

    def _on_period_changed(self, value: str) -> None:
        self.layout_state["period"] = value
        self._save_layout()
        self.snapshot = self._load_snapshot()
        self._render_sections()

    def _on_scope_changed(self, value: str) -> None:
        self.layout_state["scope"] = value
        self._save_layout()
        self._render_sections()

    def _on_display_changed(self, value: str) -> None:
        if value not in {"Grid", "Masonry", "List", "Focus"}:
            return
        self.layout_state["display"] = value
        self._save_layout()
        self._render_sections()
        self._populate_customize_sections()
        self.status_message(f"Dashboard layout changed to {value}.")

    def _set_section_visibility(self, section_id: str, visible: bool) -> None:
        keys = list(self.layout_state.get("visible", SECTION_META.keys()))
        if visible and section_id not in keys:
            keys.append(section_id)
        elif not visible and section_id in keys:
            keys.remove(section_id)
        self.layout_state["visible"] = [key for key in SECTION_META if key in keys]
        self._save_layout()
        self._render_sections()
        if self._customize_drawer is not None:
            self._populate_customize_sections()

    def _toggle_customizing(self) -> None:
        """Open or close the animated right-side dashboard customization drawer."""
        if self._customize_drawer is not None and self._customize_drawer.isVisible():
            self._close_customize_drawer()
            return
        self._open_customize_drawer()

    def _open_customize_drawer(self) -> None:
        self.customizing = True
        panel_width = min(410, max(350, self.width() - 48))
        drawer = QFrame(self)
        drawer.setObjectName("customizeDrawer")
        drawer.setFixedWidth(panel_width)
        drawer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(drawer)
        panel_layout.setContentsMargins(19, 18, 19, 18)
        panel_layout.setSpacing(13)

        title_row = QHBoxLayout()
        title_copy = QVBoxLayout()
        title_copy.setSpacing(3)
        title = QLabel("Customize dashboard")
        title.setStyleSheet("font-size:17px;font-weight:780;")
        subtitle = QLabel("Arrange your workspace to match your workflow.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size:10px;")
        title_copy.addWidget(title)
        title_copy.addWidget(subtitle)
        title_row.addLayout(title_copy, 1)
        close_button = QPushButton("×")
        close_button.setObjectName("drawerCloseButton")
        close_button.setFixedSize(34, 34)
        close_button.setToolTip("Close customization")
        close_button.clicked.connect(self._close_customize_drawer)
        title_row.addWidget(close_button, 0, Qt.AlignmentFlag.AlignTop)
        panel_layout.addLayout(title_row)

        layout_label = QLabel("DISPLAY LAYOUT")
        layout_label.setObjectName("eyebrow")
        panel_layout.addWidget(layout_label)
        self.drawer_display_combo = QComboBox()
        self.drawer_display_combo.addItems(["Grid", "Masonry", "List", "Focus"])
        self.drawer_display_combo.setCurrentText(self.layout_state["display"])
        self.drawer_display_combo.setMinimumHeight(38)
        self.drawer_display_combo.setToolTip("Choose how sections are arranged")
        self.drawer_display_combo.currentTextChanged.connect(self._on_display_changed)
        panel_layout.addWidget(self.drawer_display_combo)

        section_heading = QHBoxLayout()
        sections_title = QLabel("DASHBOARD SECTIONS")
        sections_title.setObjectName("eyebrow")
        section_heading.addWidget(sections_title)
        section_heading.addStretch(1)
        self.drawer_active_count = QLabel(f"{len(self.layout_state.get('visible', []))} active")
        self.drawer_active_count.setObjectName("muted")
        self.drawer_active_count.setStyleSheet("font-size:10px;")
        section_heading.addWidget(self.drawer_active_count)
        panel_layout.addLayout(section_heading)

        scroll = QScrollArea()
        scroll.setObjectName("customizeSectionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("customizeSectionsContent")
        self.drawer_sections_layout = QVBoxLayout(content)
        self.drawer_sections_layout.setContentsMargins(1, 1, 7, 1)
        self.drawer_sections_layout.setSpacing(9)
        scroll.setWidget(content)
        panel_layout.addWidget(scroll, 1)

        footer_row = QHBoxLayout()
        reset_button = QPushButton("Reset layout")
        reset_button.setObjectName("quietButton")
        reset_button.clicked.connect(self._reset_dashboard_layout)
        done_button = QPushButton("Done")
        done_button.setObjectName("primaryButton")
        done_button.clicked.connect(self._close_customize_drawer)
        footer_row.addWidget(reset_button)
        footer_row.addStretch(1)
        footer_row.addWidget(done_button)
        panel_layout.addLayout(footer_row)

        self._customize_drawer = drawer
        self._populate_customize_sections()
        drawer.adjustSize()
        drawer.setFixedHeight(max(360, self.height()))
        start_pos = QPoint(self.width(), 0)
        end_pos = QPoint(max(0, self.width() - panel_width), 0)
        drawer.move(start_pos)
        opacity = QGraphicsOpacityEffect(drawer)
        opacity.setOpacity(0.0)
        drawer.setGraphicsEffect(opacity)
        drawer.show()
        drawer.raise_()

        slide_animation = self._drawer_animation(drawer, b"pos", start_pos, end_pos, 230)
        opacity_animation = self._drawer_animation(opacity, b"opacity", 0.0, 1.0, 190)
        opacity_animation.finished.connect(lambda: self._finish_drawer_open(drawer, opacity))
        slide_animation.start()
        opacity_animation.start()

        if hasattr(self, "customize_button"):
            self.customize_button.setText("Close editor")

    def _drawer_animation(self, target, property_name: bytes, start_value, end_value, duration: int) -> QPropertyAnimation:
        animation = QPropertyAnimation(target, property_name, self)
        animation.setDuration(duration)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._drawer_animations.append(animation)
        animation.finished.connect(
            lambda current=animation: self._drawer_animations.remove(current)
            if current in self._drawer_animations else None
        )
        return animation

    def _finish_drawer_open(self, drawer: QFrame, effect: QGraphicsOpacityEffect) -> None:
        # Remove the transient opacity effect after the entrance; leaving it attached
        # forces Qt to composite every child icon into an off-screen image.
        if self._customize_drawer is drawer and drawer.graphicsEffect() is effect:
            drawer.setGraphicsEffect(None)

    def _close_customize_drawer(self) -> None:
        drawer = self._customize_drawer
        if drawer is None:
            self.customizing = False
            return
        self._customize_drawer = None
        self.customizing = False
        self.drawer_sections_layout = None
        self.drawer_active_count = None
        self.drawer_display_combo = None
        if hasattr(self, "customize_button"):
            self.customize_button.setText("Customize")

        effect = drawer.graphicsEffect()
        # Stop an in-flight entrance if the user closes the drawer immediately.
        for animation in tuple(self._drawer_animations):
            if animation.targetObject() is drawer or animation.targetObject() is effect:
                animation.stop()
                if animation in self._drawer_animations:
                    self._drawer_animations.remove(animation)
        effect = drawer.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(drawer)
            effect.setOpacity(1.0)
            drawer.setGraphicsEffect(effect)
        start_pos = drawer.pos()
        end_pos = QPoint(self.width(), 0)
        slide_animation = self._drawer_animation(drawer, b"pos", start_pos, end_pos, 190)
        fade_animation = self._drawer_animation(effect, b"opacity", effect.opacity(), 0.0, 155)
        fade_animation.finished.connect(drawer.deleteLater)
        slide_animation.start()
        fade_animation.start()

    def _populate_customize_sections(self) -> None:
        if self.drawer_sections_layout is None:
            return
        while self.drawer_sections_layout.count():
            item = self.drawer_sections_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        active = set(self.layout_state.get("visible", []))
        if self.drawer_active_count is not None:
            self.drawer_active_count.setText(f"{len(active)} active")
        for index, section_id in enumerate(self.layout_state["order"]):
            meta = SECTION_META[section_id]
            card = QFrame()
            card.setObjectName("customizeSectionRow")
            row_layout = QVBoxLayout(card)
            row_layout.setContentsMargins(11, 9, 11, 10)
            row_layout.setSpacing(8)

            heading_row = QHBoxLayout()
            visible_toggle = QCheckBox(meta["title"])
            visible_toggle.setChecked(section_id in active)
            visible_toggle.setToolTip("Show or hide this dashboard section")
            visible_toggle.toggled.connect(
                lambda checked, key=section_id: self._set_section_visibility(key, checked)
            )
            heading_row.addWidget(visible_toggle, 1)

            up_button = QPushButton()
            up_button.setObjectName("sectionToolButton")
            up_button.setIcon(svg_icon("chevron-up", "#74786E", 13))
            up_button.setFixedSize(28, 28)
            up_button.setToolTip("Move section up")
            up_button.setEnabled(index > 0)
            up_button.clicked.connect(
                lambda checked=False, key=section_id: self._move_section_from_drawer(key, -1)
            )
            down_button = QPushButton()
            down_button.setObjectName("sectionToolButton")
            down_button.setIcon(svg_icon("chevron-down", "#74786E", 13))
            down_button.setFixedSize(28, 28)
            down_button.setToolTip("Move section down")
            down_button.setEnabled(index < len(self.layout_state["order"]) - 1)
            down_button.clicked.connect(
                lambda checked=False, key=section_id: self._move_section_from_drawer(key, 1)
            )
            heading_row.addWidget(up_button)
            heading_row.addWidget(down_button)
            row_layout.addLayout(heading_row)

            options_row = QHBoxLayout()
            width_combo = QComboBox()
            width_combo.addItems(["Half", "Full"])
            width_combo.setCurrentText(self.layout_state["sections"][section_id]["width"].title())
            width_combo.setMinimumHeight(32)
            width_combo.setToolTip("Section width")
            width_combo.currentTextChanged.connect(
                lambda value, key=section_id: self._set_section_option(key, "width", value)
            )
            if self.layout_state["display"] == "List":
                width_combo.setEnabled(False)
                width_combo.setToolTip("List layout uses the full available width")
            elif self.layout_state["display"] == "Focus" and index == 0:
                width_combo.setEnabled(False)
                width_combo.setToolTip("Focus layout keeps the first section full width")

            height_combo = QComboBox()
            height_combo.addItems(["Compact", "Comfortable", "Tall"])
            height_value = self.layout_state["sections"][section_id]["height"]
            height_combo.setCurrentText({"compact": "Compact", "regular": "Comfortable", "tall": "Tall"}.get(height_value, "Comfortable"))
            height_combo.setMinimumHeight(32)
            height_combo.setToolTip("Section height")
            height_combo.currentTextChanged.connect(
                lambda value, key=section_id: self._set_section_option(key, "height", value)
            )
            options_row.addWidget(width_combo, 1)
            options_row.addWidget(height_combo, 1)
            row_layout.addLayout(options_row)
            self.drawer_sections_layout.addWidget(card)

        self.drawer_sections_layout.addStretch(1)

    def _move_section_from_drawer(self, section_id: str, offset: int) -> None:
        self._move_section(section_id, offset)
        self._populate_customize_sections()

    def _reset_dashboard_layout(self) -> None:
        self.layout_state = json.loads(json.dumps(DEFAULT_LAYOUT))
        self.period_combo.setCurrentText(self.layout_state["period"])
        self.scope_combo.setCurrentText(self.layout_state["scope"])
        if self.drawer_display_combo:
            self.drawer_display_combo.setCurrentText(self.layout_state["display"])
        self._save_layout()
        self._render_sections()
        self._populate_customize_sections()
        self.status_message("Dashboard layout restored to its defaults.")

    def status_message(self, message: str) -> None:
        window = self.window()
        if hasattr(window, "_show_toast"):
            window._show_toast(message)
        elif hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 3500)

    def _move_section(self, section_id: str, offset: int) -> None:
        order = self.layout_state["order"]
        index = order.index(section_id)
        target = index + offset
        if target < 0 or target >= len(order):
            return
        order[index], order[target] = order[target], order[index]
        self._save_layout()
        self._render_sections()

    def _set_section_option(self, section_id: str, key: str, value: str) -> None:
        if key == "width" and value not in {"Full", "Half"}:
            return
        if key == "height" and value not in {"Compact", "Comfortable", "Tall"}:
            return
        normalized = value.casefold()
        if normalized == "comfortable":
            normalized = "regular"
        self.layout_state["sections"][section_id][key] = normalized
        self._save_layout()
        self._render_sections()

    def _render_sections(self) -> None:
        """Rebuild the dashboard surface directly to avoid nested-layout blanking."""
        if not hasattr(self, "canvas_layout"):
            return

        # Replace the layout host itself on each render. Keeping one permanent
        # QVBoxLayout and nesting a fresh grid inside it caused the scroll viewport
        # to retain an empty native surface on some Windows Qt configurations.
        old_host = getattr(self, "grid_host", None)
        if old_host is not None:
            self.canvas_layout.removeWidget(old_host)
            old_host.deleteLater()

        self.grid_host = QWidget()
        self.grid_host.setObjectName("dashboardSectionHost")
        self.grid_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.canvas_layout.insertWidget(0, self.grid_host)
        self._section_layout = None
        self._section_widgets.clear()
        self._section_bodies.clear()

        enabled = set(self.layout_state.get("visible", SECTION_META.keys()))
        visible = [
            key for key in self.layout_state["order"]
            if key in enabled and (
                self.layout_state["scope"] == "Everything"
                or SECTION_META[key]["category"] == self.layout_state["scope"]
            )
        ]

        if not visible:
            empty_layout = QVBoxLayout(self.grid_host)
            empty_layout.setContentsMargins(22, 22, 22, 22)
            self._section_layout = empty_layout
            empty = QFrame()
            empty.setObjectName("softPanel")
            title = QLabel("Your dashboard is clear")
            title.setStyleSheet("font-size:15px;font-weight:730;")
            description = QLabel(
                "No sections match these filters. Open Customize or choose Everything "
                "to bring cards back."
            )
            description.setObjectName("muted")
            description.setWordWrap(True)
            empty_layout.addWidget(title)
            empty_layout.addWidget(description)
            empty_layout.addStretch(1)
            self._refresh_canvas_geometry()
            return

        cards: dict[str, QFrame] = {}
        for index, section_id in enumerate(visible):
            cards[section_id] = self._build_section(section_id, index, len(visible))
            self._section_widgets[section_id] = cards[section_id]

        display = self.layout_state["display"]
        if display == "List":
            section_layout = QVBoxLayout(self.grid_host)
            section_layout.setContentsMargins(1, 1, 7, 5)
            section_layout.setSpacing(13)
            self._section_layout = section_layout
            for section_id in visible:
                section_layout.addWidget(cards[section_id])
            section_layout.addStretch(1)

        elif display == "Masonry":
            section_layout = QVBoxLayout(self.grid_host)
            section_layout.setContentsMargins(1, 1, 7, 5)
            section_layout.setSpacing(13)
            self._section_layout = section_layout
            pending: list[str] = []

            def flush_masonry_group() -> None:
                if not pending:
                    return
                row_widget = QWidget()
                row_widget.setObjectName("dashboardMasonryRow")
                row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(13)
                column_layouts: list[QVBoxLayout] = []
                for _ in range(2):
                    column = QWidget()
                    column.setObjectName("dashboardMasonryColumn")
                    column.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                    column_layout = QVBoxLayout(column)
                    column_layout.setContentsMargins(0, 0, 0, 0)
                    column_layout.setSpacing(13)
                    column_layouts.append(column_layout)
                    row_layout.addWidget(column, 1)
                estimated_heights = [0, 0]
                for key in pending:
                    height_key = self.layout_state["sections"][key]["height"]
                    weight = {"compact": 115, "regular": 180, "tall": 280}.get(height_key, 180)
                    if key in {"revenue", "cashflow"}:
                        weight += 85
                    target = 0 if estimated_heights[0] <= estimated_heights[1] else 1
                    column_layouts[target].addWidget(cards[key])
                    estimated_heights[target] += weight
                for column_layout in column_layouts:
                    column_layout.addStretch(1)
                section_layout.addWidget(row_widget)
                pending.clear()

            for section_id in visible:
                if self.layout_state["sections"][section_id]["width"] == "full":
                    flush_masonry_group()
                    section_layout.addWidget(cards[section_id])
                else:
                    pending.append(section_id)
            flush_masonry_group()
            section_layout.addStretch(1)

        else:
            grid = QGridLayout(self.grid_host)
            grid.setContentsMargins(1, 1, 7, 5)
            grid.setHorizontalSpacing(13)
            grid.setVerticalSpacing(13)
            self._section_layout = grid
            row, column = 0, 0
            for index, section_id in enumerate(visible):
                width = self.layout_state["sections"][section_id]["width"]
                full_width = width == "full" or (display == "Focus" and index == 0)
                if full_width:
                    if column != 0:
                        row += 1
                        column = 0
                    grid.addWidget(cards[section_id], row, 0, 1, 2)
                    row += 1
                    column = 0
                else:
                    grid.addWidget(cards[section_id], row, column, 1, 1)
                    column += 1
                    if column >= 2:
                        row += 1
                        column = 0
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

        self._refresh_canvas_geometry()

    def _refresh_canvas_geometry(self) -> None:
        if self._section_layout is not None:
            self._section_layout.activate()
        self.grid_host.updateGeometry()
        self.canvas_layout.activate()
        self.canvas.adjustSize()
        self.canvas.updateGeometry()
        self.canvas.update()
        self.scroll_area.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        target_columns = 6 if self.width() >= 1400 else 3 if self.width() >= 900 else 2
        if self._metrics_columns_used is not None and target_columns != self._metrics_columns_used:
            if "metrics" in self.layout_state.get("visible", []):
                self._render_sections()
        if self._customize_drawer is not None:
            drawer = self._customize_drawer
            drawer.setFixedHeight(max(360, self.height()))
            if not any(animation.targetObject() is drawer and animation.state() == QAbstractAnimation.State.Running
                       for animation in self._drawer_animations):
                drawer.move(max(0, self.width() - drawer.width()), 0)

    def _build_section(self, section_id: str, index: int, count: int) -> QFrame:
        meta = SECTION_META[section_id]
        section = CardFrame("dashboardSection")
        section.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(16, 14, 16, 15)
        section_layout.setSpacing(11)

        header = QFrame()
        header.setObjectName("sectionHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(7)
        icon = QLabel()
        icon.setFixedSize(30, 30)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(svg_icon(meta["icon"], "#6F8737", 16).pixmap(16, 16))
        icon.setStyleSheet("background:#F0F4E3;border-radius:10px;")
        header_layout.addWidget(icon)
        title = QLabel(meta["title"])
        title.setStyleSheet("font-size:13px;font-weight:740;")
        header_layout.addWidget(title, 1)
        section_layout.addWidget(header)

        body = self._build_section_body(section_id)
        self._section_bodies[section_id] = body
        section_layout.addWidget(body, 1)
        height_name = self.layout_state["sections"][section_id]["height"]
        min_height = {"compact": 94, "regular": 154, "tall": 245}.get(height_name, 154)
        if section_id == "metrics":
            min_height = max(150, min_height)
        if section_id in {"revenue", "cashflow"}:
            min_height = {"compact": 205, "regular": 235, "tall": 285}.get(height_name, 235)
        if section_id in {"invoices", "activity"}:
            min_height = max(min_height, 185)
        if section_id == "business_profile":
            min_height = max(min_height, 170)
        section.setMinimumHeight(min_height)
        return section

    def _build_section_body(self, section_id: str) -> QWidget:
        builders = {
            "metrics": self._build_metrics,
            "revenue": self._build_revenue_chart,
            "cashflow": self._build_cashflow,
            "receivables": self._build_receivables,
            "payables": self._build_payables,
            "expenses": self._build_expenses,
            "inventory": self._build_inventory,
            "products": self._build_products,
            "invoices": self._build_invoices,
            "purchases": self._build_purchases,
            "deadlines": self._build_deadlines,
            "quick_actions": self._build_quick_actions,
            "customers": self._build_customers,
            "tax": self._build_tax,
            "business_profile": self._build_business_profile,
            "activity": self._build_activity,
            "insights": self._build_insights,
        }
        return builders.get(section_id, self._build_workspace_empty)()

    def _empty_state(self, icon_name: str, title_text: str, detail_text: str,
                     action_text: str | None = None, callback=None) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("dashboardEmptyState")
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 6, 0, 6)
        row.setSpacing(12)
        icon_shell = QFrame()
        icon_shell.setObjectName("emptyStateIcon")
        icon_shell.setFixedSize(44, 44)
        icon_layout = QVBoxLayout(icon_shell)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(svg_icon(icon_name, "#71883A", 20).pixmap(20, 20))
        icon_layout.addWidget(icon)
        row.addWidget(icon_shell, 0, Qt.AlignmentFlag.AlignVCenter)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(4)
        title = QLabel(title_text)
        title.setStyleSheet("font-size:12px;font-weight:730;")
        detail = QLabel(detail_text)
        detail.setObjectName("muted")
        detail.setWordWrap(True)
        detail.setStyleSheet("font-size:10px;line-height:1.35;")
        copy.addWidget(title)
        copy.addWidget(detail)
        row.addLayout(copy, 1)
        if action_text and callback:
            action = QPushButton(action_text)
            action.setObjectName("quietButton")
            action.setCursor(Qt.CursorShape.PointingHandCursor)
            action.setMinimumHeight(34)
            action.clicked.connect(callback)
            row.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
        return wrapper

    def _small_stat(self, title_text: str, value_text: str, note_text: str,
                    icon_name: str) -> QFrame:
        card = QFrame()
        card.setObjectName("dashboardStatTile")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 11)
        layout.setSpacing(5)
        header = QHBoxLayout()
        label = QLabel(title_text)
        label.setObjectName("muted")
        label.setStyleSheet("font-size:10px;font-weight:650;")
        header.addWidget(label, 1)
        icon = QLabel()
        icon.setPixmap(svg_icon(icon_name, "#71883A", 15).pixmap(15, 15))
        header.addWidget(icon)
        value = QLabel(value_text)
        value.setStyleSheet("font-size:20px;font-weight:780;letter-spacing:-0.45px;")
        note = QLabel(note_text)
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setStyleSheet("font-size:9px;")
        layout.addLayout(header)
        layout.addWidget(value)
        layout.addWidget(note)
        return card

    def _compact_record(self, title_text: str, detail_text: str, amount_text: str, icon_name: str) -> QWidget:
        row = QFrame()
        row.setObjectName("dashboardRecordRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(svg_icon(icon_name, "#71883A", 14).pixmap(14, 14))
        layout.addWidget(icon)
        copy = QVBoxLayout()
        copy.setContentsMargins(0, 0, 0, 0)
        copy.setSpacing(2)
        title = QLabel(title_text)
        title.setStyleSheet("font-size:10px;font-weight:700;")
        title.setWordWrap(True)
        detail = QLabel(detail_text)
        detail.setObjectName("muted")
        detail.setStyleSheet("font-size:9px;")
        detail.setWordWrap(True)
        copy.addWidget(title); copy.addWidget(detail)
        layout.addLayout(copy, 1)
        amount = QLabel(amount_text)
        amount.setStyleSheet("font-size:10px;font-weight:720;")
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount.setWordWrap(True)
        layout.addWidget(amount)
        return row

    def _build_metrics(self) -> QWidget:
        wrapper = QWidget()
        grid = QGridLayout(wrapper)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        data = self.snapshot
        sales = data.get("net_sales")
        margin = data.get("gross_margin_percent")
        ledger_note = "From posted accounting entries" if data.get("gross_profit") is not None else "Ledger margin unavailable"
        metrics = [
            ("Net sales", f"₹{sales}" if sales is not None else "—", f"{data.get('invoice_count', 0)} issued invoice(s) · {data.get('start_date','')} to {data.get('end_date','')}", "receipt"),
            ("Invoices issued", str(data.get("invoice_count", 0)) if sales is not None else "—", f"Gross billed ₹{data.get('gross_sales','—')}", "file-check"),
            ("Receivables", f"₹{data.get('receivables','—')}" if sales is not None else "—", f"Overdue ₹{data.get('overdue_receivables','—')} · {data.get('overdue_invoice_count',0)} overdue", "hand-coins"),
            ("Supplier payables", f"₹{data.get('supplier_payables','—')}" if sales is not None else "—", f"Overdue ₹{data.get('overdue_payables','—')} · {data.get('overdue_purchase_count',0)} overdue", "landmark"),
            ("Cash & bank", f"₹{data.get('cash_position')}" if data.get("cash_position") is not None else "—", f"Receipts ₹{data.get('customer_receipts','—')} in selected period", "wallet"),
            ("Gross margin", f"{margin}%" if margin is not None else "—", f"Gross profit ₹{data.get('gross_profit','—')} · {ledger_note}", "trending-up"),
        ]
        columns = 6 if self.width() >= 1400 else 3 if self.width() >= 900 else 2
        self._metrics_columns_used = columns
        for index, (label, value, hint, icon_name) in enumerate(metrics):
            grid.addWidget(self._small_stat(label, value, hint, icon_name), index // columns, index % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        return wrapper

    def _period_labels(self) -> list[str]:
        period = self.layout_state["period"]
        if period == "Today":
            return ["9a", "10a", "11a", "12p", "1p", "2p", "3p", "Now"]
        if period == "This month":
            return ["1st", "5th", "9th", "13th", "17th", "21st", "25th", "Now"]
        if period == "This quarter":
            return ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "Now"]
        if period == "Financial year":
            return ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Now"]
        return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Now"]

    def _build_revenue_chart(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        intro = QHBoxLayout()
        label = QLabel(f"Net sales · {self.layout_state['period']}")
        label.setObjectName("muted")
        intro.addWidget(label, 1)
        period = QLabel(self.layout_state["period"].upper())
        period.setObjectName("eyebrow")
        intro.addWidget(period)
        layout.addLayout(intro)
        series = self.snapshot.get("revenue_series", [])
        values = [float(r.get("value", 0)) for r in series]
        labels = [str(r.get("label", "")) for r in series]
        chart = TrendChart(values, labels or self._period_labels(), "Net sales from issued invoices")
        chart.setMinimumHeight(174)
        if not values or not any(values):
            chart.set_series([], labels or self._period_labels(), "No issued sales in this period", animate=False)
        layout.addWidget(chart, 1)
        return wrapper

    def _build_cashflow(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        row = QHBoxLayout()
        row.addWidget(self._small_stat("Customer receipts", f"₹{self.snapshot.get('customer_receipts','—')}", "Recorded bill payments in selected period", "trending-up"), 1)
        row.addWidget(self._small_stat("Supplier payments", f"₹{self.snapshot.get('supplier_payments','—')}", "Recorded supplier payments in selected period", "trending-down"), 1)
        layout.addLayout(row)
        series = self.snapshot.get("receipt_series", [])
        chart = TrendChart([float(r.get("value", 0)) for r in series], [str(r.get("label", "")) for r in series], "Recorded customer receipts")
        chart.setMinimumHeight(110)
        layout.addWidget(chart, 1)
        return wrapper

    def _build_receivables(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        overdue = [r for r in self.snapshot.get("overdue_receivable_rows", [])[:4]]
        if not overdue:
            layout.addWidget(self._empty_state("hand-coins", "No overdue customer invoices", f"Open receivables total ₹{self.snapshot.get('receivables','0.00')}. Due dates are sourced from issued bills.", "Open billing", lambda: self.on_navigate("billing_manage")))
        else:
            heading = QLabel(f"Overdue balance · ₹{self.snapshot.get('overdue_receivables','0.00')}")
            heading.setStyleSheet("font-size:12px;font-weight:740;")
            layout.addWidget(heading)
            for item in overdue:
                layout.addWidget(self._compact_record(item["customer"], f"{item['number']} · Due {item['due_date']}", f"₹{item['amount']}", "alert-circle"))
            action = QPushButton("Review invoices")
            action.setObjectName("smallAction")
            action.clicked.connect(lambda: self.on_navigate("billing_manage"))
            layout.addWidget(action)
        return wrapper

    def _build_payables(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        overdue = self.snapshot.get("overdue_payable_rows", [])[:4]
        if not overdue:
            layout.addWidget(self._empty_state("landmark", "No overdue supplier bills", f"Open supplier payables total ₹{self.snapshot.get('supplier_payables','0.00')}.", "Open purchasing", lambda: self.on_navigate("purchase_bills")))
        else:
            heading = QLabel(f"Overdue payable · ₹{self.snapshot.get('overdue_payables','0.00')}")
            heading.setStyleSheet("font-size:12px;font-weight:740;")
            layout.addWidget(heading)
            for item in overdue:
                layout.addWidget(self._compact_record(item["supplier"], f"{item['number']} · Due {item['due_date']}", f"₹{item['amount']}", "calendar-clock"))
            action = QPushButton("Review supplier bills")
            action.setObjectName("smallAction")
            action.clicked.connect(lambda: self.on_navigate("purchase_bills"))
            layout.addWidget(action)
        return wrapper

    def _build_expenses(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        rows = sorted(self.snapshot.get("expense_rows", []), key=lambda r: float(r.get("amount", 0)), reverse=True)[:5]
        if not rows:
            layout.addWidget(self._empty_state("chart-pie", "No posted expenses for this period", "Expense figures come from posted journals. Use Accounts to record eligible expense entries.", "Open accounts", lambda: self.on_navigate("accounts")))
        else:
            for item in rows:
                layout.addWidget(self._compact_record(item["name"], f"Ledger account {item['code']}", f"₹{item['amount']}", "chart-pie"))
            action = QPushButton("Open Profit & Loss")
            action.setObjectName("smallAction")
            action.clicked.connect(lambda: self.on_navigate("reports"))
            layout.addWidget(action)
        return wrapper

    def _build_inventory(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(9)
        values = [
            ("Low stock", str(self.snapshot.get("low_stock_count", 0)), "At or below reorder level"),
            ("Out of stock", str(self.snapshot.get("out_of_stock_count", 0)), "Zero or negative recorded quantity"),
            ("Stock value", f"₹{self.snapshot.get('inventory_value','0.00')}", "On-hand quantity × average cost"),
        ]
        for index, (label, value, hint) in enumerate(values):
            grid.addWidget(self._small_stat(label, value, hint, "package-search"), 0, index)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        low = self.snapshot.get("low_stock_products", [])[:4]
        if low:
            for item in low:
                layout.addWidget(self._compact_record(item["name"], f"{item['sku']} · On hand {item['quantity_on_hand']} {item['unit']}", f"Reorder {item['reorder_level']}", "package"))
        else:
            layout.addWidget(self._empty_state("package", "No low-stock items", "Active products are currently above their configured reorder levels.", "Open inventory", lambda: self.on_navigate("inventory")))
        button = QPushButton("View inventory reports")
        button.setObjectName("smallAction")
        button.clicked.connect(lambda: self.on_navigate("inventory_reports"))
        layout.addWidget(button)
        return wrapper

    def _build_products(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        products = self.snapshot.get("top_products", [])
        if not products:
            layout.addWidget(self._empty_state("trophy", "No product rankings yet", "Top products are ranked from actual issued invoice lines for the selected period.", "Open inventory", lambda: self.on_navigate("inventory")))
        else:
            for index, item in enumerate(products, 1):
                layout.addWidget(self._compact_record(f"{index}. {item['name']}", f"{item.get('sku') or 'Non-catalog line'} · Qty {item['quantity']}", f"₹{item['sales']}", "trophy"))
            button = QPushButton("Open sales reports")
            button.setObjectName("smallAction")
            button.clicked.connect(lambda: self.on_navigate("reports"))
            layout.addWidget(button)
        return wrapper

    def _build_invoices(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        note = QLabel(f"Issued documents · {self.layout_state['period']}")
        note.setObjectName("muted")
        toolbar.addWidget(note, 1)
        add = QPushButton("Create bill")
        add.setObjectName("smallAction")
        add.setIcon(svg_icon("plus", "#71883A", 14))
        add.clicked.connect(lambda: self.on_navigate("billing_create"))
        toolbar.addWidget(add)
        layout.addLayout(toolbar)
        invoices = self.snapshot.get("recent_invoices", [])
        if not invoices:
            layout.addWidget(self._empty_state("receipt", "No issued invoices in this period", "Drafts and cancelled documents are excluded from the sales totals.", "Open billing", lambda: self.on_navigate("billing")))
        else:
            for row in invoices[:5]:
                layout.addWidget(self._compact_record(row["number"], f"{row['customer']} · {row['date']} · {row['status'].replace('_',' ').title()}", f"₹{row['amount']}", "receipt"))
        return wrapper

    def _build_purchases(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(f"Posted purchases · {self.layout_state['period']}"), 1)
        action = QPushButton("Open purchasing")
        action.setObjectName("smallAction")
        action.clicked.connect(lambda: self.on_navigate("purchasing"))
        toolbar.addWidget(action)
        layout.addLayout(toolbar)
        purchases = self.snapshot.get("recent_purchases", [])
        if not purchases:
            layout.addWidget(self._empty_state("truck", "No purchase documents in this period", "Posted purchase bills and supplier payment records will appear here.", "Open purchasing", lambda: self.on_navigate("purchasing")))
        else:
            for row in purchases[:5]:
                layout.addWidget(self._compact_record(row["number"], f"{row['supplier']} · {row['date']} · {row['status'].title()}", f"₹{row['amount']}", "truck"))
        return wrapper

    def _build_deadlines(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        rows = self.snapshot.get("due_rows", [])[:6]
        if not rows:
            layout.addWidget(self._empty_state("calendar-clock", "No upcoming payments within 14 days", "Only due dates saved on invoices, purchase bills and purchase orders are shown.", "Open reports", lambda: self.on_navigate("reports")))
        else:
            for row in rows:
                layout.addWidget(self._compact_record(f"{row['type']} · {row['document']}", f"{row['party']} · Due {row['due_date']}", f"₹{row['amount']}", "calendar-clock"))
        return wrapper

    def _build_quick_actions(self) -> QWidget:
        wrapper = QWidget()
        grid = QGridLayout(wrapper)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(9)
        actions = [
            ("Quick billing", "sparkles", lambda: self.on_navigate("quick_billing")),
            ("Create bill", "receipt", lambda: self.on_navigate("billing_create")),
            ("Add contact", "users", lambda: self.on_navigate("contacts")),
            ("Add stock item", "package", lambda: self.on_navigate("product_catalog")),
            ("Purchase orders", "truck", lambda: self.on_navigate("purchase_orders")),
            ("Open accounts", "wallet", lambda: self.on_navigate("accounts")),
            ("View reports", "chart", lambda: self.on_navigate("reports")),
            ("Business settings", "settings", lambda: self.on_navigate("settings", 0)),
        ]
        for index, (label, icon_name, callback) in enumerate(actions):
            button = QPushButton(label)
            button.setObjectName("dashboardActionButton")
            button.setIcon(svg_icon(icon_name, "#71883A", 16))
            button.setIconSize(QtCoreQSize(16, 16))
            button.setMinimumHeight(43)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(callback)
            grid.addWidget(button, index // 2, index % 2)
        return wrapper

    def _build_customers(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._small_stat("Active customers", str(self.snapshot.get("customer_count", 0)), f"{self.snapshot.get('new_customer_count',0)} added in selected period", "users"))
        customers = self.snapshot.get("top_customers", [])
        if customers:
            for row in customers[:4]:
                layout.addWidget(self._compact_record(row["name"], f"{row['invoice_count']} invoice(s) · Outstanding ₹{row['outstanding']}", f"₹{row['sales']}", "users"))
        else:
            layout.addWidget(self._empty_state("users", "No customer sales in this period", "Customer sales ranking appears after invoices are issued.", "Add a contact", lambda: self.on_navigate("contacts")))
        return wrapper

    def _build_tax(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        gstin = str(self.profile.get("gstin") or "").strip()
        state = str(self.profile.get("state") or "").strip()
        rows = [
            ("Business state / UT", state or "Not configured", "building"),
            ("GST registration", "GSTIN recorded" if gstin else "No GSTIN recorded", "file-check"),
            ("Report availability", "GST & HSN support reports available", "chart"),
        ]
        for label_text, value_text, icon_name in rows:
            line = QHBoxLayout()
            mark = QLabel(); mark.setPixmap(svg_icon(icon_name, "#71883A", 15).pixmap(15, 15))
            label = QLabel(label_text); label.setObjectName("muted")
            value = QLabel(value_text); value.setStyleSheet("font-size:10px;font-weight:650;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter); value.setWordWrap(True)
            line.addWidget(mark); line.addWidget(label, 1); line.addWidget(value); layout.addLayout(line)
        edit = QPushButton("Open GST reports")
        edit.setObjectName("smallAction")
        edit.setIcon(svg_icon("arrow-up-right", "#71883A", 13))
        edit.clicked.connect(lambda: self.on_navigate("reports"))
        layout.addWidget(edit)
        note = QLabel("These are supporting reports, not tax-return filing confirmations.")
        note.setObjectName("muted"); note.setWordWrap(True); note.setStyleSheet("font-size:9px;")
        layout.addWidget(note)
        return wrapper

    def _build_activity(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        rows: list[tuple[str, str, str]] = []
        if self.database:
            try:
                with self.database.connection() as connection:
                    records = connection.execute(
                        "SELECT action, entity_type, created_at FROM audit_logs "
                        "WHERE business_id = ? ORDER BY created_at DESC LIMIT 6",
                        (self.session.business_id,),
                    ).fetchall()
                rows = [
                    (str(record["action"]).replace("_", " ").title(),
                     str(record["entity_type"] or "Workspace").replace("_", " ").title(),
                     str(record["created_at"]))
                    for record in records
                ]
            except Exception:
                rows = []
        if not rows:
            layout.addWidget(self._empty_state(
                "clock", "No recent activity yet",
                "Security and business actions will appear here as work is recorded.",
                "Review settings", lambda: self.on_navigate("settings", 0),
            ))
        else:
            for title_text, entity_text, timestamp in rows:
                row = QHBoxLayout()
                dot = QLabel()
                dot.setFixedSize(8, 8)
                dot.setStyleSheet("background:#C9E86A;border-radius:4px;")
                copy = QVBoxLayout()
                copy.setSpacing(2)
                title = QLabel(title_text)
                title.setStyleSheet("font-size:11px;font-weight:660;")
                detail = QLabel(f"{entity_text} · {timestamp}")
                detail.setObjectName("muted")
                detail.setStyleSheet("font-size:9px;")
                copy.addWidget(title)
                copy.addWidget(detail)
                row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                row.addLayout(copy, 1)
                layout.addLayout(row)
        layout.addStretch(1)
        return wrapper

    def _build_business_profile(self) -> QWidget:
        """Show the configured business identity (including its actual uploaded logo)."""
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(14)

        logo_shell = QFrame()
        logo_shell.setObjectName("dashboardBusinessLogoShell")
        logo_shell.setFixedSize(148, 84)
        logo_layout = QVBoxLayout(logo_shell)
        logo_layout.setContentsMargins(8, 8, 8, 8)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QLabel()
        logo.setObjectName("dashboardBusinessLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setMinimumSize(0, 0)
        invoice_identity: dict[str, Any] = {}
        if self.database:
            try:
                invoice_identity = load_invoice_profile(self.database, self.session.business_id)
            except Exception:
                invoice_identity = {}
        logo_path = str(invoice_identity.get("logo_path") or "")
        pixmap = QPixmap(logo_path) if logo_path and Path(logo_path).is_file() else QPixmap()
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(132, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            logo.setToolTip("Configured business logo")
        else:
            brand = (self.profile.get("trade_name") or self.profile.get("legal_name") or "KoshFlow Business").strip()
            initials = "".join(part[0] for part in brand.split()[:2]).upper() or "B"
            logo.setText(initials[:2])
            logo.setStyleSheet("font-size:24px;font-weight:800;color:#171916;background:#C9E86A;border-radius:12px;")
            logo.setToolTip("Add a business logo in Settings → Invoice & payments")
        logo_layout.addWidget(logo)
        row.addWidget(logo_shell, 0, Qt.AlignmentFlag.AlignTop)

        details = QVBoxLayout()
        details.setContentsMargins(0, 2, 0, 0)
        details.setSpacing(5)
        display_name = str(self.profile.get("trade_name") or self.profile.get("legal_name") or "Business name not configured").strip()
        title = QLabel(display_name)
        title.setStyleSheet("font-size:16px;font-weight:780;")
        title.setWordWrap(True)
        details.addWidget(title)
        legal_name = str(self.profile.get("legal_name") or "").strip()
        if legal_name and legal_name.casefold() != display_name.casefold():
            legal = QLabel(legal_name)
            legal.setObjectName("muted")
            legal.setWordWrap(True)
            details.addWidget(legal)
        address_parts = [self.profile.get(key, "") for key in ("address", "city", "state", "pincode")]
        address = ", ".join(str(value).strip() for value in address_parts if str(value or "").strip())
        if address:
            address_label = QLabel(address)
            address_label.setObjectName("muted")
            address_label.setWordWrap(True)
            details.addWidget(address_label)
        contacts = [str(self.profile.get(key) or "").strip() for key in ("phone", "email") if str(self.profile.get(key) or "").strip()]
        website = str(invoice_identity.get("website") or "").strip()
        if website:
            contacts.append(website)
        if contacts:
            contact_label = QLabel(" · ".join(contacts))
            contact_label.setObjectName("muted")
            contact_label.setWordWrap(True)
            details.addWidget(contact_label)
        details.addStretch(1)
        edit = QPushButton("Edit business identity")
        edit.setObjectName("smallAction")
        edit.setIcon(svg_icon("arrow-up-right", "#71883A", 13))
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.clicked.connect(lambda: self.on_navigate("settings", 0))
        details.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        row.addLayout(details, 1)
        return wrapper

    def _build_insights(self) -> QWidget:
        """A clearly labelled, restrained animated launch panel; never fabricated AI output."""
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        hero = QFrame()
        hero.setObjectName("aiComingSoonPanel")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(13)

        icon_shell = QFrame()
        icon_shell.setObjectName("aiInsightIconShell")
        icon_shell.setFixedSize(54, 54)
        icon_layout = QVBoxLayout(icon_shell)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(svg_icon("sparkles", "#171916", 26).pixmap(26, 26))
        icon_layout.addWidget(icon)
        hero_layout.addWidget(icon_shell, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(5)
        title = QLabel("AI Business Insights")
        title.setStyleSheet("font-size:16px;font-weight:790;")
        copy.addWidget(title)
        description = QLabel(
            "Understand margins, spot cash-flow risks and find stock opportunities from your verified business records."
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        copy.addWidget(description)
        badge = QLabel("✦  COMING SOON")
        badge.setObjectName("aiComingSoonBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(28)
        badge.setMaximumWidth(150)
        effect = QGraphicsOpacityEffect(badge)
        effect.setOpacity(0.92)
        badge.setGraphicsEffect(effect)
        pulse = QPropertyAnimation(effect, b"opacity", badge)
        pulse.setDuration(1450)
        pulse.setStartValue(0.56)
        pulse.setKeyValueAt(0.5, 1.0)
        pulse.setEndValue(0.56)
        pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        pulse.setLoopCount(-1)
        pulse.start()
        # Keep an explicit reference as the Qt wrapper may otherwise collect it.
        badge._koshflow_pulse = pulse  # type: ignore[attr-defined]
        copy.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(copy, 1)
        layout.addWidget(hero)

        feature_row = QHBoxLayout()
        feature_row.setSpacing(8)
        for icon_name, text in (
            ("chart-no-axes-combined", "Performance explanations"),
            ("wallet", "Cash-flow signals"),
            ("package-search", "Stock opportunities"),
        ):
            feature = QFrame()
            feature.setObjectName("aiInsightFeature")
            feature_layout = QHBoxLayout(feature)
            feature_layout.setContentsMargins(9, 8, 9, 8)
            feature_layout.setSpacing(6)
            feature_icon = QLabel()
            feature_icon.setPixmap(svg_icon(icon_name, "#819B3D", 14).pixmap(14, 14))
            feature_layout.addWidget(feature_icon)
            feature_label = QLabel(text)
            feature_label.setWordWrap(True)
            feature_label.setObjectName("muted")
            feature_label.setStyleSheet("font-size:10px;")
            feature_layout.addWidget(feature_label, 1)
            feature_row.addWidget(feature, 1)
        layout.addLayout(feature_row)
        footer = QLabel("Not active yet. No AI recommendations or financial values are generated in this version.")
        footer.setObjectName("muted")
        footer.setWordWrap(True)
        footer.setStyleSheet("font-size:10px;")
        layout.addWidget(footer)
        open_ai = QPushButton("Open AI Insights")
        open_ai.setObjectName("smallAction")
        open_ai.setIcon(svg_icon("arrow-up-right", "#819B3D", 13))
        open_ai.clicked.connect(lambda: self.on_navigate("ai"))
        layout.addWidget(open_ai, 0, Qt.AlignmentFlag.AlignLeft)
        return wrapper

    def _build_workspace_empty(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(self._empty_state(
            "circle-help", "No section content is available", 
            "Try another dashboard section or restore the default layout.",
            "Open settings", lambda: self.on_navigate("settings", 0),
        ))
        return wrapper

    def _profile_completion(self) -> int:
        fields = ["legal_name", "trade_name", "business_type", "address", "city", "state", "pincode", "phone", "email"]
        complete = sum(bool(str(self.profile.get(field, "") or "").strip()) for field in fields)
        return round(complete * 100 / len(fields))

    def _profile_completion_label(self) -> str:
        return f"{self._profile_completion()}% complete"

    def _create_backup(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        try:
            path = self.backup_manager.create_backup()
        except Exception as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        QMessageBox.information(self, "Backup created", f"Backup verified successfully.\n\n{path}")

    def _show_export_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(svg_icon("file-spreadsheet", "#71883A", 16), "Export dashboard summary (CSV)", self._export_csv)
        menu.addAction(svg_icon("file-down", "#71883A", 16), "Export layout and preferences (JSON)", self._export_json)
        menu.addAction(svg_icon("file-image", "#71883A", 16), "Export dashboard snapshot (PNG)", self._export_png)
        menu.addAction(svg_icon("file-check", "#71883A", 16), "Export printable report (PDF)", self._export_pdf)
        menu.exec(self.export_button.mapToGlobal(QPoint(0, self.export_button.height() + 5)))

    def _export_csv(self) -> None:
        default_path = self.data_dir / "exports" / f"koshflow-dashboard-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export dashboard summary", str(default_path), "CSV files (*.csv)")
        if not path:
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            ("Report", "KoshFlow business overview"),
            ("Exported at (IST)", datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds")),
            ("Reporting period", self.layout_state["period"]),
            ("Business", self.profile.get("trade_name") or self.profile.get("legal_name") or "Not set"),
            ("Net sales (INR)", self.snapshot.get("net_sales", "Not available")),
            ("Invoices issued", str(self.snapshot.get("invoice_count", "Not available"))),
            ("Customer receipts (INR)", self.snapshot.get("customer_receipts", "Not available")),
            ("Receivables (INR)", self.snapshot.get("receivables", "Not available")),
            ("Supplier payables (INR)", self.snapshot.get("supplier_payables", "Not available")),
            ("Inventory valuation (INR)", self.snapshot.get("inventory_value", "Not available")),
            ("Low-stock products", str(self.snapshot.get("low_stock_count", "Not available"))),
            ("Dashboard data status", "Error — see dashboard warning" if self.snapshot_error else "Loaded from local records"),
            ("Dashboard layout", self.layout_state["display"]),
            ("Visible sections", ", ".join(SECTION_META[key]["title"] for key in self.layout_state["order"] if key in self.layout_state.get("visible", []))),
        ]
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Field", "Value"])
            writer.writerows(rows)
        self.status_message(f"Dashboard CSV exported: {Path(path).name}")

    def _export_json(self) -> None:
        default_path = self.data_dir / "exports" / "koshflow-dashboard-layout.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export dashboard layout", str(default_path), "JSON files (*.json)")
        if not path:
            return
        payload = {
            "app": "KoshFlow",
            "exported_at_ist": datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds"),
            "data_source": "local_workspace",
            "layout": self.layout_state,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.status_message(f"Dashboard layout exported: {Path(path).name}")

    def _export_png(self) -> None:
        default_path = self.data_dir / "exports" / f"koshflow-dashboard-{datetime.now().strftime('%Y%m%d-%H%M')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export dashboard snapshot", str(default_path), "PNG images (*.png)")
        if not path:
            return
        pixmap = self.canvas.grab()
        if not pixmap.save(path, "PNG"):
            QMessageBox.warning(self, "Export failed", "KoshFlow could not save the dashboard snapshot.")
            return
        self.status_message(f"Dashboard PNG exported: {Path(path).name}")

    def _export_pdf(self) -> None:
        default_path = self.data_dir / "exports" / f"koshflow-dashboard-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export dashboard PDF", str(default_path), "PDF files (*.pdf)")
        if not path:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Export failed", "KoshFlow could not initialize the PDF renderer.")
            return
        page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        source_size = self.canvas.size()
        scale = min(page_rect.width() / max(1, source_size.width()), page_rect.height() / max(1, source_size.height()))
        painter.translate(page_rect.left(), page_rect.top())
        painter.scale(scale, scale)
        self.canvas.render(painter, QPoint(0, 0))
        painter.end()
        self.status_message(f"Dashboard PDF exported: {Path(path).name}")


# Keep this tiny helper separate so dashboard controls don't need a QtGui import just for QSize.
def QtCoreQSize(width: int, height: int):
    from PySide6.QtCore import QSize
    return QSize(width, height)
