"""KoshFlow v0.6.3 visual system and 60–30–10 theme tokens.

Purpose: Maintain a premium, legible white/charcoal/citron interface in light and dark modes.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/ui/styles.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Call apply_theme(app, 'light' or 'dark') after creating QApplication.
Changelog: v0.6.3 — Completed theme-aware dashboard business identity, animated AI Insights, settings surfaces and active/hover states.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

ACCENT = "#C9E86A"

THEMES = {
    "light": {
        "window": "#F5F6F1", "surface": "#FFFFFF", "surface_alt": "#F0F2EA",
        "text": "#191B16", "muted": "#74786E", "border": "#D8DDCF",
        "panel": "#FFFFFF", "input": "#FFFFFF", "black": "#171916",
        "soft_black": "#282B24", "accent": ACCENT, "accent_text": "#171916",
        "taskbar_text": "#E2E5DC", "shadow": "#202616",
    },
    "dark": {
        "window": "#171916", "surface": "#20231D", "surface_alt": "#272A23",
        "text": "#F3F5EE", "muted": "#AEB3A5", "border": "#414638",
        "panel": "#20231D", "input": "#252820", "black": "#10110F",
        "soft_black": "#2C3027", "accent": ACCENT, "accent_text": "#171916",
        "taskbar_text": "#E2E5DC", "shadow": "#000000",
    },
}


def tokens(theme: str = "light") -> dict[str, str]:
    return THEMES.get(theme, THEMES["light"])


def stylesheet(theme: str = "light", font_family: str = "Segoe UI", ui_scale: float = 1.0, control_size: str = "comfortable", control_width: str = "fluid") -> str:
    c = tokens(theme)
    css = f"""
QWidget {{ color: {c['text']}; font-family: "Inter", "Segoe UI Variable", "Segoe UI", sans-serif; font-size: 13px; outline: none; }}
QMainWindow, QWidget#appRoot, QWidget#gatewayRoot {{ background: {c['window']}; }}
QWidget#gatewayCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 22px; }}
QFrame#setupHero {{ background: {c['black']}; border: none; border-radius: 18px; }}
QFrame#setupPanel {{ background: {c['surface']}; border: none; border-radius: 18px; }}
QFrame#headerBar {{ background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; }}
QLabel#brandSubtitle {{ color: {c['muted']}; font-size: 8px; font-weight: 680; letter-spacing: 1.15px; }}
QFrame#headerDivider {{ background: {c['border']}; border: none; }}
QFrame#bottomBar {{ background: {c['black']}; border: none; border-top: 1px solid #30342A; }}
QFrame#contentCard, QFrame#metricCard, QFrame#settingsCard, QFrame#businessSummary, QFrame#dashboardSection {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 17px; }}
QFrame#dashboardSection:hover {{ border-color: #BCCB92; }}
QFrame#contentCard:hover, QFrame#metricCard:hover, QFrame#settingsCard:hover {{ border-color: #B6C884; }}
QFrame#settingsCard:hover, QFrame#metricCard:hover {{ border-color: #B6C884; }}
QWidget#dashboardPage {{ background: {c['window']}; }}
QScrollArea#dashboardScrollArea {{ background: {c['window']}; border: none; }}
QWidget#dashboardViewport {{ background: {c['window']}; }}
QWidget#dashboardCanvas {{ background: {c['window']}; }}
QWidget#dashboardSectionHost {{ background: transparent; }}
QFrame#dashboardDataWarning {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid #C9A45A; border-radius: 11px; }}
QFrame#dashboardBusinessLogoShell {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 13px; }}
QLabel#dashboardBusinessLogo {{ color: {c['text']}; background: transparent; font-weight: 800; }}
QFrame#aiComingSoonPanel {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 15px; }}
QFrame#aiInsightIconShell {{ background: {c['accent']}; border: 1px solid {c['accent']}; border-radius: 14px; }}
QLabel#aiComingSoonBadge {{ background: {c['accent']}; color: #171916; border: 1px solid {c['accent']}; border-radius: 9px; padding: 3px 9px; font-size: 9px; font-weight: 850; letter-spacing: 0.6px; }}
QFrame#aiInsightFeature {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QWidget#aiInsightsPage {{ background: {c['window']}; color: {c['text']}; }}
QFrame#aiInsightsHero {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 20px; }}
QFrame#aiInsightPageEmblem {{ background: {c['accent']}; border: 1px solid {c['accent']}; border-radius: 20px; }}
QLabel#aiInsightsHeroTitle {{ color: {c['text']}; font-size: 23px; font-weight: 820; }}
QLabel#aiInsightsHeroBody {{ color: {c['muted']}; font-size: 13px; }}
QFrame#aiInsightsFeatureCard {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 15px; }}
QFrame#aiInsightsFeatureCard:hover {{ background: {c['surface_alt']}; border-color: #A8BE69; }}
QLabel#aiInsightsFeatureTitle {{ color: {c['text']}; font-size: 14px; font-weight: 750; }}
QFrame#dashboardStatTile {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 13px; }}
QFrame#dashboardStatTile:hover {{ border-color: #BCCB92; }}
QFrame#emptyStateIcon {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 13px; }}
QPushButton#dashboardActionButton {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; text-align: left; padding: 10px 12px; }}
QPushButton#dashboardActionButton:hover {{ background: {c['surface_alt']}; border-color: #A8BE69; }}
QFrame#customizeDrawer {{ background: {c['surface']}; border-left: 1px solid {c['border']}; }}
QFrame#customizeSectionRow {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#customizeSectionRow:hover {{ border-color: #BCCB92; }}
QScrollArea#customizeSectionsScroll, QWidget#customizeSectionsContent {{ background: transparent; border: none; }}
QFrame#darkFeaturePanel {{ background: {c['black']}; border: 1px solid {c['soft_black']}; border-radius: 20px; }}
QFrame#softPanel {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 13px; }}
QFrame#accentPanel {{ background: {c['accent']}; border: none; border-radius: 16px; }}
QFrame#popoverPanel {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#toastPopup {{ background: #171916; border: 1px solid #3C4330; border-radius: 12px; }}
QWidget#settingsPage {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsAppearancePage, QWidget#settingsAppearanceContent, QWidget#settingsNotificationsPage {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QTabWidget#settingsTabs, QWidget#settingsPage QTabWidget#settingsTabs::pane, QWidget#settingsPage QTabWidget#settingsTabs QStackedWidget {{ background: {c['window']}; color: {c['text']}; border-color: {c['border']}; }}
QWidget#settingsPage QTabWidget#settingsTabs QWidget#settingsAppearancePage, QWidget#settingsPage QTabWidget#settingsTabs QWidget#settingsNotificationsPage {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QScrollArea, QWidget#settingsPage QScrollArea::viewport {{ background: {c['window']}; border: none; }}
QWidget#settingsPage QWidget#settingsAppearanceContent {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QWidget#settingsAppearancePage {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QFrame#settingsCard {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QWidget#settingsPage QLabel#sectionTitle {{ color: {c['text']}; }}
QWidget#settingsPage QLabel#muted {{ color: {c['muted']}; }}
QWidget#settingsPage QTabBar::tab {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 9px 13px; }}
QWidget#settingsPage QTabBar::tab:selected {{ background: {c['surface']}; color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QWidget#settingsPage QTabBar::tab:hover {{ background: {c['surface']}; border-color: #A8BE69; }}
QLabel#notificationTestResult {{ color: {c['text']}; background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 9px 11px; }}
QPushButton#themeModeButton {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 10px 15px; font-weight: 700; }}
QPushButton#themeModeButton[selectedTheme="true"] {{ background: {c['accent']}; color: #171916; border-color: {c['accent']}; }}
QPushButton#themeModeButton[selectedTheme="false"]:hover {{ background: {c['surface']}; border-color: #A8BE69; }}
QLabel#toastText {{ color: #F7F8F3; font-size: 11px; font-weight: 620; }}
QFrame#sectionHeader {{ background: transparent; border: none; }}
QFrame#sectionToolbar {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QLabel#eyebrow {{ color: {c['muted']}; font-size: 10px; font-weight: 750; letter-spacing: 1.35px; }}
QLabel#headline {{ color: {c['text']}; font-size: 29px; font-weight: 730; }}
QLabel#pageTitle {{ color: {c['text']}; font-size: 25px; font-weight: 750; }}
QLabel#sectionTitle {{ color: {c['text']}; font-size: 15px; font-weight: 730; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#heroTitle {{ color: #FFFFFF; font-size: 29px; font-weight: 730; }}
QLabel#heroBody {{ color: #C9CCC2; font-size: 13px; }}
QLabel#brandName {{ color: {c['text']}; font-size: 16px; font-weight: 760; }}
QLabel#smallBrand {{ color: #FFFFFF; font-size: 13px; font-weight: 720; }}
QLabel#taskbarMuted {{ color: #AEB2A5; font-size: 9px; }}
QLabel#taskbarTime {{ color: #FFFFFF; font-size: 11px; font-weight: 680; }}
QLabel#taskbarDate {{ color: #BFC3B8; font-size: 9px; }}
QLabel#pill {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 9px; color: {c['text']}; font-size: 11px; font-weight: 650; }}
QLabel#accentPill {{ background: {c['accent']}; border: none; border-radius: 8px; padding: 5px 9px; color: #171916; font-size: 10px; font-weight: 750; }}
QLabel#customTooltip {{ background: #171916; color: #F7F8F4; border: 1px solid #393D32; border-radius: 8px; padding: 7px 10px; font-size: 11px; font-weight: 600; }}
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QAbstractSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 9px 11px; selection-background-color: {c['accent']}; selection-color: #171916; min-height: 19px; }}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{ border: 1px solid #9CB94B; }}
QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QDateTimeEdit:disabled {{ color: {c['muted']}; background: {c['surface_alt']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView, QCompleter QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; selection-background-color: {c['accent']}; selection-color: #171916; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ background: {c['surface_alt']}; border: none; width: 15px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['accent']}; }}
QPushButton {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 9px 13px; font-weight: 630; }}
QPushButton:hover {{ background: {c['surface']}; border-color: #B4C77F; }}
QPushButton:pressed {{ background: {c['accent']}; color: #171916; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface_alt']}; border-color: {c['border']}; }}
QPushButton#primaryButton {{ background: {c['accent']}; color: #171916; border: 1px solid {c['accent']}; font-weight: 760; padding: 10px 15px; }}
QPushButton#primaryButton:hover {{ background: #D4EF80; border-color: #D4EF80; }}
QPushButton#primaryButton:pressed {{ background: #B6D35B; }}
QPushButton#quietButton {{ background: transparent; border: 1px solid {c['border']}; }}
QPushButton#iconButton {{ background: transparent; border: 1px solid transparent; padding: 7px; border-radius: 12px; }}
QPushButton#iconButton:hover {{ background: {c['surface_alt']}; border-color: {c['border']}; }}
QPushButton#headerIconButton {{ background: transparent; border: 1px solid {c['border']}; border-radius: 20px; padding: 0px; min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QPushButton#headerIconButton:hover {{ background: {c['surface_alt']}; border-color: {c['accent']}; }}
QPushButton#headerIconButton:pressed {{ background: {c['accent']}; border-color: {c['accent']}; }}
QPushButton#headerIconButton[active="true"] {{ background: {c['accent']}; border-color: {c['accent']}; }}
QPushButton#headerIconButton[themeMode="light"]:hover, QPushButton#headerIconButton[themeMode="dark"]:hover {{ background: {c['surface_alt']}; border-color: {c['accent']}; }}
QPushButton#circleIconButton {{ background: transparent; color: #D8DBD2; border: 1px solid #43483A; border-radius: 21px; padding: 0px; min-width: 40px; max-width: 42px; min-height: 40px; max-height: 42px; }}
QPushButton#circleIconButton:hover {{ background: #2C3027; color: #F3F5EE; border-color: #C9E86A; }}
QPushButton#circleIconButton:pressed {{ background: #363B2D; color: #FFFFFF; border-color: #C9E86A; }}
QPushButton#circleIconButton[active="true"] {{ background: #C9E86A; color: #171916; border: 1px solid #C9E86A; }}
QPushButton#circleIconButton[active="true"]:hover {{ background: #D4EF80; border-color: #D4EF80; }}
QPushButton#circleIconButton:focus {{ border: 2px solid #C9E86A; }}
QPushButton#navProfileButton {{ background: transparent; border: 1px solid transparent; padding: 5px 8px; border-radius: 13px; text-align: left; }}
QPushButton#navProfileButton:hover {{ background: #252820; border-color: #424737; }}
QPushButton#navProfileButton[popupOpen="true"] {{ background: #252820; border-color: #C9E86A; }}
QPushButton#navProfileButton[popupOpen="true"]:hover {{ background: #303528; border-color: #D4EF80; }}
QLabel#profileDisplayName {{ color: #FFFFFF; font-size: 11px; font-weight: 700; }}
QLabel#profileRole {{ color: #AEB2A5; font-size: 10px; }}
QPushButton#drawerCloseButton {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 0; font-size: 22px; font-weight: 450; }}
QPushButton#drawerCloseButton:hover {{ border-color: {c['accent']}; background: {c['surface']}; }}
QCheckBox {{ spacing: 8px; font-size: 11px; font-weight: 640; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border']}; border-radius: 5px; background: {c['surface']}; }}
QCheckBox::indicator:hover {{ border-color: #9FB85A; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QPushButton#sectionToolButton {{ background: transparent; border: 1px solid {c['border']}; border-radius: 8px; padding: 3px; min-width: 26px; max-width: 28px; min-height: 26px; max-height: 28px; }}
QPushButton#sectionToolButton:hover {{ background: {c['accent']}; color: #171916; border-color: {c['accent']}; }}
QPushButton#smallAction {{ background: transparent; border: none; color: {c['text']}; padding: 3px 0; text-align: left; }}
QPushButton#smallAction:hover {{ color: #78952D; }}
QPushButton#workspaceActionCard {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 16px; text-align: left; padding: 0; }}
QPushButton#workspaceActionCard:hover {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid #A8C64B; }}
QPushButton#workspaceActionCard:pressed {{ background: {c['surface_alt']}; border: 1px solid #9EB84A; }}
QFrame#actionCardIcon[accent="true"] {{ background: {c['accent']}; border: 1px solid {c['accent']}; border-radius: 12px; }}
QFrame#actionCardIcon[accent="false"] {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QWidget#workspaceCanvas {{ background: {c['window']}; }}
QScrollArea#workspaceScroll {{ background: {c['window']}; border: none; }}
QTabWidget::pane {{ background: {c['window']}; border: 1px solid {c['border']}; border-radius: 11px; top: -1px; }}
QTabBar::tab {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 9px 13px; margin-right: 4px; }}
QTabBar::tab:selected {{ background: {c['surface']}; color: {c['text']}; border-color: {c['border']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover {{ background: {c['surface']}; border-color: #A8C64B; }}
QTableWidget, QTableView, QTreeWidget {{ background: {c['surface']}; alternate-background-color: {c['surface_alt']}; color: {c['text']}; gridline-color: {c['border']}; border: 1px solid {c['border']}; border-radius: 10px; selection-background-color: {c['accent']}; selection-color: #171916; }}
QHeaderView::section {{ background: {c['surface_alt']}; color: {c['text']}; border: none; border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['border']}; padding: 8px 7px; font-weight: 700; }}
QRadioButton {{ color: {c['text']}; spacing: 7px; }}
QGroupBox {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 12px; margin-top: 10px; padding: 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {c['text']}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 8px; background: transparent; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #AFBC8A; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: #171916; color: #FFFFFF; border: 1px solid #3C4035; border-radius: 7px; padding: 6px 8px; }}
QDialog {{ background: {c['surface']}; }}
QListWidget {{ border: 1px solid {c['border']}; border-radius: 12px; background: {c['surface']}; padding: 5px; }}
QListWidget::item {{ border-radius: 8px; padding: 9px; }}
QListWidget::item:selected {{ background: {c['accent']}; color: #171916; }}
QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QWidget#settingsPage QTabWidget::pane {{ background: {c['window']}; }}
QWidget#settingsPage QScrollArea#businessProfileScroll, QWidget#settingsPage QScrollArea#invoiceSettingsScroll, QWidget#settingsPage QScrollArea#dataBackupScroll, QWidget#settingsPage QScrollArea#notificationsSettingsScroll {{ background: {c['window']}; border: none; }}
QWidget#settingsPage QWidget#businessProfileScrollViewport, QWidget#settingsPage QWidget#invoiceSettingsScrollViewport, QWidget#settingsPage QWidget#dataBackupScrollViewport, QWidget#settingsPage QWidget#notificationsSettingsScrollViewport, QWidget#settingsPage QWidget#businessProfileScrollContent, QWidget#settingsPage QWidget#invoiceSettingsScrollContent, QWidget#settingsPage QWidget#dataBackupScrollContent, QWidget#settingsPage QWidget#notificationsSettingsScrollContent {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QTabWidget#settingsTabs QStackedWidget > QWidget {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QWidget#settingsScrollViewport {{ background: {c['window']}; color: {c['text']}; }}
QWidget#settingsPage QPushButton:hover {{ border-color: #A8BE69; }}
QWidget#settingsPage QLineEdit:focus, QWidget#settingsPage QComboBox:focus, QWidget#settingsPage QTextEdit:focus, QWidget#settingsPage QSpinBox:focus, QWidget#settingsPage QDoubleSpinBox:focus {{ border-color: #9CB94B; }}
"""
    allowed_fonts = {"Segoe UI", "Inter", "Noto Sans", "Arial", "System default"}
    if font_family not in allowed_fonts:
        font_family = "Segoe UI"
    if font_family == "System default":
        font_family = QFont().defaultFamily() if hasattr(QFont, "defaultFamily") else "Segoe UI"
    scale = min(1.25, max(0.80, float(ui_scale)))
    css = css.replace('font-family: "Inter", "Segoe UI Variable", "Segoe UI", sans-serif;',
                      f'font-family: "{font_family}", "Segoe UI", sans-serif;')
    css = re.sub(r"(?<![A-Za-z0-9#])([0-9]+(?:\.[0-9]+)?)px", lambda m: f"{max(1, round(float(m.group(1)) * scale))}px", css)
    density = {"compact": 34, "comfortable": 42, "roomy": 50}.get(control_size, 42)
    css += f"\nQLineEdit, QComboBox, QDateEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateTimeEdit {{ min-height: {round(density * scale)}px; }}\n"
    css += f"QPushButton {{ min-height: {round((density - 8) * scale)}px; }}\n"
    if control_width in {"compact", "balanced"}:
        max_width = {"compact": 340, "balanced": 620}[control_width]
        css += f"QLineEdit, QComboBox, QDateEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateTimeEdit {{ max-width: {round(max_width * scale)}px; }}\n"

    # Quick Billing uses wider, explicitly themed controls even when global input-width
    # preferences are compact; otherwise form fields can become clipped on laptop screens.
    css += f"""
QWidget#quickBillingPage {{ background: {c['window']}; color: {c['text']}; }}
QFrame#quickBillingCard {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#quickCustomerPanel {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#quickSearchEmptyState {{ background: {c['surface_alt']}; border: 1px dashed {c['border']}; border-radius: 12px; }}
QLabel#quickFieldLabel, QLabel#quickSearchCaption {{ color: {c['muted']}; font-size: 9px; font-weight: 760; letter-spacing: 0.8px; }}
QLabel#quickSearchEmptyTitle {{ color: {c['text']}; font-size: 15px; font-weight: 740; }}
QWidget#quickBillingPage QLineEdit, QWidget#quickBillingPage QComboBox, QWidget#quickBillingPage QDoubleSpinBox {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 7px 10px; min-width: 0px; max-width: 16777215px; min-height: 36px; selection-background-color: {c['accent']}; selection-color: #171916; }}
QWidget#quickBillingPage QLineEdit:focus, QWidget#quickBillingPage QComboBox:focus, QWidget#quickBillingPage QDoubleSpinBox:focus {{ border: 1px solid #9CB94B; }}
QWidget#quickBillingPage QComboBox::drop-down {{ border: none; width: 23px; }}
QDoubleSpinBox#quickQuantityToAdd {{ min-height: 40px; min-width: 112px; max-width: 150px; font-size: 15px; font-weight: 750; }}
QWidget#quickBillingPage QCompleter QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['accent']}; selection-color: #171916; }}
QListWidget#quickProductResults {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 6px; outline: none; }}
QListWidget#quickProductResults::item {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 7px 9px; margin: 2px; }}
QListWidget#quickProductResults::item:hover {{ background: {c['surface_alt']}; border-color: #A8BE69; }}
QListWidget#quickProductResults::item:selected {{ background: {c['accent']}; color: #171916; border-color: {c['accent']}; }}
QTableWidget#quickSaleTable {{ background: {c['surface']}; alternate-background-color: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; gridline-color: {c['border']}; selection-background-color: {c['surface_alt']}; selection-color: {c['text']}; }}
QTableWidget#quickSaleTable::item {{ padding: 5px; }}
QFrame#quickSaleSummary {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 11px; }}
QLabel#quickSaleGrandTotal {{ color: {c['text']}; font-size: 23px; font-weight: 820; }}
QSplitter#quickBillingSplitter::handle {{ background: {c['border']}; border-radius: 3px; }}
QSplitter#quickBillingSplitter::handle:hover {{ background: {c['accent']}; }}
"""

    # QFrame cards have real child layouts; unlike QPushButton-with-layout, this
    # prevents platform styles from painting over the card's labels in light mode.
    css += f"""
QFrame#workspaceActionCard {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#workspaceActionCard:hover {{ background: {c['surface_alt']}; border: 1px solid #A8C64B; }}
QFrame#workspaceActionCard:focus {{ border: 2px solid {c['accent']}; }}
QFrame#workspaceActionCard[pressed=\"true\"] {{ background: {c['surface_alt']}; border: 1px solid #9EB84A; }}
QLabel#actionCardTitle {{ color: {c['text']}; font-size: 14px; font-weight: 730; }}
QLabel#actionCardDescription {{ color: {c['muted']}; font-size: 11px; }}
QComboBox#catalogProductCombo {{ background: {c['input']}; color: {c['text']}; padding: 2px 19px 2px 6px; min-height: 22px; max-height: 26px; border-radius: 6px; }}
QComboBox#catalogProductCombo::drop-down {{ border: none; width: 18px; }}
QComboBox#catalogProductCombo QAbstractItemView {{ min-width: 240px; padding: 4px; }}
QTableWidget#billItemsTable {{ background: {c['surface']}; alternate-background-color: {c['surface_alt']}; color: {c['text']}; gridline-color: {c['border']}; selection-background-color: {c['surface_alt']}; selection-color: {c['text']}; }}
QTableWidget#billItemsTable::item:selected, QTableWidget#billItemsTable::item:selected:active {{ background: {c['surface_alt']}; color: {c['text']}; }}
QLabel#billTotalsSummary {{ background: {c['surface_alt']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 10px 12px; font-size: 13px; font-weight: 730; }}
"""
    return css


def apply_theme(app: QApplication, theme: str, font_family: str = "Segoe UI", ui_scale: float = 1.0, control_size: str = "comfortable", control_width: str = "fluid") -> None:
    allowed_fonts = {"Segoe UI", "Inter", "Noto Sans", "Arial", "System default"}
    resolved_font = font_family if font_family in allowed_fonts else "Segoe UI"
    if resolved_font == "System default":
        resolved_font = "Segoe UI"
    app.setFont(QFont(resolved_font, max(8, round(10 * min(1.25, max(0.80, float(ui_scale)))))))
    app.setStyleSheet(stylesheet(theme, font_family, ui_scale, control_size, control_width))
