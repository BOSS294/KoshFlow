"""Source-contract regressions for KoshFlow v0.6.3 UI refinements.

Purpose: Protect dashboard cleanup, AI Coming Soon, notification settings, profile state and light theme styling.
Project: KoshFlow | Version: 0.6.3
Developer: Mayank Chawdhari AKA BOSS294
Changelog: Added source contracts for the v0.6.3 user-reported fixes.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_dashboard_has_business_profile_and_animated_ai_but_no_health_or_priority_card():
    dashboard = read("koshflow/ui/pages/dashboard_page.py")
    assert '"business_profile": {"title": "Business profile"' in dashboard
    assert '"insights": {"title": "AI Business Insights"' in dashboard
    assert '"priorities": {"title": "Priority radar"' not in dashboard
    assert '"workspace_health": {"title": "Workspace health"' not in dashboard
    assert 'def _build_business_profile' in dashboard
    assert 'def _build_insights' in dashboard
    assert 'COMING SOON' in dashboard
    assert 'load_invoice_profile' in dashboard


def test_saved_dashboard_layout_migrates_old_profiles_and_insights():
    dashboard = read("koshflow/ui/pages/dashboard_page.py")
    assert 'legacy_keys = {"priorities", "priority_radar", "priority-radar", "workspace_health", "workspace_health_card", "workspace-health", "workspace"}' in dashboard
    assert 'for new_section in ("business_profile", "insights")' in dashboard


def test_settings_has_notification_rules_test_and_explicit_tab_surfaces():
    settings = read("koshflow/ui/pages/settings_page.py")
    styles = read("koshflow/ui/styles.py")
    assert '"Notifications"' in settings
    assert 'def _build_notifications_tab' in settings
    assert 'def _test_notification' in settings
    assert 'Send test notification' in settings
    assert 'self.tabs.setObjectName("settingsTabs")' in settings
    assert 'if not content.objectName()' in settings
    assert 'QTabWidget#settingsTabs QStackedWidget' in styles
    assert 'QWidget#settingsPage QWidget#businessProfileScrollViewport' in styles
    assert 'QWidget#settingsPage QWidget#businessProfileScrollContent' in styles
    assert 'QWidget#settingsPage QTabWidget#settingsTabs QStackedWidget > QWidget' in styles


def test_profile_popover_state_and_lime_dock_feedback_are_explicit():
    main_window = read("koshflow/ui/main_window.py")
    styles = read("koshflow/ui/styles.py")
    assert 'def eventFilter(self, watched, event)' in main_window
    assert 'QEvent.Type.Hide' in main_window
    assert 'popupOpen' in main_window
    assert 'QPushButton#circleIconButton[active="true"] {{ background: #C9E86A' in styles
    assert 'QPushButton#circleIconButton:hover {{ background: #2C3027' in styles


def test_version_metadata_matches_release():
    config = read("koshflow/config.py")
    package = read("koshflow/__init__.py")
    project = read("pyproject.toml")
    login = read("koshflow/ui/pages/login_page.py")
    assert 'APP_VERSION = "0.6.3"' in config
    assert '__version__ = "0.6.3"' in package
    assert 'version = "0.6.3"' in project
    assert 'BUSINESS DESKTOP 0.6.3' in login
