"""AI Business Insights launch page with an animated, honest coming-soon state.

Purpose: Provide a complete, themed destination for the future AI analysis module without fabricating insights.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/ui/pages/ai_insights_page.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate from MainWindow when the AI Insights navigation item is selected.
Changelog: v0.6.3 — Added animated AI Business Insights landing page with future capability preview.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from koshflow.ui.icons import svg_icon


class AIBusinessInsightsPage(QWidget):
    """Polished non-functional-yet page; never implies AI is already active."""

    def __init__(self, on_navigate, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("aiInsightsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(18)

        eyebrow = QLabel("BUSINESS INTELLIGENCE")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("AI Business Insights")
        title.setObjectName("pageTitle")
        title.setWordWrap(True)
        subtitle = QLabel("A future decision-support layer built on top of KoshFlow's verified accounting and operational data.")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        outer.addWidget(eyebrow)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        hero = QFrame()
        hero.setObjectName("aiInsightsHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(26, 26, 26, 26)
        hero_layout.setSpacing(22)
        emblem = QFrame()
        emblem.setObjectName("aiInsightPageEmblem")
        emblem.setFixedSize(92, 92)
        emblem_layout = QVBoxLayout(emblem)
        emblem_layout.setContentsMargins(0, 0, 0, 0)
        glyph = QLabel()
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setPixmap(svg_icon("sparkles", "#171916", 42).pixmap(42, 42))
        emblem_layout.addWidget(glyph)
        hero_layout.addWidget(emblem, 0, Qt.AlignmentFlag.AlignTop)
        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(10)
        hero_title = QLabel("Clear decisions. Grounded in your numbers.")
        hero_title.setObjectName("aiInsightsHeroTitle")
        hero_title.setWordWrap(True)
        hero_copy.addWidget(hero_title)
        hero_text = QLabel(
            "KoshFlow is preparing an insight layer that can explain changes in profitability, "
            "identify cash-flow pressure, highlight stock risks and summarize customer trends."
        )
        hero_text.setObjectName("aiInsightsHeroBody")
        hero_text.setWordWrap(True)
        hero_copy.addWidget(hero_text)
        badge = QLabel("✦  COMING SOON")
        badge.setObjectName("aiComingSoonBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(156, 32)
        effect = QGraphicsOpacityEffect(badge)
        badge.setGraphicsEffect(effect)
        effect.setOpacity(0.72)
        pulse = QPropertyAnimation(effect, b"opacity", badge)
        pulse.setDuration(1450)
        pulse.setStartValue(0.55)
        pulse.setKeyValueAt(0.5, 1.0)
        pulse.setEndValue(0.55)
        pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        pulse.setLoopCount(-1)
        pulse.start()
        badge._koshflow_pulse = pulse  # type: ignore[attr-defined]
        hero_copy.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(hero_copy, 1)
        outer.addWidget(hero)

        feature_grid = QGridLayout()
        feature_grid.setContentsMargins(0, 0, 0, 0)
        feature_grid.setSpacing(14)
        cards = [
            ("chart-no-axes-combined", "Performance explanations", "Explain revenue, cost, margin and profit movements from posted records."),
            ("wallet", "Cash-flow outlook", "Highlight upcoming receipts, payables and periods that need attention."),
            ("package-search", "Inventory opportunities", "Identify slow-moving stock, reorder risks and margin outliers."),
            ("users", "Customer patterns", "Summarize repeat sales, outstanding balances and purchasing trends."),
        ]
        for index, (icon_name, card_title, body) in enumerate(cards):
            card = QFrame()
            card.setObjectName("aiInsightsFeatureCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 18, 18, 18)
            card_layout.setSpacing(9)
            icon_label = QLabel()
            icon_label.setPixmap(svg_icon(icon_name, "#819B3D", 21).pixmap(21, 21))
            card_layout.addWidget(icon_label)
            heading = QLabel(card_title)
            heading.setObjectName("aiInsightsFeatureTitle")
            heading.setWordWrap(True)
            card_layout.addWidget(heading)
            description = QLabel(body)
            description.setObjectName("muted")
            description.setWordWrap(True)
            card_layout.addWidget(description)
            card_layout.addStretch(1)
            feature_grid.addWidget(card, index // 2, index % 2)
        outer.addLayout(feature_grid)

        note = QLabel(
            "AI analysis is not enabled in this release. No generated recommendations are presented as real, "
            "and accounting calculations will remain deterministic and auditable."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        outer.addWidget(note)
        actions = QHBoxLayout()
        reports = QPushButton("Open Reports")
        reports.setIcon(svg_icon("chart", "#171916", 16))
        reports.setObjectName("primaryButton")
        reports.clicked.connect(lambda: on_navigate("reports"))
        settings = QPushButton("Notification settings")
        settings.setIcon(svg_icon("bell-ring", "#819B3D", 16))
        settings.clicked.connect(lambda: on_navigate("settings", 5))
        actions.addWidget(reports)
        actions.addWidget(settings)
        actions.addStretch(1)
        outer.addLayout(actions)
        outer.addStretch(1)
