from __future__ import annotations

import re
from datetime import date, datetime


def describe_contract(name: str) -> str:
    match = re.match(r"([A-Z]+)(\d{6})([CP])(\d{8})", name)
    if not match:
        return name
    symbol, _, option_type, strike_raw = match.groups()
    option_label = "Call" if option_type == "C" else "Put"
    strike_value = int(strike_raw) / 1000.0
    if strike_value.is_integer():
        strike_text = f"{strike_value:.0f}"
    else:
        strike_text = f"{strike_value:.3f}".rstrip("0").rstrip(".")
    return f"{symbol} {option_label} {strike_text}"


def extract_underlying_symbol(symbol: str) -> str:
    match = re.match(r"([A-Z]+)(\d{6})([CP])(\d{8})", symbol)
    if match:
        return match.group(1)
    return symbol


def extract_contract_expiration(symbol: str) -> date | None:
    match = re.match(r"([A-Z]+)(\d{6})([CP])(\d{8})", symbol)
    if not match:
        return None
    expiration_text = match.group(2)
    return datetime.strptime(expiration_text, "%y%m%d").date()


def describe_contract_timing(symbol: str, initiated_date: date) -> str | None:
    expiration = extract_contract_expiration(symbol)
    if expiration is None:
        return None
    dte = (expiration - initiated_date).days
    return f"Expiration: {expiration.isoformat()} | Open DTE: {dte}"


def format_currency(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"
