"""Accounting workspaces for chart of accounts, journals and core financial reports.

Purpose: Expose Phase 3 double-entry accounting and exportable reports in the desktop app.
Canonical path: koshflow/ui/pages/accounting_pages.py
Project: KoshFlow | Version: 0.6.2
Developer: Mayank Chawdhari AKA BOSS294
Integration: Route `accounts` to AccountingWorkspacePage and `reports` to AccountingReportsPage.
Changelog: v0.6.2 — Expanded the Reports workspace with inventory, stock movements, customer/supplier balances and payment registers, all exportable to PDF/CSV.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView, QInputDialog,
)

from koshflow.core.permissions import has_permission
from koshflow.core.session import Session
from koshflow.core.database import Database
from koshflow.services.accounting_service import AccountingError, AccountingService
from koshflow.services.accounting_export_service import generate_accounting_report_pdf
from koshflow.services.operational_report_service import OperationalReportService
from koshflow.ui.components import CardFrame, HoverButton, muted_label

ACCENT = "#C9E86A"


def _money(value: Any) -> str:
    """Format report amounts without converting accounting values through binary float."""
    try:
        amount = Decimal(str(value if value not in (None, "") else "0")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"₹{amount:,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return "₹0.00"


def _item(value: Any, *, right: bool = False, bold: bool = False) -> QTableWidgetItem:
    cell = QTableWidgetItem(str(value if value is not None else ""))
    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if right:
        cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if bold:
        font = cell.font()
        font.setBold(True)
        cell.setFont(font)
    return cell


def _base_page(root: QVBoxLayout, eyebrow: str, title: str, description: str) -> None:
    crumb = QLabel(eyebrow.upper())
    crumb.setObjectName("eyebrow")
    root.addWidget(crumb)
    heading = QHBoxLayout()
    title_label = QLabel(title)
    title_label.setObjectName("headline")
    title_label.setWordWrap(True)
    heading.addWidget(title_label, 1)
    root.addLayout(heading)
    desc = muted_label(description)
    root.addWidget(desc)


def _build_table(headers: list[str], parent: QWidget | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(260)
    return table


def _fill_table(table: QTableWidget, rows: list[list[Any]], right_columns: set[int] | None = None,
                bold_rows: set[int] | None = None) -> None:
    right_columns = right_columns or set()
    bold_rows = bold_rows or set()
    table.setRowCount(len(rows))
    for ri, row in enumerate(rows):
        for ci, value in enumerate(row):
            table.setItem(ri, ci, _item(value, right=ci in right_columns, bold=ri in bold_rows))
    table.resizeRowsToContents()


class ManualJournalDialog(QDialog):
    def __init__(self, service: AccountingService, business_id: str, actor_user_id: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.business_id = business_id
        self.actor_user_id = actor_user_id
        self.setWindowTitle("New journal entry")
        self.resize(900, 620)
        root = QVBoxLayout(self)
        heading = QLabel("Post a balanced journal")
        heading.setObjectName("sectionTitle")
        root.addWidget(heading)
        tip = muted_label("Enter each debit and credit line. The entry is posted only when both totals match exactly.")
        root.addWidget(tip)
        form = QFormLayout()
        self.entry_date = QDateEdit(QDate.currentDate())
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("yyyy-MM-dd")
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Optional source / reference")
        self.narration = QLineEdit()
        self.narration.setPlaceholderText("Reason for this journal entry")
        form.addRow("Entry date", self.entry_date)
        form.addRow("Reference", self.reference)
        form.addRow("Narration *", self.narration)
        root.addLayout(form)
        self.accounts = service.list_accounts(business_id)
        self.table = _build_table(["Account", "Line description", "Debit (₹)", "Credit (₹)"])
        self.table.setMinimumHeight(260)
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.add_line_button = HoverButton("+ Add line")
        self.remove_line_button = HoverButton("Remove selected")
        self.total_label = QLabel("Debits ₹0.00 · Credits ₹0.00")
        self.total_label.setObjectName("muted")
        actions.addWidget(self.add_line_button)
        actions.addWidget(self.remove_line_button)
        actions.addStretch(1)
        actions.addWidget(self.total_label)
        root.addLayout(actions)
        self.add_line_button.clicked.connect(self.add_line)
        self.remove_line_button.clicked.connect(self.remove_line)
        self.table.itemChanged.connect(lambda *_: self.update_totals())
        self.add_line(); self.add_line()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Post journal")
        buttons.accepted.connect(self.post)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def add_line(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        account = QComboBox()
        for record in self.accounts:
            account.addItem(f"{record['account_code']} · {record['account_name']}", record["account_id"])
        desc = QLineEdit()
        desc.setPlaceholderText("Optional line note")
        debit = QLineEdit("0.00")
        credit = QLineEdit("0.00")
        debit.setMaximumWidth(150); credit.setMaximumWidth(150)
        for field in (debit, credit):
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setPlaceholderText("0.00")
            field.textChanged.connect(self.update_totals)
        self.table.setCellWidget(row, 0, account)
        self.table.setCellWidget(row, 1, desc)
        self.table.setCellWidget(row, 2, debit)
        self.table.setCellWidget(row, 3, credit)
        self.table.setRowHeight(row, 42)
        self.update_totals()

    def remove_line(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for row in rows:
            self.table.removeRow(row)
        self.update_totals()

    def update_totals(self) -> None:
        debit = credit = 0.0
        for row in range(self.table.rowCount()):
            for col, which in ((2, "debit"), (3, "credit")):
                field = self.table.cellWidget(row, col)
                try:
                    number = float(field.text().replace(",", "").strip() or 0)
                except ValueError:
                    number = 0.0
                if which == "debit": debit += number
                else: credit += number
        self.total_label.setText(f"Debits {_money(debit)} · Credits {_money(credit)} · Difference {_money(debit-credit)}")

    def post(self) -> None:
        lines = []
        for row in range(self.table.rowCount()):
            account = self.table.cellWidget(row, 0)
            desc = self.table.cellWidget(row, 1)
            debit = self.table.cellWidget(row, 2)
            credit = self.table.cellWidget(row, 3)
            lines.append({"account_id": account.currentData(), "description": desc.text(),
                          "debit": debit.text().replace(",", "") or "0", "credit": credit.text().replace(",", "") or "0"})
        try:
            entry_id = self.service.create_manual_journal(
                self.business_id, self.actor_user_id, self.entry_date.date().toString("yyyy-MM-dd"),
                self.narration.text(), self.reference.text(), lines,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Journal not posted", str(exc))
            return
        self.setProperty("createdEntryId", entry_id)
        self.accept()


class CreateAccountDialog(QDialog):
    """Dialog for adding a custom chart-of-accounts record."""
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add account")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("e.g. 1150")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Account name")
        self.kind = QComboBox()
        self.kind.addItems(["asset", "liability", "equity", "income", "expense"])
        self.normal_side = QComboBox()
        self.normal_side.addItems(["debit", "credit"])
        self.description = QLineEdit()
        self.description.setPlaceholderText("Optional purpose / reporting note")
        self.kind.currentTextChanged.connect(self._suggest_normal_side)
        form.addRow("Account code *", self.code)
        form.addRow("Account name *", self.name)
        form.addRow("Account type *", self.kind)
        form.addRow("Normal balance side", self.normal_side)
        form.addRow("Description", self.description)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._suggest_normal_side(self.kind.currentText())

    def _suggest_normal_side(self, kind: str) -> None:
        self.normal_side.setCurrentText("debit" if kind in {"asset", "expense"} else "credit")

    def values(self) -> dict[str, str]:
        return {"code": self.code.text().strip(), "name": self.name.text().strip(),
                "account_type": self.kind.currentText(), "normal_side": self.normal_side.currentText(),
                "description": self.description.text().strip()}


class LockPeriodDialog(QDialog):
    """Dialog for locking a closed period after review."""
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Lock closed accounting period")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        form = QFormLayout()
        today = QDate.currentDate()
        default_end = today.addDays(-1)
        default_start = default_end.addDays(1 - default_end.day())
        self.start = QDateEdit(default_start)
        self.end = QDateEdit(default_end)
        for field in (self.start, self.end):
            field.setCalendarPopup(True)
            field.setDisplayFormat("yyyy-MM-dd")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("e.g. September accounts reconciled and approved")
        form.addRow("Period starts", self.start)
        form.addRow("Period ends", self.end)
        form.addRow("Lock reason *", self.reason)
        root.addWidget(muted_label("A locked period rejects new backdated postings. Reopening it requires an authorized user and a recorded reason."))
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Lock period")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> tuple[str, str, str]:
        return (self.start.date().toString("yyyy-MM-dd"), self.end.date().toString("yyyy-MM-dd"), self.reason.text().strip())


class AccountingWorkspacePage(QWidget):
    def __init__(self, database: Database, session: Session, on_navigate, parent: QWidget | None = None):
        super().__init__(parent)
        self.database, self.session, self.on_navigate = database, session, on_navigate
        self.service = AccountingService(database)
        self.sync_warnings: list[str] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 16)
        root.setSpacing(12)
        _base_page(root, "Finance workspace / general ledger", "Accounts & journal", "A balanced, traceable ledger behind bills, purchases and payments.")
        toolbar = QHBoxLayout()
        self.sync_state = QLabel("Local ledger")
        self.sync_state.setObjectName("muted")
        toolbar.addWidget(self.sync_state)
        toolbar.addStretch(1)
        self.new_account = HoverButton("+ Add account")
        self.new_account.clicked.connect(self.open_create_account)
        self.lock_period_button = HoverButton("Lock period")
        self.lock_period_button.clicked.connect(self.open_lock_period)
        self.new_journal = HoverButton("+ New journal entry")
        self.new_journal.setObjectName("primaryButton")
        self.refresh_button = HoverButton("Refresh ledger")
        self.export_tab_pdf_button = HoverButton("Export current tab PDF")
        self.export_tab_csv_button = HoverButton("Export current tab CSV")
        self.export_tab_pdf_button.clicked.connect(self.export_current_tab_pdf)
        self.export_tab_csv_button.clicked.connect(self.export_current_tab_csv)
        self.new_journal.setEnabled(has_permission(self.session.role, "accounts.journal_manage"))
        self.new_account.setEnabled(has_permission(self.session.role, "accounts.manage"))
        self.lock_period_button.setEnabled(has_permission(self.session.role, "accounts.period_lock"))
        self.new_journal.clicked.connect(self.open_journal)
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.new_account); toolbar.addWidget(self.lock_period_button)
        toolbar.addWidget(self.new_journal); toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.export_tab_pdf_button); toolbar.addWidget(self.export_tab_csv_button)
        root.addLayout(toolbar)

        self.metrics_layout = QGridLayout()
        self.metrics_layout.setSpacing(10)
        self.metric_labels: dict[str, QLabel] = {}
        metric_names = [("revenue", "Period revenue"), ("expenses", "Period expenses"), ("net_profit", "Net profit / loss"), ("total_assets", "Total assets")]
        for idx, (key, label) in enumerate(metric_names):
            card = CardFrame("metricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 13, 16, 13)
            name = QLabel(label); name.setObjectName("muted")
            value = QLabel("₹0.00"); value.setObjectName("metricValue")
            card_layout.addWidget(name); card_layout.addWidget(value)
            self.metrics_layout.addWidget(card, 0, idx)
            self.metric_labels[key] = value
        root.addLayout(self.metrics_layout)

        self.tabs = QTabWidget()
        self.accounts_table = _build_table(["Code", "Account name", "Type", "Normal side", "System", "Status"])
        self.accounts_table.setObjectName("accountChartTable")
        self.journal_table = _build_table(["Date", "Entry no.", "Reference", "Narration", "Debit", "Credit", "Lines"])
        self.journal_table.setObjectName("journalEntriesTable")
        self.journal_table.cellDoubleClicked.connect(self.show_entry_details)
        self.period_table = _build_table(["Period start", "Period end", "Reason", "Locked at", "Status", "Reopen reason"])
        self.period_table.setObjectName("accountingPeriodsTable")
        period_tab = QWidget()
        period_layout = QVBoxLayout(period_tab)
        period_layout.setContentsMargins(8, 8, 8, 8)
        period_layout.setSpacing(10)
        period_note = muted_label("Closed periods are protected from backdated postings. Reopening is permission-controlled and audited.")
        period_layout.addWidget(period_note)
        period_layout.addWidget(self.period_table, 1)
        period_actions = QHBoxLayout()
        self.period_tab_lock = HoverButton("+ Lock closed period")
        self.period_tab_lock.clicked.connect(self.open_lock_period)
        self.period_tab_unlock = HoverButton("Reopen selected period")
        self.period_tab_unlock.clicked.connect(self.reopen_selected_period)
        period_actions.addWidget(self.period_tab_lock)
        period_actions.addWidget(self.period_tab_unlock)
        period_actions.addStretch(1)
        period_layout.addLayout(period_actions)
        self.tabs.addTab(self.accounts_table, "Chart of accounts")
        self.tabs.addTab(self.journal_table, "Journal entries")
        self.tabs.addTab(period_tab, "Accounting periods")
        root.addWidget(self.tabs, 1)
        if not has_permission(self.session.role, "accounts.journal_manage"):
            self.new_journal.hide()
        if not has_permission(self.session.role, "accounts.manage"):
            self.new_account.hide()
        if not has_permission(self.session.role, "accounts.period_lock"):
            self.lock_period_button.hide()
            self.period_tab_lock.hide()
            self.period_tab_unlock.hide()

    def refresh(self) -> None:
        self.sync_warnings = self.service.synchronize_business(self.session.business_id, self.session.user_id)
        today = date.today().isoformat()
        start = f"{date.today().year if date.today().month >= 4 else date.today().year - 1}-04-01"
        try:
            summary = self.service.dashboard_summary(self.session.business_id, start, today)
            for key, label in self.metric_labels.items():
                label.setText(_money(summary.get(key, "0")))
            self.sync_state.setText("Ledger ready · Trial balance " + summary["trial_balance"] + (f" · {len(self.sync_warnings)} item(s) need review" if self.sync_warnings else ""))
        except Exception as exc:
            self.sync_state.setText(f"Ledger needs attention: {exc}")
        accounts = self.service.list_accounts(self.session.business_id)
        _fill_table(self.accounts_table, [[r["account_code"], r["account_name"], r["account_type"].title(), r["normal_side"].title(), "System" if r["is_system"] else "Custom", "Active" if r["is_active"] else "Inactive"] for r in accounts])
        entries = self.service.list_entries(self.session.business_id, limit=500)
        _fill_table(self.journal_table, [[r["entry_date"], r["entry_number"], r["reference"], r["narration"], _money(r["total_debit"]), _money(r["total_credit"]), r["line_count"]] for r in entries], right_columns={4, 5})
        for col, width in enumerate([110, 130, 140, 460, 130, 130, 70]):
            self.journal_table.setColumnWidth(col, width)
        for col, width in enumerate([100, 260, 130, 110, 90, 100]):
            self.accounts_table.setColumnWidth(col, width)
        period_rows = self.service.list_period_locks(self.session.business_id)
        _fill_table(self.period_table, [[r["start_date"], r["end_date"], r["reason"], r["locked_at"],
                                         "Locked" if not r.get("unlocked_at") else "Reopened", r.get("unlock_reason", "")]
                                        for r in period_rows])
        for row_index, record in enumerate(period_rows):
            if self.period_table.item(row_index, 0):
                self.period_table.item(row_index, 0).setData(Qt.ItemDataRole.UserRole, record["period_lock_id"])
        for col, width in enumerate([112, 112, 300, 175, 100, 250]):
            self.period_table.setColumnWidth(col, width)

    def _current_account_tab_export(self) -> tuple[str, str, list[str], list[list[Any]]]:
        index = self.tabs.currentIndex()
        if index == 0:
            title = "Chart of Accounts"
            table = self.accounts_table
            headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
            rows = [[table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())]
                    for r in range(table.rowCount())]
            subtitle = f"Active account chart · {len(rows)} account(s)"
        elif index == 1:
            title = "Journal Register"
            start = "1900-01-01"
            end = date.today().isoformat()
            entries = self.service.journal_register(self.session.business_id, start, end, limit=5000)
            headers = ["Date", "Entry no.", "Reference", "Narration", "Debit", "Credit", "Lines"]
            rows = [[r["entry_date"], r["entry_number"], r["reference"], r["narration"],
                     _money(r["total_debit"]), _money(r["total_credit"]), r["line_count"]] for r in entries["rows"]]
            rows.append(["", "TOTAL", "", f"{entries['count']} journal(s)", _money(entries["total_debit"]),
                         _money(entries["total_credit"]), ""])
            subtitle = f"Posted journal entries · {start} to {end} · {entries['count']} entry/entries"
        else:
            title = "Accounting Periods"
            table = self.period_table
            headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
            rows = [[table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())]
                    for r in range(table.rowCount())]
            subtitle = f"Period lock history · {len(rows)} record(s)"
        return title, subtitle, headers, rows

    def export_current_tab_pdf(self) -> None:
        try:
            title, subtitle, headers, rows = self._current_account_tab_export()
            path, _ = QFileDialog.getSaveFileName(
                self, "Export accounting PDF", f"koshflow-{title.lower().replace(' ', '-')}.pdf", "PDF files (*.pdf)"
            )
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            generate_accounting_report_pdf(self.database, self.session.business_id, path, title, subtitle, headers, rows)
            QMessageBox.information(self, "PDF exported", f"Saved accounting PDF to:\n{Path(path)}")
        except Exception as exc:
            QMessageBox.warning(self, "PDF export failed", str(exc))

    def export_current_tab_csv(self) -> None:
        try:
            title, subtitle, headers, rows = self._current_account_tab_export()
            path, _ = QFileDialog.getSaveFileName(
                self, "Export accounting CSV", f"koshflow-{title.lower().replace(' ', '-')}.csv", "CSV files (*.csv)"
            )
            if not path:
                return
            if not path.lower().endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
            QMessageBox.information(self, "CSV exported", f"Saved accounting CSV to:\n{Path(path)}")
        except OSError as exc:
            QMessageBox.warning(self, "CSV export failed", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "CSV export failed", str(exc))

    def open_create_account(self) -> None:
        dialog = CreateAccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            self.service.create_account(
                self.session.business_id, self.session.user_id, values["code"], values["name"],
                values["account_type"], values["normal_side"], values["description"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "Account not created", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Account added", "The custom account is now available in the chart and journal editor.")

    def open_lock_period(self) -> None:
        dialog = LockPeriodDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        start, end, reason = dialog.values()
        try:
            self.service.lock_period(self.session.business_id, self.session.user_id, start, end, reason)
        except Exception as exc:
            QMessageBox.warning(self, "Period not locked", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Period locked", f"Posting is now blocked for {start} through {end}.")

    def reopen_selected_period(self) -> None:
        row = self.period_table.currentRow()
        item = self.period_table.item(row, 0) if row >= 0 else None
        period_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not period_id:
            QMessageBox.information(self, "Select a period", "Select a locked accounting period first.")
            return
        record = next((r for r in self.service.list_period_locks(self.session.business_id) if r["period_lock_id"] == period_id), None)
        if not record or record.get("unlocked_at"):
            QMessageBox.information(self, "Period already open", "Choose a row whose status is Locked.")
            return
        reason, accepted = QInputDialog.getText(self, "Reopen accounting period", "Reason for reopening:")
        if not accepted:
            return
        try:
            self.service.unlock_period(self.session.business_id, self.session.user_id, str(period_id), reason)
        except Exception as exc:
            QMessageBox.warning(self, "Period not reopened", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Period reopened", "The period is open again. The action has been recorded in the audit log.")

    def open_journal(self) -> None:
        dialog = ManualJournalDialog(self.service, self.session.business_id, self.session.user_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            QMessageBox.information(self, "Journal posted", "The balanced journal entry has been posted and added to the audit trail.")

    def export_journal_entry_pdf(self, entry: dict[str, Any]) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export journal voucher PDF", f"{entry['entry_number'].lower()}.pdf", "PDF files (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        headers = ["Account code", "Account name", "Description", "Debit", "Credit"]
        rows = [[line["account_code"], line["account_name"], line["description"],
                 _money(line["debit"]), _money(line["credit"])] for line in entry["lines"]]
        rows.append(["", "TOTAL", "", _money(entry["total_debit"]), _money(entry["total_credit"])])
        subtitle = f"Date: {entry['entry_date']} · Entry: {entry['entry_number']} · Reference: {entry['reference'] or '—'} · {entry['narration']}"
        try:
            generate_accounting_report_pdf(
                self.database, self.session.business_id, path, "Journal Voucher", subtitle, headers, rows
            )
            QMessageBox.information(self, "Journal exported", f"Saved journal voucher PDF to:\n{Path(path)}")
        except Exception as exc:
            QMessageBox.warning(self, "Journal export failed", str(exc))

    def show_entry_details(self, row: int, column: int) -> None:
        number_item = self.journal_table.item(row, 1)
        if not number_item:
            return
        entry_number = number_item.text()
        found = next((r for r in self.service.list_entries(self.session.business_id, search=entry_number, limit=10) if r["entry_number"] == entry_number), None)
        if not found:
            return
        entry = self.service.get_entry(self.session.business_id, found["entry_id"])
        if not entry:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Journal {entry['entry_number']}")
        dialog.resize(780, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"{entry['entry_date']} · {entry['narration']}"))
        table = _build_table(["Account", "Description", "Debit", "Credit"])
        _fill_table(table, [[f"{line['account_code']} · {line['account_name']}", line["description"], _money(line["debit"]), _money(line["credit"])] for line in entry["lines"]], right_columns={2, 3})
        layout.addWidget(table)
        dialog_actions = QHBoxLayout()
        export_entry = HoverButton("Export journal PDF")
        export_entry.clicked.connect(lambda _checked=False, journal_entry=entry: self.export_journal_entry_pdf(journal_entry))
        dialog_actions.addWidget(export_entry)
        dialog_actions.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject); close.accepted.connect(dialog.accept)
        dialog_actions.addWidget(close)
        layout.addLayout(dialog_actions)
        dialog.exec()


class AccountingReportsPage(QWidget):
    REPORTS = [
        "Trial balance", "Trading account", "Profit & loss", "Balance sheet", "Cash flow statement",
        "Journal register", "General ledger", "GST summary", "HSN/SAC summary", "Sales register",
        "Purchase register", "Inventory valuation", "Low stock report", "Stock movement register",
        "Customer balances", "Supplier payables", "Top selling products", "Customer sales summary",
        "Supplier purchase summary", "Customer payment register", "Supplier payment register",
    ]
    CURRENT_STATE_REPORTS = {"Trial balance", "Balance sheet", "Inventory valuation", "Low stock report", "Customer balances", "Supplier payables"}
    OPERATIONAL_REPORTS = {
        "Inventory valuation", "Low stock report", "Stock movement register", "Customer balances",
        "Supplier payables", "Top selling products", "Customer sales summary", "Supplier purchase summary",
        "Customer payment register", "Supplier payment register",
    }

    def __init__(self, database: Database, session: Session, on_navigate, parent: QWidget | None = None):
        super().__init__(parent)
        self.database, self.session, self.on_navigate = database, session, on_navigate
        self.service = AccountingService(database)
        self._last_report: list[dict[str, Any]] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 16)
        root.setSpacing(12)
        _base_page(root, "Business reports / statements", "Reports & statements", "Exportable financial statements and GST-supporting summaries from posted local records.")
        controls = CardFrame("filterCard")
        filter_grid = QGridLayout(controls)
        filter_grid.setContentsMargins(12, 10, 12, 10)
        filter_grid.setHorizontalSpacing(10); filter_grid.setVerticalSpacing(8)
        self.report_type = QComboBox(); self.report_type.addItems(self.REPORTS)
        self.start_date = QDateEdit(QDate.currentDate().addMonths(-1)); self.start_date.setCalendarPopup(True); self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = QDateEdit(QDate.currentDate()); self.end_date.setCalendarPopup(True); self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.as_of_label = QLabel("As of"); self.as_of_label.setObjectName("muted")
        self.account_combo = QComboBox()
        for account in self.service.list_accounts(self.session.business_id):
            self.account_combo.addItem(f"{account['account_code']} · {account['account_name']}", account["account_id"])
        self.refresh_button = HoverButton("Run report"); self.refresh_button.setObjectName("primaryButton")
        self.export_pdf_button = HoverButton("Export PDF")
        self.export_button = HoverButton("Export CSV")
        filter_grid.addWidget(QLabel("Report"), 0, 0)
        filter_grid.addWidget(self.report_type, 0, 1, 1, 2)
        filter_grid.addWidget(QLabel("Account"), 0, 3)
        filter_grid.addWidget(self.account_combo, 0, 4, 1, 2)
        self.from_label = QLabel("From")
        self.to_label = QLabel("To / as of")
        filter_grid.addWidget(self.from_label, 1, 0)
        filter_grid.addWidget(self.start_date, 1, 1)
        filter_grid.addWidget(self.to_label, 1, 2)
        filter_grid.addWidget(self.end_date, 1, 3)
        filter_grid.addWidget(self.refresh_button, 1, 4)
        filter_grid.addWidget(self.export_pdf_button, 1, 5)
        filter_grid.addWidget(self.export_button, 1, 6)
        filter_grid.setColumnStretch(1, 1); filter_grid.setColumnStretch(4, 1)
        root.addWidget(controls)
        self.summary = QLabel("Reports always reflect posted records only.")
        self.summary.setObjectName("muted")
        root.addWidget(self.summary)
        self.table = _build_table(["Code", "Name", "Type", "Debit", "Credit"])
        self.table.setObjectName("financialReportTable")
        root.addWidget(self.table, 1)
        self.report_type.currentTextChanged.connect(self._update_controls)
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button.clicked.connect(self.export_csv)
        self.export_pdf_button.clicked.connect(self.export_pdf)
        self._update_controls()

    def _update_controls(self, *_args) -> None:
        kind = self.report_type.currentText()
        is_as_of = kind in self.CURRENT_STATE_REPORTS
        self.start_date.setEnabled(not is_as_of)
        self.from_label.setEnabled(not is_as_of)
        self.end_date.setEnabled(True)
        self.to_label.setText("As of" if is_as_of else "To")
        self.account_combo.setVisible(kind == "General ledger")
        # Hide the Account label except for the General Ledger selector.
        for label in self.findChildren(QLabel):
            if label.text() == "Account":
                label.setVisible(kind == "General ledger")
        self._configure_headers(kind)

    def _configure_headers(self, kind: str) -> None:
        headers = {
            "Trial balance": ["Code", "Account", "Type", "Debit balance", "Credit balance"],
            "Trading account": ["Section", "Code", "Particulars", "Amount"],
            "Profit & loss": ["Code", "Account", "Type", "Amount"],
            "Balance sheet": ["Section", "Code", "Account", "Balance"],
            "Journal register": ["Date", "Entry no.", "Reference", "Narration", "Debit", "Credit", "Lines"],
            "Cash flow statement": ["Date", "Entry", "Reference", "Narration", "Cash / bank", "Counterpart", "Activity", "Inflow", "Outflow"],
            "General ledger": ["Date", "Entry", "Reference", "Narration / line", "Debit", "Credit", "Running balance"],
            "GST summary": ["Tax head", "Amount"],
            "HSN/SAC summary": ["HSN/SAC", "Description", "Unit", "Quantity", "Tax rate %", "Taxable value", "Tax total"],
            "Sales register": ["Invoice", "Date", "Customer", "GSTIN", "Type", "Taxable", "Tax", "Total", "Paid", "Status"],
            "Purchase register": ["Purchase bill", "Supplier invoice", "Date", "Supplier", "GSTIN", "Taxable", "Tax", "Total", "Paid", "Status"],
            "Inventory valuation": ["SKU", "Product", "Category", "On hand", "Unit", "Average cost", "Stock value", "Reorder level"],
            "Low stock report": ["SKU", "Product", "Category", "On hand", "Reorder level", "Shortfall", "Unit", "Status"],
            "Stock movement register": ["Date/time", "Type", "SKU", "Product", "Change", "Before", "After", "Unit cost", "Value", "Source", "Reason", "User"],
            "Customer balances": ["Customer", "Phone", "Open invoices", "Invoiced", "Paid", "Outstanding", "Overdue"],
            "Supplier payables": ["Supplier", "Phone", "Open bills", "Billed", "Paid", "Credits/returns", "Payable", "Overdue"],
            "Top selling products": ["SKU", "Product", "Units sold", "Taxable sales", "Tax", "Invoice count"],
            "Customer sales summary": ["Customer", "Phone", "Invoices", "Taxable sales", "Tax", "Total billed", "Paid (recorded)", "Outstanding"],
            "Supplier purchase summary": ["Supplier", "GSTIN", "Bills", "Taxable purchases", "Input tax", "Total billed", "Paid (recorded)", "Payable"],
            "Customer payment register": ["Date/time", "Receipt", "Invoice", "Customer", "Amount", "Method", "Reference"],
            "Supplier payment register": ["Date/time", "Payment", "Purchase bill", "Supplier", "Amount", "Method", "Reference"],
        }[kind]
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers)

    def _operational_report(self, kind: str, start: str, end: str) -> tuple[list[str], list[list[Any]], str]:
        report = OperationalReportService(self.database).report(kind, self.session.business_id, start, end)
        return report["headers"], report["rows"], report["summary"]

    def refresh(self) -> None:
        try:
            warnings = self.service.synchronize_business(self.session.business_id, self.session.user_id)
            kind = self.report_type.currentText()
            start = self.start_date.date().toString("yyyy-MM-dd")
            end = self.end_date.date().toString("yyyy-MM-dd")
            rows: list[list[Any]] = []
            self._last_report = []
            if kind in self.OPERATIONAL_REPORTS:
                headers, rows, summary = self._operational_report(kind, start, end)
                self.table.setColumnCount(len(headers))
                self.table.setHorizontalHeaderLabels(headers)
                self.summary.setText(summary)
                _fill_table(self.table, rows, right_columns=set(range(2, len(headers))))
                self.table.resizeColumnsToContents()
                self.table.horizontalHeader().setStretchLastSection(True)
                return
            if kind == "Trial balance":
                report = self.service.trial_balance(self.session.business_id, end)
                self._last_report = report["rows"]
                rows = [[r["code"], r["name"], r["type"].title(), _money(r["debit"]), _money(r["credit"])] for r in report["rows"]]
                rows.append(["", "TOTAL", "", _money(report["total_debit"]), _money(report["total_credit"])])
                self.summary.setText(f"As of {end} · Trial balance {'balances' if report['balanced'] else 'DOES NOT BALANCE'}" + (f" · {len(warnings)} legacy item(s) need review" if warnings else ""))
            elif kind == "Trading account":
                report = self.service.trading_account(self.session.business_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["section"], r["code"], r["particulars"], _money(r["amount"])] for r in report["rows"]]
                self.summary.setText(
                    f"Trading account {start} to {end} · Gross profit {_money(report['gross_profit'])} · {report['basis']}"
                )
            elif kind == "Profit & loss":
                report = self.service.profit_and_loss(self.session.business_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["code"], r["name"], r["type"].title(), _money(r["amount"])] for r in report["rows"]]
                rows.extend([["", "Total revenue", "", _money(report["revenue"])], ["", "Total expenses", "", _money(report["expenses"])], ["", "NET PROFIT / (LOSS)", "", _money(report["net_profit"])]] )
                self.summary.setText(f"Period {start} to {end} · Revenue {_money(report['revenue'])} · Expenses {_money(report['expenses'])} · Net {_money(report['net_profit'])}")
            elif kind == "Balance sheet":
                report = self.service.balance_sheet(self.session.business_id, end)
                self._last_report = []
                for label, key in (("ASSETS", "assets"), ("LIABILITIES", "liabilities"), ("EQUITY", "equity")):
                    rows.append([label, "", "", ""])
                    for record in report[key]:
                        rows.append([label.title(), record.get("code", ""), record["name"], _money(record["amount"])])
                    totalkey = {"assets":"total_assets","liabilities":"total_liabilities","equity":"total_equity"}[key]
                    rows.append(["", "", f"Total {label.title()}", _money(report[totalkey])])
                rows.append(["", "", "LIABILITIES + EQUITY", _money(report["liabilities_and_equity"])])
                self.summary.setText(f"As of {end} · Balance sheet {'balances' if report['balanced'] else 'DOES NOT BALANCE'}")
            elif kind == "Cash flow statement":
                report = self.service.cash_flow_statement(self.session.business_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["date"], r["entry_number"], r["reference"], r["narration"], r["cash_account"],
                         r["counterpart"], r["activity"], _money(r["inflow"]), _money(r["outflow"])] for r in report["rows"]]
                rows.append(["", "", "", "OPENING CASH + BANK", "", "", "", "", _money(report["opening_cash_bank"])])
                rows.append(["", "", "", "TOTAL INFLOWS", "", "", "", _money(report["inflows"]), ""])
                rows.append(["", "", "", "TOTAL OUTFLOWS", "", "", "", "", _money(report["outflows"])])
                rows.append(["", "", "", "NET CHANGE", "", "", "", "", _money(report["net_change"])])
                rows.append(["", "", "", "CLOSING CASH + BANK", "", "", "", "", _money(report["closing_cash_bank"])])
                self.summary.setText(f"Cash and bank movement {start} to {end} · {report['note']}")
            elif kind == "General ledger":
                account_id = self.account_combo.currentData()
                report = self.service.general_ledger(self.session.business_id, account_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["entry_date"], r["entry_number"], r["reference"], r["description"] or r["narration"], _money(r["debit"]), _money(r["credit"]), _money(r["running_balance"])] for r in report["rows"]]
                self.summary.setText(f"{report['account']['account_code']} · {report['account']['account_name']} · Closing balance {_money(report['closing_balance'])}")
            elif kind == "Journal register":
                report = self.service.journal_register(self.session.business_id, start, end, limit=5000)
                self._last_report = report["rows"]
                rows = [[r["entry_date"], r["entry_number"], r["reference"], r["narration"],
                         _money(r["total_debit"]), _money(r["total_credit"]), r["line_count"]] for r in report["rows"]]
                rows.append(["", "TOTAL", "", f"{report['count']} journal(s)", _money(report["total_debit"]),
                             _money(report["total_credit"]), ""])
                self.summary.setText(
                    f"Journal register {start} to {end} · {report['count']} entries · "
                    f"{'debits equal credits' if report['balanced'] else 'REVIEW: debit and credit totals differ'}"
                )
            elif kind == "GST summary":
                report = self.service.gst_summary(self.session.business_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["code"], _money(r["amount"])] for r in report["rows"]]
                rows.extend([["Total output tax", _money(report["output_tax"])], ["Total input tax", _money(report["input_tax"])], ["NET GST PAYABLE / (CREDIT)", _money(report["net_payable"])]] )
                self.summary.setText(f"GST-supporting summary {start} to {end} · This is a report, not a filed return.")
            elif kind == "HSN/SAC summary":
                report = self.service.hsn_sac_summary(self.session.business_id, start, end)
                self._last_report = report["rows"]
                rows = [[r["hsn_sac"], r["description"], r["unit"], r["quantity"], r["tax_rate"],
                         _money(r["taxable_value"]), _money(r["tax_amount"])] for r in report["rows"]]
                rows.append(["", "TOTAL", "", "", "", _money(report["taxable_total"]), _money(report["tax_total"])])
                self.summary.setText(f"HSN/SAC support {start} to {end} · {report['note']}")
            elif kind == "Sales register":
                self._last_report = self.service.sales_register(self.session.business_id, start, end)
                rows = [[r["bill_number"], r["invoice_date"], r["customer_name"], r["customer_gstin"], r["customer_type"], _money(r["taxable_total"]), _money(r["tax_total"]), _money(r["grand_total"]), _money(r["amount_paid"]), r["status"].title()] for r in self._last_report]
                self.summary.setText(f"Issued sales documents {start} to {end} · {len(rows)} record(s)")
            else:
                self._last_report = self.service.purchase_register(self.session.business_id, start, end)
                rows = [[r["purchase_number"], r["supplier_invoice_number"], r["purchase_date"], r["supplier_name"], r["gstin"], _money(r["taxable_total"]), _money(r["tax_total"]), _money(r["grand_total"]), _money(r["amount_paid"]), r["status"].title()] for r in self._last_report]
                self.summary.setText(f"Posted purchase documents {start} to {end} · {len(rows)} record(s)")
            _fill_table(self.table, rows, right_columns=set(range(3, max(4, self.table.columnCount()))))
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setStretchLastSection(True)
        except Exception as exc:
            QMessageBox.warning(self, "Report could not be generated", str(exc))

    def export_pdf(self) -> None:
        """Export the report currently displayed, with business identity and page footers."""
        kind = self.report_type.currentText()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export accounting report PDF",
            f"koshflow-{kind.lower().replace(' ', '-')}.pdf", "PDF files (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            headers = [self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())]
            rows = [[self.table.item(r, c).text() if self.table.item(r, c) else ""
                     for c in range(self.table.columnCount())] for r in range(self.table.rowCount())]
            start = self.start_date.date().toString("yyyy-MM-dd")
            end = self.end_date.date().toString("yyyy-MM-dd")
            subtitle = self.summary.text().strip()
            generate_accounting_report_pdf(
                self.database, self.session.business_id, path, kind, subtitle or f"{start} to {end}", headers, rows
            )
            QMessageBox.information(self, "Report exported", f"Saved PDF report to:\n{Path(path)}")
        except Exception as exc:
            QMessageBox.warning(self, "PDF export failed", str(exc))

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export report", f"koshflow-{self.report_type.currentText().lower().replace(' ', '-')}.csv", "CSV files (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow([self.table.horizontalHeaderItem(i).text() for i in range(self.table.columnCount())])
                for row in range(self.table.rowCount()):
                    writer.writerow([self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())])
            QMessageBox.information(self, "Report exported", f"Saved report to:\n{Path(path)}")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
