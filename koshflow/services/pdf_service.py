"""Full-document invoice renderer backed by persisted bill and theme records.

Purpose: Generate print-ready, coordinated invoice PDFs with complete layout themes.
Canonical path: koshflow/services/pdf_service.py
Project: KoshFlow | Version: 0.6.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Call generate_invoice_pdf(database, business_id, bill_id, output_path, template_id=None).
Changelog: v0.6.0 — Fixed silent logo omission, trimmed transparent logo canvas and aligned business identity in a measured invoice header.
"""

from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, KeepTogether, Image as RLImage

try:
    from PIL import Image, ImageChops
except ImportError:  # ReportLab-only fallback can still preserve the logo aspect ratio.
    Image = None
    ImageChops = None

from koshflow.core.database import Database
from koshflow.services.bill_service import BillService, BillError
from koshflow.services.business_service import BusinessService
from koshflow.services.invoice_profile_service import load_invoice_profile
from koshflow.services.theme_design import resolve_theme_design


class PDFGenerationError(RuntimeError):
    """PDF creation failed or required source records were not found."""


def _register_font(template: dict) -> tuple[str, str]:
    requested = str(template.get("font_family", "Helvetica"))
    if requested != "Unicode Sans":
        bold = f"{requested}-Bold" if requested != "Helvetica" else "Helvetica-Bold"
        if requested == "Times-Roman":
            bold = "Times-Bold"
        if requested == "Courier":
            bold = "Courier-Bold"
        return requested, bold

    candidates = [
        (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
    ]
    for regular_path, bold_path in candidates:
        if not regular_path.exists():
            continue
        try:
            if "KoshFlowBody" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("KoshFlowBody", str(regular_path)))
            if bold_path.exists() and "KoshFlowBody-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("KoshFlowBody-Bold", str(bold_path)))
            return "KoshFlowBody", "KoshFlowBody-Bold" if bold_path.exists() else "Helvetica-Bold"
        except Exception:
            continue
    return "Helvetica", "Helvetica-Bold"


def _color(hex_value: str) -> colors.Color:
    try:
        return colors.HexColor(hex_value)
    except (ValueError, TypeError):
        return colors.HexColor("#FFFFFF")


def _money(value: object) -> str:
    return f"{Decimal(str(value or '0')):,.2f}"


def _make_para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _style_table(table: Table, *, background: colors.Color, border: colors.Color,
                 padding: int = 7, grid: bool = True) -> None:
    commands = [
        ("BACKGROUND", (0, 0), (-1, -1), background),
        ("BOX", (0, 0), (-1, -1), 0.65, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding),
        ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]
    if grid:
        commands.append(("INNERGRID", (0, 0), (-1, -1), 0.35, border))
    table.setStyle(TableStyle(commands))



def _cropped_logo_stream(path: Path, max_width: float, max_height: float) -> tuple[BytesIO, float, float] | None:
    """Trim empty canvas around a business logo and fit it within a real aspect-ratio box.

    This is important for wide wordmarks: placing a 4:1 logo inside an 18 mm square
    makes it render as a tiny strip even though the image itself is high resolution.
    """
    try:
        if Image is None:
            from reportlab.lib.utils import ImageReader
            reader = ImageReader(str(path))
            width, height = reader.getSize()
            ratio = width / max(1, height)
            display_width = min(max_width, max_height * ratio)
            display_height = display_width / ratio
            stream = BytesIO(path.read_bytes())
            stream.seek(0)
            return stream, display_width, display_height

        with Image.open(path) as original:
            image = original.convert("RGBA")
        alpha = image.getchannel("A")
        bbox = alpha.getbbox() if alpha.getextrema() != (255, 255) else None
        if not bbox:
            rgb = image.convert("RGB")
            white = Image.new("RGB", rgb.size, (255, 255, 255))
            difference = ImageChops.difference(rgb, white).convert("L")
            # Ignore compression noise; retain genuine marks and colored logo elements.
            bbox = difference.point(lambda value: 255 if value > 26 else 0).getbbox()
        if bbox:
            left, top, right, bottom = bbox
            pad_x = max(2, int((right - left) * 0.018))
            pad_y = max(2, int((bottom - top) * 0.06))
            bbox = (max(0, left - pad_x), max(0, top - pad_y),
                    min(image.width, right + pad_x), min(image.height, bottom + pad_y))
            if bbox[2] > bbox[0] and bbox[3] > bbox[1]:
                image = image.crop(bbox)
        width_px, height_px = image.size
        if not width_px or not height_px:
            return None
        ratio = width_px / height_px
        display_width = min(max_width, max_height * ratio)
        display_height = display_width / ratio
        stream = BytesIO()
        image.save(stream, format="PNG", optimize=True)
        stream.seek(0)
        return stream, display_width, display_height
    except Exception:
        return None


def generate_invoice_pdf(database: Database, business_id: str, bill_id: str,
                         output_path: str | Path, template_id: str | None = None) -> Path:
    bill_service = BillService(database)
    bill = bill_service.get_bill(business_id, bill_id)
    if not bill:
        raise PDFGenerationError("The selected bill could not be found in this business workspace.")
    if not bill.get("items"):
        raise PDFGenerationError("This bill has no line items to render.")

    profile = BusinessService(database).get_profile(business_id)
    invoice_profile = load_invoice_profile(database, business_id)
    templates = bill_service.list_templates(business_id)
    if not templates:
        bill_service.ensure_starter_templates(business_id)
        templates = bill_service.list_templates(business_id)
    chosen_template_id = template_id or bill.get("template_id")
    template = next((item for item in templates if item["template_id"] == chosen_template_id), None)
    template = template or next((item for item in templates if item["is_default"]), templates[0])

    design = resolve_theme_design(template)
    layout_style = design["style"]
    palette = design["colors"]
    page_bg = _color(palette["page_bg"])
    text_color = _color(palette["text"])
    muted_color = _color(palette["muted"])
    surface = _color(palette["surface"])
    border = _color(palette["border"])
    accent = _color(design["accent"])
    accent_text = _color(palette["accent_text"])

    page_size_name = template.get("page_size", "A4")
    page_size = A5 if page_size_name == "A5" else A4
    if page_size_name == "THERMAL_80":
        def wrapped_line_count(value: object, width: int) -> int:
            text = str(value or "").strip()
            return max(1, (len(text) + width - 1) // width) if text else 0

        item_line_count = sum(wrapped_line_count(item.get("description", ""), 21) for item in bill["items"])
        note_line_count = wrapped_line_count(bill.get("notes", ""), 58) + wrapped_line_count(bill.get("terms", ""), 54)
        receipt_height_mm = 158 + len(bill["items"]) * 3 + item_line_count * 2 + note_line_count * 2.5
        page_size = (80 * mm, min(600, max(166, receipt_height_mm)) * mm)
    font_regular, font_bold = _register_font(template)
    currency_prefix = "₹ " if font_regular == "KoshFlowBody" else "INR "
    invoice_money_prefix = "" if page_size_name == "THERMAL_80" else currency_prefix
    font_size = max(7, min(18, int(template.get("font_size", 9))))
    is_compact = layout_style in {"compact", "receipt"} or page_size_name == "THERMAL_80"
    is_formal = layout_style == "formal"
    if is_formal and font_regular in {"Helvetica", "KoshFlowBody"}:
        font_regular, font_bold = "Times-Roman", "Times-Bold"
    if is_compact:
        font_size = min(font_size, 8 if page_size_name == "THERMAL_80" else 9)

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    margin = 4.5 * mm if page_size_name == "THERMAL_80" else (11 * mm if is_compact else 15 * mm)
    top_margin = 12 * mm if layout_style in {"bold", "dark", "modern"} else margin
    bottom_margin = 15 * mm

    def paint_page(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(page_bg)
        canvas.rect(0, 0, page_size[0], page_size[1], fill=1, stroke=0)
        if layout_style in {"modern", "bold", "dark", "boxed"}:
            strip_height = 2.6 * mm if layout_style in {"bold", "dark"} else 1.4 * mm
            canvas.setFillColor(accent)
            canvas.rect(0, page_size[1] - strip_height, page_size[0], strip_height, fill=1, stroke=0)
        if layout_style in {"editorial", "formal", "ledger"}:
            canvas.setStrokeColor(border)
            canvas.setLineWidth(0.55)
            canvas.line(margin, 10 * mm, page_size[0] - margin, 10 * mm)
        canvas.setFont(font_regular if font_regular in pdfmetrics.getRegisteredFontNames() else "Helvetica", 7)
        canvas.setFillColor(muted_color)
        canvas.drawString(margin, 6 * mm, "Generated by KoshFlow")
        canvas.drawRightString(page_size[0] - margin, 6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    business_name = profile.get("trade_name") or profile.get("legal_name") or "Business"
    doc_label = {
        "tax_invoice": "TAX INVOICE", "bill_of_supply": "BILL OF SUPPLY",
        "proforma": "PRO FORMA INVOICE", "estimate": "ESTIMATE / QUOTATION",
    }.get(bill.get("document_type", "tax_invoice"), "INVOICE")
    try:
        doc = SimpleDocTemplate(
            str(target), pagesize=page_size,
            rightMargin=margin, leftMargin=margin,
            topMargin=top_margin, bottomMargin=bottom_margin,
            title=f"{bill['bill_number']} - {business_name}",
            author=business_name,
            subject="Business invoice generated by KoshFlow",
        )
    except Exception as exc:
        raise PDFGenerationError(f"PDF document could not be initialized: {exc}") from exc

    styles = getSampleStyleSheet()
    title_size = font_size + (7 if layout_style in {"compact", "receipt"} else 10)
    title_style = ParagraphStyle(
        "KoshTitleV031", parent=styles["Title"], fontName=font_bold,
        fontSize=title_size, leading=title_size + 2, textColor=text_color,
        alignment=TA_CENTER if layout_style in {"classic", "receipt"} else TA_LEFT,
        spaceAfter=2 * mm,
    )
    doc_title_style = ParagraphStyle(
        "KoshDocumentTitleV031", parent=styles["Heading2"], fontName=font_bold,
        fontSize=font_size + (4 if layout_style in {"bold", "dark"} else 2),
        leading=font_size + 5, textColor=accent_text if layout_style in {"boxed", "bold", "dark"} else text_color,
        alignment=TA_RIGHT if layout_style in {"modern", "editorial", "boxed", "bold", "dark"} else TA_LEFT,
        spaceAfter=1.5 * mm,
    )
    section_style = ParagraphStyle(
        "KoshSectionV031", parent=styles["Normal"], fontName=font_bold,
        fontSize=font_size + 1, leading=font_size + 4, textColor=text_color,
        spaceBefore=1 * mm, spaceAfter=1.3 * mm,
    )
    body_style = ParagraphStyle(
        "KoshBodyV031", parent=styles["Normal"], fontName=font_regular,
        fontSize=font_size, leading=font_size + (2 if is_compact else 3), textColor=text_color,
        spaceAfter=0.5 * mm,
    )
    surface_text_color = _color(palette.get("surface_text", palette["text"]))
    surface_muted_color = _color(palette.get("surface_muted", palette["muted"]))
    surface_body_style = ParagraphStyle(
        "KoshSurfaceBodyV031", parent=body_style, textColor=surface_text_color,
    )
    surface_small_style = ParagraphStyle(
        "KoshSurfaceSmallV031", parent=body_style, fontSize=max(7, font_size - 1),
        leading=max(8, font_size + 1), textColor=surface_muted_color,
    )
    surface_right_style = ParagraphStyle(
        "KoshSurfaceRightV031", parent=surface_body_style, alignment=TA_RIGHT,
    )
    surface_label_style = ParagraphStyle(
        "KoshSurfaceLabelV031", parent=surface_small_style, fontName=font_bold,
        textColor=surface_muted_color,
    )
    small_style = ParagraphStyle(
        "KoshSmallV031", parent=body_style, fontSize=max(7, font_size - 1),
        leading=max(8, font_size + 1), textColor=muted_color,
    )
    white_or_accent_style = ParagraphStyle(
        "KoshAccentStyleV031", parent=body_style, fontName=font_bold,
        fontSize=font_size + 1, leading=font_size + 3, textColor=accent_text,
    )
    right_style = ParagraphStyle("KoshRightV031", parent=body_style, alignment=TA_RIGHT)
    center_style = ParagraphStyle("KoshCenterV031", parent=body_style, alignment=TA_CENTER)
    label_style = ParagraphStyle("KoshLabelV031", parent=small_style, fontName=font_bold, textColor=muted_color)

    def business_contact() -> list[str]:
        lines = []
        if template.get("show_business_contact", 1):
            address = ", ".join(part for part in [profile.get("address", ""), profile.get("city", ""), profile.get("state", ""), profile.get("pincode", "")] if part)
            if address:
                lines.append(address)
            contact_line = " · ".join(part for part in [profile.get("phone", ""), profile.get("email", "")] if part)
            if contact_line:
                lines.append(contact_line)
            website = str(invoice_profile.get("website") or "").strip()
            if website:
                lines.append(website)
        if template.get("show_gstin", 1) and profile.get("gstin"):
            lines.append(f"GSTIN: {escape(profile['gstin'])}")
        return lines

    contact_html = "<br/>".join(escape(line) if not line.startswith("GSTIN:") else line for line in business_contact())
    brand_alignment = TA_CENTER if page_size_name == "THERMAL_80" else TA_LEFT
    business_name_style = ParagraphStyle(
        "KoshBusinessNameV060", parent=body_style, fontName=font_bold,
        fontSize=max(font_size + 4, 13 if page_size_name != "THERMAL_80" else 10),
        leading=max(font_size + 7, 15 if page_size_name != "THERMAL_80" else 12),
        textColor=text_color, alignment=brand_alignment, spaceAfter=1.2 * mm,
    )
    business_contact_style = ParagraphStyle(
        "KoshBusinessContactV060", parent=small_style, alignment=brand_alignment,
        fontSize=max(7, font_size - 1), leading=max(9, font_size + 1), textColor=muted_color,
    )
    logo_path_value = str(invoice_profile.get("logo_path") or "").strip()
    logo_path = Path(logo_path_value).expanduser() if logo_path_value else Path()
    logo = None
    logo_stream = None
    logo_width = logo_height = 0.0
    if logo_path_value and logo_path.is_file():
        # Non-thermal pages use a broad wordmark area; receipts use a centered mark above the name.
        max_logo_width = (43 * mm if page_size_name == "THERMAL_80" else 36 * mm)
        max_logo_height = (14 * mm if page_size_name == "THERMAL_80" else 15 * mm)
        prepared_logo = _cropped_logo_stream(logo_path, max_logo_width, max_logo_height)
        if prepared_logo:
            logo_stream, logo_width, logo_height = prepared_logo
            logo = RLImage(logo_stream, width=logo_width, height=logo_height)

    contact_paragraph = Paragraph(contact_html, business_contact_style) if contact_html else None
    if page_size_name == "THERMAL_80":
        business_block = []
        if logo is not None:
            logo_table = Table([[logo]], colWidths=[doc.width], hAlign="CENTER")
            logo_table.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2 * mm),
            ]))
            business_block.append(logo_table)
        business_block.append(Paragraph(escape(business_name), business_name_style))
        if contact_paragraph:
            business_block.append(contact_paragraph)
        business_block.append(Spacer(1, 1.8 * mm))
    else:
        # A single measured identity row keeps the logo, business name and address aligned.
        identity_width = doc.width * (0.56 if layout_style in {"modern", "editorial", "boxed", "bold", "dark"} else 0.76)
        if logo is not None:
            logo_gap = 3.0 * mm
            logo_column = logo_width + logo_gap
            identity_text_width = max(28 * mm, identity_width - logo_column)
            identity = Table(
                [[logo, [Paragraph(escape(business_name), business_name_style), *([contact_paragraph] if contact_paragraph else [])]]],
                colWidths=[logo_column, identity_text_width], hAlign="LEFT",
            )
            identity.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            business_block = [identity, Spacer(1, 2.0 * mm)]
        else:
            business_block = [Paragraph(escape(business_name), business_name_style)]
            if contact_paragraph:
                business_block.append(contact_paragraph)
            business_block.append(Spacer(1, 2.0 * mm))

    invoice_meta_top = Paragraph(
        f"<b>{escape(bill['bill_number'])}</b><br/>{escape(bill['invoice_date'])}<br/>"
        f"Due: {escape(bill.get('due_date') or 'Not specified')}<br/>"
        f"Status: {escape(bill['status'].replace('_', ' ').title())}", body_style,
    )

    story = []
    if layout_style in {"modern", "editorial", "boxed", "bold", "dark"}:
        title_paragraph = Paragraph(doc_label, doc_title_style)
        heading_data = [[business_block, [title_paragraph, invoice_meta_top]]]
        heading = Table(heading_data, colWidths=[doc.width * 0.58, doc.width * 0.42], hAlign="LEFT")
        heading.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        if layout_style in {"boxed", "bold", "dark"}:
            heading.setStyle(TableStyle([
                ("BACKGROUND", (1, 0), (1, 0), accent),
                ("BOX", (1, 0), (1, 0), 0.65, border),
                ("LEFTPADDING", (1, 0), (1, 0), 9), ("RIGHTPADDING", (1, 0), (1, 0), 9),
                ("TOPPADDING", (1, 0), (1, 0), 8), ("BOTTOMPADDING", (1, 0), (1, 0), 8),
            ]))
            right_meta_style = ParagraphStyle("KoshAccentMetaV031", parent=body_style, textColor=accent_text)
            invoice_meta_top = Paragraph(
                f"<b>{escape(bill['bill_number'])}</b><br/>{escape(bill['invoice_date'])}<br/>"
                f"Due: {escape(bill.get('due_date') or 'Not specified')}<br/>"
                f"Status: {escape(bill['status'].replace('_', ' ').title())}", right_meta_style,
            )
            heading_data = [[business_block, [title_paragraph, invoice_meta_top]]]
            heading = Table(heading_data, colWidths=[doc.width * 0.58, doc.width * 0.42], hAlign="LEFT")
            heading.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("BACKGROUND", (1, 0), (1, 0), accent), ("BOX", (1, 0), (1, 0), 0.65, border),
                ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 9),
                ("LEFTPADDING", (1, 0), (1, 0), 9), ("TOPPADDING", (1, 0), (1, 0), 8),
                ("BOTTOMPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 9),
                ("TOPPADDING", (0, 0), (0, 0), 0), ("BOTTOMPADDING", (0, 0), (0, 0), 0),
            ]))
        story.append(heading)
    elif layout_style in {"classic", "formal", "ledger", "minimal", "compact", "receipt"}:
        if layout_style == "receipt":
            story.extend(business_block)
            story.append(Spacer(1, 1 * mm))
            story.append(Paragraph(doc_label, ParagraphStyle("KoshReceiptTitleV031", parent=doc_title_style, alignment=TA_CENTER)))
            story.append(Paragraph(f"<b>{escape(bill['bill_number'])}</b> · {escape(bill['invoice_date'])}", center_style))
        else:
            story.extend(business_block)
            story.append(Paragraph(doc_label, doc_title_style))
            story.append(Paragraph(
                f"Invoice: <b>{escape(bill['bill_number'])}</b>  ·  Date: {escape(bill['invoice_date'])}  ·  "
                f"Due: {escape(bill.get('due_date') or 'Not specified')}  ·  Status: {escape(bill['status'].replace('_', ' ').title())}",
                small_style,
            ))
        if layout_style == "ledger":
            story.append(Spacer(1, 1.5 * mm))
            ruled = Table([[""]], colWidths=[doc.width], rowHeights=[0.8 * mm])
            ruled.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), accent)]))
            story.append(ruled)
    story.append(Spacer(1, 3 * mm if is_compact else 5 * mm))

    customer_details = [bill.get("customer_address", "")]
    customer_details.extend(value for value in [bill.get("customer_phone", ""), bill.get("customer_email", "")] if value)
    if bill.get("customer_gstin"):
        customer_details.append(f"GSTIN: {bill['customer_gstin']}")
    if bill.get("place_of_supply"):
        customer_details.append(f"Place of supply: {bill['place_of_supply']}")
    details_html = "<br/>".join(escape(value) for value in customer_details if value)
    customer_uses_surface = layout_style in {"boxed", "modern", "bold", "dark"}
    customer_heading = Paragraph(
        "BILL TO" if layout_style in {"modern", "editorial", "bold", "dark"} else "Customer / party",
        surface_label_style if customer_uses_surface else label_style,
    )
    customer_name = Paragraph(
        f"<b>{escape(bill['customer_name'])}</b>" + (f"<br/>{details_html}" if details_html else ""),
        surface_body_style if customer_uses_surface else body_style,
    )
    customer_type_box = Paragraph(
        f"<b>{escape(bill['customer_type'])}</b><br/>{escape(bill.get('document_type', 'tax_invoice').replace('_', ' ').title())}",
        surface_small_style if customer_uses_surface else small_style,
    )
    if page_size_name == "THERMAL_80":
        story.append(Paragraph("CUSTOMER", label_style))
        story.append(Paragraph(
            f"<b>{escape(bill['customer_name'])}</b>" + (f"<br/>{details_html}" if details_html else ""),
            body_style,
        ))
        story.append(Paragraph(
            f"{escape(bill['customer_type'])} · {escape(bill.get('document_type', 'tax_invoice').replace('_', ' ').title())}",
            small_style,
        ))
        story.append(Spacer(1, 2 * mm))
    else:
        customer_data = [[customer_heading, customer_type_box], [customer_name, ""]]
        customer_table = Table(customer_data, colWidths=[doc.width * 0.76, doc.width * 0.24], hAlign="LEFT")
        customer_style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8 if layout_style in {"boxed", "modern", "bold", "dark"} else 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8 if layout_style in {"boxed", "modern", "bold", "dark"} else 4),
            ("TOPPADDING", (0, 0), (-1, -1), 6 if layout_style in {"boxed", "modern", "bold", "dark"} else 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6 if layout_style in {"boxed", "modern", "bold", "dark"} else 3),
            ("SPAN", (0, 1), (1, 1)),
        ]
        if layout_style in {"boxed", "modern", "bold", "dark"}:
            customer_style.extend([("BACKGROUND", (0, 0), (-1, -1), surface), ("BOX", (0, 0), (-1, -1), 0.6, border)])
        else:
            customer_style.append(("LINEBELOW", (0, 0), (-1, 0), 0.7, accent))
        customer_table.setStyle(TableStyle(customer_style))
        story.append(customer_table)
        story.append(Spacer(1, 3 * mm if is_compact else 4 * mm))

    if page_size_name == "THERMAL_80":
        headings = ["#", "Item", "Qty", "Rate", "Total"]
        thermal_body_style = ParagraphStyle(
            "KoshThermalBodyV031", parent=body_style, fontSize=7.2, leading=8.2,
        )
        thermal_right_style = ParagraphStyle(
            "KoshThermalRightV031", parent=right_style, fontSize=6.4, leading=7.1,
        )
        thermal_surface_body_style = ParagraphStyle(
            "KoshThermalSurfaceBodyV031", parent=surface_body_style, fontSize=7.2, leading=8.2,
        )
        thermal_surface_right_style = ParagraphStyle(
            "KoshThermalSurfaceRightV031", parent=surface_right_style, fontSize=6.4, leading=7.1,
        )
        thermal_surface_small_style = ParagraphStyle(
            "KoshThermalSurfaceSmallV031", parent=surface_small_style, fontSize=6.6, leading=7.2,
        )
        thermal_small_style = ParagraphStyle(
            "KoshThermalSmallV031", parent=small_style, fontSize=6.6, leading=7.2,
        )
        rows = [[Paragraph(f"<b>{escape(head)}</b>", ParagraphStyle(
            "KoshThermalHeaderV031", parent=white_or_accent_style, fontSize=7.0, leading=7.5,
        )) for head in headings]]
        for index, item in enumerate(bill["items"], start=1):
            row_is_surface = index % 2 == 0
            row_body = thermal_surface_body_style if row_is_surface else thermal_body_style
            row_right = thermal_surface_right_style if row_is_surface else thermal_right_style
            row_small = thermal_surface_small_style if row_is_surface else thermal_small_style
            rows.append([
                Paragraph(str(index), row_small),
                Paragraph(escape(item["description"]), row_body),
                Paragraph(f"{Decimal(item['quantity']):f}", row_right),
                Paragraph(_money(item["unit_price"]), row_right),
                Paragraph(_money(item["line_total"]), row_right),
            ])
        widths = [doc.width * share for share in (0.07, 0.39, 0.11, 0.21, 0.22)]
        numeric_start = 2
    else:
        headings = ["#", "Description", "HSN/SAC", "Qty", "Rate", "Tax %", "Amount"]
        rows = [[Paragraph(f"<b>{escape(head)}</b>", white_or_accent_style) for head in headings]]
        for index, item in enumerate(bill["items"], start=1):
            row_is_surface = layout_style not in {"minimal", "editorial"} and index % 2 == 0
            row_body = surface_body_style if row_is_surface else body_style
            row_small = surface_small_style if row_is_surface else small_style
            row_right = surface_right_style if row_is_surface else right_style
            rows.append([
                Paragraph(str(index), row_small),
                Paragraph(escape(item["description"]), row_body),
                Paragraph(escape(item.get("hsn_sac", "")), row_small),
                Paragraph(f"{Decimal(item['quantity']):f} {escape(item.get('unit', ''))}", row_right),
                Paragraph(f"{currency_prefix}{_money(item['unit_price'])}", row_right),
                Paragraph(f"{Decimal(item['tax_rate']):g}%", row_right),
                Paragraph(f"{currency_prefix}{_money(item['line_total'])}", row_right),
            ])
        widths = [doc.width * share for share in (0.055, 0.325, 0.12, 0.12, 0.14, 0.09, 0.15)]
        numeric_start = 3
    item_table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("GRID", (0, 0), (-1, -1), 0.35 if layout_style in {"minimal", "editorial"} else 0.5, border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 if is_compact else 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 if is_compact else 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3 if is_compact else 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if is_compact else 6),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (numeric_start, 1), (-1, -1), "RIGHT"),
    ]
    if layout_style in {"minimal", "editorial"}:
        table_style.extend([("LINEBELOW", (0, 0), (-1, 0), 1.0, accent), ("GRID", (0, 1), (-1, -1), 0, border), ("LINEBELOW", (0, 1), (-1, -1), 0.3, border)])
    elif layout_style in {"ledger", "classic", "formal"}:
        table_style.append(("LINEBELOW", (0, 1), (-1, -1), 0.45, border))
    else:
        table_style.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [page_bg, surface]))
    item_table.setStyle(TableStyle(table_style))
    story.append(item_table)
    if page_size_name == "THERMAL_80":
        story.append(Paragraph("Amounts in INR", ParagraphStyle(
            "KoshThermalCurrencyNoteV031", parent=small_style, alignment=TA_RIGHT, fontSize=6.5,
        )))
    story.append(Spacer(1, 3 * mm if is_compact else 4 * mm))

    accent_body_style = ParagraphStyle("KoshAccentBodyV031", parent=body_style, fontName=font_bold, textColor=accent_text)
    accent_right_style = ParagraphStyle("KoshAccentRightV031", parent=right_style, fontName=font_bold, textColor=accent_text)
    money_rows = [
        ["Subtotal", f"{invoice_money_prefix}{_money(bill['subtotal'])}"],
        ["Discount", f"- {invoice_money_prefix}{_money(bill['discount_total'])}"],
        ["Taxable value", f"{invoice_money_prefix}{_money(bill['taxable_total'])}"],
        ["Tax total", f"{invoice_money_prefix}{_money(bill['tax_total'])}"],
        ["Grand total", f"{invoice_money_prefix}{_money(bill['grand_total'])}"],
        ["Paid", f"{invoice_money_prefix}{_money(bill['amount_paid'])}"],
        ["Balance due", f"{invoice_money_prefix}{_money(bill['balance_due'])}"],
    ]
    totals_rows = []
    totals_on_surface = layout_style in {"boxed", "modern", "bold", "dark"}
    totals_body_style = surface_body_style if totals_on_surface else body_style
    totals_right_style = surface_right_style if totals_on_surface else right_style
    totals_text = surface_text_color if totals_on_surface else text_color
    for label, value in money_rows:
        is_important = label in {"Grand total", "Balance due"}
        label_style_for_row = accent_body_style if label == "Grand total" else (ParagraphStyle("KoshEmphasisLabelV031", parent=totals_body_style, fontName=font_bold, textColor=totals_text) if is_important else totals_body_style)
        value_style_for_row = accent_right_style if label == "Grand total" else (ParagraphStyle("KoshEmphasisAmountV031", parent=totals_right_style, fontName=font_bold, textColor=totals_text) if is_important else totals_right_style)
        label_p = Paragraph(f"<b>{escape(label)}</b>" if is_important else escape(label), label_style_for_row)
        value_p = Paragraph(f"<b>{escape(value)}</b>" if is_important else escape(value), value_style_for_row)
        totals_rows.append([label_p, value_p])
    if page_size_name == "THERMAL_80":
        totals_width = doc.width * 0.98
    else:
        totals_width = doc.width * (0.58 if layout_style in {"receipt", "compact"} else 0.54)
    totals_table = Table(totals_rows, colWidths=[totals_width * 0.61, totals_width * 0.39], hAlign="RIGHT")
    totals_commands = [
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 2 if page_size_name == "THERMAL_80" else (3 if is_compact else 5)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if page_size_name == "THERMAL_80" else (3 if is_compact else 5)),
        ("LINEABOVE", (0, 4), (-1, 4), 1.0, accent),
        ("BACKGROUND", (0, 4), (-1, 4), accent),
        ("TEXTCOLOR", (0, 4), (-1, 4), accent_text),
        ("BOX", (0, 4), (-1, 4), 0.6, border),
        ("LINEABOVE", (0, 6), (-1, 6), 0.65, border),
    ]
    if layout_style in {"boxed", "modern", "bold", "dark"}:
        totals_commands.extend([("BACKGROUND", (0, 0), (-1, 3), surface), ("BACKGROUND", (0, 5), (-1, 6), surface), ("BOX", (0, 0), (-1, -1), 0.45, border)])
    else:
        totals_commands.extend([("LINEBELOW", (0, 0), (-1, 3), 0.25, border), ("LINEBELOW", (0, 5), (-1, 6), 0.25, border)])
    totals_table.setStyle(TableStyle(totals_commands))
    story.append(totals_table)
    story.append(Spacer(1, 4 * mm))

    # Optional invoice payment instructions, configured in Settings > Invoice & payments.
    payment_body = [Paragraph("PAYMENT DETAILS", label_style)]
    if invoice_profile.get("show_bank"):
        bank_lines = [
            ("Account holder", invoice_profile.get("bank_account_name", "")),
            ("Bank", invoice_profile.get("bank_name", "")),
            ("Account number", invoice_profile.get("account_number", "")),
            ("IFSC", invoice_profile.get("ifsc", "")),
            ("Branch", invoice_profile.get("branch", "")),
        ]
        for label, value in bank_lines:
            value = str(value or "").strip()
            if value:
                payment_body.append(Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", small_style))
    if invoice_profile.get("show_upi") and str(invoice_profile.get("upi_id") or "").strip():
        payment_body.append(Paragraph(f"<b>UPI ID:</b> {escape(str(invoice_profile['upi_id']).strip())}", body_style))
    qr_path_value = str(invoice_profile.get("qr_code_path") or "").strip()
    qr_image = None
    if invoice_profile.get("show_qr") and qr_path_value and Path(qr_path_value).is_file():
        try:
            qr_size = 17 * mm if page_size_name == "THERMAL_80" else 24 * mm
            qr_image = RLImage(qr_path_value, width=qr_size, height=qr_size, kind="proportional", hAlign="CENTER")
        except Exception:
            qr_image = None
    has_payment_text = len(payment_body) > 1
    if has_payment_text or qr_image is not None:
        if not has_payment_text:
            payment_body.append(Paragraph("Scan to pay", small_style))
        if qr_image is not None:
            payment_table = Table([[payment_body, qr_image]], colWidths=[max(20 * mm, doc.width - qr_size - 4 * mm), qr_size + 2 * mm], hAlign="LEFT")
        else:
            payment_table = Table([[payment_body]], colWidths=[doc.width], hAlign="LEFT")
        payment_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), surface), ("BOX", (0, 0), (-1, -1), 0.55, border),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7 if is_compact else 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7 if is_compact else 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5 if is_compact else 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5 if is_compact else 7),
        ]))
        story.append(KeepTogether([payment_table, Spacer(1, 3 * mm)]))

    note_blocks = []
    if bill.get("notes"):
        note_blocks.append([Paragraph("NOTES", label_style), Paragraph(escape(bill["notes"]).replace("\n", "<br/>"), body_style)])
    if bill.get("terms"):
        note_blocks.append([Paragraph("TERMS & CONDITIONS", label_style), Paragraph(escape(bill["terms"]).replace("\n", "<br/>"), small_style)])
    if note_blocks:
        if layout_style in {"boxed", "modern", "editorial", "bold", "dark"} and len(note_blocks) == 2:
            notes_table = Table([[note_blocks[0], note_blocks[1]]], colWidths=[doc.width / 2, doc.width / 2])
            notes_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), surface), ("BOX", (0, 0), (-1, -1), 0.5, border),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, border), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.append(notes_table)
        else:
            for block in note_blocks:
                story.append(KeepTogether([block[0], block[1], Spacer(1, 2 * mm)]))

    footer_text = escape(template.get("footer_text", "Thank you for your business.") or "Thank you for your business.")
    story.append(Spacer(1, 4 * mm if is_compact else 6 * mm))
    footer_style = ParagraphStyle(
        "KoshFooterV031", parent=small_style, alignment=TA_CENTER,
        textColor=muted_color, borderColor=border, borderWidth=0,
    )
    story.append(Paragraph(footer_text, footer_style))

    try:
        doc.build(story, onFirstPage=paint_page, onLaterPages=paint_page)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise PDFGenerationError(f"PDF could not be generated: {exc}") from exc
    return target
