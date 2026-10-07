"""Parsen und Formatieren von Mengenangaben wie "2 kg Mehl" oder "Milch (1,5 l)"."""

from __future__ import annotations

import re

from .const import CONVERSION, DEFAULT_UNIT, UNIT_LABELS

UNIT_ALIASES: dict[str, list[str]] = {
    "stk": ["stk", "stk.", "stück", "stueck", "st.", "x"],
    "pkg": ["pkg", "pkg.", "pck", "pck.", "packung", "packungen", "pack", "päckchen"],
    "dose": ["dose", "dosen"],
    "flasche": ["flasche", "flaschen", "fl", "fl."],
    "bund": ["bund", "bd.", "bd"],
    "g": ["g", "gr", "gr.", "gramm"],
    "kg": ["kg", "kilo", "kilogramm"],
    "ml": ["ml", "milliliter"],
    "l": ["l", "liter", "ltr", "ltr."],
}
_ALIAS_TO_UNIT = {
    alias: unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases
}
_UNIT = "|".join(
    re.escape(alias) for alias in sorted(_ALIAS_TO_UNIT, key=len, reverse=True)
)
_NUM = r"\d+(?:[.,]\d+)?"

# "2 kg Mehl", "500g Hack", "3 Äpfel", "2x Milch"
_LEADING = re.compile(
    rf"^\s*(?P<qty>{_NUM})\s*(?:(?P<unit>{_UNIT})(?=[\s)]|$)\s*|\s+)(?P<name>.+?)\s*$",
    re.IGNORECASE,
)
# "Milch (1,5 l)", "Eier (10)" – das Format, das die To-do-Entität ausgibt
_PARENS = re.compile(
    rf"^\s*(?P<name>.+?)\s*\(\s*(?P<qty>{_NUM})\s*(?:(?P<unit>{_UNIT}))?\s*\)\s*$",
    re.IGNORECASE,
)
# "Mehl 2 kg", "Mehl - 2kg" (Einheit hier Pflicht, sonst wäre "Windeln Größe 4" eine Menge)
_TRAILING = re.compile(
    rf"^\s*(?P<name>.+?)\s*[-–:,]?\s*(?P<qty>{_NUM})\s*(?P<unit>{_UNIT})\s*$",
    re.IGNORECASE,
)


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def _clean_name(name: str) -> str:
    name = name.strip()
    return name[:1].upper() + name[1:] if name else name


def parse_item(text: str) -> tuple[str, float | None, str | None]:
    """Zerlegt einen Freitext in (Name, Menge, Einheit)."""
    text = text.strip()
    for pattern in (_PARENS, _LEADING, _TRAILING):
        if match := pattern.match(text):
            unit = match.group("unit")
            return (
                _clean_name(match.group("name")),
                _to_float(match.group("qty")),
                _ALIAS_TO_UNIT[unit.lower()] if unit else DEFAULT_UNIT,
            )
    return _clean_name(text), None, None


def format_number(value: float) -> str:
    """1.5 -> "1,5", 2.0 -> "2"."""
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def format_quantity(quantity: float | None, unit: str | None) -> str:
    if quantity is None:
        return ""
    label = UNIT_LABELS.get(unit or "", "")
    return f"{format_number(quantity)} {label}".strip()


def format_summary(name: str, quantity: float | None, unit: str | None) -> str:
    """Text für die To-do-Entität, z. B. "Mehl (2 kg)"."""
    qty = format_quantity(quantity, unit)
    return f"{name} ({qty})" if qty else name


def _normalize(total: float, base: str) -> tuple[float, str]:
    """Wandelt große Basismengen in die größere Einheit um (1500 g -> 1,5 kg)."""
    if total >= 1000:
        return round(total / 1000, 3), "kg" if base == "g" else "l"
    return round(total, 3), base


def merge_quantities(
    q1: float | None, u1: str | None, q2: float | None, u2: str | None
) -> tuple[float | None, str | None] | None:
    """Addiert zwei Mengen. None, wenn die Einheiten nicht zusammenpassen."""
    if q2 is None:
        return q1, u1
    if q1 is None:
        return q2, u2
    if u1 == u2:
        return round(q1 + q2, 3), u1
    c1, c2 = CONVERSION.get(u1 or ""), CONVERSION.get(u2 or "")
    if c1 and c2 and c1[0] == c2[0]:
        return _normalize(q1 * c1[1] + q2 * c2[1], c1[0])
    return None
