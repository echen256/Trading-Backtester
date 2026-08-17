"""Catalogue entered assets whose adaptive MACD formed strong trends."""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from google.cloud import bigquery

from .strategies.fisher_adaptive_macd import StrategyConfig, compute_fisher_adaptive_macd_strategy
from .visualize import _load_rows

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORDER_FILES = (
    PACKAGE_ROOT.parent / "analysis" / "order-data" / "archive" / "orders-2025.csv",
    PACKAGE_ROOT.parent / "analysis" / "order-data" / "archive" / "orders-2026.csv",
    PACKAGE_ROOT.parent / "analysis" / "order-data" / "orders.csv",
)
DEFAULT_TABLE_ID = "e-observer-454820-b3:stock_data_bucket_dataset_256.stock-data-table-daily"
DEFAULT_LOCATION = "northamerica-northeast1"
DEFAULT_LOCAL_DATA_DIR = PACKAGE_ROOT / "data" / "1440"
OPTION_SYMBOL = re.compile(r"^([A-Z]+)\d{6}[CP]\d{8}$")


@dataclass(frozen=True, slots=True)
class TrendPeriod:
    ticker: str
    start: date
    confirmed: date
    end: date | None
    signal_ath_date: date
    signal_ath_value: float
    expanding_histogram_weeks: int
    entry_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class MicroTrendPeriod:
    ticker: str
    start: date
    qualified: date
    end: date | None
    trigger: str
    max_atr_expansion_pct: float
    entry_dates: tuple[date, ...]


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _underlying(symbol: str) -> str:
    normalized = symbol.strip().upper()
    match = OPTION_SYMBOL.fullmatch(normalized)
    return match.group(1) if match else normalized


def load_entry_dates(order_files: Iterable[Path], *, years: set[int]) -> dict[str, list[date]]:
    """Return distinct filled BUY dates by underlying.

    BUY fills are deliberately used as the entry definition.  They capture long
    stock/options entries without guessing whether each SELL was a close or a
    short opening order.
    """
    result: dict[str, set[date]] = defaultdict(set)
    seen_rows: set[tuple[str, ...]] = set()
    for path in order_files:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("Status") or "").strip().upper() != "FILLED":
                    continue
                if (row.get("Side") or "").strip().upper() != "BUY":
                    continue
                try:
                    if float((row.get("Filled") or "0").strip()) <= 0:
                        continue
                except ValueError:
                    continue
                entered = _as_date(row.get("Filled Time") or row.get("Placed Time"))
                symbol = (row.get("Symbol") or row.get("Name") or "").strip()
                if entered is None or entered.year not in years or not symbol:
                    continue
                fingerprint = tuple((row.get(name) or "").strip() for name in (
                    "Symbol", "Side", "Status", "Filled", "Avg Price", "Placed Time", "Filled Time"
                ))
                if fingerprint in seen_rows:
                    continue
                seen_rows.add(fingerprint)
                result[_underlying(symbol)].add(entered)
    return {ticker: sorted(dates) for ticker, dates in sorted(result.items())}


def _table_parts(table_id: str) -> tuple[str, str, str]:
    normalized = table_id.strip()
    if ":" in normalized:
        project, remainder = normalized.split(":", 1)
        dataset, table = remainder.split(".", 1)
        return project, dataset, table
    project, dataset, table = normalized.split(".", 2)
    return project, dataset, table


def fetch_daily_rows(
    tickers: list[str], *, table_id: str, location: str, start_date: str, end_date: str
) -> dict[str, list[dict[str, object]]]:
    """Fetch all requested daily bars in one BigQuery job."""
    if not tickers:
        return {}
    project, dataset, table = _table_parts(table_id)
    client = bigquery.Client(project=project)
    query = f"""
        SELECT DISTINCT UPPER(ticker) AS ticker, timestamp, open, high, low, close, volume
        FROM `{project}.{dataset}.{table}`
        WHERE UPPER(ticker) IN UNNEST(@tickers)
          AND timestamp >= @start_ts
          AND timestamp < @end_exclusive_ts
        ORDER BY ticker, timestamp
    """
    job = client.query(
        query,
        location=location,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("tickers", "STRING", tickers),
                bigquery.ScalarQueryParameter("start_ts", "TIMESTAMP", f"{start_date}T00:00:00Z"),
                bigquery.ScalarQueryParameter("end_exclusive_ts", "TIMESTAMP", f"{end_date}T00:00:00Z"),
            ]
        ),
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in job.result():
        timestamp = row.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        grouped[str(row.ticker)].append(
            {
                "timestamp": timestamp,
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume) if row.volume is not None else None,
            }
        )
    return dict(grouped)


def load_local_daily_rows(ticker: str) -> list[dict[str, object]]:
    """Use the checked-in daily archive when a ticker is absent from BigQuery."""
    csv_path = DEFAULT_LOCAL_DATA_DIR / f"{ticker.replace(':', '_')}-1440M.csv"
    return _load_rows(csv_path) if csv_path.exists() else []


def aggregate_bars(rows: list[dict[str, object]], *, timeframe_days: int = 7) -> list[dict[str, object]]:
    """Aggregate daily bars into weekly or fixed three-calendar-day bars."""
    if timeframe_days not in {3, 7}:
        raise ValueError("timeframe_days must be 3 or 7")
    buckets: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        timestamp = row["timestamp"]
        if not isinstance(timestamp, datetime):
            raise ValueError("Daily rows must have datetime timestamps")
        day = timestamp.date()
        bucket_start = day.fromordinal(day.toordinal() - day.weekday()) if timeframe_days == 7 else day.fromordinal(
            (day.toordinal() // timeframe_days) * timeframe_days
        )
        buckets[bucket_start].append(row)
    aggregated: list[dict[str, object]] = []
    for bucket_start in sorted(buckets):
        bars = sorted(buckets[bucket_start], key=lambda item: item["timestamp"])
        last = bars[-1]
        aggregated.append(
            {
                "timestamp": last["timestamp"],
                "open": bars[0]["open"],
                "high": max(float(item["high"]) for item in bars),
                "low": min(float(item["low"]) for item in bars),
                "close": last["close"],
                "volume": sum(float(item["volume"] or 0) for item in bars),
            }
        )
    return aggregated


def _timeframe_label(timeframe_days: int) -> str:
    return "weekly" if timeframe_days == 7 else "3-day"


def _max_expanding_histogram_run(values: list[float | None], start: int, end: int) -> int:
    best = current = 0
    for index in range(start, end + 1):
        value = values[index]
        previous = values[index - 1] if index > start else None
        if value is not None and previous is not None and value > 0 and value > previous:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _wilder_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains = [max(closes[index] - closes[index - 1], 0.0) for index in range(1, len(closes))]
    losses = [max(closes[index - 1] - closes[index], 0.0) for index in range(1, len(closes))]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    result[period] = 100.0 if average_loss == 0 else 100.0 - (100.0 / (1.0 + average_gain / average_loss))
    for index in range(period + 1, len(closes)):
        average_gain = ((average_gain * (period - 1)) + gains[index - 1]) / period
        average_loss = ((average_loss * (period - 1)) + losses[index - 1]) / period
        result[index] = 100.0 if average_loss == 0 else 100.0 - (100.0 / (1.0 + average_gain / average_loss))
    return result


def _wilder_atr(rows: list[dict[str, object]], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(rows)
    if len(rows) <= period:
        return result
    ranges = [float(rows[0]["high"]) - float(rows[0]["low"])]
    for index in range(1, len(rows)):
        high, low, prior_close = float(rows[index]["high"]), float(rows[index]["low"]), float(rows[index - 1]["close"])
        ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    atr = sum(ranges[1 : period + 1]) / period
    result[period] = atr
    for index in range(period + 1, len(rows)):
        atr = ((atr * (period - 1)) + ranges[index]) / period
        result[index] = atr
    return result


def find_strong_trends(
    ticker: str, rows: list[dict[str, object]], entry_dates: list[date], *, timeframe_days: int = 7, config: StrategyConfig | None = None
) -> list[TrendPeriod]:
    """Find confirmed zero-line trends satisfying the requested strength rule."""
    if len(rows) < 60:
        return []
    result = compute_fisher_adaptive_macd_strategy(
        rows, ticker=ticker, timeframe_minutes=timeframe_days * 1440, config=config or StrategyConfig(htf_tf="W")
    )
    macd = result.series["adaptive_macd"]
    signal = result.series["signal_line"]
    histogram = result.series["histogram"]
    dates = [row["timestamp"].date() for row in result.rows]
    periods: list[TrendPeriod] = []
    index = 1
    while index < len(dates):
        current_macd, current_signal = macd[index], signal[index]
        prior_macd, prior_signal = macd[index - 1], signal[index - 1]
        both_positive = current_macd is not None and current_signal is not None and current_macd > 0 and current_signal > 0
        was_both_positive = prior_macd is not None and prior_signal is not None and prior_macd > 0 and prior_signal > 0
        if not both_positive or was_both_positive:
            index += 1
            continue

        start = index
        end = len(dates) - 1
        for cursor in range(index + 1, len(dates)):
            candidate_signal = signal[cursor]
            if candidate_signal is not None and candidate_signal <= 0:
                end = cursor
                break

        # The first completed negative-histogram period must retain signal > 0.
        pullback_start: int | None = None
        confirmed: int | None = None
        cursor = start + 1
        while cursor <= end:
            if histogram[cursor] is not None and histogram[cursor] < 0:
                pullback_start = cursor
                while cursor <= end and histogram[cursor] is not None and histogram[cursor] < 0:
                    cursor += 1
                if cursor <= end:
                    pullback_signals = [value for value in signal[pullback_start:cursor] if value is not None]
                    if pullback_signals and min(pullback_signals) > 0:
                        confirmed = cursor
                break
            cursor += 1
        if confirmed is None:
            index = max(index + 1, end + 1)
            continue

        expanding = _max_expanding_histogram_run(histogram, start, end)
        prior_signals = [value for value in signal[:start] if value is not None]
        running_high = max(prior_signals) if prior_signals else float("-inf")
        ath_index: int | None = None
        for cursor in range(start, end + 1):
            value = signal[cursor]
            if value is not None and value > running_high:
                running_high = value
                ath_index = cursor
        if ath_index is not None and expanding >= 8:
            end_date = dates[end] if end < len(dates) - 1 or (signal[end] is not None and signal[end] <= 0) else None
            period_end = end_date or dates[-1]
            overlapping_entries = tuple(day for day in entry_dates if dates[start] <= day <= period_end)
            if overlapping_entries:
                periods.append(
                    TrendPeriod(
                        ticker=ticker,
                        start=dates[start],
                        confirmed=dates[confirmed],
                        end=end_date,
                        signal_ath_date=dates[ath_index],
                        signal_ath_value=float(signal[ath_index]),
                        expanding_histogram_weeks=expanding,
                        entry_dates=overlapping_entries,
                    )
                )
        index = max(index + 1, end + 1)
    return periods


def find_micro_trends(
    ticker: str,
    rows: list[dict[str, object]],
    entry_dates: list[date],
    *,
    atr_expansion_pct: float = 33.0,
    minimum_weeks: int = 3,
    timeframe_days: int = 7,
    config: StrategyConfig | None = None,
) -> list[MicroTrendPeriod]:
    """Find micro trends from a MACD or RSI-midline cross.

    Standard RSI has no zero line, so its 50 midline is used: RSI - 50 is the
    zero-centred RSI series described by the rule.
    """
    if len(rows) < 60:
        return []
    strategy = compute_fisher_adaptive_macd_strategy(
        rows, ticker=ticker, timeframe_minutes=timeframe_days * 1440, config=config or StrategyConfig(htf_tf="W")
    )
    macd, histogram = strategy.series["adaptive_macd"], strategy.series["histogram"]
    closes = [float(row["close"]) for row in strategy.rows]
    rsi, atr = _wilder_rsi(closes), _wilder_atr(strategy.rows)
    dates = [row["timestamp"].date() for row in strategy.rows]
    periods: list[MicroTrendPeriod] = []
    cursor = 1
    while cursor < len(dates):
        macd_cross = macd[cursor] is not None and macd[cursor - 1] is not None and macd[cursor - 1] <= 0 < macd[cursor]
        rsi_cross = rsi[cursor] is not None and rsi[cursor - 1] is not None and rsi[cursor - 1] <= 50 < rsi[cursor]
        if not (macd_cross or rsi_cross) or atr[cursor] is None or atr[cursor] <= 0:
            cursor += 1
            continue
        start = cursor
        trigger = "MACD + RSI-50" if macd_cross and rsi_cross else "MACD" if macd_cross else "RSI-50"
        end_index = len(dates) - 1
        for index in range(start + 1, len(dates)):
            if histogram[index] is not None and histogram[index] < 0:
                end_index = index
                break
        if end_index - start + 1 < minimum_weeks:
            cursor = max(cursor + 1, end_index + 1)
            continue
        atr_values = [value for value in atr[start : end_index + 1] if value is not None]
        max_expansion = ((max(atr_values) / float(atr[start])) - 1.0) * 100.0 if atr_values else 0.0
        if max_expansion >= atr_expansion_pct:
            period_end = dates[end_index] if end_index < len(dates) - 1 else dates[-1]
            overlapping_entries = tuple(day for day in entry_dates if dates[start] <= day <= period_end)
            if overlapping_entries:
                periods.append(
                    MicroTrendPeriod(
                        ticker=ticker,
                        start=dates[start],
                        qualified=dates[start + minimum_weeks - 1],
                        end=dates[end_index] if end_index < len(dates) - 1 else None,
                        trigger=trigger,
                        max_atr_expansion_pct=max_expansion,
                        entry_dates=overlapping_entries,
                    )
                )
        cursor = max(cursor + 1, end_index + 1)
    return periods


def find_prospective_micro_windows(
    rows: list[dict[str, object]], *, timeframe_days: int = 7, atr_expansion_pct: float = 33.0, minimum_weeks: int = 3
) -> list[dict[str, object]]:
    """Return zero-cross candidates that never matured into a micro trend.

    Completed candidates are historical/prospective setups; an unfinished one
    is a live prospective setup. Neither is a forecast beyond the final bar.
    """
    if len(rows) < 60:
        return []
    strategy = compute_fisher_adaptive_macd_strategy(
        rows, ticker="CHART", timeframe_minutes=timeframe_days * 1440, config=StrategyConfig(htf_tf="W")
    )
    macd, histogram = strategy.series["adaptive_macd"], strategy.series["histogram"]
    closes = [float(row["close"]) for row in strategy.rows]
    rsi, atr = _wilder_rsi(closes), _wilder_atr(strategy.rows)
    dates = [row["timestamp"].date() for row in strategy.rows]
    windows: list[dict[str, object]] = []
    cursor = 1
    while cursor < len(dates):
        macd_cross = macd[cursor] is not None and macd[cursor - 1] is not None and macd[cursor - 1] <= 0 < macd[cursor]
        rsi_cross = rsi[cursor] is not None and rsi[cursor - 1] is not None and rsi[cursor - 1] <= 50 < rsi[cursor]
        if not (macd_cross or rsi_cross) or atr[cursor] is None or atr[cursor] <= 0:
            cursor += 1
            continue
        start, end = cursor, len(dates) - 1
        ended = False
        for index in range(start + 1, len(dates)):
            if histogram[index] is not None and histogram[index] < 0:
                end, ended = index, True
                break
        atr_values = [value for value in atr[start : end + 1] if value is not None]
        expansion = ((max(atr_values) / float(atr[start])) - 1.0) * 100.0 if atr_values else 0.0
        if (end - start + 1 < minimum_weeks) or expansion < atr_expansion_pct:
            windows.append({"start": dates[start].isoformat(), "end": dates[end].isoformat(), "live": not ended})
        cursor = max(cursor + 1, end + 1)
    return windows


def _chart_html(
    ticker: str,
    rows: list[dict[str, object]],
    periods: list[TrendPeriod],
    micro_periods: list[MicroTrendPeriod],
    entries: list[date],
    chart_tickers: list[str],
    timeframe_days: int,
) -> str:
    strategy = compute_fisher_adaptive_macd_strategy(
        rows, ticker=ticker, timeframe_minutes=timeframe_days * 1440, config=StrategyConfig(htf_tf="W")
    )
    times = [row["timestamp"].date().isoformat() for row in strategy.rows]
    closes = [float(row["close"]) for row in strategy.rows]
    rsi = _wilder_rsi(closes)
    atr = _wilder_atr(strategy.rows)
    prospective_micro_periods = find_prospective_micro_windows(strategy.rows, timeframe_days=timeframe_days)
    payload = {
        "times": times,
        "open": [row["open"] for row in strategy.rows],
        "high": [row["high"] for row in strategy.rows],
        "low": [row["low"] for row in strategy.rows],
        "close": [row["close"] for row in strategy.rows],
        "macd": strategy.series["adaptive_macd"],
        "signal": strategy.series["signal_line"],
        "histogram": strategy.series["histogram"],
        "rsi": rsi,
        "atr": atr,
        "periods": [
            {"start": item.start.isoformat(), "confirmed": item.confirmed.isoformat(), "end": (item.end or strategy.rows[-1]["timestamp"].date()).isoformat()}
            for item in periods
        ],
        "microPeriods": [
            {"start": item.start.isoformat(), "qualified": item.qualified.isoformat(), "end": (item.end or strategy.rows[-1]["timestamp"].date()).isoformat()}
            for item in micro_periods
        ],
        "prospectiveMicroPeriods": prospective_micro_periods,
        "entries": [item.isoformat() for item in entries],
        "chartTickers": chart_tickers,
        "chartIndex": chart_tickers.index(ticker),
    }
    safe_ticker = html.escape(ticker)
    timeframe_label = _timeframe_label(timeframe_days)
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><title>{safe_ticker} {timeframe_label} adaptive trend</title>
<script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
<style>body{{margin:0;background:#0e1726;color:#e5eefc;font:14px ui-monospace,monospace}}main{{max-width:1440px;margin:auto;padding:24px}}#chart{{height:1080px}}.note{{color:#9db0cc}}.nav{{position:sticky;top:0;z-index:5;display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 16px;padding:10px 0;background:#0e1726}}button,select,a{{background:#152238;border:1px solid #38506f;border-radius:7px;color:#e5eefc;padding:8px 11px;font:inherit;text-decoration:none}}button{{cursor:pointer}}button:hover,a:hover{{border-color:#86d6e8}}select{{min-width:125px}}</style></head>
<body><main><div class=\"nav\"><a href=\"../README.md\">Catalogue</a><button id=\"previous\">← Previous</button><select id=\"asset-select\" aria-label=\"Select asset\"></select><button id=\"next\">Next →</button><span class=\"note\" id=\"position\"></span></div><h1>{safe_ticker} — {timeframe_label} adaptive-MACD trend periods</h1><p class=\"note\">Green = strong trend; orange = qualified micro trend; violet = prior prospective setup that did not mature; blue = current prospective setup. Price, MACD, RSI(14), and ATR(14) share one {timeframe_label} timeline. Drag horizontally to pan; mouse-wheel to zoom; use ←/→ arrow keys or the pinned controls to cycle assets.</p><div id=\"chart\"></div></main>
<script>const p={json.dumps(payload)};
const histColors=p.histogram.map((v,i)=>v==null?'rgba(0,0,0,0)':(v>=0?(i&&v>p.histogram[i-1]?'#86d6e8':'#347c91'):(i&&v<p.histogram[i-1]?'#ef5350':'#9b3e4f')));
const traces=[
 {{type:'candlestick',x:p.times,open:p.open,high:p.high,low:p.low,close:p.close,name:'{timeframe_label.title()} OHLC',xaxis:'x',yaxis:'y'}},
 {{type:'bar',x:p.times,y:p.histogram,name:'Histogram',marker:{{color:histColors}},xaxis:'x2',yaxis:'y2'}},
 {{type:'scatter',mode:'lines',x:p.times,y:p.macd,name:'Adaptive MACD',line:{{color:'#8ecae6',width:2}},xaxis:'x2',yaxis:'y2'}},
 {{type:'scatter',mode:'lines',x:p.times,y:p.signal,name:'Signal',line:{{color:'#ffd166',width:2}},xaxis:'x2',yaxis:'y2'}},
 {{type:'scatter',mode:'lines',x:p.times,y:p.rsi,name:'RSI (14)',line:{{color:'#c792ea',width:2}},xaxis:'x3',yaxis:'y3'}},
 {{type:'scatter',mode:'lines',x:p.times,y:p.times.map(()=>50),name:'RSI 50',line:{{color:'#9aa0a6',width:1,dash:'dot'}},xaxis:'x3',yaxis:'y3'}},
 {{type:'scatter',mode:'lines',x:p.times,y:p.atr,name:'ATR (14)',line:{{color:'#ff9f43',width:2}},xaxis:'x4',yaxis:'y4'}},
 {{type:'scatter',mode:'markers',x:p.entries,y:p.entries.map(d=>p.high[Math.max(0,p.times.findIndex(t=>t>=d))]),name:'BUY entry',marker:{{color:'#ffffff',size:8,symbol:'circle'}},xaxis:'x',yaxis:'y'}}
];
const shapes=[]; for(const t of p.periods){{shapes.push({{type:'rect',xref:'x',yref:'paper',x0:t.start,x1:t.end,y0:0,y1:1,fillcolor:'rgba(46,204,113,.16)',line:{{width:0}}}});shapes.push({{type:'line',xref:'x',yref:'paper',x0:t.confirmed,x1:t.confirmed,y0:0,y1:1,line:{{color:'#ffd166',dash:'dash'}}}})}} for(const t of p.microPeriods){{shapes.push({{type:'rect',xref:'x',yref:'paper',x0:t.start,x1:t.end,y0:0,y1:1,fillcolor:'rgba(255,152,0,.13)',line:{{width:0}}}});shapes.push({{type:'line',xref:'x',yref:'paper',x0:t.qualified,x1:t.qualified,y0:0,y1:1,line:{{color:'#ff9800',dash:'dot'}}}})}} for(const t of p.prospectiveMicroPeriods){{shapes.push({{type:'rect',xref:'x',yref:'paper',x0:t.start,x1:t.end,y0:0,y1:1,fillcolor:t.live?'rgba(52,152,219,.18)':'rgba(155,89,182,.12)',line:{{width:0}}}})}}
Plotly.newPlot('chart',traces,{{paper_bgcolor:'#0e1726',plot_bgcolor:'#152238',dragmode:'pan',font:{{color:'#e5eefc'}},grid:{{rows:4,columns:1,subplots:[['xy'],['x2y2'],['x3y3'],['x4y4']],roworder:'top to bottom'}},xaxis:{{rangeslider:{{visible:false}},showgrid:true,gridcolor:'#22324d'}},xaxis2:{{matches:'x',showgrid:true,gridcolor:'#22324d'}},xaxis3:{{matches:'x',showgrid:true,gridcolor:'#22324d'}},xaxis4:{{matches:'x',showgrid:true,gridcolor:'#22324d'}},yaxis:{{showgrid:true,gridcolor:'#22324d'}},yaxis2:{{zeroline:true,zerolinecolor:'#9aa0a6',showgrid:true,gridcolor:'#22324d'}},yaxis3:{{range:[0,100],showgrid:true,gridcolor:'#22324d'}},yaxis4:{{showgrid:true,gridcolor:'#22324d'}},legend:{{orientation:'h'}},shapes}},{{responsive:true,scrollZoom:true}});
const select=document.getElementById('asset-select'); const position=document.getElementById('position');
for(const asset of p.chartTickers){{const option=document.createElement('option');option.value=asset;option.textContent=asset;option.selected=asset==='{safe_ticker}';select.append(option)}}
position.textContent=`${{p.chartIndex+1}} / ${{p.chartTickers.length}}`;
function visit(index){{const n=p.chartTickers.length;window.location.href=`${{p.chartTickers[(index+n)%n]}}.html`}}
document.getElementById('previous').addEventListener('click',()=>visit(p.chartIndex-1)); document.getElementById('next').addEventListener('click',()=>visit(p.chartIndex+1)); select.addEventListener('change',event=>window.location.href=`${{event.target.value}}.html`);
document.addEventListener('keydown',event=>{{if(event.target.tagName==='SELECT')return;if(event.key==='ArrowLeft')visit(p.chartIndex-1);if(event.key==='ArrowRight')visit(p.chartIndex+1)}});
</script></body></html>"""


def write_report(
    output_dir: Path, *, periods: list[TrendPeriod], micro_periods: list[MicroTrendPeriod], rows_by_ticker: dict[str, list[dict[str, object]]], entries: dict[str, list[date]],
    scanned_assets: int, unavailable_assets: list[str], timeframe_days: int = 7,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    grouped: dict[str, list[TrendPeriod]] = defaultdict(list)
    for period in periods:
        grouped[period.ticker].append(period)
    grouped_micro: dict[str, list[MicroTrendPeriod]] = defaultdict(list)
    for period in micro_periods:
        grouped_micro[period.ticker].append(period)
    chart_tickers = sorted(set(grouped).union(grouped_micro))
    for ticker in chart_tickers:
        (charts_dir / f"{ticker}.html").write_text(
            _chart_html(
                ticker,
                aggregate_bars(rows_by_ticker[ticker], timeframe_days=timeframe_days),
                grouped[ticker],
                grouped_micro[ticker],
                entries[ticker],
                chart_tickers,
                timeframe_days,
            ),
            encoding="utf-8",
        )
    lines = [
        f"# {_timeframe_label(timeframe_days).title()} adaptive-MACD strong trends — entered assets",
        "",
        "This catalogue uses filled **BUY** orders from 2025 and 2026 as entries. It includes only trend periods containing at least one such entry date.",
        "",
        "## Definition",
        "",
        f"- Start: first {_timeframe_label(timeframe_days)} close where adaptive MACD and its signal are both above zero.",
        "- Confirmation: the first completed negative-histogram pullback after start keeps the signal strictly above zero; the confirmation date is its first non-negative histogram bar.",
        f"- Strength: the trend sets a new high in the signal line versus all earlier available {_timeframe_label(timeframe_days)} history, and contains at least eight consecutive positive, increasing histogram bars (the light-blue sequence).",
        "- End: first bar the signal reaches or falls below zero; otherwise the period remains active through the latest bar.",
        "",
        f"Scanned {scanned_assets} entered underlyings; {len(unavailable_assets)} had no daily archive rows. The signal ATH is relative to the downloaded history (2020-01-01 onward), not a vendor-guaranteed lifetime series. ‘Open through latest data’ means the available archive has no qualifying end signal, not that the trend is necessarily still live today.",
        "",
        "## Qualifying periods",
        "",
        "| Asset | Start | Confirmed | End | Signal ATH | Light-blue streak | Entry dates in period | Chart |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for period in sorted(periods, key=lambda item: (item.start, item.ticker), reverse=True):
        lines.append(
            f"| {period.ticker} | {period.start} | {period.confirmed} | {period.end or 'open through latest data'} | {period.signal_ath_date} ({period.signal_ath_value:.4f}) | {period.expanding_histogram_weeks} | {', '.join(str(day) for day in period.entry_dates)} | [view](charts/{period.ticker}.html) |"
        )
    if not periods:
        lines.append("| _None_ |  |  |  |  |  |  |  |")
    lines.extend([
        "",
        "## Micro trends",
        "",
        f"A micro trend starts when either the adaptive MACD crosses above zero or 14-period RSI crosses above 50 (RSI−50 crosses zero), remains in force for at least three {_timeframe_label(timeframe_days)} bars, and expands 14-period ATR by at least 33% from the start. It ends on the first negative adaptive-MACD histogram bar.",
        "",
        "| Asset | Trigger | Start | Qualified | End | Max ATR expansion | Entry dates in period | Chart |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ])
    for period in sorted(micro_periods, key=lambda item: (item.start, item.ticker), reverse=True):
        lines.append(
            f"| {period.ticker} | {period.trigger} | {period.start} | {period.qualified} | {period.end or 'open through latest data'} | {period.max_atr_expansion_pct:.1f}% | {', '.join(str(day) for day in period.entry_dates)} | [view](charts/{period.ticker}.html) |"
        )
    if not micro_periods:
        lines.append("| _None_ |  |  |  |  |  |  |  |")
    if unavailable_assets:
        lines.extend(["", "## No daily archive rows", "", ", ".join(unavailable_assets)])
    report_path = output_dir / "README.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=Path, action="append", default=[], help="Order CSV; may be repeated")
    parser.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--history-start", default="2020-01-01")
    parser.add_argument("--history-end", default="2026-08-09", help="Exclusive YYYY-MM-DD")
    parser.add_argument("--micro-atr-expansion-pct", type=float, default=33.0)
    parser.add_argument("--micro-minimum-weeks", type=int, default=3)
    parser.add_argument("--timeframe-days", type=int, choices=(3, 7), default=7, help="Bar duration: 3 or 7 calendar days")
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_ROOT / "reports" / "weekly-adaptive-trends")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    order_files = tuple(args.orders) if args.orders else DEFAULT_ORDER_FILES
    entries = load_entry_dates(order_files, years={2025, 2026})
    rows_by_ticker = fetch_daily_rows(
        list(entries), table_id=args.table_id, location=args.location,
        start_date=args.history_start, end_date=args.history_end,
    )
    for ticker in entries:
        if ticker not in rows_by_ticker:
            local_rows = load_local_daily_rows(ticker)
            if local_rows:
                rows_by_ticker[ticker] = local_rows
    periods: list[TrendPeriod] = []
    micro_periods: list[MicroTrendPeriod] = []
    for ticker, dates in entries.items():
        daily_rows = rows_by_ticker.get(ticker, [])
        if daily_rows:
            timeframe_rows = aggregate_bars(daily_rows, timeframe_days=args.timeframe_days)
            periods.extend(find_strong_trends(ticker, timeframe_rows, dates, timeframe_days=args.timeframe_days))
            micro_periods.extend(
                find_micro_trends(
                    ticker, timeframe_rows, dates, atr_expansion_pct=args.micro_atr_expansion_pct,
                    minimum_weeks=args.micro_minimum_weeks,
                    timeframe_days=args.timeframe_days,
                )
            )
    report = write_report(
        args.output_dir, periods=periods, micro_periods=micro_periods, rows_by_ticker=rows_by_ticker, entries=entries,
        scanned_assets=len(entries), unavailable_assets=sorted(set(entries).difference(rows_by_ticker)),
        timeframe_days=args.timeframe_days,
    )
    print(f"Wrote {len(periods)} strong and {len(micro_periods)} micro trend period(s) to {report}")


if __name__ == "__main__":  # pragma: no cover
    main()
