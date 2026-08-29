"""Fetch last price, size from stop, run the swing sanity checklist."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from trading_analysis.market_data.env import DEFAULT_ENV_PATH, load_env_value
from trading_analysis.position_sizer.checklist import ChecklistReport, Status, run_checklist
from trading_analysis.position_sizer.price import LastPrice, fetch_last_price
from trading_analysis.position_sizer.size import PositionSize, compute_size

DEFAULT_EQUITY = 20_000.0


def default_equity() -> float:
    raw = os.getenv("TRADING_EQUITY") or load_env_value(DEFAULT_ENV_PATH, "TRADING_EQUITY")
    if raw:
        return float(raw)
    return DEFAULT_EQUITY


def parse_manual(pairs: list[str] | None) -> dict[str, Status]:
    allowed: set[str] = {"pass", "fail", "pending", "warn", "skip"}
    out: dict[str, Status] = {}
    for item in pairs or []:
        if "=" not in item:
            raise ValueError(f"manual check must be id=pass|fail, got {item!r}")
        key, value = item.split("=", 1)
        status = value.strip().lower()
        if status not in allowed:
            raise ValueError(f"unknown status {value!r} for {key}")
        out[key.strip().lower()] = status  # type: ignore[assignment]
    return out


def size_ticket(
    symbol: str,
    *,
    stop: float,
    side: str,
    instrument: str = "stock",
    entry: float | None = None,
    equity: float | None = None,
    risk_pct: float = 0.02,
    debit_cap_pct: float = 0.04,
    checklist: str = "swing",
    manual: dict[str, Status] | None = None,
    skip_macd: bool = False,
    last: LastPrice | None = None,
) -> dict[str, Any]:
    quote = last or fetch_last_price(symbol)
    fill = entry if entry is not None else quote.price
    sized = compute_size(
        entry=fill,
        stop=stop,
        equity=equity if equity is not None else default_equity(),
        side=side,  # type: ignore[arg-type]
        instrument=instrument,  # type: ignore[arg-type]
        risk_pct=risk_pct,
        debit_cap_pct=debit_cap_pct,
    )
    report = run_checklist(
        sized,
        symbol=symbol,
        catalog=checklist,
        manual=manual,
        fetch_macd=not skip_macd,
    )
    return {
        "price": quote.to_dict(),
        "size": sized.to_dict(),
        "checklist": report.to_dict(),
        "blocked": report.blocked or sized.quantity <= 0,
    }


def format_report(payload: dict[str, Any]) -> str:
    price = payload["price"]
    size = payload["size"]
    checks: list[dict[str, Any]] = payload["checklist"]["results"]
    macd = payload["checklist"].get("macd")
    unit = "contracts" if size["instrument"] == "option" else "shares"
    lines = [
        f"{price['requested']}  last {price['price']}  [{price.get('source', '?')}]  {price.get('as_of_utc') or ''}".rstrip(),
        f"Side {size['side']}  entry {size['entry']}  stop {size['stop']}  "
        f"1R ${size['risk_dollars']:,.0f} ({size['risk_pct']:.0%} of ${size['equity']:,.0f})",
        f"Size {size['quantity']} {unit}  notional ${size['notional']:,.0f}  "
        f"({size['debit_pct']:.1%} of equity)  3R → {size['three_r_price']}",
    ]
    if size["notes"]:
        lines.append("Notes:")
        lines.extend(f"  - {note}" for note in size["notes"])
    if macd:
        top = " TOP" if macd["at_top"] else ""
        bot = " BOTTOM" if macd["at_bottom"] else ""
        lines.append(
            f"MACD hist {macd['last']}  {macd['extension']}  {macd['sign']}  "
            f"{macd['slope']}{top}{bot}"
        )
    lines.append("Checklist:")
    mark = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "pending": "…. ", "skip": "skip"}
    for item in checks:
        tag = mark.get(item["status"], item["status"])
        lines.append(f"  [{tag}] {item['id']} — {item['detail']}")
    if payload["blocked"]:
        lines.append("BLOCKED — do not send.")
    else:
        pending = [item for item in checks if item["status"] == "pending"]
        if pending:
            lines.append(
                "Size is legal. Manual gates still pending: "
                + ", ".join(item["id"] for item in pending)
            )
        else:
            lines.append("Gates clear.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Last price + stop-based size + swing sanity checklist.",
    )
    parser.add_argument("symbol", help="Ticker (QQQ, GLD, BTC, …)")
    parser.add_argument("--stop", type=float, required=True, help="Stop price (stock or option premium)")
    parser.add_argument("--side", required=True, choices=("long", "short"))
    parser.add_argument("--instrument", default="stock", choices=("stock", "option"))
    parser.add_argument("--entry", type=float, default=None, help="Override last price")
    parser.add_argument("--equity", type=float, default=None, help="Trading equity (default TRADING_EQUITY or 20000)")
    parser.add_argument("--risk-pct", type=float, default=0.02)
    parser.add_argument("--debit-cap-pct", type=float, default=0.04)
    parser.add_argument("--checklist", default="swing")
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help="Manual gate: hurry=pass, concurrent_names=fail, …",
    )
    parser.add_argument("--skip-macd", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload = size_ticket(
        args.symbol,
        stop=args.stop,
        side=args.side,
        instrument=args.instrument,
        entry=args.entry,
        equity=args.equity,
        risk_pct=args.risk_pct,
        debit_cap_pct=args.debit_cap_pct,
        checklist=args.checklist,
        manual=parse_manual(args.check),
        skip_macd=args.skip_macd,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    print(format_report(payload))


if __name__ == "__main__":
    main()
