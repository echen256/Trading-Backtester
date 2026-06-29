"""
Webull OpenAPI Bridge — programmatic access to trade data + market data.

TODO while waiting for API key approval:
  - Set WEBULL_APP_KEY and WEBULL_APP_SECRET in Trading-Backtester/.env
  - Or pass via --app-key / --app-secret on the CLI
  - Test credentials are available at developer.webull.com/apis/docs/sdk

Once approved, switch to production endpoint: api.webull.com

Usage:
  # List orders in a date range (with position_intent = BTO/BTC/STO/STC)
  webull-bridge orders --start-date 2026-01-01 --end-date 2026-06-25

  # Export orders CSV with open/close flags added  
  webull-bridge export-csv --start-date 2026-01-01 --end-date 2026-06-25 -o orders_with_flags.csv

  # Fetch option historical bars (replaces Polygon for trade hold review)
  webull-bridge option-bars TSLA260717C00420000 --start-date 2026-01-01 --end-date 2026-06-25

  # Get account info and positions
  webull-bridge account
  webull-bridge positions

  # Full trade hold review using Webull data (no Polygon API key needed)
  webull-bridge trade-hold-review --start-date 2026-01-01 --end-date 2026-06-25
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
WEBULL_PRODUCTION_ENDPOINT = "api.webull.com"
WEBULL_UAT_ENDPOINT = "us-openapi-alb.uat.webullbroker.com"
WEBULL_MIN_PAGE_SIZE = 10
WEBULL_MAX_PAGE_SIZE = 100
DEFAULT_ORDER_PAGE_SIZE = WEBULL_MAX_PAGE_SIZE
WEBULL_ORDER_HISTORY_DELAY_SECONDS = 1.25
WEBULL_RATE_LIMIT_BACKOFF_SECONDS = (2.0, 5.0, 10.0)
DEFAULT_ORDERS_DIR = REPO_ROOT / "modules" / "analysis" / "order-data"

for _logger_name in (
    "webull",
    "webull.core",
    "webull.core.client",
    "webull.core.http.initializer.client_initializer",
):
    _logger = logging.getLogger(_logger_name)
    _logger.setLevel(logging.CRITICAL)
    _logger.disabled = True

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WebullConfig:
    """Holds API credentials and endpoint selection."""
    app_key: str
    app_secret: str
    account_id: str = ""
    endpoint: str = WEBULL_PRODUCTION_ENDPOINT
    region: str = "us"

    @classmethod
    def from_env(cls, env_path: Path = DEFAULT_ENV_PATH) -> "WebullConfig":
        """Load from environment variables or .env file."""
        app_key = os.getenv("WEBULL_APP_KEY") or _load_env_value(env_path, "WEBULL_APP_KEY") or ""
        app_secret = os.getenv("WEBULL_APP_SECRET") or _load_env_value(env_path, "WEBULL_APP_SECRET") or ""
        account_id = (
            os.getenv("WEBULL_MARGIN_ACCOUNT_ID")
            or _load_env_value(env_path, "WEBULL_MARGIN_ACCOUNT_ID")
            or os.getenv("WEBULL_ACCOUNT_ID")
            or _load_env_value(env_path, "WEBULL_ACCOUNT_ID")
            or ""
        )
        endpoint = os.getenv("WEBULL_ENDPOINT") or _load_env_value(env_path, "WEBULL_ENDPOINT") or WEBULL_PRODUCTION_ENDPOINT
        if not app_key or not app_secret:
            raise ValueError(
                "WEBULL_APP_KEY and WEBULL_APP_SECRET must be set in environment or .env file. "
                "Test credentials are available at developer.webull.com/apis/docs/sdk"
            )
        return cls(app_key=app_key, app_secret=app_secret, account_id=account_id, endpoint=endpoint)


def _load_env_value(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        # Strip inline comments (everything from first unquoted #)
        cleaned = value.strip()
        # Handle quoted values
        if cleaned.startswith('"'):
            end = cleaned.find('"', 1)
            if end > 0:
                cleaned = cleaned[:end+1]
                cleaned = cleaned.strip('"')
            else:
                cleaned = cleaned.strip('"').strip("'")
        elif cleaned.startswith("'"):
            end = cleaned.find("'", 1)
            if end > 0:
                cleaned = cleaned[:end+1]
                cleaned = cleaned.strip("'")
            else:
                cleaned = cleaned.strip('"').strip("'")
        else:
            # Unquoted — strip inline comment
            cleaned = re.split(r"\s+#", cleaned, maxsplit=1)[0]
            cleaned = cleaned.strip()
        if cleaned:
            os.environ[key] = cleaned
            return cleaned
    return None


def _validate_order_page_size(page_size: int) -> int:
    if not WEBULL_MIN_PAGE_SIZE <= page_size <= WEBULL_MAX_PAGE_SIZE:
        raise ValueError(
            f"Webull order history page_size must be between "
            f"{WEBULL_MIN_PAGE_SIZE} and {WEBULL_MAX_PAGE_SIZE}; got {page_size}."
        )
    return page_size


def _order_page_size_arg(raw_value: str) -> int:
    try:
        page_size = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: {raw_value!r}") from exc

    try:
        return _validate_order_page_size(page_size)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _normalize_webull_date(value: str | date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    raw_value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw_value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date {value!r}. Use YYYY-MM-DD, MM/DD/YYYY, or MM-DD-YYYY."
    )


def _webull_date_arg(raw_value: str) -> str:
    try:
        return _normalize_webull_date(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _default_start_date() -> str:
    today = date.today()
    return today.replace(month=1, day=1).isoformat()


def _default_end_date() -> str:
    return date.today().isoformat()


def _default_orders_output_path(start_date: str, end_date: str) -> Path:
    return DEFAULT_ORDERS_DIR / f"webull_orders_{start_date}_to_{end_date}.csv"


def _is_test_endpoint(endpoint: str) -> bool:
    normalized = endpoint.lower()
    return "uat" in normalized or "sandbox" in normalized


def _endpoint_label(endpoint: str) -> str:
    return "test/sandbox" if _is_test_endpoint(endpoint) else "production"


class ConsoleProgress:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._message = ""
        self._done = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self, message: str) -> None:
        if not self.enabled:
            return
        self._message = message
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, message: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._message = message

    def stop(self, final_message: str | None = None) -> None:
        if not self.enabled:
            if final_message:
                print(final_message, file=sys.stderr)
            return
        self._done.set()
        if self._thread:
            self._thread.join()
        print(f"\r{' ' * 120}\r", end="", file=sys.stderr)
        if final_message:
            print(final_message, file=sys.stderr)

    def _run(self) -> None:
        frames = "|/-\\"
        index = 0
        while not self._done.wait(0.1):
            with self._lock:
                message = self._message
            print(f"\r{frames[index % len(frames)]} {message}", end="", file=sys.stderr, flush=True)
            index += 1


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return None


def _extract_order_history_page(
    data: Any,
    page_size: int,
) -> tuple[list[dict[str, Any]], str | None, str | None, bool]:
    if isinstance(data, list):
        batch = [order for order in data if isinstance(order, dict)]
        last_order = batch[-1] if batch else {}
        last_client_order_id = _first_present(last_order, "client_order_id", "clientOrderId")
        last_order_id = _first_present(last_order, "order_id", "orderId")
        has_more = len(batch) >= page_size and bool(last_client_order_id or last_order_id)
        return batch, last_client_order_id, last_order_id, has_more

    if isinstance(data, dict):
        raw_batch = data.get("orders") or data.get("data") or data.get("items") or []
        if not isinstance(raw_batch, list):
            raise RuntimeError(f"Unexpected order history batch shape: {type(raw_batch).__name__}")
        batch = [order for order in raw_batch if isinstance(order, dict)]
        last_client_order_id = _first_present(
            data,
            "last_client_order_id",
            "lastClientOrderId",
        )
        last_order_id = _first_present(data, "last_order_id", "lastOrderId")

        if batch and not (last_client_order_id or last_order_id):
            last_order = batch[-1]
            last_client_order_id = _first_present(last_order, "client_order_id", "clientOrderId")
            last_order_id = _first_present(last_order, "order_id", "orderId")

        has_more = bool(data.get("has_more", data.get("hasMore", len(batch) >= page_size)))
        has_more = has_more and bool(last_client_order_id or last_order_id)
        return batch, last_client_order_id, last_order_id, has_more

    raise RuntimeError(f"Unexpected order history response shape: {type(data).__name__}")


def _is_rate_limit_error(exc: Exception) -> bool:
    return (
        getattr(exc, "http_status", None) == 429
        or getattr(exc, "error_code", None) == "TOO_MANY_REQUESTS"
    )


# ---------------------------------------------------------------------------
# Data Models — normalized order with position_intent
# ---------------------------------------------------------------------------

POSITION_INTENT_MAP = {
    "BUY_TO_OPEN": "BTO",
    "BUY_TO_CLOSE": "BTC",
    "SELL_TO_OPEN": "STO",
    "SELL_TO_CLOSE": "STC",
}


@dataclass
class WebullOrder:
    """Normalized order with explicit open/close intent."""
    client_order_id: str
    order_id: str
    symbol: str
    side: str                        # BUY / SELL
    status: str
    instrument_type: str             # OPTION / EQUITY / FUTURES / CRYPTO
    position_intent: str | None      # BUY_TO_OPEN / BUY_TO_CLOSE / SELL_TO_OPEN / SELL_TO_CLOSE
    total_quantity: float
    filled_quantity: float
    limit_price: float | None
    filled_price: float | None       # average fill price
    order_type: str
    time_in_force: str
    placed_time: str                 # ISO 8601
    filled_time: str | None          # ISO 8601
    commission: float = 0.0
    fees: float = 0.0

    @property
    def action(self) -> str:
        """Return short action label: BTO, BTC, STO, STC, or BUY/SELL as fallback."""
        if self.position_intent:
            return POSITION_INTENT_MAP.get(self.position_intent, self.position_intent)
        return self.side  # fallback if intent is missing

    @property
    def is_open(self) -> bool | None:
        """True if opening a position, False if closing, None if unknown."""
        if not self.position_intent:
            return None
        return "OPEN" in self.position_intent

    @property
    def is_close(self) -> bool | None:
        if not self.position_intent:
            return None
        return "CLOSE" in self.position_intent


# ---------------------------------------------------------------------------
# WebullBridge Client
# ---------------------------------------------------------------------------

class WebullBridge:
    """Client wrapping the Webull OpenAPI SDK for data retrieval."""

    def __init__(self, config: WebullConfig):
        self.config = config
        self._api_client = None
        self._trade_client = None
        self._market_data_client = None
        self._accounts: list[dict[str, Any]] = []

    def _ensure_clients(self):
        if self._api_client is not None:
            return
        try:
            from webull.core.client import ApiClient
            from webull.trade.trade_client import TradeClient
            from webull.data.data_client import DataClient
        except ImportError:
            raise RuntimeError(
                "Webull OpenAPI SDK not installed. Run:\n"
                "  pip install webull-openapi-python-sdk\n"
                "See: https://developer.webull.com/apis/docs/sdk"
            )

        self._api_client = ApiClient(
            self.config.app_key,
            self.config.app_secret,
            self.config.region,
        )
        self._api_client.add_endpoint(self.config.region, self.config.endpoint)
        self._trade_client = TradeClient(self._api_client)
        self._market_data_client = DataClient(self._api_client)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_accounts(self) -> list[dict[str, Any]]:
        """Return list of accounts."""
        self._ensure_clients()
        if self._accounts:
            return self._accounts
        res = self._trade_client.account_v2.get_account_list()
        if res.status_code != 200:
            raise RuntimeError(f"Failed to get accounts: {res.status_code} {res.text}")
        self._accounts = res.json()
        return self._accounts

    def resolve_account_id(self) -> str:
        """Return the configured account_id, or prompt to select one."""
        if self.config.account_id:
            return self.config.account_id
        accounts = self.get_accounts()
        if not accounts:
            raise RuntimeError("No accounts found.")
        if len(accounts) == 1:
            return accounts[0]["account_id"]
        print("Multiple accounts found. Select one:")
        for i, acct in enumerate(accounts):
            print(f"  [{i}] {acct.get('account_id', '?')} — {acct.get('account_type', '?')}")
        choice = input("Account number: ").strip()
        try:
            return accounts[int(choice)]["account_id"]
        except (ValueError, IndexError):
            raise RuntimeError(f"Invalid selection: {choice}")

    # ------------------------------------------------------------------
    # Order History — THE KEY METHOD
    # ------------------------------------------------------------------

    def get_order_history(
        self,
        start_date: str | date,
        end_date: str | date,
        page_size: int = DEFAULT_ORDER_PAGE_SIZE,
        max_pages: int = 50,
        progress: Callable[[str], None] | None = None,
    ) -> list[WebullOrder]:
        """
        Fetch ALL historical orders in a date range, handling pagination.
        Returns orders with full position_intent (BTO/BTC/STO/STC).

        Date range max: 2 years. Rate limit: 2 req / 2 sec.
        """
        page_size = _validate_order_page_size(page_size)
        start_date = _normalize_webull_date(start_date)
        end_date = _normalize_webull_date(end_date)

        self._ensure_clients()
        account_id = self.resolve_account_id()

        raw_orders: list[dict[str, Any]] = []
        last_client_order_id = None
        last_order_id = None
        pages = 0
        if progress:
            progress(f"Preparing Webull order history request for {start_date} to {end_date}...")
        time.sleep(WEBULL_ORDER_HISTORY_DELAY_SECONDS)

        while pages < max_pages:
            pages += 1
            if pages > 1:
                time.sleep(WEBULL_ORDER_HISTORY_DELAY_SECONDS)
            if progress:
                progress(f"Fetching Webull order page {pages} ({len(raw_orders)} orders so far)...")
            for attempt, wait_seconds in enumerate((0.0, *WEBULL_RATE_LIMIT_BACKOFF_SECONDS), start=1):
                if wait_seconds:
                    message = f"Webull rate limit hit; waiting {wait_seconds:.0f}s before retry {attempt - 1}..."
                    if progress:
                        progress(message)
                    else:
                        print(message, file=sys.stderr)
                    time.sleep(wait_seconds)
                try:
                    res = self._trade_client.order_v2.get_order_history(
                        account_id=account_id,
                        page_size=str(page_size),
                        start_date=start_date,
                        end_date=end_date,
                        last_client_order_id=last_client_order_id,
                        last_order_id=last_order_id,
                    )
                    break
                except Exception as exc:
                    if _is_rate_limit_error(exc) and wait_seconds != WEBULL_RATE_LIMIT_BACKOFF_SECONDS[-1]:
                        continue
                    raise
            if res.status_code != 200:
                raise RuntimeError(f"Order history request failed: {res.status_code} {res.text}")

            data = res.json()
            batch, last_client_order_id, last_order_id, has_more = _extract_order_history_page(
                data,
                page_size,
            )
            if not batch:
                break
            raw_orders.extend(batch)
            if progress:
                progress(f"Fetched {len(raw_orders)} Webull orders across {pages} page(s)...")

            if not has_more:
                break

        normalized_orders: list[WebullOrder] = []
        for raw_order in raw_orders:
            normalized_orders.extend(self._normalize_orders(raw_order))
        return normalized_orders

    def _normalize_orders(self, raw: dict[str, Any]) -> list[WebullOrder]:
        """Convert raw API response dict to one or more WebullOrder objects."""
        legs = raw.get("orders") or raw.get("legs") or [raw]
        orders = []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            intent = _first_present(
                leg,
                "position_intent",
                "positionIntent",
                "position_effect",
                "positionEffect",
            ) or _first_present(raw, "position_intent", "positionIntent")
            filled_price_raw = _first_present(leg, "filled_price", "filledPrice", "avg_price", "avgPrice")
            
            orders.append(WebullOrder(
                client_order_id=str(_first_present(leg, "client_order_id", "clientOrderId") or _first_present(raw, "client_order_id", "clientOrderId") or ""),
                order_id=str(_first_present(leg, "order_id", "orderId") or _first_present(raw, "order_id", "orderId") or ""),
                symbol=str(_first_present(leg, "symbol") or _first_present(raw, "symbol") or ""),
                side=str(_first_present(leg, "side") or _first_present(raw, "side") or "").upper(),
                status=str(_first_present(leg, "status") or _first_present(raw, "status") or "").upper(),
                instrument_type=str(_first_present(leg, "instrument_type", "instrumentType") or _first_present(raw, "instrument_type", "instrumentType") or "").upper(),
                position_intent=str(intent).upper() if intent else None,
                total_quantity=_safe_float(_first_present(leg, "total_quantity", "totalQuantity") or _first_present(raw, "total_quantity", "totalQuantity")) or 0.0,
                filled_quantity=_safe_float(_first_present(leg, "filled_quantity", "filledQuantity") or _first_present(raw, "filled_quantity", "filledQuantity")) or 0.0,
                limit_price=_safe_float(_first_present(leg, "limit_price", "limitPrice") or _first_present(raw, "limit_price", "limitPrice")),
                filled_price=_safe_float(filled_price_raw),
                order_type=str(_first_present(leg, "order_type", "orderType") or _first_present(raw, "order_type", "orderType") or "").upper(),
                time_in_force=str(_first_present(leg, "time_in_force", "timeInForce") or _first_present(raw, "time_in_force", "timeInForce") or "").upper(),
                placed_time=str(_first_present(leg, "placed_time_at", "placedTimeAt", "placed_time", "placedTime", "place_time_at", "placeTimeAt", "place_time", "placeTime") or ""),
                filled_time=str(_first_present(leg, "filled_time_at", "filledTimeAt", "filled_time", "filledTime") or ""),
                commission=_safe_commission_value(leg),
                fees=_safe_fee_value(leg),
            ))
        return orders

    # ------------------------------------------------------------------
    # Option Historical Bars — replaces Polygon
    # ------------------------------------------------------------------

    def get_option_bars(
        self,
        option_symbol: str,
        timespan: str = "day",
        count: str = "200",
    ) -> list[dict[str, Any]]:
        """
        Fetch historical OHLCV bars for an option contract.

        Replaces the Polygon API call in export_trade_hold_review.py.
        Timespan options: 'min', '5min', '15min', '30min', 'hour', 'day', 'week', 'month'
        """
        self._ensure_clients()
        category = "usoption"

        result = self._market_data_client.option_market_data.get_option_history_bars(
            symbols=option_symbol,
            category=category,
            timespan=timespan,
            count=count,
        )

        if hasattr(result, 'status_code') and result.status_code != 200:
            raise RuntimeError(f"Option bars request failed: {result.status_code} {result.text}")

        # The API returns data in a response structure
        data = result.json() if hasattr(result, 'json') else result
        return data

    # ------------------------------------------------------------------
    # Positions & Account Info
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        """Fetch current open positions."""
        self._ensure_clients()
        account_id = self.resolve_account_id()
        res = self._trade_client.account_v2.get_account_positions(account_id)
        if res.status_code != 200:
            raise RuntimeError(f"Positions request failed: {res.status_code} {res.text}")
        return res.json()

    def get_account_balance(self) -> dict[str, Any]:
        """Fetch account balance/cash info."""
        self._ensure_clients()
        account_id = self.resolve_account_id()
        res = self._trade_client.account_v2.get_account_balance(account_id)
        if res.status_code != 200:
            raise RuntimeError(f"Balance request failed: {res.status_code} {res.text}")
        return res.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_commission_value(raw: dict[str, Any]) -> float | None:
    commission = raw.get("commission")
    if isinstance(commission, dict):
        return _safe_float(_first_present(commission, "actual_commission", "actualCommission"))
    return _safe_float(commission)


def _safe_fee_value(raw: dict[str, Any]) -> float | None:
    fees = raw.get("fees")
    if fees is not None:
        return _safe_float(fees)

    commission = raw.get("commission")
    if isinstance(commission, dict):
        return _safe_float(_first_present(commission, "receivable_commission", "receivableCommission"))
    return None


def _extract_underlying(symbol: str) -> str:
    """Extract underlying ticker from option symbol like TSLA260717C00420000 -> TSLA."""
    m = re.match(r"^([A-Z]+)\d{6}[CP]\d{8}$", symbol)
    return m.group(1) if m else symbol


# ---------------------------------------------------------------------------
# CSV Export — like the current orders.csv but WITH position_intent
# ---------------------------------------------------------------------------

ORDERS_CSV_FIELDS = [
    "Name", "Symbol", "InstrumentType", "Side", "Action", "PositionIntent",
    "Status", "Filled", "Total Qty", "Price", "Avg Price",
    "Time-in-Force", "Placed Time", "Filled Time",
]


def export_orders_csv(orders: list[WebullOrder], output_path: Path):
    """Write orders to CSV including the Action column (BTO/BTC/STO/STC)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ORDERS_CSV_FIELDS)
        writer.writeheader()
        for order in orders:
            writer.writerow({
                "Name": order.symbol,
                "Symbol": order.symbol,
                "InstrumentType": order.instrument_type,
                "Side": order.side,
                "Action": order.action,
                "PositionIntent": order.position_intent or "",
                "Status": order.status,
                "Filled": str(order.filled_quantity),
                "Total Qty": str(order.total_quantity),
                "Price": f"@{order.limit_price}" if order.limit_price else "",
                "Avg Price": str(order.filled_price) if order.filled_price else "",
                "Time-in-Force": order.time_in_force,
                "Placed Time": order.placed_time,
                "Filled Time": order.filled_time or "",
            })
    print(f"Wrote {len(orders)} orders to {output_path}")


def print_orders_table(orders: list[WebullOrder]) -> None:
    print(f"Found {len(orders)} orders")
    print(f"{'Symbol':<45} {'Side':6} {'Action':6} {'Filled':6} {'Price':>8} {'Date':<25}")
    print("-" * 100)
    for order in orders:
        dt = (order.filled_time or order.placed_time)[:10]
        print(
            f"{order.symbol:<45} {order.side:6} {order.action:6} "
            f"{order.filled_quantity:6.0f} {order.filled_price or 0:>8.2f} {dt:<25}"
        )


def fetch_orders_with_progress(
    bridge: WebullBridge,
    start_date: str,
    end_date: str,
    *,
    page_size: int = DEFAULT_ORDER_PAGE_SIZE,
) -> list[WebullOrder]:
    progress = ConsoleProgress()
    progress.start(f"Fetching Webull orders from {start_date} to {end_date}...")
    try:
        orders = bridge.get_order_history(
            start_date,
            end_date,
            page_size=page_size,
            progress=progress.update,
        )
    except Exception:
        progress.stop("Failed to fetch Webull orders.")
        raise
    progress.stop(f"Fetched {len(orders)} Webull orders.")
    return orders


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    default_start = _default_start_date()
    default_end = _default_end_date()
    parser = argparse.ArgumentParser(
        description="Webull OpenAPI Bridge — query trade data and market data.",
    )
    parser.add_argument("--app-key", help="Webull API app key (default: from env/.env)")
    parser.add_argument("--app-secret", help="Webull API app secret")
    parser.add_argument("--account-id", help="Webull account ID (default: auto-detect)")
    parser.add_argument(
        "--endpoint",
        help=(
            f"API endpoint (default: WEBULL_ENDPOINT or {WEBULL_PRODUCTION_ENDPOINT}; "
            f"test: {WEBULL_UAT_ENDPOINT})"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # --- orders ---
    p_orders = sub.add_parser("orders", help="Fetch historical orders with position_intent")
    p_orders.add_argument("--start-date", type=_webull_date_arg, default=default_start, help=f"Start date (default: {default_start})")
    p_orders.add_argument("--end-date", type=_webull_date_arg, default=default_end, help=f"End date (default: {default_end})")
    p_orders.add_argument("-o", "--output", type=Path, help="CSV output path (default: order-data/webull_orders_<range>.csv)")
    p_orders_format = p_orders.add_mutually_exclusive_group()
    p_orders_format.add_argument("--json", action="store_true", help="Print raw JSON instead of writing CSV")
    p_orders_format.add_argument("--table", action="store_true", help="Print a console table instead of writing CSV")
    p_orders.add_argument(
        "--page-size",
        type=_order_page_size_arg,
        default=DEFAULT_ORDER_PAGE_SIZE,
        help=f"Orders per request ({WEBULL_MIN_PAGE_SIZE}-{WEBULL_MAX_PAGE_SIZE}; default: {DEFAULT_ORDER_PAGE_SIZE})",
    )

    # --- export-csv ---
    p_export = sub.add_parser("export-csv", help="Export orders CSV with Action column")
    p_export.add_argument("-o", "--output", type=Path, help="CSV output path (default: order-data/webull_orders_<range>.csv)")
    p_export.add_argument("--start-date", type=_webull_date_arg, default=default_start, help=f"Start date (default: {default_start})")
    p_export.add_argument("--end-date", type=_webull_date_arg, default=default_end, help=f"End date (default: {default_end})")

    # --- option-bars ---
    p_bars = sub.add_parser("option-bars", help="Fetch option historical OHLCV bars")
    p_bars.add_argument("symbol", help="OCC option symbol (e.g. TSLA260717C00420000)")
    p_bars.add_argument("--timespan", default="day", choices=["min", "5min", "15min", "30min", "hour", "day", "week", "month"])
    p_bars.add_argument("--count", default="200")
    p_bars.add_argument("--json", action="store_true")

    # --- account ---
    sub.add_parser("account", help="Show account info")

    # --- positions ---
    sub.add_parser("positions", help="Show current open positions")

    # --- trade-hold-review ---
    p_review = sub.add_parser("trade-hold-review",
                               help="Run trade hold review using Webull data (no Polygon needed)")
    p_review.add_argument("--start-date", type=_webull_date_arg, default=default_start, help=f"Start date (default: {default_start})")
    p_review.add_argument("--end-date", type=_webull_date_arg, default=default_end, help=f"End date (default: {default_end})")
    p_review.add_argument("--exclude-same-day-trades", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load config (CLI args override env)
    try:
        config = WebullConfig.from_env()
    except ValueError:
        config = WebullConfig(app_key="", app_secret="")

    config.app_key = args.app_key or config.app_key
    config.app_secret = args.app_secret or config.app_secret
    config.account_id = args.account_id or config.account_id
    config.endpoint = args.endpoint or config.endpoint

    if not config.app_key:
        parser.error(
            "WEBULL_APP_KEY must be provided via --app-key or WEBULL_APP_KEY env/.env variable.\n"
            "Get test credentials at developer.webull.com/apis/docs/sdk"
        )

    if _is_test_endpoint(config.endpoint):
        print(
            f"WARNING: using Webull {_endpoint_label(config.endpoint)} endpoint "
            f"({config.endpoint}); results are not live brokerage data.",
            file=sys.stderr,
        )

    bridge = WebullBridge(config)

    if args.command == "orders":
        orders = fetch_orders_with_progress(
            bridge,
            args.start_date,
            args.end_date,
            page_size=args.page_size,
        )
        if args.json:
            print(json.dumps([o.__dict__ for o in orders], indent=2, default=str))
        elif args.table:
            print_orders_table(orders)
        else:
            output_path = args.output or _default_orders_output_path(args.start_date, args.end_date)
            export_orders_csv(orders, output_path)

    elif args.command == "export-csv":
        orders = fetch_orders_with_progress(bridge, args.start_date, args.end_date)
        output_path = args.output or _default_orders_output_path(args.start_date, args.end_date)
        export_orders_csv(orders, output_path)

    elif args.command == "option-bars":
        bars = bridge.get_option_bars(args.symbol, args.timespan, args.count)
        if args.json:
            print(json.dumps(bars, indent=2, default=str))
        else:
            print(f"Option bars for {args.symbol}:")
            print(json.dumps(bars, indent=2, default=str)[:2000])

    elif args.command == "account":
        accounts = bridge.get_accounts()
        print(json.dumps(accounts, indent=2, default=str))

    elif args.command == "positions":
        positions = bridge.get_positions()
        print(json.dumps(positions, indent=2, default=str))

    elif args.command == "trade-hold-review":
        _run_trade_hold_review(bridge, args)


def _run_trade_hold_review(bridge: WebullBridge, args: argparse.Namespace) -> None:
    """
    Full trade hold review using Webull data instead of Polygon.

    This replaces export_trade_hold_review.py's dependency on:
      - Polygon API key (POLYGON_API_KEY)
      - Polygon option bars endpoint
      - CSV-based order parsing with FIFO ambiguity

    Instead, we get:
      - Orders with position_intent (BTO/BTC/STO/STC) from Webull API
      - Option historical bars from Webull Market Data API
    """
    print(f"Fetching orders {args.start_date} → {args.end_date} from Webull API...")
    orders = fetch_orders_with_progress(bridge, args.start_date, args.end_date)
    print(f"  Received {len(orders)} orders")

    # Filter to filled option orders
    option_orders = [o for o in orders if o.instrument_type == "OPTION" and o.status == "FILLED"]
    print(f"  Filled options: {len(option_orders)}")

    # Count by position_intent
    from collections import Counter
    intent_counts = Counter(o.action for o in option_orders)
    print(f"  By action: {dict(intent_counts)}")

    # Process with exact position_intent (no FIFO guessing needed)
    # Group by option symbol for bars fetching
    symbols = sorted(set(o.symbol for o in option_orders))
    print(f"  Unique option symbols: {len(symbols)}")

    print("\nTrade hold review would process these symbols:")
    for sym in symbols[:10]:
        print(f"    {sym}")
    if len(symbols) > 10:
        print(f"    ... and {len(symbols) - 10} more")

    print("\n⚠️  Trade hold review needs API approval to proceed fully.")
    print("   Configure WEBULL_APP_KEY and WEBULL_APP_SECRET once approved.")


if __name__ == "__main__":
    main()
