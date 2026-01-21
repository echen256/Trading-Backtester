#!/usr/bin/env python3
"""Convert Schwab rollover CSV exports into ``orders.csv`` format."""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

FIELDNAMES = [
    "Name",
    "Symbol",
    "Side",
    "Status",
    "Filled",
    "Total Qty",
    "Price",
    "Avg Price",
    "Time-in-Force",
    "Placed Time",
    "Filled Time",
]

OPTION_SYMBOL_RE = re.compile(
    r"^(?P<underlying>[A-Za-z0-9./-]+)\s+"
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+"
    r"(?P<strike>[0-9,.]+)\s+"
    r"(?P<option_type>[CP])$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Schwab CSV export into the orders.csv schema."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="schwab_orders.csv",
        help="Path to the Schwab CSV file (default: schwab_orders.csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="schwab_orders_converted.csv",
        help="Destination CSV path (default: schwab_orders_converted.csv)",
    )
    parser.add_argument(
        "--timezone",
        default="EST",
        help="Timezone label appended to timestamps (default: EST)",
    )
    return parser.parse_args()


SUPPORTED_ACTION_PREFIXES = {"buy", "sell", "expired"}


def read_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not any(row.values()):
                continue
            yield row


def convert_row(row: dict[str, str], timezone: str) -> dict[str, str]:
    action = (row.get("Action") or "").strip()
    if not action:
        raise ValueError("missing Action")

    raw_symbol = (row.get("Symbol") or "").strip()
    if not raw_symbol:
        raise ValueError("missing Symbol")

    name, symbol = normalize_symbol(raw_symbol)

    quantity = parse_decimal(row.get("Quantity"))
    if quantity is None:
        raise ValueError("missing Quantity")

    side = normalize_side(action, quantity)

    price = parse_decimal(row.get("Price"))
    if price is None and action.strip().lower().startswith("expired"):
        price = Decimal(0)

    timestamp = format_timestamp(row.get("Date"), timezone)

    return {
        "Name": name,
        "Symbol": symbol,
        "Side": side,
        "Status": "Filled",
        "Filled": format_decimal(quantity.copy_abs()),
        "Total Qty": format_decimal(quantity.copy_abs()),
        "Price": format_price(price),
        "Avg Price": format_decimal(price),
        "Time-in-Force": "DAY",
        "Placed Time": timestamp,
        "Filled Time": timestamp,
    }


def normalize_side(action: str, quantity: Decimal) -> str:
    token = action.strip().split()[0].lower()
    if token == "buy":
        return "Buy"
    if token == "sell":
        return "Sell"
    if token == "expired":
        return "Buy" if quantity < 0 else "Sell"
    raise ValueError(f"unsupported Action '{action}'")


def normalize_symbol(raw_symbol: str) -> tuple[str, str]:
    match = OPTION_SYMBOL_RE.match(raw_symbol)
    if not match:
        symbol = raw_symbol.strip().upper()
        return symbol, symbol

    underlying = sanitize_underlying(match.group("underlying"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    year = int(match.group("year"))
    option_type = match.group("option_type")
    strike_component = format_strike_component(match.group("strike"))

    expiration = datetime(year, month, day)
    occ_symbol = f"{underlying}{expiration:%y%m%d}{option_type}{strike_component}"
    return occ_symbol, occ_symbol


def sanitize_underlying(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value.upper())
    if not cleaned:
        raise ValueError(f"unable to parse underlying symbol '{value}'")
    return cleaned


def format_strike_component(strike_text: str) -> str:
    strike_value = parse_decimal(strike_text)
    if strike_value is None:
        raise ValueError("missing option strike")
    scaled = (strike_value * Decimal(1000)).quantize(Decimal("1"))
    return f"{int(scaled):08d}"


def parse_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid numeric value '{value}'") from exc


def format_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.to_integral())
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_price(value: Decimal | None) -> str:
    formatted = format_decimal(value)
    return f"@{formatted}" if formatted else ""


def format_timestamp(raw_date: str | None, timezone: str) -> str:
    if not raw_date:
        raise ValueError("missing Date")
    match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", raw_date)
    if not match:
        raise ValueError(f"invalid Date '{raw_date}'")
    date_text = match.group(1)
    try:
        parsed = datetime.strptime(date_text, "%m/%d/%Y")
    except ValueError as exc:
        raise ValueError(f"invalid Date '{raw_date}'") from exc
    return f"{parsed:%m/%d/%Y} 00:00:00 {timezone.strip()}".strip()


def convert_file(source: Path, target: Path, timezone: str) -> None:
    rows = []
    for line_number, row in enumerate(read_rows(source), start=2):
        action = row.get("Action")
        if not is_supported_action(action):
            continue
        raw_symbol = (row.get("Symbol") or "").strip()
        if not is_option_symbol(raw_symbol):
            continue
        try:
            rows.append(convert_row(row, timezone))
        except ValueError as exc:
            raise ValueError(f"Row {line_number}: {exc}") from exc

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    source = Path(args.input)
    target = Path(args.output)
    convert_file(source, target, args.timezone)
    print(f"Wrote {target} from {source}")


def is_supported_action(action: str | None) -> bool:
    if not action:
        return False
    token = action.strip().split()[0].lower()
    return token in SUPPORTED_ACTION_PREFIXES


def is_option_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    return bool(OPTION_SYMBOL_RE.match(symbol.strip()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - surface helpful errors
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
