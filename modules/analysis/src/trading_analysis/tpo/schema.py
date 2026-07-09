"""Dataclasses and JSON serialization for TPO trade grades."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from ..parse_orders import RealizedTrade


def make_trade_id(trade: RealizedTrade) -> str:
    open_dt = trade.open_datetime.isoformat() if trade.open_datetime else trade.open_date.isoformat()
    close_dt = trade.trade_datetime.isoformat() if trade.trade_datetime else trade.trade_date.isoformat()
    raw = (
        f"{trade.symbol}|{open_dt}|{close_dt}|{trade.quantity:g}|"
        f"{trade.open_price:g}|{trade.price:g}|{trade.pnl:.2f}|{trade.direction}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class SessionProfileSummary:
    date: str
    poc: float
    vah: float
    val: float
    ib_high: float
    ib_low: float
    session_high: float
    session_low: float
    bracket_size: float
    tpo_count: int
    shape_tags: list[str] = field(default_factory=list)
    tpo_ascii: str = ""
    single_print_high: bool = False
    single_print_low: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextSummary:
    poc_migration: str  # up | down | balance
    balance_days: int
    trend_days: int
    session_count: int
    poc_trail: list[dict[str, float | str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TpoFeatures:
    entry_vs_prior_va: str
    entry_vs_day_va: str
    entry_vs_poc_pct: float
    entry_extreme_score: float
    short_bottom_flag: bool
    long_top_flag: bool
    ib_break_context: str
    exit_vs_va: str
    exit_vs_poc_pct: float
    gave_back_to_value: bool
    hold_session_count: int
    profile_shape_tags: list[str]
    intraday_round_trip: bool
    entry_session_attachment: str
    exit_session_attachment: str
    entry_price_source: str
    exit_price_source: str
    deterministic_score: float
    rule_hits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TpoGrade:
    status: str  # ok | features_only | error | skipped
    overall_score: float | None = None
    execution_quality: str | None = None
    rule_hits: list[str] = field(default_factory=list)
    rule_misses: list[str] = field(default_factory=list)
    what_went_wrong: list[str] = field(default_factory=list)
    what_went_right: list[str] = field(default_factory=list)
    corrective_note: str | None = None
    confidence: float | None = None
    model: str | None = None
    graded_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TpoGradeRecord:
    trade_id: str
    symbol: str
    underlying: str
    direction: str
    instrument_type: str
    option_type: str
    quantity: float
    open_datetime: str | None
    close_datetime: str | None
    open_date: str
    close_date: str
    open_price: float
    close_price: float
    realized_pnl: float
    underlying_entry_price: float | None
    underlying_exit_price: float | None
    features: dict[str, Any]
    profiles: dict[str, Any]
    grade: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_trade(
        cls,
        trade: RealizedTrade,
        *,
        underlying: str,
        underlying_entry_price: float | None,
        underlying_exit_price: float | None,
        features: TpoFeatures,
        entry_profile: SessionProfileSummary | None,
        exit_profile: SessionProfileSummary | None,
        context: ContextSummary,
        grade: TpoGrade,
    ) -> "TpoGradeRecord":
        return cls(
            trade_id=make_trade_id(trade),
            symbol=trade.symbol,
            underlying=underlying,
            direction=trade.direction,
            instrument_type=trade.instrument_type,
            option_type=trade.option_type,
            quantity=trade.quantity,
            open_datetime=trade.open_datetime.isoformat() if trade.open_datetime else None,
            close_datetime=trade.trade_datetime.isoformat() if trade.trade_datetime else None,
            open_date=trade.open_date.isoformat(),
            close_date=trade.trade_date.isoformat(),
            open_price=trade.open_price,
            close_price=trade.price,
            realized_pnl=trade.pnl,
            underlying_entry_price=underlying_entry_price,
            underlying_exit_price=underlying_exit_price,
            features=features.to_dict(),
            profiles={
                "entry_session": entry_profile.to_dict() if entry_profile else None,
                "exit_session": exit_profile.to_dict() if exit_profile else None,
                "context_summary": context.to_dict(),
            },
            grade=grade.to_dict(),
        )


@dataclass
class TpoGradesDocument:
    metadata: dict[str, Any]
    trades: list[TpoGradeRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata,
            "trades": [trade.to_dict() for trade in self.trades],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TpoGradesDocument":
        trades_raw = payload.get("trades") or []
        trades: list[TpoGradeRecord] = []
        for row in trades_raw:
            if not isinstance(row, dict):
                continue
            trades.append(
                TpoGradeRecord(
                    trade_id=str(row.get("trade_id") or ""),
                    symbol=str(row.get("symbol") or ""),
                    underlying=str(row.get("underlying") or ""),
                    direction=str(row.get("direction") or ""),
                    instrument_type=str(row.get("instrument_type") or ""),
                    option_type=str(row.get("option_type") or ""),
                    quantity=float(row.get("quantity") or 0),
                    open_datetime=row.get("open_datetime"),
                    close_datetime=row.get("close_datetime"),
                    open_date=str(row.get("open_date") or ""),
                    close_date=str(row.get("close_date") or ""),
                    open_price=float(row.get("open_price") or 0),
                    close_price=float(row.get("close_price") or 0),
                    realized_pnl=float(row.get("realized_pnl") or 0),
                    underlying_entry_price=_optional_float(row.get("underlying_entry_price")),
                    underlying_exit_price=_optional_float(row.get("underlying_exit_price")),
                    features=dict(row.get("features") or {}),
                    profiles=dict(row.get("profiles") or {}),
                    grade=dict(row.get("grade") or {}),
                )
            )
        return cls(metadata=dict(payload.get("metadata") or {}), trades=trades)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def index_grades_by_trade_id(doc: TpoGradesDocument) -> dict[str, TpoGradeRecord]:
    return {trade.trade_id: trade for trade in doc.trades if trade.trade_id}


def find_grade_for_trade(
    doc: TpoGradesDocument | None,
    trade: RealizedTrade,
) -> TpoGradeRecord | None:
    if doc is None:
        return None
    trade_id = make_trade_id(trade)
    for record in doc.trades:
        if record.trade_id == trade_id:
            return record
    return None
