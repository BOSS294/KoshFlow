"""Static validation for the dashboard blueprint without requiring a Qt runtime."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "koshflow" / "ui" / "pages" / "dashboard_page.py"


def _class_method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)


def test_dashboard_contains_seventeen_configurable_sections() -> None:
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    section_node = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "SECTION_META"
    )
    sections = ast.literal_eval(section_node.value)
    assert len(sections) == 17
    assert len(set(sections)) == 17


def test_every_dashboard_section_has_a_builder() -> None:
    tree = ast.parse(DASHBOARD_PATH.read_text(encoding="utf-8"))
    body_method = _class_method(tree, "DashboardPage", "_build_section_body")
    builders_node = next(
        node for node in ast.walk(body_method)
        if isinstance(node, ast.Dict)
        and all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys)
    )
    builder_map = {key.value: value.attr for key, value in zip(builders_node.keys, builders_node.values)}
    class_methods = {
        node.name for node in next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DashboardPage").body
        if isinstance(node, ast.FunctionDef)
    }
    assert set(builder_map) == set(ast.literal_eval(next(
        node.value for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "SECTION_META"
    )))
    assert all(method in class_methods for method in builder_map.values())


def test_dashboard_does_not_define_simulated_financial_series_or_preview_badge() -> None:
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned_names = {
        target.id for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert "SAMPLE_SERIES" not in assigned_names
    assert "SAMPLE_METRICS" not in assigned_names
    assert "SAMPLE_CASHFLOW" not in assigned_names
    assert 'QLabel("PREVIEW")' not in source
    assert '"sample_mode"' not in source or 'Kept only so older saved preferences migrate cleanly' in source


def test_dashboard_does_not_render_workspace_status_strip_or_removed_services_module() -> None:
    source = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert 'outer.addWidget(self._build_workspace_strip())' not in source
    assert '"services": self._build_services' not in source
    assert '"business": self._build_business_snapshot' not in source
    assert '"health": self._build_health' not in source


def test_services_removed_from_navigation_and_reports_added():
    from koshflow.core.permissions import NAV_ITEMS, ROLE_PERMISSIONS
    from koshflow.services.operational_report_service import OperationalReportService

    assert all(item["key"] != "services" and item["label"].casefold() != "services" for item in NAV_ITEMS)
    assert all("services.view" not in permissions for permissions in ROLE_PERMISSIONS.values())
    assert {"Inventory valuation", "Low stock report", "Stock movement register", "Customer balances", "Supplier payables", "Customer payment register", "Supplier payment register"} <= OperationalReportService.REPORTS
