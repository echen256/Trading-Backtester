"""Overlay long-only single-leg trades on a Fisher Transform of BigQuery OHLCV."""

from __future__ import annotations

import argparse
import json
import math
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .charts.enhanced_plotly import (
    AnnotatedTradeMarker,
    EnhancedChartSeries,
    build_enhanced_scrollable_figure,
    write_enhanced_chart_html,
)
from .display_common import (
    describe_contract,
    extract_contract_expiration,
    extract_contract_option_type,
    extract_contract_strike,
    extract_underlying_symbol,
)
from .export_tpo_grades import discover_tpo_grades_file, load_tpo_grades
from .parse_orders import (
    ORDER_DATA_DIR,
    RealizedTrade,
    analyze_orders,
    filter_orders,
    filter_orders_by_date,
    filter_trades_by_close_date,
    load_orders,
)
from .tpo.schema import find_grade_for_trade, make_trade_id

DEFAULT_ORDERS_CSV = ORDER_DATA_DIR / "orders.csv"
DEFAULT_HOLD_REVIEW = ORDER_DATA_DIR / "trade-hold-review-2026-01-01-to-2026-06-30.json"
DEFAULT_TABLE_ID = "e-observer-454820-b3:stock_data_bucket_dataset_256.stock-data-table-daily"
DEFAULT_LOCATION = "northamerica-northeast1"
DEFAULT_FISHER_LENGTH = 25


@dataclass(slots=True)
class HoldReviewFields:
    pre_exit_peak_pnl: float | None = None
    pre_exit_peak_date: str | None = None
    pre_exit_peak_price: float | None = None
    best_case_later_pnl: float | None = None
    best_case_later_exit_date: str | None = None
    best_case_later_exit_price: float | None = None
    realized_pnl: float | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pull ticker OHLCV from BigQuery, compute a Fisher Transform, and overlay "
            "long-only single-leg option/stock trade entries and exits."
        )
    )
    parser.add_argument("ticker", help="Underlying ticker symbol, e.g. AAPL")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_ORDERS_CSV,
        help=f"Orders CSV path (default: {DEFAULT_ORDERS_CSV})",
    )
    parser.add_argument("--start-date", help="Optional YYYY-MM-DD close-date filter start")
    parser.add_argument("--end-date", help="Optional YYYY-MM-DD close-date filter end")
    parser.add_argument(
        "--fisher-length",
        type=int,
        default=DEFAULT_FISHER_LENGTH,
        help=f"Fisher Transform lookback length (default: {DEFAULT_FISHER_LENGTH})",
    )
    parser.add_argument(
        "--table-id",
        default=DEFAULT_TABLE_ID,
        help=f"BigQuery table id (default: {DEFAULT_TABLE_ID})",
    )
    parser.add_argument(
        "--location",
        default=DEFAULT_LOCATION,
        help=f"BigQuery job location (default: {DEFAULT_LOCATION})",
    )
    parser.add_argument(
        "--local-csv",
        type=Path,
        help=(
            "Skip BigQuery and load OHLCV from this local CSV instead. "
            "If omitted and the ticker is missing from BigQuery, falls back to "
            "data-pipeline/data/1440/{TICKER}-1440M.csv or a Polygon download."
        ),
    )
    parser.add_argument(
        "--hold-review",
        type=Path,
        default=DEFAULT_HOLD_REVIEW,
        help=f"Hold-review JSON for missed PnL (default: {DEFAULT_HOLD_REVIEW})",
    )
    parser.add_argument(
        "--tpo-grades",
        type=Path,
        help="Optional TPO grades JSON for trade quality (default: newest in order-data)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="HTML output path (default: temp trading-analysis dir)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the chart in a browser",
    )
    parser.add_argument(
        "--visible-bars",
        type=int,
        default=120,
        help="Initial number of bars visible before scrolling (default: 120)",
    )
    parser.add_argument(
        "--skip-drilldowns",
        action="store_true",
        help="Skip generating 15m drill-down HTML pages for the D hotkey",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    ticker = args.ticker.strip().upper()
    start_date = _parse_iso_date(args.start_date)
    end_date = _parse_iso_date(args.end_date)
    if start_date and end_date and start_date > end_date:
        raise SystemExit("start-date must be on or before end-date")
    if args.fisher_length < 2:
        raise SystemExit("fisher-length must be >= 2")

    rows = _load_ohlcv_rows(
        ticker,
        local_csv=args.local_csv,
        table_id=args.table_id,
        location=args.location,
    )
    timestamps = [_as_utc_datetime(row["timestamp"]) for row in rows]
    opens = [float(row["open"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    closes = [float(row["close"]) for row in rows]
    medians = [(high + low) / 2.0 for high, low in zip(highs, lows)]
    fisher = compute_fisher_transform(medians, length=args.fisher_length)

    trades = load_long_only_single_leg_trades(
        ticker,
        csv_path=args.csv,
        start_date=start_date,
        end_date=end_date,
    )
    hold_index = load_hold_review_index(args.hold_review)
    grades_doc = _load_grades_doc(args.tpo_grades, start_date=start_date, end_date=end_date)

    markers = build_trade_markers(
        trades,
        timestamps=timestamps,
        fisher=fisher,
        hold_index=hold_index,
        grades_doc=grades_doc,
    )

    series = EnhancedChartSeries(
        timestamps=timestamps,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        indicator_values=fisher,
        indicator_name=f"Fisher {args.fisher_length}",
        ticker=ticker,
        title=(
            f"{ticker} Fisher {args.fisher_length} — "
            f"{len(trades)} long-only single-leg trade(s)"
        ),
    )
    figure = build_enhanced_scrollable_figure(
        series,
        markers,
        initial_visible_bars=args.visible_bars,
    )
    output_path = args.output
    if output_path is None:
        output_path = ORDER_DATA_DIR / f"{ticker.lower()}-fisher-trade-overlay.html"

    drilldown_dir = output_path.parent / f"{ticker.lower()}-fisher-drilldowns"
    drilldown_index: dict[str, str] = {}
    if not args.skip_drilldowns:
        drilldown_index = _generate_trade_drilldowns(
            ticker=ticker,
            trades=trades,
            markers=markers,
            hold_index=hold_index,
            output_dir=drilldown_dir,
        )

    output_path = write_enhanced_chart_html(
        figure,
        output_path,
        auto_open=False,
        drilldown_index=drilldown_index,
    )
    print(
        f"Wrote Fisher trade overlay for {ticker}: {len(rows)} bars, "
        f"{len(trades)} trades, {len(markers)} markers -> {output_path}"
    )
    if drilldown_index:
        print(f"Wrote {len(drilldown_index)} 15m drill-downs -> {drilldown_dir}")
    if not args.no_open:
        webbrowser.open(output_path.resolve().as_uri())


def compute_fisher_transform(values: Sequence[float], *, length: int) -> list[float | None]:
    """Ehlers Fisher Transform with recursive smoothing; None until warmup completes."""
    result: list[float | None] = []
    prev_smoothed = 0.0
    prev_fisher = 0.0
    for index, value in enumerate(values):
        start = max(0, index - length + 1)
        window = values[start : index + 1]
        highest = max(window)
        lowest = min(window)
        if highest == lowest:
            normalized = 0.0
        else:
            normalized = 2.0 * ((value - lowest) / (highest - lowest) - 0.5)
        clamped = max(-0.999, min(0.999, normalized))
        smoothed = 0.33 * clamped + 0.67 * prev_smoothed
        smoothed = max(-0.999, min(0.999, smoothed))
        fisher = 0.5 * math.log((1.0 + smoothed) / (1.0 - smoothed)) + 0.5 * prev_fisher
        result.append(fisher if index >= length - 1 else None)
        prev_smoothed = smoothed
        prev_fisher = fisher
    return result


def load_long_only_single_leg_trades(
    ticker: str,
    *,
    csv_path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[RealizedTrade]:
    """Load long-only equity and single-leg option trades for an underlying."""
    orders = load_orders(csv_path)
    orders = filter_orders(orders, symbol=ticker)
    orders = filter_orders_by_date(orders, None, end_date)
    trades = filter_trades_by_close_date(analyze_orders(orders).realized_trades, start_date, end_date)
    return [trade for trade in trades if is_long_only_single_leg(trade, ticker)]


def is_long_only_single_leg(trade: RealizedTrade, ticker: str) -> bool:
    underlying = (trade.underlying or extract_underlying_symbol(trade.symbol)).upper()
    if underlying != ticker.upper():
        return False
    if trade.direction != "long":
        return False
    if trade.open_price <= 0:
        # Vertical secondary legs are allocated $0 open price.
        return False

    instrument = (trade.instrument_type or "").upper()
    if instrument == "EQUITY" or trade.option_type == "EQUITY":
        return True
    if instrument == "OPTION" or extract_contract_expiration(trade.symbol) is not None:
        return True
    # Plain stock ticker with no OCC pattern.
    return trade.symbol.upper() == ticker.upper()


def load_hold_review_index(path: Path | None) -> dict[tuple[str, str, str, float, float, float], HoldReviewFields]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    index: dict[tuple[str, str, str, float, float, float], HoldReviewFields] = {}
    for bucket in ("profitable_trades", "unprofitable_trades"):
        for item in payload.get(bucket, []) or []:
            if not isinstance(item, dict):
                continue
            key = _hold_key_from_dict(item)
            if key is None:
                continue
            index[key] = HoldReviewFields(
                pre_exit_peak_pnl=_optional_float(item.get("pre_exit_peak_pnl")),
                pre_exit_peak_date=(
                    str(item["pre_exit_peak_date"]) if item.get("pre_exit_peak_date") else None
                ),
                pre_exit_peak_price=_optional_float(item.get("pre_exit_peak_price")),
                best_case_later_pnl=_optional_float(item.get("best_case_later_pnl")),
                best_case_later_exit_date=(
                    str(item["best_case_later_exit_date"])
                    if item.get("best_case_later_exit_date")
                    else None
                ),
                best_case_later_exit_price=_optional_float(item.get("best_case_later_exit_price")),
                realized_pnl=_optional_float(item.get("realized_pnl")),
            )
    return index


def build_trade_markers(
    trades: Sequence[RealizedTrade],
    *,
    timestamps: Sequence[datetime],
    fisher: Sequence[float | None],
    hold_index: dict[tuple[str, str, str, float, float, float], HoldReviewFields],
    grades_doc: Any,
) -> list[AnnotatedTradeMarker]:
    from .charts.trade_drilldown import resolve_ideal_exit

    markers: list[AnnotatedTradeMarker] = []
    for trade in trades:
        instrument = _instrument_label(trade)
        trade_id = make_trade_id(trade)
        hold = hold_index.get(_hold_key_from_trade(trade))
        missed_pnl, missed_label = _missed_pnl(trade, hold)
        quality, score = _trade_quality(trade, grades_doc)

        entry_dt, exit_dt = _normalized_trade_window(trade)
        _, entry_fisher = _point_on_series(entry_dt.date(), timestamps, fisher)
        _, exit_fisher = _point_on_series(exit_dt.date(), timestamps, fisher)
        entry_ts = _snap_to_series_timestamp(entry_dt, timestamps)
        exit_ts = _snap_to_series_timestamp(exit_dt, timestamps)

        ideal_exit_date = None
        ideal_exit_price = None
        ideal_exit_label = "Ideal exit"
        if hold is not None:
            ideal_exit_date, ideal_exit_price, ideal_exit_label = resolve_ideal_exit(
                entry_date=entry_dt.date(),
                actual_exit_date=exit_dt.date(),
                best_case_later_exit_date=hold.best_case_later_exit_date,
                best_case_later_exit_price=hold.best_case_later_exit_price,
                pre_exit_peak_date=hold.pre_exit_peak_date,
                pre_exit_peak_price=hold.pre_exit_peak_price,
                best_case_later_pnl=hold.best_case_later_pnl,
                pre_exit_peak_pnl=hold.pre_exit_peak_pnl,
                realized_pnl=hold.realized_pnl if hold.realized_pnl is not None else trade.pnl,
            )

        shared = dict(
            instrument=instrument,
            trade_id=trade_id,
            realized_pnl=trade.pnl,
            missed_pnl=missed_pnl,
            missed_pnl_label=missed_label,
            trade_quality=quality,
            quality_score=score,
            quantity=trade.quantity,
            open_price=trade.open_price,
            close_price=trade.price,
            ideal_exit_date=ideal_exit_date.isoformat() if ideal_exit_date else None,
            ideal_exit_price=ideal_exit_price,
            ideal_exit_label=ideal_exit_label,
            underlying=(trade.underlying or extract_underlying_symbol(trade.symbol)).upper(),
            entry_datetime=entry_dt.isoformat(),
            exit_datetime=exit_dt.isoformat(),
            strike=extract_contract_strike(trade.symbol),
            expiration=(
                extract_contract_expiration(trade.symbol).isoformat()
                if extract_contract_expiration(trade.symbol)
                else None
            ),
            option_type=extract_contract_option_type(trade.symbol) or (trade.option_type or None),
        )

        markers.append(
            AnnotatedTradeMarker(
                timestamp=entry_ts,
                y_value=entry_fisher,
                kind="entry",
                pair_timestamp=exit_ts,
                **shared,
            )
        )
        markers.append(
            AnnotatedTradeMarker(
                timestamp=exit_ts,
                y_value=exit_fisher,
                kind="exit",
                pair_timestamp=entry_ts,
                **shared,
            )
        )
    return markers


def _generate_trade_drilldowns(
    *,
    ticker: str,
    trades: Sequence[RealizedTrade],
    markers: Sequence[AnnotatedTradeMarker],
    hold_index: dict[tuple[str, str, str, float, float, float], HoldReviewFields],
    output_dir: Path,
) -> dict[str, str]:
    """Generate per-trade 15m drill-down HTML pages. Returns trade_id -> relative path."""
    from .charts.trade_drilldown import (
        build_trade_drilldown_figure,
        resolve_ideal_exit,
        write_trade_drilldown_html,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    by_id = {marker.trade_id: marker for marker in markers if marker.kind == "entry"}
    index: dict[str, str] = {}

    for trade in trades:
        trade_id = make_trade_id(trade)
        marker = by_id.get(trade_id)
        hold = hold_index.get(_hold_key_from_trade(trade))
        entry_dt, exit_dt = _normalized_trade_window(trade)
        ideal_date, ideal_price, ideal_label = resolve_ideal_exit(
            entry_date=entry_dt.date(),
            actual_exit_date=exit_dt.date(),
            best_case_later_exit_date=hold.best_case_later_exit_date if hold else None,
            best_case_later_exit_price=hold.best_case_later_exit_price if hold else None,
            pre_exit_peak_date=hold.pre_exit_peak_date if hold else None,
            pre_exit_peak_price=hold.pre_exit_peak_price if hold else None,
            best_case_later_pnl=hold.best_case_later_pnl if hold else None,
            pre_exit_peak_pnl=hold.pre_exit_peak_pnl if hold else None,
            realized_pnl=(hold.realized_pnl if hold and hold.realized_pnl is not None else trade.pnl),
        )

        ideal_dt = datetime.combine(ideal_date, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=20, minute=0
        )
        if ideal_dt < exit_dt:
            ideal_dt = exit_dt

        try:
            expiration = extract_contract_expiration(trade.symbol)
            figure = build_trade_drilldown_figure(
                underlying=ticker,
                instrument=_instrument_label(trade),
                entry_dt=entry_dt,
                actual_exit_dt=exit_dt,
                ideal_exit_dt=ideal_dt,
                ideal_exit_label=ideal_label,
                realized_pnl=trade.pnl,
                missed_pnl=marker.missed_pnl if marker else None,
                is_put=(trade.option_type or "").upper() == "PUT" or " Put " in _instrument_label(trade),
                strike=extract_contract_strike(trade.symbol),
                expiration=expiration,
            )
        except Exception as exc:  # noqa: BLE001 - keep overlay usable if one trade fails
            print(f"Drill-down skipped for {trade.symbol} ({trade_id}): {exc}")
            continue

        filename = f"{trade_id}.html"
        write_trade_drilldown_html(figure, output_dir / filename, auto_open=False)
        index[trade_id] = f"{output_dir.name}/{filename}"
    return index


def _default_local_daily_csv(ticker: str) -> Path:
    """Archive path used by trading-data-pipeline daily downloads."""
    try:
        from trading_data_pipeline.downloader import DEFAULT_DATA_DIR

        return DEFAULT_DATA_DIR / "1440" / f"{ticker.upper()}-1440M.csv"
    except ImportError:
        # Fallback when data-pipeline isn't installed editable.
        repo_data = (
            Path(__file__).resolve().parents[3]
            / "data-pipeline"
            / "data"
            / "1440"
            / f"{ticker.upper()}-1440M.csv"
        )
        return repo_data


def _download_daily_csv(ticker: str, output_path: Path) -> Path:
    try:
        from trading_data_pipeline.downloader import DownloadSettings, PolygonDownloader
    except ImportError as exc:
        raise SystemExit(
            f"Ticker {ticker} is not in BigQuery and trading-data-pipeline is unavailable "
            "to download from Polygon. Pass --local-csv PATH."
        ) from exc

    print(f"{ticker} not in BigQuery; downloading daily bars from Polygon → {output_path}")
    downloader = PolygonDownloader()
    path = downloader.download_symbol(
        ticker,
        settings=DownloadSettings(interval_minutes=1440, output_dir=output_path.parent.parent),
    )
    if path is None or not path.exists():
        raise SystemExit(f"Polygon download returned no daily bars for {ticker}")
    return path


def _load_ohlcv_rows(
    ticker: str,
    *,
    local_csv: Path | None,
    table_id: str,
    location: str,
) -> list[dict[str, object]]:
    if local_csv is not None:
        return _rows_from_csv(local_csv)

    archive = _default_local_daily_csv(ticker)

    try:
        from trading_data_pipeline.bigquery_pull import pull_ticker_dataframe
    except ImportError:
        if archive.exists():
            print(f"BigQuery client unavailable; using local archive {archive}")
            return _rows_from_csv(archive)
        path = _download_daily_csv(ticker, archive)
        return _rows_from_csv(path)

    try:
        df = pull_ticker_dataframe(
            ticker,
            table_id=table_id,
            location=location,
        )
    except LookupError:
        if archive.exists():
            print(f"No BigQuery rows for {ticker}; using local archive {archive}")
            return _rows_from_csv(archive)
        path = _download_daily_csv(ticker, archive)
        return _rows_from_csv(path)

    return df.to_dict(orient="records")


def _rows_from_csv(path: Path) -> list[dict[str, object]]:
    import csv

    if not path.exists():
        raise SystemExit(f"Local CSV not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, object]] = []
        for row in reader:
            rows.append(
                {
                    "timestamp": row["timestamp"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
    if not rows:
        raise SystemExit(f"No rows in {path}")
    return rows


def _load_grades_doc(
    path: Path | None,
    *,
    start_date: date | None,
    end_date: date | None,
) -> Any:
    grades_path = path
    if grades_path is None:
        grades_path = discover_tpo_grades_file(
            ORDER_DATA_DIR,
            start_date=start_date,
            end_date=end_date,
        )
    if grades_path is None or not grades_path.exists():
        return None
    return load_tpo_grades(grades_path)


def _instrument_label(trade: RealizedTrade) -> str:
    if (trade.instrument_type or "").upper() == "EQUITY" or trade.option_type == "EQUITY":
        return f"{trade.symbol} (stock)"
    if extract_contract_expiration(trade.symbol) is not None:
        return describe_contract(trade.symbol)
    return trade.symbol


def _missed_pnl(
    trade: RealizedTrade,
    hold: HoldReviewFields | None,
) -> tuple[float | None, str | None]:
    if hold is None:
        return None, None
    realized = hold.realized_pnl if hold.realized_pnl is not None else trade.pnl
    if hold.best_case_later_pnl is not None:
        return hold.best_case_later_pnl - realized, "Missed PnL (best later)"
    if hold.pre_exit_peak_pnl is not None:
        return hold.pre_exit_peak_pnl - realized, "Missed PnL (pre-exit peak)"
    return None, None


def _trade_quality(trade: RealizedTrade, grades_doc: Any) -> tuple[str | None, float | None]:
    record = find_grade_for_trade(grades_doc, trade)
    if record is None or not record.grade:
        return None, None
    grade = record.grade
    if isinstance(grade, dict):
        quality = grade.get("execution_quality")
        score = _optional_float(grade.get("overall_score"))
        return (str(quality) if quality else None), score
    quality = getattr(grade, "execution_quality", None)
    score = _optional_float(getattr(grade, "overall_score", None))
    return (str(quality) if quality else None), score


def _point_on_series(
    trade_date: date,
    timestamps: Sequence[datetime],
    values: Sequence[float | None],
) -> tuple[datetime, float]:
    index = _nearest_timestamp_index(trade_date, timestamps)
    y_value = values[index]
    if y_value is None:
        # Fall back to nearest non-null Fisher value.
        for offset in range(len(values)):
            left = index - offset
            right = index + offset
            if left >= 0 and values[left] is not None:
                return timestamps[left], float(values[left])
            if right < len(values) and values[right] is not None:
                return timestamps[right], float(values[right])
        y_value = 0.0
    return timestamps[index], float(y_value)


def _snap_to_series_timestamp(target: datetime, timestamps: Sequence[datetime]) -> datetime:
    """Map a fill timestamp onto the nearest series bar timestamp (for daily charts)."""
    target_utc = _as_utc_datetime(target)
    index = min(range(len(timestamps)), key=lambda i: abs(timestamps[i] - target_utc))
    return timestamps[index]


def _normalized_trade_window(trade: RealizedTrade) -> tuple[datetime, datetime]:
    """Return (entry, exit) datetimes with exit never earlier than entry.

    Expiration settlements used to be stamped at midnight, which made same-day
    0DTE entries appear after their exit. Prefer real fill times, then fall back
    to session open/close, and finally clamp exit >= entry.
    """
    if trade.open_datetime is not None:
        entry = _as_utc_datetime(trade.open_datetime)
    else:
        entry = datetime.combine(trade.open_date, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=14, minute=30
        )

    if trade.trade_datetime is not None:
        exit_ = _as_utc_datetime(trade.trade_datetime)
    else:
        exit_ = datetime.combine(trade.trade_date, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=20, minute=0
        )

    # Legacy midnight expiration stamps (naive or UTC) → treat as RTH close.
    if (
        exit_.hour == 0
        and exit_.minute == 0
        and exit_.second == 0
        and (trade.close_action or "").upper() == "EXPIRE"
    ):
        exit_ = datetime.combine(exit_.date(), datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=20, minute=0
        )

    if exit_ < entry:
        exit_ = entry
    return entry, exit_


def _nearest_timestamp_index(target_date: date, timestamps: Sequence[datetime]) -> int:
    target = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    return min(range(len(timestamps)), key=lambda index: abs(timestamps[index] - target))


def _hold_key_from_trade(trade: RealizedTrade) -> tuple[str, str, str, float, float, float]:
    return (
        trade.symbol,
        trade.open_date.isoformat(),
        trade.trade_date.isoformat(),
        float(trade.quantity),
        float(trade.open_price),
        float(trade.price),
    )


def _hold_key_from_dict(
    item: dict[str, Any],
) -> tuple[str, str, str, float, float, float] | None:
    try:
        return (
            str(item["symbol"]),
            str(item["open_date"]),
            str(item["close_date"]),
            float(item["quantity"]),
            float(item["open_price"]),
            float(item["close_price"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":  # pragma: no cover
    main()
