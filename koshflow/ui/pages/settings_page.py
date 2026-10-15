"""Business profile, appearance, and local backup settings.

Purpose: Deliver user profile, business identity, accessible appearance customization and local backup controls.
Project: KoshFlow | Version: 0.6.3
Canonical path: koshflow/ui/pages/settings_page.py
Developer: Mayank Chawdhari AKA BOSS294
Integration: Pass the database, session, BackupManager, current profile and callbacks.
Changelog: v0.6.3 — Added configurable notification preferences and a desktop-notification test panel; standardized settings backgrounds for both themes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QCheckBox,
    QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget, QComboBox,
    QSlider, QSizePolicy, QLineEdit, QSystemTrayIcon,
)

from koshflow.config import DEFAULT_TIMEZONE, get_data_dir
from koshflow.core.backups import BackupError, BackupManager
from koshflow.core.database import Database
from koshflow.core.session import Session
from koshflow.core.permissions import has_permission
from koshflow.services.business_service import BusinessProfileError, BusinessService
from koshflow.services.invoice_profile_service import load_invoice_profile, save_invoice_profile
from koshflow.ui.components import CardFrame, HoverButton, labeled_field, make_combo, make_line_edit, muted_label
from koshflow.ui.icons import svg_icon
from koshflow.ui.pages.invoice_theme_preview import InvoiceThemePreview


BUSINESS_TYPES = [
    "Retail", "Wholesale", "Manufacturing", "Services", "Professional services",
    "E-commerce", "Distributor", "Other",
]


class SettingsPage(QWidget):
    def __init__(self, database: Database, session: Session, backup_manager: BackupManager,
                 profile: dict[str, str], theme: str, on_theme_changed,
                 on_profile_updated, on_appearance_updated=None,
                 on_user_profile_updated=None, on_test_notification=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.database = database
        self.session = session
        self.backup_manager = backup_manager
        self.profile = profile
        self.theme = theme
        self.on_theme_changed = on_theme_changed
        self.on_profile_updated = on_profile_updated
        self.on_appearance_updated = on_appearance_updated
        self.on_user_profile_updated = on_user_profile_updated
        self.on_test_notification = on_test_notification
        self.business_service = BusinessService(database)
        self._fields: dict[str, QWidget] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        title_row = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Manage your business identity, appearance and local data.")
        subtitle.setObjectName("muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        title_row.addLayout(heading)
        title_row.addStretch(1)
        pill = QLabel("LOCAL WORKSPACE")
        pill.setObjectName("pill")
        title_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.tabs.setAutoFillBackground(True)
        self.tabs.addTab(self._wrap_in_scroll(self._build_profile_tab(), "businessProfileScroll"), "Business profile")
        self.tabs.addTab(self._wrap_in_scroll(self._build_invoice_settings_tab(), "invoiceSettingsScroll"), "Invoice & payments")
        self.tabs.addTab(self._build_appearance_tab(), "Appearance")
        self.tabs.addTab(self._wrap_in_scroll(self._build_backup_tab(), "dataBackupScroll"), "Data & backups")
        self.tabs.addTab(self._build_user_tab(), "My profile")
        self.tabs.addTab(self._wrap_in_scroll(self._build_notifications_tab(), "notificationsSettingsScroll"), "Notifications")
        root.addWidget(self.tabs, 1)

    @staticmethod
    def _wrap_in_scroll(content: QWidget, object_name: str) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.setAutoFillBackground(True)
        viewport = scroll.viewport()
        viewport.setObjectName(f"{object_name}Viewport")
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        viewport.setAutoFillBackground(True)
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Preserve meaningful page object names (e.g. settingsNotificationsPage) for QSS.
        if not content.objectName():
            content.setObjectName(f"{object_name}Content")
        scroll.setWidget(content)
        return scroll

    def _build_notifications_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsNotificationsPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(3, 15, 3, 8)
        layout.setSpacing(14)

        delivery_card = CardFrame("settingsCard")
        delivery_layout = QVBoxLayout(delivery_card)
        delivery_layout.setContentsMargins(22, 20, 22, 20)
        delivery_layout.setSpacing(12)
        delivery_layout.addWidget(self._card_heading(
            "Desktop notification delivery",
            "KoshFlow keeps a local notification inbox. Native Windows notifications additionally depend on system-tray availability and operating-system notification permissions.",
        ))

        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        availability_row = QHBoxLayout()
        dot = QFrame()
        dot.setFixedSize(9, 9)
        dot.setStyleSheet(f"background:{'#6A9F35' if tray_available else '#B98934'};border-radius:4px;border:none;")
        availability_row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        availability_copy = QVBoxLayout()
        self.notification_system_status = QLabel(
            "System tray detected — native notification delivery can be attempted." if tray_available
            else "System tray not detected — KoshFlow will use its in-app notification fallback."
        )
        self.notification_system_status.setWordWrap(True)
        self.notification_system_status.setStyleSheet("font-weight:680;")
        availability_copy.addWidget(self.notification_system_status)
        availability_copy.addWidget(muted_label("A successful test request confirms KoshFlow handed the message to Qt/Windows; the OS may still suppress notifications through Focus Assist or application notification settings."))
        availability_row.addLayout(availability_copy, 1)
        delivery_layout.addLayout(availability_row)

        self.desktop_notifications_enabled = QCheckBox("Enable native desktop notifications")
        self.desktop_notifications_enabled.setChecked(
            self.database.get_setting("desktop_notifications_enabled", "1", scope="user", scope_id=self.session.user_id) != "0"
        )
        delivery_layout.addWidget(self.desktop_notifications_enabled)
        self.in_app_notifications_enabled = QCheckBox("Keep the in-app notification inbox enabled")
        self.in_app_notifications_enabled.setChecked(
            self.database.get_setting("in_app_notifications_enabled", "1", scope="user", scope_id=self.session.user_id) != "0"
        )
        self.in_app_notifications_enabled.setToolTip("The inbox can remain available even when native desktop delivery is disabled.")
        delivery_layout.addWidget(self.in_app_notifications_enabled)
        layout.addWidget(delivery_card)

        rules_card = CardFrame("settingsCard")
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(22, 20, 22, 20)
        rules_layout.setSpacing(10)
        rules_layout.addWidget(self._card_heading(
            "Business alert rules",
            "These switches apply to all users in this business workspace. Disabled categories are excluded from future scans.",
        ))
        rules = [
            ("notify_customer_due", "Customer invoice due dates and overdue receivables"),
            ("notify_supplier_due", "Supplier bill due dates and overdue payables"),
            ("notify_low_stock", "Low-stock and out-of-stock products"),
            ("notify_purchase_order_dates", "Purchase order expected dates"),
        ]
        self.notification_rule_checks: dict[str, QCheckBox] = {}
        for key, label_text in rules:
            check = QCheckBox(label_text)
            check.setChecked(self.database.get_setting(key, "1", scope="business", scope_id=self.session.business_id) != "0")
            self.notification_rule_checks[key] = check
            rules_layout.addWidget(check)
        layout.addWidget(rules_card)

        test_card = CardFrame("settingsCard")
        test_layout = QVBoxLayout(test_card)
        test_layout.setContentsMargins(22, 20, 22, 20)
        test_layout.setSpacing(10)
        test_layout.addWidget(self._card_heading(
            "Test notifications",
            "Send a real test through the same local inbox/native notification path, then check the operating-system notification center.",
        ))
        actions = QHBoxLayout()
        self.notification_preferences_message = muted_label("")
        actions.addWidget(self.notification_preferences_message, 1)
        save = HoverButton("Save notification settings")
        save.setObjectName("primaryButton")
        save.setIcon(svg_icon("check", "#171916", 16))
        save.clicked.connect(self._save_notification_preferences)
        test = HoverButton("Send test notification")
        test.setIcon(svg_icon("bell-ring", self._icon_color(), 16))
        test.clicked.connect(self._test_notification)
        actions.addWidget(save)
        actions.addWidget(test)
        test_layout.addLayout(actions)
        self.notification_test_result = QLabel("No test sent yet.")
        self.notification_test_result.setObjectName("notificationTestResult")
        self.notification_test_result.setWordWrap(True)
        test_layout.addWidget(self.notification_test_result)
        layout.addWidget(test_card)
        layout.addStretch(1)
        return page

    def _save_notification_preferences(self) -> None:
        self.database.set_setting(
            "desktop_notifications_enabled", "1" if self.desktop_notifications_enabled.isChecked() else "0",
            scope="user", scope_id=self.session.user_id,
        )
        self.database.set_setting(
            "in_app_notifications_enabled", "1" if self.in_app_notifications_enabled.isChecked() else "0",
            scope="user", scope_id=self.session.user_id,
        )
        for key, check in self.notification_rule_checks.items():
            self.database.set_setting(key, "1" if check.isChecked() else "0", scope="business", scope_id=self.session.business_id)
        self.notification_preferences_message.setText("Notification preferences saved.")
        self.notification_test_result.setText("Preferences saved. Use ‘Send test notification’ to check delivery.")

    def _test_notification(self) -> None:
        if not self.on_test_notification:
            self.notification_test_result.setText("Test handler is not connected to the desktop shell.")
            return
        try:
            result = self.on_test_notification()
        except Exception as exc:
            result = f"Test notification failed: {exc}"
        self.notification_test_result.setText(str(result or "Test notification request completed."))

    def _build_user_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(3, 15, 3, 3)
        scroll = QWidget()
        layout = QVBoxLayout(scroll)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card = CardFrame("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(16)
        card_layout.addWidget(self._card_heading("Personal workspace profile", "Choose the name and profile photo shown in the KoshFlow dock. Your access role is assigned by the workspace and cannot be self-elevated here."))

        row = QHBoxLayout()
        row.setSpacing(18)
        self.avatar_preview = QLabel()
        self.avatar_preview.setFixedSize(92, 92)
        self.avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_preview.setStyleSheet("background:#C9E86A;color:#171916;border:1px solid #D7F08D;border-radius:46px;font-size:22px;font-weight:800;")
        row.addWidget(self.avatar_preview, 0, Qt.AlignmentFlag.AlignTop)
        picture_actions = QVBoxLayout()
        picture_actions.setSpacing(8)
        choose = HoverButton("Choose profile picture…")
        choose.setIcon(svg_icon("image", self._icon_color(), 16))
        choose.clicked.connect(self._choose_profile_picture)
        remove = HoverButton("Remove picture")
        remove.clicked.connect(self._remove_profile_picture)
        picture_actions.addWidget(choose, 0, Qt.AlignmentFlag.AlignLeft)
        picture_actions.addWidget(remove, 0, Qt.AlignmentFlag.AlignLeft)
        picture_actions.addWidget(muted_label("PNG, JPG or WebP. The photo is saved locally on this device."))
        picture_actions.addStretch(1)
        row.addLayout(picture_actions, 1)
        card_layout.addLayout(row)

        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        current_name = self.database.get_setting("profile_display_name", self.session.display_name, scope="user", scope_id=self.session.user_id) or self.session.display_name
        self.user_display_name = make_line_edit("How your name should appear")
        self.user_display_name.setText(current_name)
        self.user_display_name.textChanged.connect(self._refresh_avatar_preview)
        self.username_value = QLabel(self.session.username)
        self.username_value.setObjectName("pill")
        self.role_value = QLabel(self.session.role.replace("_", " ").title())
        self.role_value.setObjectName("pill")
        form.addWidget(labeled_field("DISPLAY NAME", self.user_display_name), 0, 0, 1, 2)
        form.addWidget(labeled_field("USERNAME", self.username_value), 1, 0)
        form.addWidget(labeled_field("ASSIGNED ROLE", self.role_value), 1, 1)
        card_layout.addLayout(form)
        note = muted_label("Role changes are managed by the workspace owner/admin to keep permissions and financial access controlled.")
        card_layout.addWidget(note)
        actions = QHBoxLayout()
        self.user_profile_message = muted_label("")
        actions.addWidget(self.user_profile_message, 1)
        save = HoverButton("Save profile")
        save.setObjectName("primaryButton")
        save.setIcon(svg_icon("check", "#171916", 16))
        save.clicked.connect(self._save_user_profile)
        actions.addWidget(save)
        card_layout.addLayout(actions)
        layout.addWidget(card)
        layout.addStretch(1)
        outer.addWidget(scroll)
        self._refresh_avatar_preview()
        return page

    def _profile_picture_destination(self) -> Path:
        profile_dir = get_data_dir() / "profiles"
        profile_dir.mkdir(parents=True, exist_ok=True)
        safe_user = "".join(ch for ch in self.session.user_id if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_") or "user"
        return profile_dir / f"{safe_user}.png"

    def _choose_profile_picture(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Choose profile picture", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not filename:
            return
        image = QPixmap(filename)
        if image.isNull():
            QMessageBox.warning(self, "Unsupported image", "KoshFlow could not read that image. Choose a valid PNG, JPG or WebP file.")
            return
        if image.width() > 6000 or image.height() > 6000:
            QMessageBox.warning(self, "Image too large", "Choose an image with dimensions no larger than 6000 × 6000 pixels.")
            return
        image = image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        image = image.copy((image.width() - 512) // 2, (image.height() - 512) // 2, 512, 512)
        destination = self._profile_picture_destination()
        if not image.save(str(destination), "PNG"):
            QMessageBox.warning(self, "Could not save image", "KoshFlow could not save the selected picture to its local profile folder.")
            return
        self.database.set_setting("profile_picture_path", str(destination), scope="user", scope_id=self.session.user_id)
        self._refresh_avatar_preview()
        if self.on_user_profile_updated:
            self.on_user_profile_updated()
        self.user_profile_message.setText("Profile picture saved on this device.")

    def _remove_profile_picture(self) -> None:
        self.database.set_setting("profile_picture_path", "", scope="user", scope_id=self.session.user_id)
        self._refresh_avatar_preview()
        if self.on_user_profile_updated:
            self.on_user_profile_updated()
        self.user_profile_message.setText("Profile picture removed.")

    def _refresh_avatar_preview(self) -> None:
        if not hasattr(self, "avatar_preview"):
            return
        name = (self.user_display_name.text().strip() if hasattr(self, "user_display_name") else "") or self.session.display_name or self.session.username
        path = self.database.get_setting("profile_picture_path", "", scope="user", scope_id=self.session.user_id) or ""
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        if not pixmap.isNull():
            pixmap = pixmap.scaled(184, 184, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            image = QPixmap(184, 184)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            path_clip = QPainterPath()
            path_clip.addEllipse(0, 0, 184, 184)
            painter.setClipPath(path_clip)
            painter.drawPixmap(0, 0, pixmap.copy((pixmap.width()-184)//2, (pixmap.height()-184)//2, 184, 184))
            painter.end()
            image.setDevicePixelRatio(2.0)
            self.avatar_preview.setPixmap(image)
            self.avatar_preview.setText("")
        else:
            initials = "".join(part[0] for part in name.split()[:2]).upper() or "U"
            self.avatar_preview.setPixmap(QPixmap())
            self.avatar_preview.setText(initials[:2])

    def _save_user_profile(self) -> None:
        name = self.user_display_name.text().strip()
        if not name:
            self.user_profile_message.setText("Enter a display name before saving.")
            return
        self.database.set_setting("profile_display_name", name, scope="user", scope_id=self.session.user_id)
        self.user_profile_message.setText("Profile saved.")
        self._refresh_avatar_preview()
        if self.on_user_profile_updated:
            self.on_user_profile_updated()

    def _build_profile_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(3, 15, 3, 3)
        layout.setSpacing(14)

        card = CardFrame("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(16)
        card_layout.addWidget(self._card_heading("Business identity", "These details will be used by future invoices and reports."))

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        definitions = [
            ("legal_name", "LEGAL / REGISTERED NAME *", "e.g. Example Traders", 0, 0, 1, 2),
            ("trade_name", "TRADING NAME", "Optional public-facing name", 1, 0, 1, 1),
            ("business_type", "BUSINESS TYPE", "", 1, 1, 1, 1),
            ("phone", "PHONE", "Business contact number", 2, 0, 1, 1),
            ("email", "EMAIL", "Business email address", 2, 1, 1, 1),
            ("address", "ADDRESS", "Street / building", 3, 0, 1, 2),
            ("city", "CITY", "City or town", 4, 0, 1, 1),
            ("state", "STATE / UT", "State or Union Territory", 4, 1, 1, 1),
            ("pincode", "PINCODE", "6-digit postal code", 5, 0, 1, 1),
            ("gstin", "GSTIN", "Optional unless applicable", 5, 1, 1, 1),
            ("pan", "PAN", "Optional unless applicable", 6, 0, 1, 1),
        ]
        for key, label_text, placeholder, row, col, row_span, col_span in definitions:
            if key == "business_type":
                widget = make_combo(BUSINESS_TYPES)
                widget.setCurrentText(self.profile.get(key, "Other") or "Other")
            else:
                widget = make_line_edit(placeholder)
                widget.setText(self.profile.get(key, ""))
            self._fields[key] = widget
            grid.addWidget(labeled_field(label_text, widget), row, col, row_span, col_span)
        card_layout.addLayout(grid)

        self.profile_message = QLabel("")
        self.profile_message.setWordWrap(True)
        self.profile_message.setObjectName("muted")
        actions = QHBoxLayout()
        actions.addWidget(self.profile_message, 1)
        save = HoverButton("Save business profile")
        save.setObjectName("primaryButton")
        save.setIcon(svg_icon("file-check", "#171916", 16))
        save.clicked.connect(self._save_profile)
        actions.addWidget(save)
        card_layout.addLayout(actions)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_invoice_settings_tab(self) -> QWidget:
        """Business logo, public contact and payment details used on generated invoices."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(3, 15, 3, 8)
        layout.setSpacing(14)
        self.invoice_profile = load_invoice_profile(self.database, self.session.business_id)
        self.invoice_fields: dict[str, QLineEdit] = {}

        identity_card = CardFrame("settingsCard")
        identity_layout = QVBoxLayout(identity_card)
        identity_layout.setContentsMargins(22, 20, 22, 20)
        identity_layout.setSpacing(12)
        identity_layout.addWidget(self._card_heading(
            "Invoice identity",
            "These optional details are printed on generated PDFs. Your legal name, address, phone, email and GSTIN come from Business profile.",
        ))
        asset_row = QHBoxLayout()
        asset_row.setSpacing(12)
        self.invoice_logo_label = QLabel(Path(self.invoice_profile.get("logo_path") or "").name or "No business logo selected")
        self.invoice_logo_label.setObjectName("pill")
        self.invoice_logo_label.setWordWrap(True)
        self.invoice_logo_label.setMinimumWidth(0)
        choose_logo = HoverButton("Choose business logo…")
        choose_logo.setIcon(svg_icon("image", self._icon_color(), 16))
        choose_logo.clicked.connect(self._choose_invoice_logo)
        asset_row.addWidget(self.invoice_logo_label, 1)
        asset_row.addWidget(choose_logo)
        identity_layout.addLayout(asset_row)

        website = make_line_edit("https://example.com")
        website.setText(str(self.invoice_profile.get("website") or ""))
        self.invoice_fields["website"] = website
        identity_layout.addWidget(labeled_field("BUSINESS WEBSITE (OPTIONAL)", website))
        layout.addWidget(identity_card)

        payment_card = CardFrame("settingsCard")
        payment_layout = QVBoxLayout(payment_card)
        payment_layout.setContentsMargins(22, 20, 22, 20)
        payment_layout.setSpacing(12)
        payment_layout.addWidget(self._card_heading(
            "Payment details on the bill",
            "Choose the bank, UPI ID and/or QR code that should appear in invoice PDFs and their previews.",
        ))
        bank_grid = QGridLayout()
        bank_grid.setHorizontalSpacing(14)
        bank_grid.setVerticalSpacing(10)
        bank_definitions = [
            ("bank_account_name", "ACCOUNT HOLDER NAME", "Name on the bank account", 0, 0),
            ("bank_name", "BANK NAME", "Bank name", 0, 1),
            ("account_number", "ACCOUNT NUMBER", "Bank account number", 1, 0),
            ("ifsc", "IFSC CODE", "e.g. SBIN0000000", 1, 1),
            ("branch", "BRANCH (OPTIONAL)", "Branch name", 2, 0),
            ("upi_id", "UPI ID", "business@upi", 2, 1),
        ]
        for key, caption, placeholder, row, column in bank_definitions:
            field = make_line_edit(placeholder)
            field.setText(str(self.invoice_profile.get(key) or ""))
            self.invoice_fields[key] = field
            bank_grid.addWidget(labeled_field(caption, field), row, column)
        bank_grid.setColumnStretch(0, 1)
        bank_grid.setColumnStretch(1, 1)
        payment_layout.addLayout(bank_grid)

        self.show_bank_details = QCheckBox("Include bank transfer details when provided")
        self.show_upi_details = QCheckBox("Print UPI ID when provided")
        self.show_qr_code = QCheckBox("Include payment QR image when provided")
        for checkbox, key in ((self.show_bank_details, "show_bank"), (self.show_upi_details, "show_upi"), (self.show_qr_code, "show_qr")):
            checkbox.setChecked(bool(self.invoice_profile.get(key, True)))
            checkbox.toggled.connect(self._refresh_invoice_design_preview)
            payment_layout.addWidget(checkbox)

        qr_row = QHBoxLayout()
        self.invoice_qr_label = QLabel(Path(self.invoice_profile.get("qr_code_path") or "").name or "No payment QR selected")
        self.invoice_qr_label.setObjectName("pill")
        self.invoice_qr_label.setWordWrap(True)
        self.invoice_qr_label.setMinimumWidth(0)
        choose_qr = HoverButton("Choose payment QR…")
        choose_qr.setIcon(svg_icon("qr-code", self._icon_color(), 16))
        choose_qr.clicked.connect(self._choose_invoice_qr)
        qr_row.addWidget(self.invoice_qr_label, 1)
        qr_row.addWidget(choose_qr)
        payment_layout.addLayout(qr_row)
        layout.addWidget(payment_card)

        preview_card = CardFrame("settingsCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(18, 16, 18, 16)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(self._card_heading(
            "Invoice header and payment preview",
            "This preview updates as you edit the fields and reflects the saved theme used by PDF Studio.",
        ))
        self.invoice_design_preview = InvoiceThemePreview(compact=True)
        self.invoice_design_preview.setMinimumHeight(370)
        preview_layout.addWidget(self.invoice_design_preview)
        layout.addWidget(preview_card)

        self.invoice_profile_message = QLabel("")
        self.invoice_profile_message.setObjectName("muted")
        save_row = QHBoxLayout()
        save_row.addWidget(self.invoice_profile_message, 1)
        save_payment = HoverButton("Save invoice and payment details")
        save_payment.setObjectName("primaryButton")
        save_payment.setIcon(svg_icon("file-check", "#171916", 16))
        save_payment.clicked.connect(self._save_invoice_profile)
        save_row.addWidget(save_payment)
        layout.addLayout(save_row)

        for field in self.invoice_fields.values():
            field.textChanged.connect(self._refresh_invoice_design_preview)
        default_template = {
            "template_name": "KoshFlow Classic", "accent_color": "#C9E86A",
            "layout_json": "{\"design_style\":\"classic\"}", "font_size": 9,
        }
        self.invoice_design_preview.set_template(default_template)
        self._refresh_invoice_design_preview()
        return page

    def _invoice_profile_values(self) -> dict[str, object]:
        values: dict[str, object] = {key: field.text().strip() for key, field in self.invoice_fields.items()}
        values.update({
            "logo_path": str(self.invoice_profile.get("logo_path") or ""),
            "qr_code_path": str(self.invoice_profile.get("qr_code_path") or ""),
            "show_bank": self.show_bank_details.isChecked(),
            "show_upi": self.show_upi_details.isChecked(),
            "show_qr": self.show_qr_code.isChecked(),
        })
        return values

    def _refresh_invoice_design_preview(self, *_args) -> None:
        preview = getattr(self, "invoice_design_preview", None)
        if preview is not None:
            preview.set_invoice_identity(self.profile, self._invoice_profile_values())

    def _copy_invoice_asset(self, kind: str, source: str) -> str:
        origin = Path(source).expanduser().resolve()
        if not origin.is_file() or origin.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Choose a valid PNG or JPEG image.")
        from koshflow.config import get_data_dir
        destination_dir = get_data_dir() / "business_assets" / self.session.business_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{kind}{origin.suffix.lower()}"
        if origin != destination:
            shutil.copy2(origin, destination)
        return str(destination)

    def _choose_invoice_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose business logo", "", "Image files (*.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            self.invoice_profile["logo_path"] = self._copy_invoice_asset("business-logo", path)
            self.invoice_logo_label.setText(Path(path).name)
            self._refresh_invoice_design_preview()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Logo not selected", str(exc))

    def _choose_invoice_qr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose payment QR image", "", "Image files (*.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            self.invoice_profile["qr_code_path"] = self._copy_invoice_asset("payment-qr", path)
            self.invoice_qr_label.setText(Path(path).name)
            self._refresh_invoice_design_preview()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "QR image not selected", str(exc))

    def _save_invoice_profile(self) -> None:
        try:
            self.invoice_profile = save_invoice_profile(
                self.database, self.session.business_id, self._invoice_profile_values(),
            )
        except Exception as exc:
            self.invoice_profile_message.setText(f"Could not save invoice settings: {exc}")
            return
        self.invoice_profile_message.setText("Invoice branding and payment details saved locally.")
        self._refresh_invoice_design_preview()

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsAppearancePage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setAutoFillBackground(True)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(3, 15, 3, 3)
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setObjectName("settingsScrollViewport")
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scroll.viewport().setAutoFillBackground(True)
        content = QWidget()
        content.setObjectName("settingsAppearanceContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        theme_card = CardFrame("settingsCard")
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(22, 20, 22, 20)
        theme_layout.setSpacing(12)
        theme_layout.addWidget(self._card_heading("Appearance", "Tune the entire workspace for your display. Your choices are saved locally to your user profile."))
        choices = QHBoxLayout()
        choices.setSpacing(12)
        self.light_button = HoverButton("☼   Light mode")
        self.dark_button = HoverButton("◐   Dark mode")
        self.light_button.setObjectName("themeModeButton")
        self.dark_button.setObjectName("themeModeButton")
        for button in (self.light_button, self.dark_button):
            button.setMinimumHeight(48)
            button.setCheckable(True)
            choices.addWidget(button)
        self.light_button.clicked.connect(lambda: self._choose_theme("light"))
        self.dark_button.clicked.connect(lambda: self._choose_theme("dark"))
        self._update_theme_buttons()
        theme_layout.addLayout(choices)

        palette_row = QHBoxLayout()
        palette_copy = QVBoxLayout()
        palette_copy.addWidget(QLabel("Signature accent · Citron lime"))
        palette_copy.addWidget(muted_label("60% white · 30% charcoal · 10% citron lime. The accent is reserved for primary actions and meaningful emphasis."))
        swatch = QFrame()
        swatch.setFixedSize(72, 48)
        swatch.setStyleSheet("background:#C9E86A;border:1px solid #B7D75A;border-radius:12px;")
        palette_row.addLayout(palette_copy, 1)
        palette_row.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)
        theme_layout.addLayout(palette_row)
        layout.addWidget(theme_card)

        controls_card = CardFrame("settingsCard")
        controls = QVBoxLayout(controls_card)
        controls.setContentsMargins(22, 20, 22, 20)
        controls.setSpacing(14)
        controls.addWidget(self._card_heading("Typography & display scaling", "Font selection, app-wide UI scaling and control sizing are applied consistently across KoshFlow."))

        self.font_combo = make_combo(["System default", "Segoe UI", "Inter", "Noto Sans", "Arial"])
        self.font_combo.setCurrentText(self.database.get_setting("font_family", "Segoe UI", scope="user", scope_id=self.session.user_id) or "Segoe UI")
        self.font_combo.currentTextChanged.connect(self._refresh_appearance_preview)
        controls.addWidget(labeled_field("INTERFACE FONT", self.font_combo, "Unavailable fonts fall back to the operating system's next suitable font."))

        scale_row = QHBoxLayout()
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(80, 125)
        try:
            initial_scale = int(self.database.get_setting("ui_scale_percent", "100", scope="user", scope_id=self.session.user_id) or "100")
        except ValueError:
            initial_scale = 100
        self.scale_slider.setValue(min(125, max(80, initial_scale)))
        self.scale_value = QLabel(f"{self.scale_slider.value()}%")
        self.scale_value.setObjectName("pill")
        self.scale_slider.valueChanged.connect(lambda value: (self.scale_value.setText(f"{value}%"), self._refresh_appearance_preview()))
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_value)
        controls.addWidget(labeled_field("UI SCALE · 80–125%", self._wrap_layout(scale_row), "Scale text, spacing, borders and control dimensions for laptop or high-DPI displays."))

        self.control_size_combo = make_combo(["Compact", "Comfortable", "Roomy"])
        current_size = self.database.get_setting("control_size", "comfortable", scope="user", scope_id=self.session.user_id) or "comfortable"
        self.control_size_combo.setCurrentText({"compact":"Compact", "comfortable":"Comfortable", "roomy":"Roomy"}.get(current_size, "Comfortable"))
        self.control_size_combo.currentTextChanged.connect(self._refresh_appearance_preview)
        controls.addWidget(labeled_field("CONTROL SIZE", self.control_size_combo, "Adjust the default height of input fields and buttons. Individual forms can still adapt to their content."))

        self.control_width_combo = make_combo(["Compact", "Balanced", "Fluid"])
        current_width = self.database.get_setting("control_width", "fluid", scope="user", scope_id=self.session.user_id) or "fluid"
        self.control_width_combo.setCurrentText({"compact":"Compact", "balanced":"Balanced", "fluid":"Fluid"}.get(current_width, "Fluid"))
        self.control_width_combo.currentTextChanged.connect(self._refresh_appearance_preview)
        controls.addWidget(labeled_field("CONTROL WIDTH", self.control_width_combo, "Compact keeps entry fields narrow, Balanced caps them for long forms, and Fluid lets each page use its available width."))

        layout.addWidget(controls_card)

        preview_card = CardFrame("settingsCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(22, 20, 22, 20)
        preview_layout.setSpacing(12)
        preview_layout.addWidget(self._card_heading("Live preview", "This sample updates as you change the font, scale and control size. Apply when it looks right."))
        self.appearance_preview = QFrame()
        self.appearance_preview.setObjectName("appearancePreview")
        self.appearance_preview.setMinimumHeight(150)
        preview_inner = QVBoxLayout(self.appearance_preview)
        preview_inner.setContentsMargins(16, 14, 16, 14)
        preview_inner.setSpacing(9)
        preview_header = QHBoxLayout()
        self.preview_title = QLabel("Your business at a glance")
        self.preview_title.setObjectName("sectionTitle")
        self.preview_pill = QLabel("LIVE PREVIEW")
        self.preview_pill.setObjectName("accentPill")
        preview_header.addWidget(self.preview_title, 1)
        preview_header.addWidget(self.preview_pill)
        preview_inner.addLayout(preview_header)
        self.preview_body = QLabel("Invoices, stock and customer activity stay readable at your chosen scale.")
        self.preview_body.setWordWrap(True)
        self.preview_body.setObjectName("muted")
        preview_inner.addWidget(self.preview_body)
        preview_actions = QHBoxLayout()
        self.preview_input = QLineEdit("Sample input field")
        self.preview_input.setReadOnly(True)
        self.preview_button = QPushButton("Primary action")
        self.preview_button.setObjectName("primaryButton")
        preview_actions.addWidget(self.preview_input, 1)
        preview_actions.addWidget(self.preview_button)
        preview_inner.addLayout(preview_actions)
        preview_layout.addWidget(self.appearance_preview)
        actions = QHBoxLayout()
        self.appearance_message = muted_label("")
        actions.addWidget(self.appearance_message, 1)
        reset = HoverButton("Reset defaults")
        reset.clicked.connect(self._reset_appearance)
        actions.addWidget(reset)
        apply_button = HoverButton("Apply appearance")
        apply_button.setObjectName("primaryButton")
        apply_button.setIcon(svg_icon("check", "#171916", 16))
        apply_button.clicked.connect(self._apply_appearance)
        actions.addWidget(apply_button)
        preview_layout.addLayout(actions)
        layout.addWidget(preview_card)
        layout.addStretch(1)
        self._refresh_appearance_preview()
        return page

    @staticmethod
    def _wrap_layout(layout: QHBoxLayout) -> QWidget:
        wrapper = QWidget()
        wrapper.setLayout(layout)
        return wrapper

    def _refresh_appearance_preview(self, *_args) -> None:
        if not hasattr(self, "preview_title"):
            return
        from koshflow.ui.styles import tokens
        palette = tokens(self.theme)
        font = self.font_combo.currentText() if hasattr(self, "font_combo") else "Segoe UI"
        font = "Segoe UI" if font == "System default" else font
        scale = self.scale_slider.value() / 100 if hasattr(self, "scale_slider") else 1.0
        density = self.control_size_combo.currentText().casefold() if hasattr(self, "control_size_combo") else "comfortable"
        height = {"compact":30, "comfortable":38, "roomy":46}.get(density, 38)
        self.preview_title.setStyleSheet(f"font-family:'{font}';font-size:{round(17*scale)}px;font-weight:750;color:{palette['text']};")
        self.preview_body.setStyleSheet(f"font-family:'{font}';font-size:{round(12*scale)}px;color:{palette['muted']};")
        width_mode = self.control_width_combo.currentText().casefold() if hasattr(self, "control_width_combo") else "fluid"
        preview_width = {"compact": 250, "balanced": 420, "fluid": 1400}.get(width_mode, 1400)
        self.preview_input.setMaximumWidth(max(150, round(preview_width * scale)))
        self.preview_input.setStyleSheet(f"font-family:'{font}';font-size:{round(12*scale)}px;min-height:{round(height*scale)}px;background:{palette['input']};color:{palette['text']};border:1px solid {palette['border']};border-radius:9px;padding:5px 10px;")
        self.preview_button.setStyleSheet(f"font-family:'{font}';font-size:{round(12*scale)}px;min-height:{round(height*scale)}px;background:{palette['accent']};color:#171916;border:1px solid {palette['accent']};border-radius:9px;padding:5px 14px;font-weight:750;")
        self.appearance_preview.setStyleSheet(f"QFrame#appearancePreview{{background:{palette['surface_alt']};border:1px solid {palette['border']};border-radius:13px;}}")

    def _apply_appearance(self) -> None:
        font = self.font_combo.currentText()
        scale = self.scale_slider.value()
        control_size = {"Compact":"compact", "Comfortable":"comfortable", "Roomy":"roomy"}.get(self.control_size_combo.currentText(), "comfortable")
        control_width = {"Compact":"compact", "Balanced":"balanced", "Fluid":"fluid"}.get(self.control_width_combo.currentText(), "fluid")
        self.database.set_setting("font_family", font, scope="user", scope_id=self.session.user_id)
        self.database.set_setting("ui_scale_percent", str(scale), scope="user", scope_id=self.session.user_id)
        self.database.set_setting("control_size", control_size, scope="user", scope_id=self.session.user_id)
        self.database.set_setting("control_width", control_width, scope="user", scope_id=self.session.user_id)
        if self.on_appearance_updated:
            self.on_appearance_updated(font, scale, control_size, control_width)
        self.appearance_message.setText("Appearance saved and applied.")

    def _reset_appearance(self) -> None:
        self.font_combo.setCurrentText("Segoe UI")
        self.scale_slider.setValue(100)
        self.control_size_combo.setCurrentText("Comfortable")
        self.control_width_combo.setCurrentText("Fluid")
        self._apply_appearance()

    def _build_backup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(3, 15, 3, 3)
        layout.setSpacing(14)

        card = CardFrame("settingsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(12)
        card_layout.addWidget(self._card_heading("Local data vault", "Your business database is stored on this device. Keep an additional copy somewhere safe."))

        path_label = QLabel(str(self.database.path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setObjectName("pill")
        card_layout.addWidget(path_label)
        stat_row = QHBoxLayout()
        stat_row.addWidget(self._status_tile("Database", "SQLite · Local", "database"), 1)
        stat_row.addWidget(self._status_tile("Credentials", "Argon2 password hashes", "shield"), 1)
        stat_row.addWidget(self._status_tile("Backup folder", str(self.backup_manager.backup_dir), "file-check"), 1)
        card_layout.addLayout(stat_row)

        security_note = QLabel("Backup files are standard SQLite files in this foundation release. Protect the app data folder with your operating-system account and disk encryption; encrypted backups are a production-hardening item.")
        security_note.setObjectName("muted")
        security_note.setWordWrap(True)
        security_note.setStyleSheet("font-size:10px;")
        card_layout.addWidget(security_note)

        actions = QHBoxLayout()
        create = HoverButton("Create backup now")
        create.setObjectName("primaryButton")
        create.setIcon(svg_icon("database", "#171916", 16))
        create.clicked.connect(self._create_backup)
        restore = HoverButton("Restore from backup…")
        restore.setIcon(svg_icon("file-check", self._icon_color(), 16))
        restore.setEnabled(has_permission(self.session.role, "backup.restore"))
        restore.setToolTip("Restore a validated backup" if restore.isEnabled() else "Your role cannot restore backups")
        create.setEnabled(has_permission(self.session.role, "backup.create"))
        create.setToolTip("Create a verified local backup" if create.isEnabled() else "Your role cannot create backups")
        restore.clicked.connect(self._restore_backup)
        actions.addWidget(create)
        actions.addWidget(restore)
        actions.addStretch(1)
        card_layout.addLayout(actions)

        self.backup_message = QLabel("")
        self.backup_message.setWordWrap(True)
        self.backup_message.setObjectName("muted")
        card_layout.addWidget(self.backup_message)
        layout.addWidget(card)

        listing = CardFrame("settingsCard")
        listing_layout = QVBoxLayout(listing)
        listing_layout.setContentsMargins(22, 18, 22, 16)
        listing_layout.addWidget(self._card_heading("Recent backups", "Only verified KoshFlow backup files are listed here."))
        self.backup_list = QVBoxLayout()
        listing_layout.addLayout(self.backup_list)
        self._refresh_backup_list()
        layout.addWidget(listing)
        layout.addStretch(1)
        return page

    def _card_heading(self, title_text: str, subtitle_text: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel(title_text)
        title.setObjectName("sectionTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return widget

    def _status_tile(self, title: str, value: str, icon_name: str) -> QWidget:
        tile = QFrame()
        tile.setObjectName("softPanel")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(12, 11, 12, 11)
        icon = QLabel()
        icon.setPixmap(svg_icon(icon_name, self._icon_color(), 18).pixmap(18, 18))
        heading = QLabel(title)
        heading.setObjectName("muted")
        heading.setStyleSheet("font-size:10px;")
        value_label = QLabel(value)
        value_label.setWordWrap(True)
        value_label.setStyleSheet("font-size:11px;font-weight:650;")
        layout.addWidget(icon)
        layout.addWidget(heading)
        layout.addWidget(value_label)
        return tile

    def _icon_color(self) -> str:
        return "#F1F2EC" if self.theme == "dark" else "#171916"

    def _update_theme_buttons(self) -> None:
        self.light_button.setChecked(self.theme == "light")
        self.dark_button.setChecked(self.theme == "dark")
        for button, is_selected in ((self.light_button, self.theme == "light"), (self.dark_button, self.theme == "dark")):
            button.setProperty("selectedTheme", is_selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _choose_theme(self, theme: str) -> None:
        self.theme = theme
        self.database.set_setting("theme", theme)
        self.on_theme_changed(theme)
        self._update_theme_buttons()
        self._refresh_appearance_preview()

    def _save_profile(self) -> None:
        fields: dict[str, str] = {}
        for key, widget in self._fields.items():
            fields[key] = widget.currentText() if hasattr(widget, "currentText") else widget.text()
        try:
            self.profile = self.business_service.update_profile(self.session, fields)
        except BusinessProfileError as exc:
            self.profile_message.setText(str(exc))
            self.profile_message.setStyleSheet("color:#7A6D28;font-size:11px;font-weight:600;")
            return
        self.profile_message.setText("Business profile saved.")
        self.profile_message.setStyleSheet("color:#718B2E;font-size:11px;font-weight:650;")
        self.on_profile_updated(self.profile)

    def _create_backup(self) -> None:
        try:
            path = self.backup_manager.create_backup()
        except BackupError as exc:
            self.backup_message.setText(str(exc))
            self.backup_message.setStyleSheet("color:#7A6D28;font-size:11px;")
            return
        self.backup_message.setText(f"Backup verified successfully: {path.name}")
        self.backup_message.setStyleSheet("color:#718B2E;font-size:11px;font-weight:650;")
        self._refresh_backup_list()

    def _restore_backup(self) -> None:
        candidate, _ = QFileDialog.getOpenFileName(
            self, "Restore KoshFlow backup", str(self.backup_manager.backup_dir),
            "KoshFlow backups (*.sqlite3 *.db);;All files (*)",
        )
        if not candidate:
            return
        confirmation = QMessageBox(self)
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setWindowTitle("Restore this backup?")
        confirmation.setText(
            "Restoring replaces the current local database with the selected backup. "
            "Create a fresh backup first if you need to preserve the current state. "
            "KoshFlow will close after a successful restore so the restored workspace can be loaded cleanly.\n\n"
            f"Selected file: {Path(candidate).name}"
        )
        restore_button = confirmation.addButton("Restore backup", QMessageBox.ButtonRole.AcceptRole)
        confirmation.addButton(QMessageBox.StandardButton.Cancel)
        confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
        confirmation.exec()
        if confirmation.clickedButton() is not restore_button:
            return
        try:
            self.backup_manager.restore_backup(candidate)
        except BackupError as exc:
            QMessageBox.warning(self, "Restore failed", str(exc))
            return
        QMessageBox.information(self, "Backup restored", "The backup passed validation. KoshFlow will now close; reopen the application to continue from the restored workspace.")
        app = QApplication.instance()
        if app:
            app.quit()

    def _refresh_backup_list(self) -> None:
        if not hasattr(self, "backup_list"):
            return
        while self.backup_list.count():
            item = self.backup_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        paths = self.backup_manager.list_backups()[:5]
        if not paths:
            empty = QLabel("No backups yet. Create one before making major changes or moving this workspace to another device.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.backup_list.addWidget(empty)
            return
        for path in paths:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 4, 0, 4)
            icon = QLabel()
            icon.setPixmap(svg_icon("file-check", self._icon_color(), 17).pixmap(17, 17))
            names = QVBoxLayout()
            name = QLabel(path.name)
            name.setStyleSheet("font-weight:650;font-size:11px;")
            date = datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo(DEFAULT_TIMEZONE)).strftime("%d %b %Y, %I:%M %p IST")
            meta = QLabel(f"{path.stat().st_size / 1024:,.0f} KB  ·  {date}")
            meta.setObjectName("muted")
            meta.setStyleSheet("font-size:10px;")
            names.addWidget(name)
            names.addWidget(meta)
            row_layout.addWidget(icon)
            row_layout.addLayout(names, 1)
            self.backup_list.addWidget(row)
