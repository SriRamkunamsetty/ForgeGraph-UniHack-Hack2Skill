from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

DEFAULT_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "n.a.",
    "unknown",
    "not available",
    "-- no unilog brand --",
    "-- no dib brand --",
    "-- unbranded --",
    "-- no unilog manufacturer --",
}

UNIT_ALIASES = {
    "in": "in",
    "inch": "in",
    "inches": "in",
    '"': "in",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "psi": "psi",
    "volt": "V",
    "volts": "V",
    "v": "V",
    "fahrenheit": "°F",
    "deg f": "°F",
    "f": "°F",
}


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if cleaned.lower() in DEFAULT_PLACEHOLDERS:
        return None
    return cleaned or None


def normalize_key(value: Any) -> str:
    cleaned = clean_text(value) or ""
    return re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def normalize_unit(value: Any) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    key = cleaned.lower().replace("  ", " ")
    return UNIT_ALIASES.get(key, cleaned)


def decimal_to_fraction(value: Any, denominator: int = 16) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if decimal == decimal.to_integral_value():
        return str(int(decimal))
    whole = int(decimal)
    remainder = decimal - whole
    numerator = int((remainder * denominator).to_integral_value())
    if numerator == denominator:
        return str(whole + 1)
    if numerator == 0:
        return str(whole)
    from math import gcd

    divisor = gcd(numerator, denominator)
    numerator //= divisor
    denominator //= divisor
    if whole:
        return f"{whole} {numerator}/{denominator}"
    return f"{numerator}/{denominator}"


def canonicalize_row(row: Mapping[Any, Any]) -> dict[str, Any]:
    cleaned = {str(key).strip(): clean_text(value) for key, value in row.items()}
    return cleaned


def first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    normalized = {normalize_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(normalize_key(alias))
        if value:
            return str(value)
    return None
