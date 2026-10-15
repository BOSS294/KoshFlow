<p align="center">
  <a href="https://github.com/BOSS294/KoshFlow/releases">
    <img src="https://img.shields.io/badge/Download-Windows%20Release-C9E86A?style=for-the-badge&labelColor=171916" alt="Download Windows Release">
  </a>
  <a href="https://github.com/BOSS294/KoshFlow">
    <img src="https://img.shields.io/badge/GitHub-Repository-171916?style=for-the-badge&logo=github&logoColor=C9E86A" alt="GitHub Repository">
  </a>
</p>
<p align="center">
  <img src="https://img.shields.io/badge/Version-v0.6.3-C9E86A?style=flat-square&labelColor=171916" alt="Version 0.6.3">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-171916?style=flat-square&labelColor=C9E86A" alt="Windows 10 and 11">
  <img src="https://img.shields.io/badge/Python-3.11%2B-171916?style=flat-square&logo=python&logoColor=C9E86A" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/UI-PySide6%20%7C%20Qt-171916?style=flat-square&labelColor=C9E86A" alt="PySide6 and Qt">
  <img src="https://img.shields.io/badge/Database-SQLite-171916?style=flat-square&labelColor=C9E86A" alt="SQLite">
  <img src="https://img.shields.io/badge/Status-Active%20Development-171916?style=flat-square&labelColor=C9E86A" alt="Active Development">
  <img src="https://img.shields.io/badge/Tests-101%20passed%20in%20v0.6.3-171916?style=flat-square&labelColor=C9E86A" alt="101 tests passed in the v0.6.3 validation run">
</p>

# KoshFlow

**A local-first business management and accounting desktop application for Windows.**

KoshFlow brings billing, inventory, purchasing, customer and supplier management, accounting reports, and professional business documents into one workspace. It is built with Python and PySide6, with a SQLite database stored locally on the user's computer.





---

## Table of Contents

- [Project Overview](#project-overview)
- [Screenshots](#screenshots)
- [Features](#features)
- [Download for Windows](#download-for-windows)
- [Installation from Source](#installation-from-source)
- [First-Run Setup](#first-run-setup)
- [User Guide](#user-guide)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Application Data and Privacy](#application-data-and-privacy)
- [Architecture](#architecture)
- [Developer Setup](#developer-setup)
- [Testing](#testing)
- [Building the Windows Executable](#building-the-windows-executable)
- [GitHub Pages Website](#github-pages-website)
- [Release History](#release-history)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

## Project Overview

KoshFlow is designed to help businesses manage everyday operations without depending on a hosted business database.

The project follows three core principles:

- **Local-first data:** Business records are stored locally by default.
- **Connected workflows:** Billing, purchasing, inventory and accounting are designed to use related business records.
- **Practical desktop UX:** A keyboard-friendly interface, customizable appearance, clear financial information and professional PDF documents.

### Project Information

| Property | Details |
|---|---|
| Application | KoshFlow |
| Source version | `0.6.3` |
| Database schema | `7` |
| Target platform | Windows 10/11, x64 |
| Runtime | Python 3.11 or newer |
| Desktop framework | PySide6 / Qt Widgets |
| Database | SQLite |
| PDF generation | ReportLab and Pillow |
| Testing | pytest |
| Executable packaging | PyInstaller |
| Maintainer | Mayank Chawdhari (BOSS294) |

KoshFlow uses a 60/30/10 visual system: light neutral surfaces, charcoal structure, and citron-lime (`#C9E86A`) accents. Light and dark themes, font selection, interface scaling and control sizing are supported by the desktop settings.

## Screenshots

The following screenshots illustrate the application interface. Images in `assets/site/` are intended for public documentation and should use sanitized sample records.

### Business Overview

![KoshFlow business overview with financial metrics, revenue trend and quick actions](assets/site/overview.webp)

### Billing Workspace

![Billing workspace with Quick Billing, bill management and PDF Studio](assets/site/billing.webp)

### Quick Billing

![Keyboard-first checkout with product search and current sale](assets/site/quick-billing.webp)

### Invoice Theme Designer

![Invoice theme library and document customization interface](assets/site/pdf-studio.webp)

### Reports

![Financial and operational reports with export controls](assets/site/reports.webp)

### Bill Register

![Invoice register with searchable business documents](assets/site/bill-register.webp)

## Features

### 1. Billing and Invoice Management

KoshFlow provides a local invoice workflow for creating and managing business documents.

- Create and manage draft invoices.
- Issue invoices and track payment status.
- Search and filter the invoice register.
- Record partial and full customer payments.
- Track outstanding balances.
- Support B2B and B2C invoice classification.
- Configure item quantities, discounts and tax rates.
- Generate PDFs from saved bills.
- Maintain documented cancellation and correction workflows for issued documents.

Issued financial records should not be silently overwritten. Use the appropriate payment, cancellation or correction workflow for the document's state.

### 2. Quick Billing

Quick Billing is designed for fast counter sales and retail workflows.

- Search catalog products by name, SKU or barcode.
- Enter the quantity separately.
- Add selected products to the current sale.
- Enter customer name and phone information.
- Select matching customer suggestions.
- Save or reuse customer records through the sale workflow.
- Check stock availability before completing a sale.
- Record the payment method and sale total.

Inventory-linked sales update stock when the invoice is successfully issued.

### 3. PDF Studio and Invoice Customization

PDF Studio provides reusable invoice themes and document-design controls.

- Starter invoice themes.
- Saved and reusable templates.
- Page-size and document-composition settings.
- Typography, text color and background customization.
- Panel, border, rule and highlighted-total styling.
- Live invoice preview.
- Optional business logo and branded header.
- Business address, phone number and website.
- Optional bank details, UPI ID and payment QR image.
- Multipage document support.
- Invoice attribution: `Generated by KoshFlow`.

The final document should be reviewed before it is sent to a customer, especially when changing mandatory invoice fields or tax-related information.

### 4. Inventory Management

Inventory features cover the product catalog and stock lifecycle.

- Product creation and editing.
- Automatic SKU generation.
- Product categories and units.
- HSN/SAC fields.
- Purchase and selling prices.
- Configurable tax rates.
- Opening stock and stock adjustments.
- Low-stock reports.
- Inventory valuation using recorded moving-average cost.
- Stock movement history with source references.
- CSV export where supported.

Product quantities must be interpreted according to their units. Pieces, kilograms and litres should not be combined into a single quantity total.

### 5. Purchasing and Suppliers

- Supplier records and contact details.
- Purchase orders.
- Partial and complete purchase receipts.
- Purchase-bill drafts generated from receipt workflows.
- Supplier invoice references.
- Supplier payments.
- Supplier returns and credits.
- Payable tracking.
- Purchase registers and reports.

Purchase-bill drafts should be matched to the supplier's actual invoice or reference before posting.

### 6. Customer Management

- Customer records and contact information.
- Customer lookup in Quick Billing.
- Walk-in customer persistence after completed counter sales.
- Customer balances and invoice history.
- Customer payment tracking.
- Searchable customer registers.
- CSV export in supported workflows.

### 7. Accounting and Financial Reports

The accounting workspace includes a double-entry accounting foundation and financial reports.

Supported report categories include:

- Chart of Accounts.
- Journal Register and individual journal vouchers.
- General Ledger.
- Trial Balance.
- Trading Account.
- Profit and Loss Statement.
- Balance Sheet.
- Cash Flow Statement.
- Accounting-period history.
- Sales and Purchase Registers.
- GST and HSN/SAC supporting summaries.
- Customer balances and supplier payables.
- Inventory valuation and stock movements.
- Customer and supplier payment registers.

PDF and CSV export are available for supported reports and registers.

Financial reports should be reconciled against original invoices, purchase bills, payments and journal entries before being relied on for accounting or statutory purposes.

### 8. Business Overview Dashboard

The dashboard is designed to display available business information from local records.

Depending on available and posted records, it can present:

- Sales and invoice metrics.
- Customer receivables.
- Supplier payables.
- Cash and bank figures.
- Revenue trends.
- Cash movement.
- Recent business activity.
- Quick actions.
- Business profile information.
- Upcoming dates and stock alerts.

The dashboard should not substitute fabricated metrics for missing records. Where a module has no data, the interface should present an appropriate empty state.

### 9. Notifications

KoshFlow includes a local notification inbox and desktop-notification integration.

Notification categories include supported events such as:

- Overdue customer invoices.
- Approaching payment deadlines.
- Low or out-of-stock products.
- Supplier and purchasing reminders.
- Configured compliance dates.

Notification preferences and a test action are available in Settings. Native desktop delivery depends on operating-system support and permissions; in-app notifications provide a fallback where available.

### 10. Appearance and Personalization

- Light and dark themes.
- Font selection.
- User interface scaling.
- Control sizing and input-width preferences.
- Local profile image and display name.
- Keyboard-friendly interactions.
- Theme-aware controls and navigation.

### 11. Local Data and Backups

- Local SQLite storage.
- Local workspace authentication.
- Argon2 password hashing.
- Role-aware navigation and supported permission checks.
- Database schema migrations.
- Local backup creation and restoration workflows.
- Local application logs and exports.

Backup files in this version are standard SQLite backup files and are not encrypted by the application at rest.

---

## Download for Windows

The intended end-user distribution is a portable Windows executable named `KoshFlow.exe`.

**[Open KoshFlow Releases](https://github.com/BOSS294/KoshFlow/releases)**

1. Open the Releases page.
2. Select the latest stable release.
3. Download `KoshFlow.exe` from the release assets.
4. Save it in a folder you control.
5. Run the executable and complete first-run setup if required.

The source snapshot does not itself contain a compiled Windows executable. The executable must be generated and published through the release workflow.

The current packaging configuration does not establish Windows code signing. Windows may display publisher or reputation warnings. Download release artifacts only from the official repository and verify their source before running them.

## Installation from Source

### Requirements

- Windows 10 or Windows 11, x64.
- Python 3.11 or newer.
- Internet access for initial dependency installation.
- A writable local application-data directory.

### Clone the Repository

```powershell
git clone https://github.com/BOSS294/KoshFlow.git
cd KoshFlow
```

### Create a Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install Dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Launch the Application

```powershell
python main.py
```

If PowerShell blocks virtual-environment activation, call the environment's Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

The application opens the first-run setup flow if the local database has no user account; otherwise, it opens the login screen.

## First-Run Setup

1. Launch KoshFlow.
2. Create the local owner account.
3. Enter the registered business name and applicable business details.
4. Configure contact information, state/UT and tax-registration details where applicable.
5. Open Settings to configure invoice branding, bank/UPI details and appearance.
6. Create a verified backup before entering substantial business data.
7. Add products and suppliers before using inventory-linked sales and purchasing.

Use actual legal names, tax identifiers and banking details only in your private workspace. Public screenshots and issue attachments should always use sanitized information.

## User Guide

### Create and Issue an Invoice

1. Open **Billing**.
2. Select **Create Bill**.
3. Select or enter the customer.
4. Add products or services.
5. Verify quantities, prices, discounts and applicable tax.
6. Review the totals and payment terms.
7. Save as a draft while the document is being prepared.
8. Issue the invoice only after reviewing the details.
9. Generate and check the PDF before sending it.

### Complete a Quick Sale

1. Open Billing and select **Quick Billing**.
2. Search for a pre-added product.
3. Select the matching result.
4. Enter the quantity separately.
5. Add the product to the current sale.
6. Enter customer details or select a matching customer.
7. Review the stock, payment method and total.
8. Complete the sale only after verifying the transaction.

### Record a Purchase

1. Add the supplier record.
2. Create a purchase order where applicable.
3. Record only the quantities actually received.
4. Match the generated purchase-bill draft to the supplier invoice.
5. Verify prices, discounts and taxes.
6. Post the purchase bill when the received quantities and source document are correct.
7. Record supplier payments and returns through their appropriate workflows.

### Design an Invoice

1. Open **PDF Studio**.
2. Choose an existing invoice theme or create a new one.
3. Configure page size, document composition, typography, colors and branding.
4. Add the business logo and payment details where required.
5. Inspect the live preview.
6. Generate a PDF from the saved invoice.
7. Verify the final document before sending it.

### Export Financial Reports

1. Open **Reports**.
2. Choose the required statement or register.
3. Set the appropriate date range or as-of date.
4. Run the report.
5. Review the reporting period and figures.
6. Export to PDF for a formatted document or CSV for further analysis.
7. Reconcile the results with the underlying records before relying on them.

### Test Desktop Notifications

1. Open **Settings → Notifications**.
2. Enable the channels and event categories you need.
3. Use the test-notification action.
4. Check whether the desktop notification appears.
5. If it does not, check Windows notification permissions and Focus/Do Not Disturb settings.

### Back Up and Restore

1. Open **Settings → Data & Backups**.
2. Create a backup and wait for verification.
3. Keep a second copy in a separate, protected location.
4. Test restoration on a copy before replacing the primary database.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `F2` | Focus product search in Quick Billing |
| `Down` | Move into matching product results |
| `Enter` | Add the selected product where supported |
| `F4` | Begin or confirm the Quick Billing checkout flow |
| `Delete` | Remove the selected sale item when the cart is focused |
| `Esc` | Clear product search |
| `Ctrl+K` | Open the command palette where available |
| `Ctrl+N` | Start a new bill where supported |

Shortcuts are context-specific and do not bypass stock validation or checkout confirmation.

---

## Application Data and Privacy

### Default Windows Data Directory

```text
%LOCALAPPDATA%\KoshFlow\
```

The directory contains the local database and supporting application data, including backups, logs and exports.

The database filename in this source version is:

```text
koshflow.sqlite3
```

The application supports `KOSHFLOW_HOME` for overriding the data directory in portable or testing scenarios.

### Data Handling

- The current design is local-first and does not require a KoshFlow-hosted database.
- Desktop notifications depend on operating-system capabilities and permissions.
- WhatsApp sharing involves an external application, and the user must verify the recipient and attachment.
- AI Business Insights is a coming-soon area; a live AI provider is not represented as active.
- Backup files are not encrypted at rest by the application.
- Public GitHub issues must not contain production databases, customer records, phone numbers, bank details or unredacted invoices.

Protect the application-data directory and backups using appropriate operating-system account permissions and disk encryption.

## Architecture

KoshFlow separates its UI layer from service logic and database operations. Financial calculations and transaction rules should remain in services rather than presentation widgets.

### Technology Stack

| Area | Technology |
|---|---|
| Language | Python 3.11+ |
| Desktop UI | PySide6 / Qt Widgets |
| Local database | SQLite |
| Authentication | `argon2-cffi` |
| Invoice and accounting PDFs | ReportLab |
| Image processing | Pillow |
| Testing | pytest |
| Windows executable | PyInstaller |
| Automation | GitHub Actions |

### Project Structure

```text
KoshFlow/
├── assets/
│   └── site/                  # Sanitized screenshots for GitHub Pages
├── .github/
│   └── workflows/             # Tests and Windows release automation
├── koshflow/
│   ├── core/                  # Database, migrations, permissions and backups
│   ├── services/              # Billing, inventory, accounting, reports and more
│   ├── ui/
│   │   ├── pages/             # Application screens
│   │   ├── components.py      # Reusable Qt controls
│   │   ├── icons.py           # SVG icon helpers
│   │   ├── styles.py          # Light/dark design system
│   │   └── main_window.py     # Navigation and workspace shell
│   ├── app.py                 # Application startup
│   └── config.py              # Version and application configuration
├── tests/                     # Regression and service tests
├── KoshFlow.spec              # PyInstaller build configuration
├── index.html                 # GitHub Pages website
├── main.py                    # Application entry point
├── pyproject.toml
└── requirements.txt
```

### Development Principles

- Keep UI widgets separate from business services.
- Apply financial calculations using decimal-safe monetary arithmetic.
- Keep schema migrations controlled and testable.
- Preserve auditability for posted bills and stock movements.
- Use database transactions for operations affecting financial or inventory records.
- Design reports around journal and source-document data.
- Avoid storing customer or financial data in public logs and test fixtures.

## Developer Setup

Install the project requirements and testing tools:

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest
```

### Run the Test Suite

```powershell
python -m compileall -q koshflow main.py
python -m pytest -q
```

Run the complete tests after changing the source, rather than relying on results from an earlier version.

Financial changes should include tests for debit/credit balance, duplicate posting, reversals and impacts on linked balances or stock quantities.

### Build a Windows Executable

Install PyInstaller:

```powershell
python -m pip install pyinstaller
```

Build the portable executable:

```powershell
python -m PyInstaller --noconfirm --clean KoshFlow.spec
```

The expected output is:

```text
dist/KoshFlow.exe
```

The executable is a portable single-file build, not an installer wizard. Application data remains in the user's data directory.

### Publish a Windows Release

The repository includes a Windows release workflow.

1. Update version constants and release notes.
2. Run compilation and the full test suite.
3. Commit and push the intended release commit.
4. Create and push a version tag, such as `v0.6.4`.
5. Allow the Windows workflow to test and package the application.
6. Verify the published executable on a clean Windows account before announcing the release.

Code signing and release-hash verification should be added before broad production distribution.

## GitHub Pages Website

The repository includes a static website in `index.html`.

To publish it:

1. Push the repository to GitHub.
2. Open **Settings → Pages**.
3. Configure deployment from the `main` branch and `/ (root)`.
4. Wait for the deployment to finish.
5. Confirm the repository slug in the website configuration.
6. Publish a GitHub Release with the expected `KoshFlow.exe` asset.

The default repository slug is `BOSS294/KoshFlow`. Update the website links if the final repository uses a different owner or name.

The website's download section checks GitHub Releases for an executable asset. If no release asset exists, users are directed to the Releases page instead of being given a fabricated download link.

## Release History

### v0.6.3

- Refined the Overview dashboard and business identity panel.
- Added the animated AI Business Insights coming-soon experience.
- Added notification preferences and a notification test action.
- Refined profile popover behavior and light/dark theme surfaces.

### v0.6.2

- Connected operational dashboard metrics.
- Expanded operational reports and local notification persistence.
- Removed the Services navigation module.

### v0.6.1

- Added Trading Account and journal-register PDF exports.
- Improved branded, multi-page accounting report output.

### v0.6.0

- Added the double-entry accounting foundation.
- Expanded financial statements and accounting exports.
- Improved PDF business branding.

Earlier release history can be reviewed through Git tags and commit history after publication.

## Known Limitations

KoshFlow is actively developed. The current source should not be interpreted as a fully certified production accounting or tax-compliance product.

- AI Business Insights is not yet connected to a live AI provider.
- GST-supporting reports do not themselves file statutory returns.
- Official GST portal filing, e-invoicing and e-way bill integrations remain separate work.
- Automated WhatsApp document delivery is not implemented by the manual sharing workflow.
- Cloud synchronization and multi-device collaboration are not part of the current local-first data model.
- Backup encryption at rest and an independent security review remain outstanding.
- The Windows executable must be built and published through the release process; it is not included in the source snapshot.
- The current executable configuration is not code-signed.

Always back up business data before upgrading, and test new builds against a copy of the database before using them for live financial transactions.

## Contributing

Contributions and defect reports should be focused, reproducible and safe to share publicly.

1. Open an issue describing the problem or proposed enhancement.
2. Include reproduction steps and sanitized screenshots where relevant.
3. Do not attach production databases, invoices or customer information.
4. Create a focused branch and keep changes within the intended scope.
5. Add or update tests for service logic, database migrations and financial behavior.
6. Run compilation and the full test suite.
7. Submit a pull request explaining the changes and their validation.

Accounting changes should demonstrate balanced journal entries, idempotent source-document posting and the impact on related balances and inventory.

## License

**No license has been specified in this source snapshot.**

A public GitHub repository does not automatically grant permission to use, modify or redistribute its contents. Add an appropriate `LICENSE` file before presenting KoshFlow as an open-source project or accepting external code contributions.

---

<p align="center">
  <strong>KoshFlow</strong><br>
  Local business management. Clear financial records. Better workflows.
</p>

<p align="center">
  <a href="https://github.com/BOSS294/KoshFlow/releases">Releases</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/BOSS294/KoshFlow/issues">Report an Issue</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/BOSS294/KoshFlow">Source Repository</a>
</p>
