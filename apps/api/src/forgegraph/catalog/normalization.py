from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

# Industrial placeholder strings that mean "no value"
DEFAULT_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "---",
    "n/a",
    "na",
    "n.a.",
    "unknown",
    "not available",
    "not applicable",
    "none",
    "null",
    "tbd",
    "to be determined",
    "pending",
    "see drawing",
    "see spec",
    "various",
    "assorted",
    "multiple",
    "contact factory",
    "contact supplier",
    "call for price",
    # Unilog / DIB / ERP-specific placeholders
    "-- no unilog brand --",
    "-- no dib brand --",
    "-- unbranded --",
    "-- no unilog manufacturer --",
    "-- no brand --",
    "-- no manufacturer --",
    "unbranded",
    "no brand",
    "generic",
    "oem",
    "private label",
}

# Canonical UOM aliases — covers all major industrial units
UNIT_ALIASES: dict[str, str] = {
    # Length — imperial
    "in": "in", "inch": "in", "inches": "in", '"': "in",
    "ft": "ft", "foot": "ft", "feet": "ft", "'": "ft",
    "yd": "yd", "yard": "yd", "yards": "yd",
    "mi": "mi", "mile": "mi", "miles": "mi",
    # Length — metric
    "mm": "mm", "millimeter": "mm", "millimeters": "mm",
    "millimetre": "mm", "millimetres": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm",
    "centimetre": "cm", "centimetres": "cm",
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "km": "km", "kilometer": "km", "kilometers": "km",
    # Weight — imperial
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "ton": "ton", "tons": "ton", "short ton": "ton",
    # Weight — metric
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "kilo": "kg",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "tonne": "tonne", "tonnes": "tonne", "metric ton": "tonne",
    # Pressure
    "psi": "psi", "lbs/sq in": "psi", "lb/in2": "psi", "pounds per square inch": "psi",
    "psig": "psig", "psia": "psia",
    "bar": "bar", "bars": "bar",
    "kpa": "kPa", "kilopascal": "kPa", "kilopascals": "kPa",
    "mpa": "MPa", "megapascal": "MPa", "megapascals": "MPa",
    "inHg": "inHg", "in hg": "inHg", "mmHg": "mmHg",
    # Temperature
    "°f": "°F", "f": "°F", "fahrenheit": "°F", "deg f": "°F", "deg. f": "°F",
    "°c": "°C", "c": "°C", "celsius": "°C", "centigrade": "°C", "deg c": "°C",
    "k": "K", "kelvin": "K",
    # Voltage
    "v": "V", "volt": "V", "volts": "V",
    "vac": "VAC", "vdc": "VDC",
    "kv": "kV", "kilovolt": "kV", "kilovolts": "kV",
    "mv": "mV", "millivolt": "mV", "millivolts": "mV",
    # Current
    "a": "A", "amp": "A", "amps": "A", "ampere": "A", "amperes": "A",
    "ma": "mA", "milliamp": "mA", "milliamps": "mA",
    "ka": "kA", "kiloamp": "kA", "kiloamps": "kA",
    # Power
    "w": "W", "watt": "W", "watts": "W",
    "kw": "kW", "kilowatt": "kW", "kilowatts": "kW",
    "mw": "MW", "megawatt": "MW", "megawatts": "MW",
    "hp": "HP", "h.p.": "HP", "horsepower": "HP",
    "va": "VA", "volt-amp": "VA",
    "kva": "kVA", "kilovolt-amp": "kVA",
    "btu/hr": "BTU/hr", "btu": "BTU", "british thermal unit": "BTU",
    # Frequency
    "hz": "Hz", "hertz": "Hz",
    "khz": "kHz", "kilohertz": "kHz",
    "mhz": "MHz", "megahertz": "MHz",
    # Flow
    "gpm": "GPM", "gal/min": "GPM", "gallons per minute": "GPM",
    "gph": "GPH", "gal/hr": "GPH", "gallons per hour": "GPH",
    "lpm": "LPM", "l/min": "LPM", "liters per minute": "LPM",
    "cfm": "CFM", "cubic feet per minute": "CFM",
    "m3/h": "m³/h", "m3/hr": "m³/h",
    # Torque
    "ft-lb": "ft·lb", "ft lb": "ft·lb", "foot pound": "ft·lb", "ft·lb": "ft·lb",
    "in-lb": "in·lb", "in lb": "in·lb", "inch pound": "in·lb",
    "nm": "N·m", "n.m": "N·m", "newton meter": "N·m", "newton-meter": "N·m",
    # Speed
    "rpm": "RPM", "r/min": "RPM", "rev/min": "RPM", "revolutions per minute": "RPM",
    # Illuminance / Light
    "lm": "lm", "lumen": "lm", "lumens": "lm",
    "lux": "lx", "lx": "lx",
    "fc": "fc", "foot-candle": "fc", "footcandle": "fc",
    # Percentage
    "%": "%", "percent": "%", "percentage": "%",
}


def clean_text(value: Any) -> str | None:
    """Clean a raw value — collapse whitespace, strip, reject placeholders."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    if cleaned.lower() in DEFAULT_PLACEHOLDERS:
        return None
    return cleaned or None


def normalize_key(value: Any) -> str:
    """Produce a canonical lookup key — lowercase, alphanumeric only."""
    cleaned = clean_text(value) or ""
    return re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def normalize_unit(value: Any) -> str | None:
    """Canonicalize a unit of measure alias to the canonical form."""
    cleaned = clean_text(value)
    if not cleaned:
        return None
    key = cleaned.lower().strip()
    return UNIT_ALIASES.get(key, cleaned)


def normalize_mpn(value: Any) -> str | None:
    """Clean a Manufacturer Part Number — remove common ERP prefixes/suffixes."""
    cleaned = clean_text(value)
    if not cleaned:
        return None
    # Remove common ERP wrapper patterns: [MPN-001], (MPN-001), "MPN-001"
    stripped = re.sub(r'^[\[\("\']+|[\]\)"\']+$', "", cleaned).strip()
    return stripped or cleaned


def decimal_to_fraction(value: Any, denominator: int = 16) -> str | None:
    """Convert a decimal number to a mixed-number fraction string.
    
    Examples: 0.5 → "1/2", 1.25 → "1 1/4", 2.0 → "2"
    """
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
    """Clean all values in a row — used at ingest time."""
    return {str(key).strip(): clean_text(value) for key, value in row.items()}


def first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    """Look up the first non-None value from a row by trying multiple column name aliases."""
    normalized = {normalize_key(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(normalize_key(alias))
        if value:
            return str(value)
    return None


def extract_numeric(value: Any) -> tuple[float | None, str | None]:
    """Split a value like '1.5 in' into (1.5, 'in') for UOM-aware comparison."""
    if value is None:
        return None, None
    text = str(value).strip()
    match = re.match(r"^([+-]?\d+(?:\.\d+)?(?:/\d+)?)\s*(.*)$", text)
    if not match:
        return None, None
    num_str, unit_str = match.group(1), match.group(2).strip()
    try:
        # Handle fractions like 1/2, 1 1/2
        if "/" in num_str:
            parts = num_str.split("/")
            num_val = float(parts[0]) / float(parts[1])
        else:
            num_val = float(num_str)
    except (ValueError, ZeroDivisionError):
        return None, None
    canonical_unit = normalize_unit(unit_str) if unit_str else None
    return num_val, canonical_unit
