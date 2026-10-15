"""Invoice theme presets and contrast-safe color normalization.

Purpose: Keep full-document PDF themes coordinated across color, layout and typography.
Canonical path: koshflow/services/theme_design.py
Project: KoshFlow | Version: 0.4.0
Developer: Mayank Chawdhari AKA BOSS294
Integration: Use resolve_theme_design(template) in PDF generation and live UI previews.
Changelog: v0.3.1 — Added full-document design presets, coordinated palettes and contrast checks.
"""

from __future__ import annotations

import json
import re
from typing import Any

HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Each preset intentionally changes more than a table heading: layout treatment,
# paper/surface colors, border weight, metadata cards and totals presentation vary.
PRESETS: dict[str, dict[str, Any]] = {
    "KoshFlow Classic": {"style": "modern", "colors": {"page_bg": "#FFFFFF", "text": "#20231C", "muted": "#62675C", "surface": "#F3F6EB", "border": "#D9E0CD", "accent_text": "#171916"}},
    "Mono Ledger": {"style": "ledger", "colors": {"page_bg": "#FFFFFF", "text": "#242720", "muted": "#5F625B", "surface": "#F0F1EF", "border": "#CFD1CC", "accent_text": "#FFFFFF"}},
    "Olive Register": {"style": "ledger", "colors": {"page_bg": "#FFFFFF", "text": "#292E22", "muted": "#646B58", "surface": "#F0F3E8", "border": "#D7DEC9", "accent_text": "#171916"}},
    "Forest Statement": {"style": "bold", "colors": {"page_bg": "#FBFDFC", "text": "#20352A", "muted": "#587064", "surface": "#EDF4EF", "border": "#CBDCD1", "accent_text": "#FFFFFF"}},
    "Cedar Paper": {"style": "editorial", "colors": {"page_bg": "#FFFCF7", "text": "#38291F", "muted": "#7B6251", "surface": "#F6EDE4", "border": "#E6D4C4", "accent_text": "#FFFFFF"}},
    "Burgundy Formal": {"style": "formal", "colors": {"page_bg": "#FFFCFD", "text": "#38212A", "muted": "#7C5963", "surface": "#F7EDF0", "border": "#E4CCD3", "accent_text": "#FFFFFF"}},
    "Graphite Invoice": {"style": "minimal", "colors": {"page_bg": "#FFFFFF", "text": "#292D29", "muted": "#666B66", "surface": "#F0F1EF", "border": "#D8DAD7", "accent_text": "#FFFFFF"}},
    "Ivory Trade": {"style": "editorial", "colors": {"page_bg": "#FFFEFA", "text": "#3B3323", "muted": "#766B51", "surface": "#F6F0E3", "border": "#E6D8B9", "accent_text": "#171916"}},
    "Terracotta Sales": {"style": "modern", "colors": {"page_bg": "#FFFCFA", "text": "#38261F", "muted": "#805E52", "surface": "#F7EEE9", "border": "#E7D3C9", "accent_text": "#FFFFFF"}},
    "Evergreen Goods": {"style": "boxed", "colors": {"page_bg": "#FBFDFC", "text": "#21362E", "muted": "#587167", "surface": "#EDF4F0", "border": "#CDDDD5", "accent_text": "#FFFFFF"}},
    "Sage Minimal": {"style": "minimal", "colors": {"page_bg": "#FFFFFF", "text": "#30392C", "muted": "#687262", "surface": "#F1F4EE", "border": "#DDE3D7", "accent_text": "#171916"}},
    "Copper Contract": {"style": "formal", "colors": {"page_bg": "#FFFCF8", "text": "#3C2D24", "muted": "#796253", "surface": "#F5ECE4", "border": "#E4D0BF", "accent_text": "#171916"}},
    "Charcoal Modern": {"style": "bold", "colors": {"page_bg": "#FFFFFF", "text": "#252823", "muted": "#666A61", "surface": "#EFF0ED", "border": "#D5D7D1", "accent_text": "#FFFFFF"}},
    "Olive Compact": {"style": "compact", "colors": {"page_bg": "#FFFFFF", "text": "#2C3025", "muted": "#696E5C", "surface": "#F2F4EB", "border": "#D8DEC9", "accent_text": "#171916"}},
    "Cedar Compact": {"style": "compact", "colors": {"page_bg": "#FFFCF7", "text": "#38291F", "muted": "#7B6251", "surface": "#F6EDE4", "border": "#E6D4C4", "accent_text": "#FFFFFF"}},
    "Market Receipt": {"style": "receipt", "colors": {"page_bg": "#FFFFFF", "text": "#20231C", "muted": "#676B61", "surface": "#F3F6EB", "border": "#CDD5C0", "accent_text": "#171916"}},
    "Clean Service": {"style": "modern", "colors": {"page_bg": "#FFFFFF", "text": "#283027", "muted": "#667062", "surface": "#F0F4EE", "border": "#D3DDD0", "accent_text": "#171916"}},
    "Formal Estimate": {"style": "formal", "colors": {"page_bg": "#FFFFFF", "text": "#2E3028", "muted": "#68695F", "surface": "#F2F2ED", "border": "#D8D8CF", "accent_text": "#FFFFFF"}},
    "Supplier Copy": {"style": "ledger", "colors": {"page_bg": "#FFFEFB", "text": "#353126", "muted": "#77705A", "surface": "#F6F2E8", "border": "#E1D7BD", "accent_text": "#171916"}},
    "Night Ledger": {"style": "dark", "colors": {"page_bg": "#171916", "text": "#F2F4ED", "muted": "#C2C8B9", "surface": "#242720", "border": "#454A3F", "accent_text": "#FFFFFF"}},
}

DEFAULT_COLORS = {
    "page_bg": "#FFFFFF",
    "text": "#20231C",
    "muted": "#62675C",
    "surface": "#F3F6EB",
    "border": "#D9E0CD",
    "accent_text": "#171916",
}
ALLOWED_STYLES = {"modern", "classic", "editorial", "boxed", "minimal", "compact", "formal", "ledger", "bold", "receipt", "dark"}


def _valid_hex(value: Any, fallback: str) -> str:
    value = str(value or "").strip()
    return value.upper() if HEX_PATTERN.fullmatch(value) else fallback


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def contrast_safe(foreground: str, background: str, minimum: float = 4.5) -> str:
    foreground = _valid_hex(foreground, "#20231C")
    background = _valid_hex(background, "#FFFFFF")
    if contrast_ratio(foreground, background) >= minimum:
        return foreground
    return "#171916" if contrast_ratio("#171916", background) >= contrast_ratio("#FFFFFF", background) else "#FFFFFF"


def resolve_theme_design(template: dict[str, Any] | None) -> dict[str, Any]:
    """Return a cohesive, contrast-checked theme and layout preset for a template row."""
    template = template or {}
    name = str(template.get("template_name", "KoshFlow Classic"))
    preset = PRESETS.get(name, PRESETS["KoshFlow Classic"])
    try:
        saved_layout = json.loads(template.get("layout_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        saved_layout = {}
    if not isinstance(saved_layout, dict):
        saved_layout = {}

    style = str(saved_layout.get("style", preset["style"]))
    if style not in ALLOWED_STYLES:
        style = preset["style"]
    saved_colors = saved_layout.get("colors", {})
    if not isinstance(saved_colors, dict):
        saved_colors = {}
    preset_colors = dict(DEFAULT_COLORS)
    preset_colors.update(preset.get("colors", {}))
    accent = _valid_hex(template.get("accent_color"), "#C9E86A")
    colors_map = {
        key: _valid_hex(saved_colors.get(key), preset_colors.get(key, DEFAULT_COLORS[key]))
        for key in DEFAULT_COLORS
    }

    # The saved accent is authoritative, but all neighboring colors are checked
    # against it and the page/surface they will actually appear on.
    colors_map["text"] = contrast_safe(colors_map["text"], colors_map["page_bg"], 4.5)
    colors_map["muted"] = contrast_safe(colors_map["muted"], colors_map["page_bg"], 4.0)
    colors_map["accent_text"] = contrast_safe(colors_map["accent_text"], accent, 4.5)
    colors_map["surface_text"] = contrast_safe(colors_map["text"], colors_map["surface"], 4.5)
    colors_map["surface_muted"] = contrast_safe(colors_map["muted"], colors_map["surface"], 4.0)

    return {
        "style": style,
        "colors": colors_map,
        "accent": accent,
        "layout": saved_layout.get("placements", {}) if isinstance(saved_layout.get("placements", {}), dict) else {},
    }


def layout_json_for_template(template: dict[str, Any]) -> dict[str, Any]:
    """Return editable layout JSON materialized with current resolved values."""
    design = resolve_theme_design(template)
    return {"style": design["style"], "colors": design["colors"], "placements": design["layout"]}
