#!/usr/bin/env python3
"""
Compute Fibonacci levels from previous trading day high/low for next-day strategy.

Use either:
  1. Manual levels: --high <PDH> --low <PDL>
  2. From DB: --symbol NIFTY 50 --exchange NSE [--date YYYY-MM-DD]

Run from project root:
  python scripts/fib_prev_day_levels.py --high 25818.30 --low 25552.40
  python scripts/fib_prev_day_levels.py --symbol "NIFTY 50" --exchange NSE
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Standard Fib ratios (retracements between 0 and 1; extensions above/below)
RETRACEMENT_RATIOS = (0.27, 0.382, 0.5, 0.618, 0.786)
EXTENSION_RATIOS = (1.11, 1.272, 1.618, 2.618, 3.618, 4.236)


def fib_levels(high: float, low: float) -> dict:
    """Compute retracement and extension levels. Low = 0, High = 1."""
    r = high - low
    retracements = {}
    for ratio in RETRACEMENT_RATIOS:
        retracements[ratio] = round(low + r * ratio, 2)
    extensions_above = {}
    for ratio in EXTENSION_RATIOS:
        extensions_above[ratio] = round(high + r * (ratio - 1), 2)
    extensions_below = {}
    for ratio in EXTENSION_RATIOS:
        extensions_below[ratio] = round(low - r * (ratio - 1), 2)
    return {
        "high": high,
        "low": low,
        "range": round(r, 2),
        "retracements": retracements,
        "extensions_above": extensions_above,
        "extensions_below": extensions_below,
    }


def get_prev_day_high_low_from_db(
    symbol: str,
    exchange: str,
    as_of_date: date,
) -> tuple[float, float, date] | None:
    """Return (high, low, prev_date) for the previous trading day from multi_resolution_bars."""
    try:
        import database as db
    except ImportError:
        return None
    if not hasattr(db, "get_db_connection"):
        return None
    # Previous calendar day (no holiday calendar; can be improved)
    prev = as_of_date - timedelta(days=1)
    start_dt = datetime.combine(prev, datetime.min.time())
    end_dt = datetime.combine(prev + timedelta(days=1), datetime.min.time())
    res_variants = ("1m", "1", "1min", "minute", "MINUTE", "ONE_MINUTE", "5", "5m", "5min")
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT high_price, low_price
        FROM multi_resolution_bars
        WHERE exchange = %s
          AND symbol = %s
          AND timestamp >= %s
          AND timestamp < %s
          AND resolution = ANY(%s)
        """,
        (exchange, symbol, start_dt, end_dt, list(res_variants)),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)
    if not rows:
        return None
    valid = [r for r in rows if r[0] is not None and r[1] is not None]
    if not valid:
        return None
    high = max(float(r[0]) for r in valid)
    low = min(float(r[1]) for r in valid)
    return (high, low, prev)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fibonacci levels from previous day high/low for next-day strategy",
    )
    parser.add_argument("--high", type=float, help="Previous day high (manual)")
    parser.add_argument("--low", type=float, help="Previous day low (manual)")
    parser.add_argument("--symbol", type=str, default="", help="Symbol (e.g. NIFTY 50) for DB fetch")
    parser.add_argument("--exchange", type=str, default="NSE", help="Exchange (default NSE)")
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="As-of date YYYY-MM-DD (default: today); prev day H/L fetched for next day",
    )
    args = parser.parse_args()

    high: float | None = args.high
    low: float | None = args.low
    prev_date: date | None = None

    if high is not None and low is not None:
        if high < low:
            high, low = low, high
    elif args.symbol:
        as_of = date.today()
        if args.date:
            try:
                as_of = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print("Invalid --date; use YYYY-MM-DD", file=sys.stderr)
                sys.exit(1)
        result = get_prev_day_high_low_from_db(args.symbol.strip(), args.exchange.upper(), as_of)
        if result is None:
            print(
                f"No bars for symbol={args.symbol!r} exchange={args.exchange} on previous day of {as_of}",
                file=sys.stderr,
            )
            sys.exit(1)
        high, low, prev_date = result
        if high < low:
            high, low = low, high
    else:
        parser.print_help()
        print("\nProvide either (--high and --low) or --symbol (and optional --exchange, --date).", file=sys.stderr)
        sys.exit(1)

    levels = fib_levels(high, low)
    print("Fibonacci levels (Prev Day High/Low → Next Day)")
    print("Low = 0, High = 1, Range =", levels["range"])
    if prev_date:
        print("Prev trading day:", prev_date)
    print()
    print("Anchor:  Low (0) =", levels["low"], "  High (1) =", levels["high"])
    print()
    print("Retracements (between low and high):")
    for r in RETRACEMENT_RATIOS:
        print(f"  {r:.3f}  {levels['retracements'][r]}")
    print()
    print("Extensions above high:")
    for r in EXTENSION_RATIOS:
        print(f"  {r:.3f}  {levels['extensions_above'][r]}")
    print()
    print("Extensions below low:")
    for r in EXTENSION_RATIOS:
        print(f"  {r:.3f}  {levels['extensions_below'][r]}")


if __name__ == "__main__":
    main()
