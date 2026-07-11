#!/usr/bin/env python3
"""Install weekday cron jobs for the compliance monitor at market-relative times.

Schedule (US equity RTH, America/New_York):
  - 1 hour after open  → 10:30 ET
  - session midpoint   → 12:45 ET
  - 1 hour before close → 15:00 ET

Cron itself uses the machine's local timezone. This installer reads the local
timezone automatically and converts those ET times into local HH:MM so the
jobs stay correct in Chicago, NY, etc. Re-run after changing system timezone.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")
# (hour, minute) in America/New_York
ET_SCHEDULE = (
    (10, 30),  # +1h after 09:30 open
    (12, 45),  # midpoint of 09:30–16:00
    (15, 0),  # -1h before 16:00 close
)
MARKER_BEGIN = "# BEGIN trading-compliance-monitor"
MARKER_END = "# END trading-compliance-monitor"


def detect_local_tz() -> ZoneInfo:
    explicit = os.getenv("COMPLIANCE_CRON_TZ") or os.getenv("TZ")
    if explicit:
        return ZoneInfo(explicit)
    # macOS: /etc/localtime → zoneinfo path
    try:
        target = Path("/etc/localtime").resolve()
        parts = target.parts
        if "zoneinfo" in parts:
            idx = parts.index("zoneinfo")
            key = "/".join(parts[idx + 1 :])
            return ZoneInfo(key)
    except Exception:  # noqa: BLE001
        pass
    # Fallback: system local offset as a fixed zone name via datetime
    local = datetime.now().astimezone()
    key = str(local.tzinfo)
    # key may be 'CDT' — prefer tzlocal-style from utcoffset via ZoneInfo guess
    # Use the zone from dateutil isn't available; keep America/Chicago if CST/CDT
    if key in {"CST", "CDT"}:
        return ZoneInfo("America/Chicago")
    if key in {"EST", "EDT"}:
        return ZoneInfo("America/New_York")
    return ZoneInfo("America/New_York")


def et_to_local_hm(et_hour: int, et_minute: int, local_tz: ZoneInfo, on: date) -> tuple[int, int]:
    et_dt = datetime(on.year, on.month, on.day, et_hour, et_minute, tzinfo=MARKET_TZ)
    local_dt = et_dt.astimezone(local_tz)
    return local_dt.hour, local_dt.minute


def next_weekday(from_day: date | None = None) -> date:
    day = from_day or date.today()
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def build_cron_block(repo_root: Path, local_tz: ZoneInfo) -> str:
    runner = repo_root / "modules/analysis/scripts/run_compliance_monitor.sh"
    runner_str = str(runner)
    day = next_weekday()
    lines = [
        MARKER_BEGIN,
        f"# Auto-installed for market times in {MARKET_TZ.key}; local TZ={local_tz.key}",
        f"# Re-run: python3 {repo_root}/modules/analysis/scripts/install_compliance_cron.py",
        f"# ET schedule: 10:30, 12:45, 15:00 America/New_York (Mon-Fri)",
    ]
    labels = ("+1h after open", "mid-session", "-1h before close")
    for (et_h, et_m), label in zip(ET_SCHEDULE, labels, strict=True):
        lh, lm = et_to_local_hm(et_h, et_m, local_tz, day)
        # Verify DST-safe: also check a winter weekday
        winter = date(day.year, 1, 6)
        while winter.weekday() >= 5:
            winter += timedelta(days=1)
        wh, wm = et_to_local_hm(et_h, et_m, local_tz, winter)
        note = f"ET {et_h:02d}:{et_m:02d} → local {lh:02d}:{lm:02d}"
        if (wh, wm) != (lh, lm):
            note += f" (winter local {wh:02d}:{wm:02d}; cron uses current-season local wall times — re-run installer after DST if needed)"
        lines.append(f"# {label}: {note}")
        lines.append(f"{lm} {lh} * * 1-5 {runner_str}")
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def read_crontab() -> str:
    try:
        completed = subprocess.run(
            ["crontab", "-l"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SystemExit("crontab not found on PATH") from exc
    if completed.returncode != 0:
        err = (completed.stderr or "").strip()
        if "no crontab" in err.lower():
            return ""
        raise SystemExit(f"crontab -l failed: {err or completed.stdout}")
    return completed.stdout


def write_crontab(contents: str) -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write(contents)
        temp_path = handle.name
    try:
        subprocess.run(["crontab", temp_path], check=True)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def upsert_block(existing: str, block: str) -> str:
    pattern = re.compile(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        re.DOTALL,
    )
    cleaned = pattern.sub("", existing).rstrip() + "\n"
    if cleaned.strip():
        return cleaned + "\n" + block
    return block


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Trading-Backtester repo root",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print crontab block only")
    parser.add_argument("--remove", action="store_true", help="Remove installed block")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    runner = repo_root / "modules/analysis/scripts/run_compliance_monitor.sh"
    if not runner.exists():
        raise SystemExit(f"Missing runner script: {runner}")
    ensure_executable(runner)

    local_tz = detect_local_tz()
    existing = read_crontab()

    if args.remove:
        pattern = re.compile(
            re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
            re.DOTALL,
        )
        new = pattern.sub("", existing).rstrip() + ("\n" if existing.strip() else "")
        if args.dry_run:
            print(new or "(empty crontab)")
            return
        if new.strip():
            write_crontab(new)
        else:
            subprocess.run(["crontab", "-r"], check=False)
        print("Removed trading-compliance-monitor cron block.")
        return

    block = build_cron_block(repo_root, local_tz)
    print(f"Detected local timezone: {local_tz.key}")
    print("Installing schedule (local wall times for Mon–Fri):")
    print(block)
    if args.dry_run:
        return

    merged = upsert_block(existing, block)
    write_crontab(merged)
    print("Installed. Verify with: crontab -l")
    print("Logs: modules/analysis/order-data/compliance-monitor.cron.log")


if __name__ == "__main__":
    main()
