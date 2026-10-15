"""Static regression guards for Qt-only UI defects when PySide6 is unavailable in CI."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_quick_billing_has_no_stale_saved_customer_selector_or_checkbox():
    source = read_source("koshflow/ui/pages/contact_pages.py")
    assert "self.save_customer.setWordWrap" not in source
    assert "self.save_customer.setSizePolicy" not in source
    quick_billing = source.split("class QuickBillingPage(QWidget):", 1)[1]
    assert "self.customer_combo" not in quick_billing
    assert "self.save_customer" not in quick_billing


def test_quick_billing_is_search_first_and_only_renders_added_products_in_sale_cart():
    source = read_source("koshflow/ui/pages/contact_pages.py")
    quick_billing = source.split("class QuickBillingPage(QWidget):", 1)[1]
    assert 'self.search_results = QListWidget()' in quick_billing
    assert 'self.search_results.hide()' in quick_billing
    assert 'if not query:' in quick_billing
    assert 'self.search_empty_state.show()' in quick_billing
    assert 'self.cart_table = _make_table(["Item", "Qty", "Rate", "Tax", "Total"]' in quick_billing
    assert '_make_table(["SKU", "Product", "In stock", "Price", "Tax"]' not in quick_billing
    assert 'self.search_results.itemActivated.connect' in quick_billing
    assert 'self.cart[product_id] = current + quantity' in quick_billing
    assert 'self.quantity_to_add = QDoubleSpinBox()' in quick_billing
    assert 'self.quantity_to_add.setValue(1.0)' in quick_billing
    assert 'self.cart_table.setCellWidget(row, 1, quantity_widget)' not in quick_billing


def test_quick_billing_customer_fields_are_laid_out_and_inputs_are_theme_overridden():
    source = read_source("koshflow/ui/pages/contact_pages.py")
    styles = read_source("koshflow/ui/styles.py")
    quick_billing = source.split("class QuickBillingPage(QWidget):", 1)[1]
    assert '"quickCustomerName"' in quick_billing
    assert '"quickCustomerPhone"' in quick_billing
    assert 'customer_fields.addWidget(make_customer_field("Customer name"' in quick_billing
    assert 'customer_fields.addWidget(make_customer_field("Phone number"' in quick_billing
    assert 'self.customer_name.setCompleter(self.customer_completer)' in quick_billing
    assert 'self.customer_completer.activated[str].connect(self._select_customer_suggestion)' in quick_billing
    assert 'self._selected_customer_id = ""' in quick_billing
    assert "QWidget#quickBillingPage QLineEdit, QWidget#quickBillingPage QComboBox" in styles
    assert "max-width: 16777215px" in styles
    assert "QListWidget#quickProductResults::item:selected" in styles
    assert "QFrame#quickCustomerPanel" in styles
    assert "QDoubleSpinBox#quickQuantityToAdd" in styles
    assert "QCompleter QAbstractItemView" in styles


def test_layout_managed_controls_do_not_animate_position():
    source = read_source("koshflow/ui/components.py")
    assert 'QPropertyAnimation(self, b"pos"' not in source
    assert "class TooltipIconButton" in source
    assert "class HoverButton" in source
    assert "class CardFrame" in source


def test_billing_workspace_has_responsive_scroll_layout_and_theme_tokens():
    source = read_source("koshflow/ui/pages/billing_hub_page.py")
    styles = read_source("koshflow/ui/styles.py")
    assert "QScrollArea(self)" in source
    assert "def _layout_action_cards" in source
    assert "available_width >= 1760" in source
    assert "QFrame#workspaceActionCard {{ background: {c['surface']}; color: {c['text']};" in styles
    assert "QFrame#actionCardIcon[accent=\"false\"]" in styles
    assert "QLabel#actionCardTitle" in styles
    assert "QLabel#actionCardDescription" in styles


def test_settings_contains_profile_appearance_preview_and_scaling_controls():
    source = read_source("koshflow/ui/pages/settings_page.py")
    assert "def _build_user_tab" in source
    assert "Choose profile picture" in source
    assert "ASSIGNED ROLE" in source
    assert "self.font_combo" in source
    assert "self.scale_slider.setRange(80, 125)" in source
    assert "self.control_width_combo" in source
    assert "def _refresh_appearance_preview" in source


def test_global_light_dark_theme_styles_tabs_and_data_tables():
    source = read_source("koshflow/ui/styles.py")
    assert "QTabBar::tab:selected" in source
    assert "QTableWidget, QTableView, QTreeWidget" in source
    assert "QFrame#settingsCard" in source
    assert "def apply_theme(app: QApplication, theme: str, font_family" in source
    assert "QPlainTextEdit, QSpinBox, QDoubleSpinBox, QAbstractSpinBox" in source


def test_settings_imports_live_preview_input_widget():
    source = read_source("koshflow/ui/pages/settings_page.py")
    imports = source.split("from PySide6.QtWidgets import (", 1)[1].split(")", 1)[0]
    assert "QLineEdit" in imports
    assert 'self.preview_input = QLineEdit("Sample input field")' in source


def test_billing_action_cards_use_layout_safe_frame_and_reflow_kpis():
    source = read_source("koshflow/ui/pages/billing_hub_page.py")
    assert "class ActionCard(QFrame)" in source
    assert "clicked = Signal(bool)" in source
    assert "def _layout_stat_tiles" in source
    assert "self._layout_stat_tiles()" in source
    assert "setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)" in source
    assert "QPushButton" not in source.split("class BillingHubPage", 1)[0].split("class ActionCard", 1)[1]


def test_bill_items_catalog_selector_is_compact_and_totals_are_theme_aware():
    source = read_source("koshflow/ui/pages/bill_editor_page.py")
    styles = read_source("koshflow/ui/styles.py")
    assert 'self.items_table.setObjectName("billItemsTable")' in source
    assert 'self.calculated_totals.setObjectName("billTotalsSummary")' in source
    assert 'product_combo.setObjectName("catalogProductCombo")' in source
    assert "product_combo.setFixedHeight(26)" in source
    assert "product_combo.setMinimumWidth(0)" in source
    assert "QComboBox#catalogProductCombo" in styles
    assert "QLabel#billTotalsSummary" in styles
    assert "palette(alternate-base)" not in source


def test_quick_billing_delete_shortcut_respects_text_field_focus():
    source = read_source("koshflow/ui/pages/contact_pages.py")
    quick_billing = source.split("class QuickBillingPage(QWidget):", 1)[1]
    assert '("Delete", self._remove_selected_if_cart_focused)' in quick_billing
    assert "def _remove_selected_if_cart_focused(self)" in quick_billing
    assert "if focused is self.cart_table:" in quick_billing
    assert "Preserve Delete's normal text-editing behavior" in quick_billing
