"""V1 midday compliance monitor: Webull positions → rules → DeepSeek brief → email."""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .webull_bridge import WebullBridge, WebullConfig

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parent.parent if PACKAGE_ROOT.name == "analysis" else PACKAGE_ROOT
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
ORDER_DATA_DIR = PACKAGE_ROOT / "order-data"
DEFAULT_STATE_PATH = ORDER_DATA_DIR / "compliance-monitor-state.json"
DEFAULT_ALERT_TO = "ericthechen@gmail.com"

NY = ZoneInfo("America/New_York")
CHI = ZoneInfo("America/Chicago")

DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_CHAT_URL = f"{DEEPSEEK_BASE}/chat/completions"
DEEPSEEK_BALANCE_URL = f"{DEEPSEEK_BASE}/user/balance"
DEEPSEEK_MODEL = "deepseek-chat"


@dataclass(slots=True)
class MonitorConfig:
    alert_email_to: str = DEFAULT_ALERT_TO
    var_soft_pct: float = 10.0
    var_hard_pct: float = 20.0
    max_underlyings: int = 3
    min_hold_sessions: int = 2  # calendar days before discretionary exit
    deepseek_warn_balance: float = 2.0
    poll_seconds: int = 120
    once: bool = False
    dry_run: bool = False
    rth_only: bool = True


@dataclass(slots=True)
class Flag:
    code: str
    severity: str  # info | warning | critical
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Snapshot:
    fetched_at: str
    nlv: float | None
    cash: float | None
    market_value: float | None
    day_pnl: float | None
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    premium_at_risk: float
    underlyings: list[str]
    opened_today_symbols: list[str]


def _load_env() -> None:
    if DEFAULT_ENV_PATH.exists():
        load_dotenv(DEFAULT_ENV_PATH)
    load_dotenv()


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_et() -> datetime:
    return datetime.now(tz=NY)


def is_rth(now: datetime | None = None) -> bool:
    now = now or _now_et()
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes <= (16 * 60)


def _root_symbol(symbol: str) -> str:
    text = (symbol or "").upper().strip()
    if not text:
        return ""
    # OCC: ROOT + YYMMDD + C/P + strike
    match = re.match(r"^([A-Z]+)\d{6}[CP]\d+$", text)
    if match:
        return match.group(1)
    return text.split()[0]


def _position_underlying(pos: dict[str, Any]) -> str:
    symbol = str(pos.get("symbol") or "").upper()
    legs = pos.get("legs") or []
    if legs and isinstance(legs[0], dict) and legs[0].get("symbol"):
        return str(legs[0]["symbol"]).upper()
    return symbol


def _position_premium(pos: dict[str, Any]) -> float:
    # Prefer entry cost (premium at risk); fall back to market value.
    for key in ("cost", "market_value"):
        value = _f(pos.get(key))
        if value is not None:
            return abs(value)
    legs = pos.get("legs") or []
    total = 0.0
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        qty = abs(_f(leg.get("quantity")) or _f(pos.get("quantity")) or 1.0)
        px = _f(leg.get("cost")) or _f(leg.get("cost_price")) or 0.0
        mult = _f(leg.get("option_contract_multiplier")) or 100.0
        leg_cost = _f(leg.get("cost"))
        # Parent often already has aggregate cost; leg.cost may be per-share premium.
        if leg_cost is not None and leg_cost > 50:
            total += abs(leg_cost)
        else:
            total += abs(px) * qty * mult
    return total


def _normalize_positions(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pos in raw:
        legs = pos.get("legs") if isinstance(pos.get("legs"), list) else []
        leg0 = legs[0] if legs and isinstance(legs[0], dict) else {}
        underlying = _position_underlying(pos)
        out.append(
            {
                "position_id": pos.get("position_id"),
                "underlying": underlying,
                "symbol": pos.get("symbol") or underlying,
                "instrument_type": pos.get("instrument_type") or leg0.get("instrument_type"),
                "option_type": (leg0.get("option_type") or pos.get("option_type") or "").upper(),
                "expiry": leg0.get("option_expire_date") or pos.get("option_expire_date"),
                "strike": _f(leg0.get("option_exercise_price") or pos.get("option_exercise_price")),
                "quantity": _f(pos.get("quantity")) or _f(leg0.get("quantity")) or 0.0,
                "cost": _f(pos.get("cost")),
                "cost_price": _f(pos.get("cost_price") or leg0.get("cost")),
                "last_price": _f(pos.get("last_price") or leg0.get("last_price")),
                "market_value": _f(pos.get("market_value")),
                "unrealized_pnl": _f(pos.get("unrealized_profit_loss") or leg0.get("unrealized_profit_loss")),
                "unrealized_pnl_rate": _f(pos.get("unrealized_profit_loss_rate")),
                "day_pnl": _f(pos.get("day_profit_loss") or leg0.get("day_profit_loss")),
                "premium_at_risk": _position_premium(pos),
                "raw": pos,
            }
        )
    return out


def fetch_snapshot(bridge: WebullBridge) -> Snapshot:
    balance = bridge.get_account_balance()
    assets = {}
    if isinstance(balance, dict):
        aca = balance.get("account_currency_assets") or []
        if aca and isinstance(aca[0], dict):
            assets = aca[0]
    nlv = _f(balance.get("total_net_liquidation_value")) if isinstance(balance, dict) else None
    cash = _f(balance.get("total_cash_balance")) if isinstance(balance, dict) else None
    market_value = _f(balance.get("total_market_value")) if isinstance(balance, dict) else None
    day_pnl = _f(balance.get("total_day_profit_loss")) if isinstance(balance, dict) else None
    if nlv is None:
        nlv = _f(assets.get("net_liquidation_value"))
    if cash is None:
        cash = _f(assets.get("cash_balance"))

    positions = _normalize_positions(bridge.get_positions())
    option_positions = []
    for p in positions:
        itype = str(p.get("instrument_type") or "").upper()
        if itype in {"OPTION", "OPTIONS"} or p.get("option_type") in {"CALL", "PUT"} or p.get("expiry"):
            option_positions.append(p)
    risk_positions = option_positions
    open_orders = bridge.get_open_orders()
    underlyings = sorted({p["underlying"] for p in risk_positions if p["underlying"]})
    premium = sum(p["premium_at_risk"] for p in risk_positions)

    # Today's opens from order history (best-effort).
    opened_today: list[str] = []
    try:
        today = _now_et().date()
        start = date.fromordinal(today.toordinal() - 1).isoformat()
        end = today.isoformat()
        orders = bridge.get_order_history(start, end, page_size=100, max_pages=5)
        for order in orders:
            intent = (order.position_intent or "").upper()
            if "OPEN" not in intent:
                continue
            filled_qty = float(order.filled_quantity or 0.0)
            if filled_qty <= 0 and (order.status or "").upper() not in {
                "FILLED",
                "PARTIALLY_FILLED",
                "COMPLETED",
            }:
                continue
            traded_raw = order.filled_time or order.placed_time
            traded_day = None
            if traded_raw:
                try:
                    traded_dt = datetime.fromisoformat(traded_raw.replace("Z", "+00:00"))
                    traded_day = traded_dt.astimezone(NY).date()
                except ValueError:
                    traded_day = None
            if traded_day != today:
                continue
            root = _root_symbol(order.symbol)
            opened_today.append(root)
        opened_today = sorted({s.upper() for s in opened_today if s})
    except Exception as exc:  # noqa: BLE001 — monitor must stay up
        opened_today = []
        print(f"[compliance-monitor] order history for today unavailable: {exc}", file=sys.stderr)

    return Snapshot(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        nlv=nlv,
        cash=cash,
        market_value=market_value,
        day_pnl=day_pnl,
        positions=risk_positions,
        open_orders=open_orders,
        premium_at_risk=premium,
        underlyings=underlyings,
        opened_today_symbols=opened_today,
    )


def evaluate_rules(snapshot: Snapshot, config: MonitorConfig) -> list[Flag]:
    flags: list[Flag] = []
    nlv = snapshot.nlv or 0.0
    premium = snapshot.premium_at_risk
    var_pct = (100.0 * premium / nlv) if nlv > 0 else None

    if var_pct is not None:
        if var_pct >= config.var_hard_pct:
            flags.append(
                Flag(
                    "VAR_HARD",
                    "critical",
                    f"Options premium at risk {var_pct:.1f}% of NLV (${premium:,.0f} / ${nlv:,.0f}) ≥ hard cap {config.var_hard_pct:.0f}%.",
                    {"var_pct": var_pct, "premium": premium, "nlv": nlv},
                )
            )
        elif var_pct >= config.var_soft_pct:
            flags.append(
                Flag(
                    "VAR_SOFT",
                    "warning",
                    f"Options premium at risk {var_pct:.1f}% of NLV (${premium:,.0f} / ${nlv:,.0f}) ≥ soft target {config.var_soft_pct:.0f}%.",
                    {"var_pct": var_pct, "premium": premium, "nlv": nlv},
                )
            )

    if len(snapshot.underlyings) > config.max_underlyings:
        flags.append(
            Flag(
                "TOO_MANY_UNDERLYINGS",
                "warning",
                f"{len(snapshot.underlyings)} underlyings open ({', '.join(snapshot.underlyings)}); max {config.max_underlyings}.",
                {"underlyings": snapshot.underlyings},
            )
        )

    opened = set(snapshot.opened_today_symbols)
    for pos in snapshot.positions:
        und = pos["underlying"]
        if und in opened:
            flags.append(
                Flag(
                    "SAME_DAY_HOLD_LOCK",
                    "warning",
                    f"{und} appears opened today — do not discretionary-exit before min hold ({config.min_hold_sessions} sessions).",
                    {"underlying": und, "expiry": pos.get("expiry"), "option_type": pos.get("option_type")},
                )
            )
        rate = pos.get("unrealized_pnl_rate")
        if rate is not None and rate <= -0.35:
            flags.append(
                Flag(
                    "LARGE_UNREALIZED_DRAWDOWN",
                    "info",
                    f"{und} unrealized {rate*100:.1f}% — review thesis, don't panic-scratch if still day-0/1.",
                    {"underlying": und, "unrealized_pnl_rate": rate},
                )
            )
        exp = pos.get("expiry")
        if exp:
            try:
                dte = (date.fromisoformat(str(exp)[:10]) - _now_et().date()).days
                if dte <= 2:
                    flags.append(
                        Flag(
                            "SHORT_DTE",
                            "info",
                            f"{und} expires in {dte}d ({exp}) — size/hold rules tighter.",
                            {"underlying": und, "dte": dte},
                        )
                    )
            except ValueError:
                pass

    # Working close orders on same-day opens
    for order in snapshot.open_orders:
        text = json.dumps(order, default=str).upper()
        for und in opened:
            if und in text and any(tok in text for tok in ("CLOSE", "SELL", "BTC", "STC")):
                flags.append(
                    Flag(
                        "SAME_DAY_EXIT_ORDER",
                        "critical",
                        f"Working order looks like a same-day exit involving {und}.",
                        {"underlying": und, "order": order},
                    )
                )

    if not snapshot.positions:
        flags.append(Flag("FLAT", "info", "No open positions.", {}))

    # Deduplicate by code+message
    seen: set[str] = set()
    unique: list[Flag] = []
    for flag in flags:
        key = f"{flag.code}|{flag.message}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(flag)
    return unique


def fetch_deepseek_balance(api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        DEEPSEEK_BALANCE_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def deepseek_credit_flags(balance: dict[str, Any], warn_below: float) -> tuple[list[Flag], dict[str, Any]]:
    flags: list[Flag] = []
    infos = balance.get("balance_infos") or []
    summary = {
        "is_available": balance.get("is_available"),
        "balances": infos,
        "warn_below": warn_below,
    }
    if balance.get("is_available") is False:
        flags.append(
            Flag(
                "DEEPSEEK_UNAVAILABLE",
                "critical",
                "DeepSeek reports is_available=false — API calls may fail; top up credits.",
                summary,
            )
        )
    total = 0.0
    currency = "USD"
    for info in infos:
        if not isinstance(info, dict):
            continue
        # Prefer USD if present
        cur = str(info.get("currency") or "")
        bal = _f(info.get("total_balance")) or 0.0
        if cur == "USD" or total == 0.0:
            total = bal
            currency = cur or currency
    summary["total_balance"] = total
    summary["currency"] = currency
    # Rough FX: if CNY, treat warn_below as USD-ish * 7 for comparison simplicity
    comparable = total / 7.0 if currency == "CNY" else total
    if comparable <= 0:
        flags.append(
            Flag(
                "DEEPSEEK_CREDITS_EMPTY",
                "critical",
                f"DeepSeek balance is {total} {currency} — at risk of running out of API credits.",
                summary,
            )
        )
    elif comparable < warn_below:
        flags.append(
            Flag(
                "DEEPSEEK_CREDITS_LOW",
                "warning",
                f"DeepSeek balance low: {total} {currency} (warn threshold ~{warn_below} USD-equivalent).",
                summary,
            )
        )
    return flags, summary


def deepseek_brief(
    api_key: str,
    snapshot: Snapshot,
    flags: list[Flag],
    credit_summary: dict[str, Any],
) -> str:
    payload_flags = [asdict(f) for f in flags]
    user_prompt = {
        "directives": [
            "Options VaR soft 10% / hard 20% of NLV",
            "Max 3 concurrent underlyings",
            "No discretionary same-day exits; min ~2 session hold",
            "Alert only — do not recommend revenge sizing",
        ],
        "snapshot": {
            "nlv": snapshot.nlv,
            "premium_at_risk": snapshot.premium_at_risk,
            "underlyings": snapshot.underlyings,
            "positions": [
                {
                    k: v
                    for k, v in p.items()
                    if k != "raw"
                }
                for p in snapshot.positions
            ],
            "opened_today": snapshot.opened_today_symbols,
            "day_pnl": snapshot.day_pnl,
        },
        "flags": payload_flags,
        "deepseek_credits": credit_summary,
    }
    body = {
        "model": os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a trading compliance coach. Write a concise email body (plain text) "
                    "for the trader. Lead with whether they are violating hold/VaR directives. "
                    "Be direct. Include a short 'DeepSeek API credits' line stating if they are "
                    "at risk of running out. No markdown tables. Max ~250 words."
                ),
            },
            {"role": "user", "content": json.dumps(user_prompt)},
        ],
    }
    req = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def _fallback_brief(snapshot: Snapshot, flags: list[Flag], credit_summary: dict[str, Any]) -> str:
    lines = [
        "Compliance monitor snapshot",
        f"Time (ET): {_now_et().strftime('%Y-%m-%d %H:%M')}",
        f"NLV: ${snapshot.nlv:,.2f}" if snapshot.nlv is not None else "NLV: n/a",
        f"Premium at risk: ${snapshot.premium_at_risk:,.2f}",
        f"Underlyings ({len(snapshot.underlyings)}): {', '.join(snapshot.underlyings) or 'none'}",
        f"Opened today: {', '.join(snapshot.opened_today_symbols) or 'none'}",
        "",
        "Flags:",
    ]
    if not flags:
        lines.append("- none")
    for flag in flags:
        lines.append(f"- [{flag.severity}] {flag.code}: {flag.message}")
    lines.extend(
        [
            "",
            "DeepSeek API credits:",
            f"- available={credit_summary.get('is_available')} total={credit_summary.get('total_balance')} {credit_summary.get('currency')}",
        ]
    )
    return "\n".join(lines)


def send_email_smtp(to_addr: str, subject: str, body: str) -> bool:
    user = os.getenv("SMTP_USER") or os.getenv("GMAIL_USER") or to_addr
    password = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    if not password:
        return False
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    return True


def send_email_mailapp(to_addr: str, subject: str, body: str) -> bool:
    """Send via macOS Mail.app if configured (no SMTP app password required)."""
    if sys.platform != "darwin":
        return False

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    # Write body to a temp file to avoid AppleScript escaping issues with newlines.
    ORDER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    body_path = ORDER_DATA_DIR / "compliance-monitor-mail-body.txt"
    body_path.write_text(body)
    script = f'''
    set bodyText to read POSIX file "{body_path}" as «class utf8»
    tell application "Mail"
      set newMessage to make new outgoing message with properties {{subject:"{esc(subject)}", content:bodyText, visible:false}}
      tell newMessage
        make new to recipient at end of to recipients with properties {{address:"{esc(to_addr)}"}}
      end tell
      send newMessage
    end tell
    '''
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"[compliance-monitor] Mail.app send failed: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return False


def notify_macos(title: str, body: str) -> None:
    if sys.platform != "darwin":
        return
    script = f'display notification "{body[:180].replace(chr(34), "")}" with title "{title.replace(chr(34), "")}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except FileNotFoundError:
        pass


def send_alert(to_addr: str, subject: str, body: str, *, dry_run: bool) -> str:
    if dry_run:
        out = ORDER_DATA_DIR / "compliance-monitor-last-email.txt"
        ORDER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(f"Subject: {subject}\n\n{body}\n")
        notify_macos("Compliance monitor (dry-run)", subject)
        return f"dry-run wrote {out}"

    if send_email_smtp(to_addr, subject, body):
        notify_macos("Compliance monitor", subject)
        return "sent via SMTP"
    if send_email_mailapp(to_addr, subject, body):
        notify_macos("Compliance monitor", subject)
        return "sent via Mail.app"
    # Last resort: save + notify
    out = ORDER_DATA_DIR / "compliance-monitor-last-email.txt"
    ORDER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(f"Subject: {subject}\n\n{body}\n")
    notify_macos("Compliance monitor (email failed)", subject)
    return (
        f"email failed (set GMAIL_APP_PASSWORD or configure Mail.app); saved {out}"
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def should_alert(flags: list[Flag], state: dict[str, Any], *, force: bool) -> bool:
    if force:
        return True
    actionable = [f for f in flags if f.severity in {"warning", "critical"}]
    if not actionable:
        return False
    signature = "|".join(sorted(f"{f.code}:{f.message}" for f in actionable))
    if state.get("last_signature") == signature:
        # Re-alert at most every 30 minutes for same signature
        last = state.get("last_alert_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if (datetime.now(timezone.utc) - last_dt).total_seconds() < 1800:
                    return False
            except ValueError:
                pass
    return True


def run_once(config: MonitorConfig, *, force_email: bool = False) -> int:
    _load_env()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY missing in environment / .env")

    bridge = WebullBridge(WebullConfig.from_env())
    snapshot = fetch_snapshot(bridge)
    flags = evaluate_rules(snapshot, config)

    credit_flags: list[Flag] = []
    credit_summary: dict[str, Any] = {}
    try:
        balance = fetch_deepseek_balance(api_key)
        credit_flags, credit_summary = deepseek_credit_flags(balance, config.deepseek_warn_balance)
    except Exception as exc:  # noqa: BLE001
        credit_flags = [
            Flag(
                "DEEPSEEK_BALANCE_CHECK_FAILED",
                "warning",
                f"Could not read DeepSeek balance: {exc}",
                {},
            )
        ]
        credit_summary = {"error": str(exc)}

    all_flags = flags + credit_flags

    try:
        brief = deepseek_brief(api_key, snapshot, all_flags, credit_summary)
    except Exception as exc:  # noqa: BLE001
        brief = _fallback_brief(snapshot, all_flags, credit_summary) + f"\n\n(DeepSeek brief failed: {exc})"

    credit_line = (
        f"DeepSeek credits: available={credit_summary.get('is_available')} "
        f"balance={credit_summary.get('total_balance')} {credit_summary.get('currency')}"
    )
    if any(f.code.startswith("DEEPSEEK_CREDITS") or f.code == "DEEPSEEK_UNAVAILABLE" for f in credit_flags):
        credit_line = "AT RISK OF RUNNING OUT OF DEEPSEEK API CREDITS — " + credit_line

    body = (
        f"{brief}\n\n"
        f"---\n"
        f"{credit_line}\n"
        f"Monitor time (ET): {_now_et().isoformat()}\n"
        f"Positions: {len(snapshot.positions)} | Premium@risk: ${snapshot.premium_at_risk:,.2f}\n"
        f"Note: X/Grok push not configured (needs user OAuth for DMs; "
        f"will not publicly tweet positions).\n"
    )

    severities = {f.severity for f in all_flags}
    prefix = "CRITICAL" if "critical" in severities else "WARN" if "warning" in severities else "OK"
    subject = f"[Compliance {prefix}] VaR/holds check — {len(snapshot.positions)} pos — {_now_et().strftime('%Y-%m-%d %H:%M ET')}"

    state_path = Path(os.getenv("COMPLIANCE_STATE_PATH", str(DEFAULT_STATE_PATH)))
    state = load_state(state_path)
    if should_alert(all_flags, state, force=force_email or config.once):
        result = send_alert(config.alert_email_to, subject, body, dry_run=config.dry_run)
        print(f"[compliance-monitor] alert: {result}")
        state["last_signature"] = "|".join(
            sorted(f"{f.code}:{f.message}" for f in all_flags if f.severity in {"warning", "critical"})
        )
        state["last_alert_at"] = datetime.now(timezone.utc).isoformat()
        state["last_subject"] = subject
        save_state(state_path, state)
    else:
        print("[compliance-monitor] no new actionable alert (deduped)")

    # Always print summary locally
    print(subject)
    print(credit_line)
    for flag in all_flags:
        print(f"  [{flag.severity}] {flag.code}: {flag.message}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="V1 midday compliance monitor (Webull positions → rules → DeepSeek → email)"
    )
    parser.add_argument("--email", default=DEFAULT_ALERT_TO, help="Alert recipient")
    parser.add_argument("--once", action="store_true", help="Single run then exit (still emails if warranted)")
    parser.add_argument("--force-email", action="store_true", help="Email even if only info flags / deduped")
    parser.add_argument("--dry-run", action="store_true", help="Do not send email; write last-email file")
    parser.add_argument("--poll-seconds", type=int, default=120)
    parser.add_argument("--no-rth-only", action="store_true", help="Run outside regular trading hours too")
    parser.add_argument("--var-soft", type=float, default=10.0)
    parser.add_argument("--var-hard", type=float, default=20.0)
    parser.add_argument("--max-underlyings", type=int, default=3)
    parser.add_argument("--deepseek-warn-balance", type=float, default=2.0)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = MonitorConfig(
        alert_email_to=args.email,
        var_soft_pct=args.var_soft,
        var_hard_pct=args.var_hard,
        max_underlyings=args.max_underlyings,
        deepseek_warn_balance=args.deepseek_warn_balance,
        poll_seconds=args.poll_seconds,
        once=args.once,
        dry_run=args.dry_run,
        rth_only=not args.no_rth_only,
    )
    if config.once:
        raise SystemExit(run_once(config, force_email=args.force_email))

    print(
        f"[compliance-monitor] looping every {config.poll_seconds}s; "
        f"email={config.alert_email_to}; rth_only={config.rth_only}"
    )
    while True:
        try:
            if config.rth_only and not is_rth():
                print(f"[compliance-monitor] outside RTH ({_now_et().strftime('%H:%M ET')}); sleeping")
            else:
                run_once(config, force_email=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[compliance-monitor] error: {exc}", file=sys.stderr)
        time.sleep(max(30, config.poll_seconds))


if __name__ == "__main__":
    main()
