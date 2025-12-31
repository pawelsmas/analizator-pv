"""
Rounding policy helpers for deterministic output.

Provides consistent rounding functions for financial and energy values:
- round_pln(x) -> round(x, 2) for PLN currency values
- round_mwh(x) -> round(x, 3) for MWh energy values
- round_kwh(x) -> round(x, 1) for kWh energy values
- round_kw(x) -> round(x, 1) for kW power values
- round_pct(x) -> round(x, 2) for percentage values

v1.6.0: Added for determinism and correctness freeze.
"""

from typing import Union

Number = Union[int, float]


def round_pln(value: Number) -> float:
    """
    Round PLN currency value to 2 decimal places (grosze).

    Args:
        value: PLN amount to round

    Returns:
        Rounded value with 2 decimal places

    Example:
        >>> round_pln(1234.5678)
        1234.57
    """
    return round(float(value), 2)


def round_mwh(value: Number) -> float:
    """
    Round MWh energy value to 3 decimal places.

    Args:
        value: MWh amount to round

    Returns:
        Rounded value with 3 decimal places

    Example:
        >>> round_mwh(1.23456)
        1.235
    """
    return round(float(value), 3)


def round_kwh(value: Number) -> float:
    """
    Round kWh energy value to 1 decimal place.

    Args:
        value: kWh amount to round

    Returns:
        Rounded value with 1 decimal place

    Example:
        >>> round_kwh(1234.56)
        1234.6
    """
    return round(float(value), 1)


def round_kw(value: Number) -> float:
    """
    Round kW power value to 1 decimal place.

    Args:
        value: kW amount to round

    Returns:
        Rounded value with 1 decimal place

    Example:
        >>> round_kw(500.456)
        500.5
    """
    return round(float(value), 1)


def round_pct(value: Number) -> float:
    """
    Round percentage value to 2 decimal places.

    Args:
        value: Percentage amount to round

    Returns:
        Rounded value with 2 decimal places

    Example:
        >>> round_pct(12.3456)
        12.35
    """
    return round(float(value), 2)
