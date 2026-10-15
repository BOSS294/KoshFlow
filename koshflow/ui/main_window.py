"""KoshFlow desktop shell with icon-first navigation and animated popovers.

Purpose: Provide a clean desktop header, profile-aware bottom dock, notifications,
         theme control, command palette, shortcuts and permission-aware navigation.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/ui/main_window.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Instantiate after AuthService returns a validated Session.
Changelog: v0.6.3 — Added AI Business Insights landing page, notification preferences/testing, repaired profile popover identity, and improved theme-aware active navigation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt, QSize
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut, QPainter, QPainterPath, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget, QSystemTrayIcon, QMenu, QScrollArea,
)

from koshflow.config import DEFAULT_TIMEZONE, get_data_dir
from koshflow.core.backups import BackupError, BackupManager
from koshflow.core.database import Database
from koshflow.core.permissions import NAV_ITEMS, has_permission, visible_navigation
from koshflow.core.session import Session
from koshflow.services.business_service import BusinessService
from koshflow.services.notification_service import NotificationService
from koshflow.ui.animations import fade_in
from koshflow.ui.components import CommandSearch, TooltipIconButton
from koshflow.ui.icons import svg_icon
from koshflow.ui.pages.dashboard_page import DashboardPage
from koshflow.ui.pages.billing_hub_page import BillingHubPage, PDFStudioHubPage
from koshflow.ui.pages.bill_editor_page import BillEditorPage
from koshflow.ui.pages.branded_loading_page import BrandedLoadingPage
from koshflow.ui.pages.bill_detail_page import BillDetailPage
from koshflow.ui.pages.bill_list_page import BillListPage
from koshflow.ui.pages.pdf_studio_pages import BillingExportsPage, PDFGeneratorPage, PDFTemplatePage, SendBillPage
from koshflow.ui.pages.contact_pages import CustomerDirectoryPage, CustomerDetailPage, SupplierDetailPage, QuickBillingPage
from koshflow.ui.pages.inventory_pages import (
    InventoryHubPage, ProductCatalogPage, StockAdjustmentPage, StockMovementsPage,
    PurchasingHubPage, SupplierCatalogPage, PurchaseOrderPage, PurchaseBillPage,
    SupplierPaymentsPage, SupplierReturnsPage, InventoryReportsPage,
)
from koshflow.ui.pages.placeholder_page import PlaceholderPage
from koshflow.ui.pages.settings_page import SettingsPage
from koshflow.ui.pages.accounting_pages import AccountingWorkspacePage, AccountingReportsPage
from koshflow.ui.pages.ai_insights_page import AIBusinessInsightsPage
from koshflow.ui.styles import apply_theme, tokens


class MainWindow(QMainWindow):
    """Authenticated workspace with compact controls and a persistent dock."""

    def __init__(self, database: Database, backup_manager: BackupManager, session: Session,
                 on_logout, parent: QWidget | None = None):
        super().__init__(parent)
        self.database = database
        self.backup_manager = backup_manager
        self.session = session
        self.on_logout = on_logout
        self.business_service = BusinessService(database)
        self.profile = self.business_service.get_profile(session.business_id)
        self.notification_service = NotificationService(database)
        self._tray_icon: QSystemTrayIcon | None = None
        self.theme = database.get_setting("theme", "light") or "light"
        if self.theme not in {"light", "dark"}:
            self.theme = "light"
        self.font_family = database.get_setting("font_family", "Segoe UI", scope="user", scope_id=session.user_id) or "Segoe UI"
        try:
            self.ui_scale = int(database.get_setting("ui_scale_percent", "100", scope="user", scope_id=session.user_id) or "100") / 100
        except ValueError:
            self.ui_scale = 1.0
        self.control_size = database.get_setting("control_size", "comfortable", scope="user", scope_id=session.user_id) or "comfortable"
        self.control_width = database.get_setting("control_width", "fluid", scope="user", scope_id=session.user_id) or "fluid"

        self._nav_buttons: dict[str, TooltipIconButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._settings_page: SettingsPage | None = None
        self._loading_page: BrandedLoadingPage | None = None
        self._pending_bill_route: tuple[str, int | None] | None = None
        self._bill_loading_token = 0
        self._building_delayed_route = False
        self._command_dialog: QDialog | None = None
        self._profile_popup: QFrame | None = None
        self._notification_popup: QFrame | None = None
        self._popup_animations: list[QPropertyAnimation] = []
        self._toast_popup: QFrame | None = None
        self._toast_animation: QPropertyAnimation | None = None
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)
        self._asset_root = Path(__file__).resolve().parents[2] / "assets"
        self._mark_path = self._asset_root / "koshflow-mark-rounded.png"

        self.setWindowTitle("KoshFlow — Business workspace")
        self.setWindowIcon(QIcon(str(self._asset_root / "koshflow.ico")))
        self.setMinimumSize(1024, 640)
        self.setObjectName("mainWindow")
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            available = screen.availableGeometry() if screen else None
            width = min(1440, max(1024, available.width() - 40)) if available else 1280
            height = min(900, max(640, available.height() - 50)) if available else 800
            self.resize(width, height)
            apply_theme(app, self.theme, self.font_family, self.ui_scale, self.control_size, self.control_width)
        self._build_shell()
        self._register_shortcuts()
        self._refresh_clock()
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(30_000)
        self.clock_timer.timeout.connect(self._refresh_clock)
        self.clock_timer.start()
        self._setup_desktop_notifications()
        self._navigate("overview")

    def _build_shell(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        self.header = self._build_header()
        layout.addWidget(self.header)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        layout.addWidget(self.stack, 1)
        self.bottom_bar = self._build_bottom_bar()
        layout.addWidget(self.bottom_bar)

        # Keep the icon dock flush with the actual bottom edge of the desktop window.
        # Status messages remain available to the controller but do not create a second, clipped-looking bar.
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setVisible(False)

    def _build_header(self) -> QFrame:
        """Branding on the left; notification and appearance controls on the right."""
        header = QFrame()
        header.setObjectName("headerBar")
        header.setFixedHeight(66)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(22, 7, 22, 7)
        layout.setSpacing(10)

        mark = QLabel()
        mark.setObjectName("headerBrandMark")
        mark.setFixedSize(40, 40)
        pixmap = QPixmap(str(self._mark_path))
        if not pixmap.isNull():
            mark_pixmap = pixmap.scaled(
                120, 120, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            mark_pixmap.setDevicePixelRatio(3)
            mark.setPixmap(mark_pixmap)
        layout.addWidget(mark)

        brand_copy = QVBoxLayout()
        brand_copy.setContentsMargins(0, 0, 0, 0)
        brand_copy.setSpacing(2)
        brand = QLabel("KoshFlow")
        brand.setObjectName("brandName")
        subtitle = QLabel("BUSINESS DESKTOP")
        subtitle.setObjectName("brandSubtitle")
        brand_copy.addWidget(brand)
        brand_copy.addWidget(subtitle)
        layout.addLayout(brand_copy)

        layout.addStretch(1)

        self.notification_button = TooltipIconButton("Notifications")
        self.notification_button.setObjectName("headerIconButton")
        self.notification_button.setFixedSize(40, 40)
        self.notification_button.setIcon(svg_icon("bell", self._text_color(), 18))
        self.notification_button.clicked.connect(self._show_notifications)
        layout.addWidget(self.notification_button)

        divider = QFrame()
        divider.setObjectName("headerDivider")
        divider.setFixedSize(1, 24)
        layout.addWidget(divider)

        self.theme_button = TooltipIconButton("Switch light / dark mode")
        self.theme_button.setObjectName("headerIconButton")
        self.theme_button.setFixedSize(40, 40)
        self.theme_button.setIcon(svg_icon("moon" if self.theme == "light" else "sun", self._text_color(), 18))
        self.theme_button.clicked.connect(self._toggle_theme)
        layout.addWidget(self.theme_button)
        return header

    def _build_bottom_bar(self) -> QFrame:
        """Bottom dock: local status at left, icon-only navigation centered, user at right."""
        bar = QFrame()
        bar.setObjectName("bottomBar")
        bar.setFixedHeight(78)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 7, 22, 7)
        layout.setSpacing(12)

        status_col = QVBoxLayout()
        status_col.setSpacing(3)
        local_row = QHBoxLayout()
        local_row.setSpacing(5)
        dot = QFrame()
        dot.setFixedSize(6, 6)
        dot.setStyleSheet("background:#C9E86A;border:none;border-radius:3px;")
        local_label = QLabel("DATA ON DEVICE")
        local_label.setObjectName("taskbarMuted")
        local_label.setStyleSheet("font-size:8px;letter-spacing:0.8px;")
        local_row.addWidget(dot)
        local_row.addWidget(local_label)
        local_row.addStretch(1)
        status_col.addLayout(local_row)
        self.clock_time = QLabel("--:-- IST")
        self.clock_time.setObjectName("taskbarTime")
        self.clock_date = QLabel("Loading date…")
        self.clock_date.setObjectName("taskbarDate")
        status_col.addWidget(self.clock_time)
        status_col.addWidget(self.clock_date)
        status_wrap = QWidget()
        status_wrap.setLayout(status_col)
        status_wrap.setMinimumWidth(168)
        layout.addWidget(status_wrap, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)
        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(8)
        for item in visible_navigation(self.session.role):
            button = TooltipIconButton(self._nav_tooltip(item["key"], item["label"]))
            button.setObjectName("circleIconButton")
            button.setProperty("navKey", item["key"])
            button.setProperty("active", False)
            button.setIcon(svg_icon(item["icon"], "#D8DBD2", 19))
            button.setIconSize(QSize(19, 19))
            button.clicked.connect(lambda checked=False, key=item["key"]: self._navigate(key))
            self._nav_buttons[item["key"]] = button
            nav_layout.addWidget(button)
        layout.addLayout(nav_layout)
        layout.addStretch(1)

        right_divider = QFrame()
        right_divider.setFixedSize(1, 38)
        right_divider.setStyleSheet("background:#34372F;border:none;")
        layout.addWidget(right_divider)

        self.profile_button = QPushButton()
        self.profile_button.setObjectName("navProfileButton")
        self.profile_button.setProperty("popupOpen", False)
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_button.setMinimumWidth(180)
        self.profile_button.setMaximumWidth(236)
        profile_layout = QHBoxLayout(self.profile_button)
        profile_layout.setContentsMargins(6, 3, 7, 3)
        profile_layout.setSpacing(9)

        display_name_text = self.session.display_name or self.session.username
        initials = "".join(part[0] for part in display_name_text.split()[:2]).upper() or "U"
        if len(initials) == 1 and len(display_name_text) > 1:
            initials = display_name_text[:2].upper()
        avatar = QLabel(initials[:2])
        avatar.setObjectName("profileAvatar")
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            "background:#C9E86A;color:#171916;border:1px solid #D7F08D;"
            "border-radius:19px;font-weight:800;font-size:12px;"
        )
        self.profile_avatar_label = avatar
        profile_layout.addWidget(avatar)

        profile_copy = QVBoxLayout()
        profile_copy.setSpacing(3)
        display_name = QLabel(display_name_text)
        display_name.setObjectName("profileDisplayName")
        display_name.setStyleSheet("color:#FFFFFF;font-size:11px;font-weight:700;")
        display_name.setMaximumWidth(142)
        display_name.setToolTip(display_name_text)
        role = QLabel(self.session.role.replace("_", " ").title())
        role.setObjectName("profileRole")
        role.setStyleSheet("color:#AEB2A5;font-size:10px;")
        self.profile_name_label = display_name
        self.profile_role_label = role
        profile_copy.addWidget(display_name)
        profile_copy.addWidget(role)
        profile_layout.addLayout(profile_copy, 1)
        caret = QLabel()
        caret.setPixmap(svg_icon("chevron-down", "#AEB2A5", 13).pixmap(13, 13))
        self.profile_caret_label = caret
        profile_layout.addWidget(caret)
        self.profile_button.clicked.connect(self._show_profile_controls)
        self.profile_button.setToolTip("Open account controls")
        layout.addWidget(self.profile_button)
        self._refresh_profile_identity()
        return bar

    @staticmethod
    def _nav_tooltip(key: str, label: str) -> str:
        shortcuts = {
            "overview": "Overview", "billing": "Billing · Ctrl+N", "inventory": "Inventory",
            "contacts": "Contacts", "accounts": "Accounts",
            "reports": "Reports", "ai": "AI insights", "settings": "Settings · Ctrl+,",
        }
        return shortcuts.get(key, label)

    def _text_color(self) -> str:
        return "#F3F5EE" if self.theme == "dark" else "#191B16"

    def _update_header_icons(self) -> None:
        if hasattr(self, "theme_button"):
            icon = "sun" if self.theme == "dark" else "moon"
            self.theme_button.setIcon(svg_icon(icon, self._text_color(), 18))
            self.theme_button.tooltip_text = "Switch to light mode" if self.theme == "dark" else "Switch to dark mode"
            self.theme_button.setProperty("themeMode", self.theme)
            self.theme_button.style().unpolish(self.theme_button)
            self.theme_button.style().polish(self.theme_button)
        if hasattr(self, "notification_button"):
            self._refresh_notification_badge()
        active_key = getattr(self, "_active_key", "overview")
        for key, button in self._nav_buttons.items():
            active = (key == active_key) or (
                key == "billing"
                and (active_key.startswith("billing") or active_key.startswith("pdf_") or active_key.startswith(("bill_edit:", "bill_view:")))
            )
            active = active or (
                key == "inventory"
                and (
                    active_key.startswith(("inventory", "product_catalog", "stock_"))
                    or active_key in {
                        "purchasing", "suppliers", "purchase_orders", "purchase_bills",
                        "supplier_payments", "supplier_returns", "purchasing_reports",
                    }
                )
            )
            button.setProperty("active", active)
            # The dock remains charcoal in both themes. An active lime surface gets a
            # charcoal glyph for contrast; inactive/hover glyphs stay light on charcoal.
            button.setIcon(svg_icon(self._icon_for_nav(key), "#171916" if active else "#D8DBD2", 19))
            button.style().unpolish(button)
            button.style().polish(button)

    @staticmethod
    def _icon_for_nav(key: str) -> str:
        return next((item["icon"] for item in NAV_ITEMS if item["key"] == key), "sparkles")

    def _refresh_clock(self) -> None:
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
        if hasattr(self, "clock_time"):
            self.clock_time.setText(now.strftime("%I:%M %p IST"))
            self.clock_date.setText(now.strftime("%a, %d %b %Y"))
            self.clock_time.setToolTip(now.strftime("%Y-%m-%d %H:%M:%S %Z"))

    def _register_shortcuts(self) -> None:
        shortcuts = [
            ("Ctrl+K", self._open_command_palette),
            ("Ctrl+N", lambda: self._navigate("billing_create") if has_permission(self.session.role, "billing.view") else None),
            ("Ctrl+Shift+B", self._create_backup),
            ("Ctrl+,", lambda: self._navigate("settings") if has_permission(self.session.role, "settings.view") else None),
            ("F1", self._show_shortcuts),
        ]
        self._shortcuts: list[QShortcut] = []
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _navigate(self, key: str, settings_tab: int | None = None) -> None:
        # Let Qt paint the branded loading screen before expensive bill/PDF page
        # construction begins. The generation token prevents stale delayed routes.
        if not self._building_delayed_route and self._needs_bill_loader(key) and has_permission(self.session.role, "billing.view"):
            self._show_bill_loading(key, settings_tab)
            return

        if key != "overview":
            item = next((entry for entry in NAV_ITEMS if entry["key"] == key), None)
            if item and not has_permission(self.session.role, item["permission"]):
                self._show_toast("Your current role does not allow access to this module.")
                return

        if key == "overview":
            page = self._pages.get("overview")
            if page is None:
                page = DashboardPage(
                    self.session, self.profile, get_data_dir(), self.backup_manager,
                    lambda target, tab=0: self._navigate(target, tab),
                    self._create_backup, self.database,
                )
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key == "settings":
            if self._settings_page is None:
                self._settings_page = SettingsPage(
                    self.database, self.session, self.backup_manager, self.profile, self.theme,
                    self._set_theme, self._update_profile,
                    on_appearance_updated=self._apply_appearance_preferences,
                    on_user_profile_updated=self._refresh_profile_identity,
                    on_test_notification=self._test_desktop_notification,
                )
                self._pages[key] = self._settings_page
                self.stack.addWidget(self._settings_page)
            page = self._settings_page
            if settings_tab is not None and 0 <= settings_tab < page.tabs.count():
                page.tabs.setCurrentIndex(settings_tab)
        elif key == "ai":
            page = self._pages.get(key)
            if page is None:
                page = AIBusinessInsightsPage(self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
        elif key == "accounts":
            page = self._pages.get(key)
            if page is None:
                page = AccountingWorkspacePage(self.database, self.session, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key == "reports":
            page = self._pages.get(key)
            if page is None:
                page = AccountingReportsPage(self.database, self.session, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key == "contacts":
            page = self._pages.get(key)
            if page is None:
                page = CustomerDirectoryPage(self.database, self.session, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key.startswith("customer_view:"):
            if not has_permission(self.session.role, "contacts.view"):
                self._show_toast("Your current role does not allow access to contacts.")
                return
            customer_id = key.split(":", 1)[1]
            page = self._pages.get(key)
            if page is None:
                page = CustomerDetailPage(self.database, self.session, customer_id, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
        elif key.startswith("supplier_view:"):
            if not has_permission(self.session.role, "purchasing.view"):
                self._show_toast("Your current role does not allow access to supplier accounts.")
                return
            supplier_id = key.split(":", 1)[1]
            page = self._pages.get(key)
            if page is None:
                page = SupplierDetailPage(self.database, self.session, supplier_id, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
        elif key == "billing":
            page = self._pages.get(key)
            if page is None:
                page = BillingHubPage(self.database, self.session, self.profile, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key == "pdf_studio":
            page = self._pages.get(key)
            if page is None:
                page = PDFStudioHubPage(self.database, self.session, self._navigate)
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key in {
            "inventory", "product_catalog", "inventory_low_stock", "stock_movements",
            "inventory_reports", "stock_adjustment", "purchasing", "suppliers",
            "purchase_orders", "purchase_bills", "supplier_payments", "supplier_returns",
            "purchasing_reports",
        } or key.startswith("stock_adjustment:"):
            inventory_routes = {
                "inventory": "inventory.view", "product_catalog": "inventory.view",
                "inventory_low_stock": "inventory.view", "stock_movements": "inventory.view",
                "inventory_reports": "inventory.view", "stock_adjustment": "inventory.view",
                "purchasing": "purchasing.view", "suppliers": "purchasing.view",
                "purchase_orders": "purchasing.view", "purchase_bills": "purchasing.view",
                "supplier_payments": "purchasing.view", "supplier_returns": "purchasing.view",
                "purchasing_reports": "purchasing.report",
            }
            base_key = "stock_adjustment" if key.startswith("stock_adjustment:") else key
            required = inventory_routes.get(base_key, "inventory.view")
            if not has_permission(self.session.role, required):
                self._show_toast("Your current role does not allow access to this workspace.")
                return
            page = self._pages.get(key)
            if page is None:
                if key == "inventory":
                    page = InventoryHubPage(self.database, self.session, self._navigate)
                elif key == "product_catalog":
                    page = ProductCatalogPage(self.database, self.session, self._navigate)
                elif key == "inventory_low_stock":
                    page = ProductCatalogPage(self.database, self.session, self._navigate, low_stock_only=True)
                elif key == "stock_movements":
                    page = StockMovementsPage(self.database, self.session, self._navigate)
                elif base_key == "stock_adjustment":
                    product_id = key.split(":", 1)[1] if ":" in key else None
                    page = StockAdjustmentPage(self.database, self.session, self._navigate, product_id)
                elif key == "inventory_reports":
                    page = InventoryReportsPage(self.database, self.session, self._navigate)
                elif key == "purchasing":
                    page = PurchasingHubPage(self.database, self.session, self._navigate)
                elif key == "suppliers":
                    page = SupplierCatalogPage(self.database, self.session, self._navigate)
                elif key == "purchase_orders":
                    page = PurchaseOrderPage(self.database, self.session, self._navigate)
                elif key == "purchase_bills":
                    page = PurchaseBillPage(self.database, self.session, self._navigate)
                elif key == "supplier_payments":
                    page = SupplierPaymentsPage(self.database, self.session, self._navigate)
                elif key == "supplier_returns":
                    page = SupplierReturnsPage(self.database, self.session, self._navigate)
                else:
                    page = InventoryReportsPage(
                        self.database, self.session, self._navigate,
                        initial_report="Purchasing summary" if key == "purchasing_reports" else "Stock valuation",
                    )
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh"):
                page.refresh()
        elif key in {"billing_manage", "billing_send", "pdf_templates", "pdf_generator", "billing_exports", "billing_create", "quick_billing"} or key.startswith(("bill_edit:", "bill_view:", "quick_billing:")):
            if not has_permission(self.session.role, "billing.view"):
                self._show_toast("Your current role does not allow access to billing.")
                return
            page = self._pages.get(key)
            # Editors are deliberately rebuilt on entry so unsaved values from a prior
            # abandoned session cannot masquerade as the saved draft.
            if key == "billing_create" or key.startswith("bill_edit:"):
                if page is not None:
                    self.stack.removeWidget(page)
                    page.deleteLater()
                    self._pages.pop(key, None)
                page = None
            if page is None:
                if key == "quick_billing" or key.startswith("quick_billing:"):
                    selected_customer_id = key.split(":", 1)[1] if ":" in key else None
                    page = QuickBillingPage(self.database, self.session, self._navigate, selected_customer_id)
                elif key == "billing_manage":
                    page = BillListPage(self.database, self.session, self._navigate)
                elif key == "billing_send":
                    page = SendBillPage(self.database, self.session, self._navigate)
                elif key == "pdf_templates":
                    page = PDFTemplatePage(self.database, self.session, self._navigate)
                elif key == "pdf_generator":
                    page = PDFGeneratorPage(self.database, self.session, self._navigate)
                elif key == "billing_exports":
                    page = BillingExportsPage(self.database, self.session, self._navigate)
                elif key.startswith("bill_view:"):
                    page = BillDetailPage(self.database, self.session, key.split(":", 1)[1], self._navigate)
                else:
                    editing_id = key.split(":", 1)[1] if key.startswith("bill_edit:") else None
                    page = BillEditorPage(
                        self.database, self.session, editing_id,
                        self._bill_saved,
                        lambda: self._navigate("billing"),
                    )
                self._pages[key] = page
                self.stack.addWidget(page)
            elif hasattr(page, "refresh_after_return"):
                page.refresh_after_return()
            elif hasattr(page, "refresh"):
                page.refresh()
        else:
            page = self._pages.get(key)
            if page is None:
                page = PlaceholderPage(
                    key,
                    lambda: self._navigate("overview"),
                    lambda: self._navigate("settings", 0),
                )
                self._pages[key] = page
                self.stack.addWidget(page)

        self.stack.setCurrentWidget(page)
        fade_in(page, 180)
        self._active_key = key
        for nav_key, button in self._nav_buttons.items():
            active = (nav_key == key) or (nav_key == "billing" and (key.startswith("billing") or key.startswith("pdf_") or key.startswith(("bill_edit:", "bill_view:"))))
            active = active or (nav_key == "inventory" and (key.startswith(("inventory", "product_catalog", "stock_", "supplier_view:")) or key in {"purchasing", "suppliers", "purchase_orders", "purchase_bills", "supplier_payments", "supplier_returns", "purchasing_reports"}))
            active = active or (nav_key == "contacts" and (key == "contacts" or key.startswith("customer_view:")))
            active = active or (nav_key == "billing" and (key == "quick_billing" or key.startswith("quick_billing:")))
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        self._update_header_icons()
        if key == "overview":
            self._show_toast("Overview · Workspace data is stored locally")
        elif key == "settings":
            self._show_toast("Settings · Business profile, appearance and backups")
        elif key == "billing":
            self._show_toast("Billing · Local invoice register")
        elif key == "pdf_studio":
            self._show_toast("PDF Studio · Reusable invoice themes")
        elif key == "inventory":
            self._show_toast("Inventory · Product catalog, stock ledger and valuation")
        elif key == "purchasing":
            self._show_toast("Purchasing · Suppliers, orders, bills, payments and returns")
        elif key == "accounts":
            self._show_toast("Accounts · Double-entry general ledger")
        elif key == "reports":
            self._show_toast("Reports · Posted financial statements and GST summaries")
        elif key.startswith("billing_") or key.startswith("pdf_") or key.startswith(("bill_edit:", "bill_view:")):
            self._show_toast("Billing workspace · Changes are saved locally")
        elif key.startswith(("inventory", "product_catalog", "stock_")) or key in {
            "suppliers", "purchase_orders", "purchase_bills", "supplier_payments", "supplier_returns", "purchasing_reports",
        }:
            self._show_toast(f"{page.windowTitle() or key.replace('_', ' ').title()} · Changes are saved locally")
        else:
            self._show_toast(f"{page.windowTitle() or key.title()} · Planned for a later phase")

    @staticmethod
    def _needs_bill_loader(key: str) -> bool:
        return (
            key.startswith(("bill_view:", "bill_edit:"))
            or key in {"billing_create", "billing_manage", "billing_send", "pdf_generator", "quick_billing"}
            or key.startswith("quick_billing:")
        )

    def _show_bill_loading(self, key: str, settings_tab: int | None) -> None:
        self._bill_loading_token += 1
        token = self._bill_loading_token
        self._pending_bill_route = (key, settings_tab)
        if self._loading_page is not None:
            self.stack.removeWidget(self._loading_page)
            self._loading_page.deleteLater()
            self._loading_page = None
        self._loading_page = BrandedLoadingPage(self._mark_path, self.theme, self.stack)
        self.stack.addWidget(self._loading_page)
        self.stack.setCurrentWidget(self._loading_page)
        self._active_key = key
        self._update_header_icons()
        QTimer.singleShot(320, lambda route_token=token: self._complete_bill_loading(route_token))

    def _complete_bill_loading(self, token: int) -> None:
        if token != self._bill_loading_token or self._pending_bill_route is None:
            return
        key, settings_tab = self._pending_bill_route
        self._pending_bill_route = None
        self._building_delayed_route = True
        try:
            self._navigate(key, settings_tab)
        finally:
            self._building_delayed_route = False

    def _bill_saved(self, bill_id: str) -> None:
        """Return to the bill register after a saved draft or issued document."""
        self._show_toast("Bill saved · Local record updated")
        # Recreate summary hubs so counts reflect the saved transaction immediately.
        for page_key, old_page in list(self._pages.items()):
            if page_key in {"billing", "pdf_studio", "billing_create"} or page_key.startswith(("bill_edit:", "bill_view:")):
                self._pages.pop(page_key, None)
                self.stack.removeWidget(old_page)
                old_page.deleteLater()
        self._navigate("billing_manage")

    def _set_theme(self, theme: str) -> None:
        if theme not in {"light", "dark"}:
            return
        self.theme = theme
        self.database.set_setting("theme", theme)
        app = QApplication.instance()
        if app:
            apply_theme(app, theme, self.font_family, self.ui_scale, self.control_size, self.control_width)
        self._update_header_icons()
        if self._settings_page:
            self._settings_page.theme = theme
            self._settings_page._update_theme_buttons()
            self._settings_page._refresh_appearance_preview()
        self._show_toast(f"{theme.title()} appearance enabled")

    def _apply_appearance_preferences(self, font_family: str, scale_percent: int, control_size: str, control_width: str = "fluid") -> None:
        self.font_family = font_family
        self.ui_scale = min(1.25, max(0.80, int(scale_percent) / 100))
        self.control_size = control_size if control_size in {"compact", "comfortable", "roomy"} else "comfortable"
        self.control_width = control_width if control_width in {"compact", "balanced", "fluid"} else "fluid"
        self.database.set_setting("font_family", self.font_family, scope="user", scope_id=self.session.user_id)
        self.database.set_setting("ui_scale_percent", str(int(scale_percent)), scope="user", scope_id=self.session.user_id)
        self.database.set_setting("control_size", self.control_size, scope="user", scope_id=self.session.user_id)
        self.database.set_setting("control_width", self.control_width, scope="user", scope_id=self.session.user_id)
        app = QApplication.instance()
        if app:
            apply_theme(app, self.theme, self.font_family, self.ui_scale, self.control_size, self.control_width)
        self._show_toast("Appearance preferences applied")

    def _profile_avatar_pixmap(self, logical_size: int) -> QPixmap:
        """Return a DPR-aware circular copy of the current user photo, if configured."""
        photo_path = self.database.get_setting(
            "profile_picture_path", "", scope="user", scope_id=self.session.user_id
        ) or ""
        source = QPixmap(photo_path) if photo_path and Path(photo_path).is_file() else QPixmap()
        if source.isNull():
            return QPixmap()
        physical_size = max(32, int(logical_size * 2))
        source = source.scaled(
            physical_size, physical_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        crop = source.copy(
            max(0, (source.width() - physical_size) // 2),
            max(0, (source.height() - physical_size) // 2), physical_size, physical_size,
        )
        output = QPixmap(physical_size, physical_size)
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        clip = QPainterPath()
        clip.addEllipse(0, 0, physical_size, physical_size)
        painter.setClipPath(clip)
        painter.drawPixmap(0, 0, crop)
        painter.end()
        output.setDevicePixelRatio(2.0)
        return output

    def _profile_display_name(self) -> str:
        return (
            self.database.get_setting(
                "profile_display_name", self.session.display_name, scope="user", scope_id=self.session.user_id
            ) or self.session.display_name or self.session.username
        )

    def _refresh_profile_identity(self) -> None:
        if not hasattr(self, "profile_avatar_label"):
            return
        display_name = self._profile_display_name()
        if hasattr(self, "profile_name_label"):
            label = self.profile_name_label
            label.setText(QFontMetrics(label.font()).elidedText(
                display_name, Qt.TextElideMode.ElideRight, max(72, label.maximumWidth())
            ))
            label.setToolTip(f"{display_name} · {self.session.username}")
        if hasattr(self, "profile_role_label"):
            self.profile_role_label.setText(self.session.role.replace("_", " ").title())
        avatar = self.profile_avatar_label
        photo = self._profile_avatar_pixmap(38)
        if not photo.isNull():
            avatar.setPixmap(photo)
            avatar.setText("")
            avatar.setStyleSheet("background:transparent;border:1px solid #C9E86A;border-radius:19px;")
        else:
            name_for_initials = display_name.strip() or self.session.username
            initials = "".join(part[0] for part in name_for_initials.split()[:2]).upper() or "U"
            if len(initials) == 1 and len(name_for_initials) > 1:
                initials = name_for_initials[:2].upper()
            avatar.setPixmap(QPixmap())
            avatar.setText(initials[:2])
            avatar.setStyleSheet("background:#C9E86A;color:#171916;border:1px solid #D7F08D;border-radius:19px;font-weight:800;font-size:12px;")
        if self._profile_popup is not None and self._profile_popup.isVisible():
            popup_name = getattr(self, "_profile_popup_name", None)
            popup_role = getattr(self, "_profile_popup_role", None)
            popup_avatar = getattr(self, "_profile_popup_avatar", None)
            if popup_name:
                popup_name.setText(display_name)
                popup_name.setToolTip(f"{display_name} · {self.session.username}")
            if popup_role:
                popup_role.setText(f"{self.session.role.replace('_', ' ').title()} · Local account")
            if popup_avatar:
                photo = self._profile_avatar_pixmap(42)
                if not photo.isNull():
                    popup_avatar.setPixmap(photo)
                    popup_avatar.setText("")
                else:
                    popup_avatar.setPixmap(QPixmap())
                    popup_avatar.setText("".join(part[0] for part in display_name.split()[:2]).upper()[:2] or "U")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 1180
        if hasattr(self, "bottom_bar"):
            for button in self._nav_buttons.values():
                button.setIconSize(QSize(17 if compact else 19, 17 if compact else 19))
            for layout in self.bottom_bar.findChildren(QHBoxLayout):
                if layout.count() >= 8:
                    layout.setSpacing(4 if compact else 8)
            if hasattr(self, "profile_button"):
                self.profile_button.setMinimumWidth(140 if compact else 180)

    def _toggle_theme(self) -> None:
        self._set_theme("dark" if self.theme == "light" else "light")

    def _update_profile(self, profile: dict[str, str]) -> None:
        self.profile = profile
        was_on_overview = getattr(self, "_active_key", "overview") == "overview"
        if "overview" in self._pages:
            old = self._pages.pop("overview")
            self.stack.removeWidget(old)
            old.deleteLater()
        if self._settings_page:
            self._settings_page.profile = profile
        if was_on_overview:
            self._navigate("overview")
        else:
            self._show_toast("Business profile saved")

    def _animate_popup(self, panel: QFrame, anchor: QWidget, align: str = "right", above: bool = True) -> None:
        panel.adjustSize()
        width = panel.width()
        height = panel.height()
        global_anchor = anchor.mapToGlobal(QPoint(0, 0))
        x = global_anchor.x() + anchor.width() - width if align == "right" else global_anchor.x()
        y = global_anchor.y() - height - 10 if above else global_anchor.y() + anchor.height() + 10
        screen = anchor.screen().availableGeometry() if anchor.screen() else None
        if screen:
            x = min(max(x, screen.left() + 8), screen.right() - width - 8)
            if y < screen.top() + 8:
                y = global_anchor.y() + anchor.height() + 8
            if y + height > screen.bottom() - 8:
                y = max(screen.top() + 8, global_anchor.y() - height - 8)
        final_position = QPoint(x, y)
        opening_position = QPoint(x, y + 8 if above else y - 8)
        panel.move(opening_position)
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(0.0)
        panel.setGraphicsEffect(effect)
        panel.show()
        panel.raise_()

        fade = QPropertyAnimation(effect, b"opacity", panel)
        fade.setDuration(180)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(
            lambda current_panel=panel, current_effect=effect:
                current_panel.setGraphicsEffect(None)
                if current_panel.graphicsEffect() is current_effect else None
        )
        slide = QPropertyAnimation(panel, b"pos", panel)
        slide.setDuration(210)
        slide.setStartValue(opening_position)
        slide.setEndValue(final_position)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        for animation in (fade, slide):
            self._popup_animations.append(animation)
            animation.finished.connect(
                lambda current=animation: self._popup_animations.remove(current)
                if current in self._popup_animations else None
            )
            animation.start()

    def _show_toast(self, message: str) -> None:
        """Show a compact animated status toast above the bottom dock."""
        if self._toast_popup:
            self._toast_timer.stop()
            self._toast_popup.close()
            self._toast_popup.deleteLater()
            self._toast_popup = None

        panel = QFrame(self, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        panel.setObjectName("toastPopup")
        row = QHBoxLayout(panel)
        row.setContentsMargins(13, 10, 16, 10)
        row.setSpacing(9)
        indicator = QFrame()
        indicator.setFixedSize(7, 7)
        indicator.setStyleSheet("background:#C9E86A;border:none;border-radius:3px;")
        row.addWidget(indicator, 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(message)
        label.setObjectName("toastText")
        label.setWordWrap(True)
        label.setMaximumWidth(420)
        row.addWidget(label)
        panel.adjustSize()

        local_point = QPoint(
            max(12, self.width() - panel.width() - 24),
            max(12, self.height() - self.bottom_bar.height() - panel.height() - 18),
        )
        global_point = self.mapToGlobal(local_point)
        panel.move(global_point)
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(0.0)
        panel.setGraphicsEffect(effect)
        panel.show()
        panel.raise_()

        animation = QPropertyAnimation(effect, b"opacity", panel)
        animation.setDuration(150)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_animation = animation
        self._toast_popup = panel
        animation.start()
        self._toast_timer.start(2800)

    def _hide_toast(self) -> None:
        panel = self._toast_popup
        if panel is None:
            return
        effect = panel.graphicsEffect()
        if effect is None:
            panel.close()
            panel.deleteLater()
            self._toast_popup = None
            return
        animation = QPropertyAnimation(effect, b"opacity", panel)
        animation.setDuration(130)
        animation.setStartValue(effect.opacity())
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_animation = animation

        def finish() -> None:
            panel.close()
            panel.deleteLater()
            if self._toast_popup is panel:
                self._toast_popup = None

        animation.finished.connect(finish)
        animation.start()

    def _show_profile_controls(self) -> None:
        if self._profile_popup and self._profile_popup.isVisible():
            self._profile_popup.close()
            self._profile_popup = None
            self.profile_caret_label.setPixmap(svg_icon("chevron-down", "#AEB2A5", 13).pixmap(13, 13))
            return
        panel = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        panel.installEventFilter(self)
        panel.setObjectName("popoverPanel")
        panel.setFixedWidth(min(330, max(280, self.width() - 28)))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        avatar = QLabel()
        avatar.setFixedSize(42, 42)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setObjectName("profilePopupAvatar")
        photo = self._profile_avatar_pixmap(42)
        if not photo.isNull():
            avatar.setPixmap(photo)
            avatar.setStyleSheet("background:transparent;border:1px solid #C9E86A;border-radius:21px;")
        else:
            initials = "".join(part[0] for part in self._profile_display_name().split()[:2]).upper() or "U"
            avatar.setText(initials[:2])
            avatar.setStyleSheet("background:#C9E86A;color:#171916;border:1px solid #D7F08D;border-radius:21px;font-weight:800;font-size:12px;")
        header.addWidget(avatar)
        copy = QVBoxLayout()
        title = QLabel(self._profile_display_name())
        title.setObjectName("profilePopupName")
        title.setStyleSheet(f"font-size:13px;font-weight:750;color:{palette['text']};")
        title.setWordWrap(True)
        title.setToolTip(f"{self._profile_display_name()} · {self.session.username}")
        subtitle = QLabel(f"{self.session.role.replace('_', ' ').title()} · Local account")
        subtitle.setObjectName("muted")
        subtitle.setStyleSheet("font-size:10px;")
        copy.addWidget(title)
        copy.addWidget(subtitle)
        header.addLayout(copy, 1)
        layout.addLayout(header)
        self._profile_popup_avatar = avatar
        self._profile_popup_name = title
        self._profile_popup_role = subtitle

        divider = QFrame()
        divider.setFixedHeight(1)
        palette = tokens(self.theme)
        divider.setStyleSheet(f"background:{palette['border']};border:none;")
        layout.addWidget(divider)
        for text, icon_name, callback in (
            ("Business profile & settings", "building", lambda: self._navigate("settings", 0)),
            ("Create verified backup", "database", self._create_backup),
            ("Keyboard shortcuts", "keyboard", self._show_shortcuts),
            ("Lock workspace / sign out", "lock", self._confirm_logout),
        ):
            button = QPushButton(text)
            button.setObjectName("smallAction")
            button.setIcon(svg_icon(icon_name, palette["muted"], 16))
            button.setIconSize(QSize(16, 16))
            button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, action=callback, popup=panel: self._trigger_popup_action(popup, action))
            layout.addWidget(button)
        self._profile_popup = panel
        self.profile_button.setProperty("popupOpen", True)
        self.profile_button.style().unpolish(self.profile_button)
        self.profile_button.style().polish(self.profile_button)
        self._animate_popup(panel, self.profile_button, align="right", above=True)
        self.profile_caret_label.setPixmap(svg_icon("chevron-up", "#AEB2A5", 13).pixmap(13, 13))

    def eventFilter(self, watched, event):
        # Popup windows close automatically when the user clicks elsewhere. Keep the
        # account dock's caret and selected state synchronized with those implicit closes.
        if watched is getattr(self, "_profile_popup", None) and event.type() == QEvent.Type.Hide:
            self._profile_popup = None
            if hasattr(self, "profile_caret_label"):
                self.profile_caret_label.setPixmap(svg_icon("chevron-down", "#AEB2A5", 13).pixmap(13, 13))
            if hasattr(self, "profile_button"):
                self.profile_button.setProperty("popupOpen", False)
                self.profile_button.style().unpolish(self.profile_button)
                self.profile_button.style().polish(self.profile_button)
        return super().eventFilter(watched, event)

    def _trigger_popup_action(self, panel: QFrame, callback) -> None:
        panel.close()
        if self._profile_popup is panel:
            self._profile_popup = None
        self.profile_button.setProperty("popupOpen", False)
        self.profile_button.style().unpolish(self.profile_button)
        self.profile_button.style().polish(self.profile_button)
        self.profile_caret_label.setPixmap(svg_icon("chevron-down", "#AEB2A5", 13).pixmap(13, 13))
        callback()

    def _setup_desktop_notifications(self) -> None:
        """Connect the local alert engine to native desktop notifications when available."""
        icon_path = str(self._asset_root / "koshflow.ico")
        self._tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
        self._tray_icon.setToolTip("KoshFlow business alerts")
        menu = QMenu()
        open_action = menu.addAction("Open KoshFlow")
        open_action.triggered.connect(self._restore_from_tray)
        inbox_action = menu.addAction("View notifications")
        inbox_action.triggered.connect(self._show_notifications)
        menu.addSeparator()
        exit_action = menu.addAction("Sign out / close")
        exit_action.triggered.connect(self._confirm_logout)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._tray_activated)
        self._tray_icon.messageClicked.connect(self._show_notifications)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.setVisible(True)
        self._refresh_notification_badge()
        self.notification_scan_timer = QTimer(self)
        self.notification_scan_timer.setInterval(120_000)
        self.notification_scan_timer.timeout.connect(self._scan_notifications)
        self.notification_scan_timer.start()
        QTimer.singleShot(1600, self._scan_notifications)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _refresh_notification_badge(self) -> None:
        if not hasattr(self, "notification_button"):
            return
        inbox_enabled = self.database.get_setting(
            "in_app_notifications_enabled", "1", scope="user", scope_id=self.session.user_id
        ) != "0"
        try:
            count = self.notification_service.unread_count(self.session.business_id) if inbox_enabled else 0
        except Exception:
            count = 0
        if count:
            # A crisp overlay dot indicates an unread alert without squeezing text into the icon button.
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.drawPixmap(2, 3, svg_icon("bell", self._text_color(), 18).pixmap(18, 18))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#C9E86A"))
            painter.drawEllipse(16, 1, 7, 7)
            painter.end()
            self.notification_button.setIcon(QIcon(pixmap))
            self.notification_button.tooltip_text = f"Notifications · {count} unread"
        else:
            self.notification_button.setIcon(svg_icon("bell", self._text_color(), 18))
            self.notification_button.tooltip_text = "Notifications"
        if self._tray_icon:
            self._tray_icon.setToolTip(f"KoshFlow · {count} unread notification(s)" if count else "KoshFlow business alerts")

    def _scan_notifications(self) -> None:
        """Scan saved bill due dates, expected purchase dates and inventory levels."""
        try:
            new_alerts = self.notification_service.scan_business(self.session.business_id)
        except Exception as exc:
            self._show_toast(f"Notification scan failed: {exc}")
            return
        self._refresh_notification_badge()
        if not new_alerts:
            return
        desktop_enabled = self.database.get_setting(
            "desktop_notifications_enabled", "1", scope="user", scope_id=self.session.user_id
        ) != "0"
        if not desktop_enabled:
            return
        severity_rank = {"critical": 0, "warning": 1, "info": 2, "success": 3}
        alerts = sorted(new_alerts, key=lambda row: severity_rank.get(row.get("severity", "info"), 2))[:3]
        if self._tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
            for index, alert in enumerate(alerts):
                def deliver(item=alert):
                    icon = QSystemTrayIcon.MessageIcon.Critical if item.get("severity") == "critical" else (QSystemTrayIcon.MessageIcon.Warning if item.get("severity") == "warning" else QSystemTrayIcon.MessageIcon.Information)
                    self._tray_icon.showMessage(str(item["title"]), str(item["message"]), icon, 8000)
                QTimer.singleShot(index * 900, deliver)
        else:
            self._show_toast(f"{alerts[0]['title']} · {alerts[0]['message']}")

    def _test_desktop_notification(self) -> str:
        """Create a persistent test entry and attempt native desktop delivery."""
        notification = self.notification_service.create_test_notification(self.session.business_id)
        self._refresh_notification_badge()
        desktop_enabled = self.database.get_setting(
            "desktop_notifications_enabled", "1", scope="user", scope_id=self.session.user_id
        ) != "0"
        tray_available = bool(self._tray_icon and QSystemTrayIcon.isSystemTrayAvailable() and self._tray_icon.isVisible())
        if desktop_enabled and tray_available and self._tray_icon:
            self._tray_icon.showMessage(
                notification["title"], notification["message"],
                QSystemTrayIcon.MessageIcon.Information, 8000,
            )
            self._show_toast("Test notification request sent to the operating system.")
            return "Test alert saved and native delivery requested. Check the Windows notification center; Focus Assist or OS permissions may still suppress the toast."
        if not desktop_enabled:
            self._show_toast("Test alert saved. Native desktop notifications are disabled in Settings.")
            return "The test alert was saved to the local notification service, but native desktop delivery is disabled. Enable it and save settings to test again."
        self._show_toast("Test alert saved. Native tray is unavailable; using the in-app fallback.")
        return "The test alert was saved. This system has no available tray notification service, so KoshFlow used its in-app fallback."

    def _show_notifications(self) -> None:
        if self.database.get_setting(
            "in_app_notifications_enabled", "1", scope="user", scope_id=self.session.user_id
        ) == "0":
            self._show_toast("The in-app notification inbox is disabled in Settings.")
            return
        if self._notification_popup and self._notification_popup.isVisible():
            self._notification_popup.close()
            self._notification_popup = None
            return
        panel = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        panel.setObjectName("popoverPanel")
        panel.setFixedWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(17, 16, 17, 17)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Notifications")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        try:
            unread = self.notification_service.unread_count(self.session.business_id)
            notifications = self.notification_service.list_notifications(self.session.business_id, limit=40)
        except Exception:
            unread, notifications = 0, []
        status = QLabel(f"{unread} UNREAD" if unread else "ALL CAUGHT UP")
        status.setObjectName("accentPill")
        header.addWidget(status)
        layout.addLayout(header)

        active = [r for r in notifications if r.get("is_active") and not r.get("is_dismissed")]
        recent = [r for r in notifications if not r.get("is_active") and not r.get("is_dismissed")]
        shown = (active + recent)[:6]
        if not shown:
            empty = QFrame(); empty.setObjectName("softPanel")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(14, 18, 14, 18)
            icon = QLabel(); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setPixmap(svg_icon("bell", "#829A43", 25).pixmap(25, 25))
            heading = QLabel("You're all caught up"); heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet("font-size:13px;font-weight:720;")
            description = QLabel("Customer due dates, supplier deadlines and stock-level alerts will appear here when their saved conditions are met.")
            description.setObjectName("muted"); description.setWordWrap(True); description.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(icon); empty_layout.addWidget(heading); empty_layout.addWidget(description)
            layout.addWidget(empty)
        else:
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body = QWidget(); body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0); body_layout.setSpacing(7)
            for item in shown:
                card = QFrame(); card.setObjectName("softPanel")
                card_layout = QVBoxLayout(card); card_layout.setContentsMargins(10, 9, 10, 9); card_layout.setSpacing(5)
                row = QHBoxLayout()
                title_label = QLabel(str(item["title"])); title_label.setStyleSheet("font-size:11px;font-weight:740;")
                title_label.setWordWrap(True); row.addWidget(title_label, 1)
                severity_label = QLabel("RESOLVED" if not item.get("is_active") else str(item.get("severity", "info")).upper())
                severity_label.setObjectName("accentPill" if item.get("severity") != "critical" else "warningPill")
                row.addWidget(severity_label, 0, Qt.AlignmentFlag.AlignTop)
                card_layout.addLayout(row)
                message = QLabel(str(item["message"])); message.setObjectName("muted"); message.setWordWrap(True)
                message.setStyleSheet("font-size:10px;")
                card_layout.addWidget(message)
                actions = QHBoxLayout(); actions.addStretch(1)
                if item.get("related_page") and item.get("is_active"):
                    open_button = QPushButton("Open")
                    open_button.setObjectName("smallAction")
                    open_button.clicked.connect(lambda _checked=False, record=item, pop=panel: self._open_notification(record, pop))
                    actions.addWidget(open_button)
                dismiss_button = QPushButton("Dismiss")
                dismiss_button.setObjectName("smallAction")
                dismiss_button.clicked.connect(lambda _checked=False, record=item, pop=panel: self._dismiss_notification(record, pop))
                actions.addWidget(dismiss_button)
                card_layout.addLayout(actions)
                body_layout.addWidget(card)
            body_layout.addStretch(1)
            scroll.setWidget(body); scroll.setMinimumHeight(min(390, 105 * len(shown)))
            layout.addWidget(scroll)
        footer_row = QHBoxLayout()
        footer_note = QLabel("Alerts are generated from locally recorded invoices, purchase dates and stock levels.")
        footer_note.setObjectName("muted"); footer_note.setWordWrap(True); footer_note.setStyleSheet("font-size:9px;")
        footer_row.addWidget(footer_note, 1)
        mark_all = QPushButton("Mark all read"); mark_all.setObjectName("smallAction")
        mark_all.setEnabled(unread > 0)
        mark_all.clicked.connect(lambda _checked=False, pop=panel: self._mark_all_notifications_read(pop))
        footer_row.addWidget(mark_all)
        layout.addLayout(footer_row)
        self._notification_popup = panel
        self._animate_popup(panel, self.notification_button, align="right", above=False)

    def _open_notification(self, notification: dict, popup: QFrame) -> None:
        self.notification_service.mark_read(self.session.business_id, str(notification["notification_id"]))
        target = str(notification.get("related_page") or "overview")
        popup.close(); self._notification_popup = None
        self._refresh_notification_badge()
        self._navigate(target)

    def _dismiss_notification(self, notification: dict, popup: QFrame) -> None:
        self.notification_service.dismiss(self.session.business_id, str(notification["notification_id"]))
        popup.close(); self._notification_popup = None
        self._refresh_notification_badge()
        self._show_notifications()

    def _mark_all_notifications_read(self, popup: QFrame) -> None:
        self.notification_service.mark_all_read(self.session.business_id)
        popup.close(); self._notification_popup = None
        self._refresh_notification_badge()
        self._show_notifications()

    def _open_command_palette(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("KoshFlow command palette")
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setMinimumHeight(430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        label = QLabel("Jump to a page or run an action")
        label.setObjectName("sectionTitle")
        search = QLineEdit()
        search.setPlaceholderText("Type a page or command…")
        listing = QListWidget()
        commands = [
            ("overview", "Go to overview", "Page"), ("billing", "Open billing", "Page · Ctrl+N"),
            ("inventory", "Open inventory", "Page"), ("contacts", "Open contacts", "Page"),
            ("accounts", "Open accounting & tax", "Page"),
            ("reports", "Open reports", "Page"), ("ai", "Open AI insights", "Page"),
            ("settings", "Open business settings", "Page · Ctrl+,"),
            ("backup", "Create a verified local backup", "Action · Ctrl+Shift+B"),
            ("theme", "Switch light / dark mode", "Appearance"), ("shortcuts", "View keyboard shortcuts", "Help · F1"),
            ("logout", "Lock workspace / sign out", "Account"),
        ]
        available = {item["key"] for item in visible_navigation(self.session.role)} | {"overview"}
        for key, text, hint in commands:
            if key not in available and key not in {"backup", "theme", "shortcuts", "logout"}:
                continue
            if key == "backup" and not has_permission(self.session.role, "backup.create"):
                continue
            item = QListWidgetItem(f"{text}     ·     {hint}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            listing.addItem(item)

        def filter_items(query: str) -> None:
            value = query.strip().casefold()
            visible = 0
            for index in range(listing.count()):
                item = listing.item(index)
                item.setHidden(value not in item.text().casefold())
                if not item.isHidden():
                    visible += 1
            listing.setCurrentRow(next((i for i in range(listing.count()) if not listing.item(i).isHidden()), -1) if visible else -1)

        def activate(item: QListWidgetItem | None = None) -> None:
            item = item or listing.currentItem()
            if not item:
                return
            action = item.data(Qt.ItemDataRole.UserRole)
            dialog.accept()
            if action in available:
                self._navigate(action)
            elif action == "backup":
                self._create_backup()
            elif action == "theme":
                self._toggle_theme()
            elif action == "shortcuts":
                self._show_shortcuts()
            elif action == "logout":
                self._confirm_logout()

        search.textChanged.connect(filter_items)
        search.returnPressed.connect(lambda: activate())
        listing.itemActivated.connect(activate)
        layout.addWidget(label)
        layout.addWidget(search)
        layout.addWidget(listing, 1)
        hint = QLabel("↑ ↓ to move  ·  Enter to open  ·  Esc to close")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        self._command_dialog = dialog
        search.setFocus()
        listing.setCurrentRow(0)
        dialog.exec()
        self._command_dialog = None

    def _create_backup(self) -> None:
        if not has_permission(self.session.role, "backup.create"):
            QMessageBox.information(self, "Permission required", "Your current role does not allow creating database backups.")
            return
        try:
            path = self.backup_manager.create_backup()
        except BackupError as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        self._show_toast(f"Backup verified · {path.name}")
        QMessageBox.information(self, "Backup created", f"Your local database backup passed integrity checks.\n\n{path}")
        if "overview" in self._pages:
            old = self._pages.pop("overview")
            self.stack.removeWidget(old)
            old.deleteLater()
            if self._active_key == "overview":
                self._navigate("overview")

    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "Ctrl + K      Command palette\n"
            "Ctrl + N      Open billing workspace\n"
            "Ctrl + Shift + B      Create a local backup\n"
            "Ctrl + ,      Business settings\n"
            "F1                 Keyboard shortcut reference\n"
            "Esc                Close the active dialog\n\n"
            "Billing and accounting actions become active as those modules ship.",
        )

    def _confirm_logout(self) -> None:
        result = QMessageBox.question(
            self, "Lock workspace?", "Sign out of this local workspace? Your saved business data will remain on this device.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Yes:
            self.clock_timer.stop()
            self.close()
            self.on_logout()
