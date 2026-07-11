"""15-minute trade drill-down chart from entry through ideal exit."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import plotly.graph_objects as go

from ..market_data import (
    DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    fetch_sessions_minute_bars,
    parse_bar_timestamp,
)
from ..tpo.sessions import is_rth_session_day, to_ny


def build_trade_drilldown_figure(
    *,
    underlying: str,
    instrument: str,
    entry_dt: datetime,
    actual_exit_dt: datetime,
    ideal_exit_dt: datetime | None,
    ideal_exit_label: str,
    entry_price: float | None = None,
    actual_exit_price: float | None = None,
    ideal_exit_price: float | None = None,
    realized_pnl: float | None = None,
    missed_pnl: float | None = None,
    candle_minutes: int = 15,
    cache_dir: Path = DEFAULT_UNDERLYING_MINUTE_CACHE_DIR,
    is_put: bool | None = None,
    strike: float | None = None,
    expiration: date | None = None,
) -> go.Figure:
    """Build a 15m candlestick chart spanning entry → ideal (or actual) exit.

    Chart uses a contiguous category axis (no weekend/holiday gaps), pads one
    RTH session on each side under a translucent overlay, and scales Y so the
    top/bottom 10% of the pane are empty. Option trades also show a strike
    line and a shaded range through expiration.
    """
    del entry_price, actual_exit_price, ideal_exit_price  # option premiums — not underlying

    entry_ny = to_ny(entry_dt)
    actual_ny = to_ny(actual_exit_dt)
    ideal_ny = to_ny(ideal_exit_dt) if ideal_exit_dt else actual_ny

    core_start = entry_ny.date()
    core_end = max(actual_ny.date(), ideal_ny.date())
    if expiration is not None and expiration > core_end:
        core_end = expiration
    if core_end < core_start:
        core_end = core_start

    left_pad = _previous_session_day(core_start)
    right_pad = _next_session_day(core_end)
    fetch_start = left_pad or core_start
    fetch_end = right_pad or core_end

    sessions = _session_days(fetch_start, fetch_end)
    bars_by_day = fetch_sessions_minute_bars(
        underlying,
        sessions,
        cache_dir=cache_dir,
        throttle_seconds=0.05,
    )
    minute_bars: list[dict[str, object]] = []
    for session in sessions:
        minute_bars.extend(bars_by_day.get(session, []))

    candles = _aggregate_candles(minute_bars, candle_minutes=candle_minutes)
    if not candles:
        raise RuntimeError(
            f"No {candle_minutes}m bars available for {underlying} "
            f"{fetch_start.isoformat()} → {fetch_end.isoformat()}"
        )

    put = is_put if is_put is not None else _infer_is_put(instrument)

    # Contiguous index axis removes weekend/holiday gaps.
    xs = list(range(len(candles)))
    session_dates = [candle["t"].date() for candle in candles]
    left_pad_indexes = [i for i, day in enumerate(session_dates) if left_pad and day == left_pad]
    right_pad_indexes = [i for i, day in enumerate(session_dates) if right_pad and day == right_pad]

    highs = [float(c["h"]) for c in candles]
    lows = [float(c["l"]) for c in candles]
    # Scale from candle extremes (+ strike when present).
    y_min = min(lows)
    y_max = max(highs)
    if strike is not None:
        y_min = min(y_min, float(strike))
        y_max = max(y_max, float(strike))
    y_span = max(y_max - y_min, 1e-6)
    # Top 10% and bottom 10% empty → visible band is middle 80%.
    y_pad = y_span * (0.10 / 0.80)
    y_range = [y_min - y_pad, y_max + y_pad]

    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=xs,
            open=[float(c["o"]) for c in candles],
            high=highs,
            low=lows,
            close=[float(c["c"]) for c in candles],
            name=f"{underlying} {candle_minutes}m",
            increasing_line_color="#2ca02c",
            decreasing_line_color="#d62728",
            xperiodalignment="middle",
        )
    )

    entry_idx = _nearest_candle_index(candles, entry_ny)
    actual_idx = _nearest_candle_index(candles, actual_ny)
    ideal_idx = _ideal_candle_index(candles, ideal_ny.date(), is_put=put)

    entry_y = float(candles[entry_idx]["l"])
    actual_y = float(candles[actual_idx]["h"] if not put else candles[actual_idx]["l"])
    ideal_y = float(candles[ideal_idx]["h"] if not put else candles[ideal_idx]["l"])

    figure.add_trace(
        go.Scatter(
            x=[entry_idx],
            y=[entry_y],
            mode="markers+text",
            name="Entry",
            text=["Entry"],
            textposition="bottom center",
            marker={
                "size": 14,
                "color": "#2ca02c",
                "symbol": "triangle-up",
                "line": {"width": 1, "color": "#111111"},
            },
            customdata=[[candles[entry_idx]["t"].isoformat()]],
            hovertemplate="Entry<br>%{customdata[0]}<br>%{y:.2f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[actual_idx],
            y=[actual_y],
            mode="markers+text",
            name="Actual exit",
            text=["Actual exit"],
            textposition="top center",
            marker={
                "size": 14,
                "color": "#d62728",
                "symbol": "triangle-down",
                "line": {"width": 1, "color": "#111111"},
            },
            customdata=[[candles[actual_idx]["t"].isoformat()]],
            hovertemplate="Actual exit<br>%{customdata[0]}<br>%{y:.2f}<extra></extra>",
        )
    )
    # Always show ideal when we have a distinct index, or when label says it differs.
    if ideal_idx != actual_idx or (ideal_exit_label and "actual" not in ideal_exit_label.lower()):
        # Nudge ideal slightly if it lands on the same candle as actual.
        ideal_x = ideal_idx + (0.15 if ideal_idx == actual_idx else 0.0)
        figure.add_trace(
            go.Scatter(
                x=[ideal_x],
                y=[ideal_y],
                mode="markers+text",
                name="Ideal exit",
                text=[ideal_exit_label or "Ideal exit"],
                textposition="top center",
                marker={
                    "size": 15,
                    "color": "#f0ad4e",
                    "symbol": "triangle-down",
                    "line": {"width": 2, "color": "#111111"},
                },
                customdata=[[candles[ideal_idx]["t"].isoformat()]],
                hovertemplate=(
                    f"{ideal_exit_label or 'Ideal exit'}<br>%{{customdata[0]}}<br>%{{y:.2f}}<extra></extra>"
                ),
            )
        )

    shapes: list[dict[str, Any]] = []
    annotations: list[dict[str, Any]] = []

    # Option life: shade from entry session through expiration session.
    if expiration is not None:
        exp_indexes = [i for i, day in enumerate(session_dates) if day == expiration]
        life_start = entry_idx - 0.5
        if exp_indexes:
            life_end = exp_indexes[-1] + 0.5
        else:
            # Expiration not in loaded sessions — shade through chart end.
            life_end = len(candles) - 0.5
        shapes.append(
            {
                "type": "rect",
                "xref": "x",
                "yref": "paper",
                "x0": life_start,
                "x1": life_end,
                "y0": 0,
                "y1": 1,
                "fillcolor": "rgba(59, 130, 246, 0.10)",
                "line": {"width": 0},
                "layer": "below",
            }
        )
        if exp_indexes:
            exp_x = exp_indexes[-1]
            shapes.append(
                {
                    "type": "line",
                    "xref": "x",
                    "yref": "paper",
                    "x0": exp_x,
                    "x1": exp_x,
                    "y0": 0,
                    "y1": 1,
                    "line": {"color": "#2563eb", "width": 1.5, "dash": "dash"},
                    "layer": "above",
                }
            )
            annotations.append(
                {
                    "x": exp_x,
                    "y": 1.0,
                    "xref": "x",
                    "yref": "paper",
                    "text": f"Exp {expiration.isoformat()}",
                    "showarrow": False,
                    "yshift": 10,
                    "font": {"size": 11, "color": "#2563eb"},
                }
            )

    if strike is not None:
        shapes.append(
            {
                "type": "line",
                "xref": "paper",
                "yref": "y",
                "x0": 0,
                "x1": 1,
                "y0": float(strike),
                "y1": float(strike),
                "line": {"color": "#7c3aed", "width": 1.5, "dash": "dot"},
                "layer": "above",
            }
        )
        strike_text = f"{strike:.0f}" if float(strike).is_integer() else f"{strike:g}"
        annotations.append(
            {
                "x": 1.0,
                "y": float(strike),
                "xref": "paper",
                "yref": "y",
                "text": f"Strike {strike_text}",
                "showarrow": False,
                "xanchor": "right",
                "xshift": -4,
                "font": {"size": 11, "color": "#7c3aed"},
                "bgcolor": "rgba(255,255,255,0.75)",
            }
        )

    if left_pad_indexes:
        shapes.append(
            _pad_overlay(
                x0=left_pad_indexes[0] - 0.5,
                x1=left_pad_indexes[-1] + 0.5,
            )
        )
    if right_pad_indexes:
        shapes.append(
            _pad_overlay(
                x0=right_pad_indexes[0] - 0.5,
                x1=right_pad_indexes[-1] + 0.5,
            )
        )

    tick_vals, tick_text = _session_ticks(candles)
    subtitle_bits = [instrument]
    if strike is not None:
        strike_text = f"{strike:.0f}" if float(strike).is_integer() else f"{strike:g}"
        subtitle_bits.append(f"strike {strike_text}")
    if expiration is not None:
        subtitle_bits.append(f"exp {expiration.isoformat()}")
    if realized_pnl is not None:
        subtitle_bits.append(f"realized {_fmt_money(realized_pnl)}")
    if missed_pnl is not None:
        subtitle_bits.append(f"missed {_fmt_money(missed_pnl)}")

    # Default view focuses on core + pads; y uses 10% headroom.
    x_range = [-0.5, len(candles) - 0.5]

    annotations.append(
        {
            "text": (
                "Green ▲ entry · Red ▼ actual exit · Orange ▼ ideal exit. "
                "Purple dotted = strike · Blue band/line = option life → expiration. "
                "Shaded wings = ±1 RTH day context. Weekends/holidays removed."
            ),
            "xref": "paper",
            "yref": "paper",
            "x": 0,
            "y": -0.14,
            "showarrow": False,
            "font": {"size": 12, "color": "#4b5563"},
            "align": "left",
        }
    )

    figure.update_layout(
        title=f"{underlying} 15m drill-down — {' · '.join(subtitle_bits)}",
        template="plotly_white",
        height=720,
        hovermode="x unified",
        dragmode="pan",
        shapes=shapes,
        annotations=annotations,
        xaxis={
            "title": None,
            "tickmode": "array",
            "tickvals": tick_vals,
            "ticktext": tick_text,
            "range": x_range,
            "rangeslider": {"visible": True, "thickness": 0.08},
            "fixedrange": False,
            "showgrid": True,
            "zeroline": False,
            # Category-style contiguous axis: no date gaps.
            "type": "linear",
        },
        yaxis={
            "title": "Price",
            "fixedrange": False,
            "range": y_range,
            "zeroline": False,
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        margin={"l": 60, "r": 30, "t": 70, "b": 50},
    )
    # Keep candlestick rangeslider from duplicating; we already set xaxis.rangeslider.
    figure.update_layout(xaxis_rangeslider_visible=True)
    return figure


def write_trade_drilldown_html(
    figure: go.Figure,
    output_path: Path,
    *,
    auto_open: bool = False,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(
        str(output_path),
        auto_open=auto_open,
        include_plotlyjs="cdn",
        config={"scrollZoom": True, "displayModeBar": True, "responsive": True},
    )
    return output_path


def resolve_ideal_exit(
    *,
    entry_date: date,
    actual_exit_date: date,
    best_case_later_exit_date: str | None,
    best_case_later_exit_price: float | None,
    pre_exit_peak_date: str | None,
    pre_exit_peak_price: float | None,
    best_case_later_pnl: float | None,
    pre_exit_peak_pnl: float | None,
    realized_pnl: float | None,
) -> tuple[date, float | None, str]:
    """Pick the ideal exit date/price from hold-review counterfactuals."""
    later_date = _parse_date(best_case_later_exit_date)
    peak_date = _parse_date(pre_exit_peak_date)

    # Prefer post-exit best case when it beats realized.
    if (
        later_date is not None
        and later_date >= entry_date
        and best_case_later_pnl is not None
        and (realized_pnl is None or best_case_later_pnl > realized_pnl)
    ):
        return later_date, best_case_later_exit_price, "Ideal exit (best later)"

    # Else prefer pre-exit peak when it beats realized.
    if (
        peak_date is not None
        and peak_date >= entry_date
        and pre_exit_peak_pnl is not None
        and (realized_pnl is None or pre_exit_peak_pnl > realized_pnl)
    ):
        return peak_date, pre_exit_peak_price, "Ideal exit (pre-exit peak)"

    # Fall back to whichever counterfactual exists, else actual exit.
    if later_date is not None and later_date >= entry_date:
        return later_date, best_case_later_exit_price, "Ideal exit (best later)"
    if peak_date is not None and peak_date >= entry_date:
        return peak_date, pre_exit_peak_price, "Ideal exit (pre-exit peak)"
    return actual_exit_date, None, "Ideal exit (= actual)"


def _pad_overlay(*, x0: float, x1: float) -> dict[str, Any]:
    return {
        "type": "rect",
        "xref": "x",
        "yref": "paper",
        "x0": x0,
        "x1": x1,
        "y0": 0,
        "y1": 1,
        "fillcolor": "rgba(55, 65, 81, 0.28)",
        "line": {"width": 0},
        "layer": "above",
    }


def _session_ticks(candles: Sequence[dict[str, Any]]) -> tuple[list[int], list[str]]:
    ticks: list[int] = []
    labels: list[str] = []
    seen: set[date] = set()
    for index, candle in enumerate(candles):
        day = candle["t"].date()
        if day in seen:
            continue
        seen.add(day)
        ticks.append(index)
        labels.append(day.strftime("%b %d"))
    return ticks, labels


def _ideal_candle_index(candles: Sequence[dict[str, Any]], ideal_day: date, *, is_put: bool) -> int:
    """Place ideal exit on the extreme candle of the ideal session day."""
    day_indexes = [i for i, candle in enumerate(candles) if candle["t"].date() == ideal_day]
    if not day_indexes:
        # Fall back to nearest candle to midday on that date.
        target = datetime(ideal_day.year, ideal_day.month, ideal_day.day, 12, 0, tzinfo=candles[0]["t"].tzinfo)
        return _nearest_candle_index(candles, target)
    if is_put:
        return min(day_indexes, key=lambda i: float(candles[i]["l"]))
    return max(day_indexes, key=lambda i: float(candles[i]["h"]))


def _nearest_candle_index(candles: Sequence[dict[str, Any]], target: datetime) -> int:
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    target_ny = to_ny(target)
    return min(range(len(candles)), key=lambda i: abs(candles[i]["t"] - target_ny))


def _previous_session_day(day: date) -> date | None:
    cursor = day - timedelta(days=1)
    for _ in range(10):
        if is_rth_session_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return None


def _next_session_day(day: date) -> date | None:
    cursor = day + timedelta(days=1)
    for _ in range(10):
        if is_rth_session_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return None


def _session_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if is_rth_session_day(cursor):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _aggregate_candles(
    bars: Sequence[dict[str, object]],
    *,
    candle_minutes: int,
) -> list[dict[str, Any]]:
    if candle_minutes <= 1:
        candles: list[dict[str, Any]] = []
        for bar in bars:
            try:
                ts = to_ny(parse_bar_timestamp(bar.get("t")))
                candles.append(
                    {
                        "t": ts,
                        "o": float(bar["o"]),
                        "h": float(bar["h"]),
                        "l": float(bar["l"]),
                        "c": float(bar["c"]),
                    }
                )
            except (TypeError, ValueError, KeyError):
                continue
        return candles

    buckets: dict[datetime, dict[str, Any]] = {}
    order: list[datetime] = []
    for bar in bars:
        try:
            ts = to_ny(parse_bar_timestamp(bar.get("t")))
            o = float(bar["o"])
            h = float(bar["h"])
            l = float(bar["l"])
            c = float(bar["c"])
        except (TypeError, ValueError, KeyError):
            continue
        minute = (ts.minute // candle_minutes) * candle_minutes
        key = ts.replace(minute=minute, second=0, microsecond=0)
        if key not in buckets:
            buckets[key] = {"t": key, "o": o, "h": h, "l": l, "c": c}
            order.append(key)
        else:
            bucket = buckets[key]
            bucket["h"] = max(float(bucket["h"]), h)
            bucket["l"] = min(float(bucket["l"]), l)
            bucket["c"] = c
    return [buckets[key] for key in order]


def _infer_is_put(instrument: str) -> bool:
    lowered = instrument.lower()
    if " put " in f" {lowered} " or lowered.endswith(" put") or " put" in lowered:
        return True
    return False


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else "+"
    return f"{sign}${abs(value):,.2f}"
