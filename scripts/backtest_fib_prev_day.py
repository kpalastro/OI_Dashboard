#!/usr/bin/env python3
"""
Backtest Fibonacci previous-day high/low strategy on futures data.

- From 1 December to latest data in DB.
- BSE and NSE: use December future for December, January future for January, etc.
- Daily outcome: one trade per day based on first 0.618 bounce (long) or rejection (short).

Usage (from project root):
  python scripts/backtest_fib_prev_day.py
  python scripts/backtest_fib_prev_day.py --start 2025-12-01 --exchange NSE --exchange BSE
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database as db

# Resolutions for bars (1m or 5m)
RES_VARIANTS = ("1m", "1", "1min", "minute", "MINUTE", "ONE_MINUTE", "5", "5m", "5min")

# Month name -> substring to match in symbol (DEC future for Dec, etc.)
MONTH_SYMBOL_HINT = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}


def get_latest_date_in_db(exchange: str, start_dt: datetime) -> Optional[date]:
    """Return latest date with bars in DB for exchange (on or after start_dt)."""
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DATE(MAX(timestamp)) AS last_date
        FROM multi_resolution_bars
        WHERE exchange = %s
          AND timestamp >= %s
          AND resolution = ANY(%s)
        """,
        (exchange, start_dt, list(RES_VARIANTS)),
    )
    row = cur.fetchone()
    db.release_db_connection(conn)
    return row[0] if row and row[0] else None


def get_symbols_with_coverage(
    exchange: str,
    start_dt: datetime,
    end_dt: datetime,
) -> List[Tuple[str, date, date, int]]:
    """Return list of (symbol, first_date, last_date, bar_count) for exchange in range."""
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT symbol,
               DATE(MIN(timestamp)) AS first_date,
               DATE(MAX(timestamp)) AS last_date,
               COUNT(*) AS bar_count
        FROM multi_resolution_bars
        WHERE exchange = %s
          AND timestamp >= %s
          AND timestamp < %s
          AND resolution = ANY(%s)
          AND symbol IS NOT NULL
        GROUP BY symbol
        ORDER BY bar_count DESC
        """,
        (exchange, start_dt, end_dt, list(RES_VARIANTS)),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)
    return [
        (row[0], row[1], row[2], row[3])
        for row in rows
        if row[1] and row[2]
    ]


def pick_symbol_for_date(
    exchange: str,
    trade_date: date,
    symbols_with_coverage: List[Tuple[str, date, date, int]],
) -> Optional[str]:
    """
    Pick futures symbol for trade_date: December -> DEC future, January -> JAN future, etc.
    If no month-specific futures symbol has data on trade_date, use symbol with most bars in range.
    """
    month_hint = MONTH_SYMBOL_HINT.get(trade_date.month, "")
    candidates = []
    fallback = None
    for symbol, first_d, last_d, bar_count in symbols_with_coverage:
        if not (first_d <= trade_date <= last_d):
            continue
        sym_upper = symbol.upper()
        if month_hint and month_hint in sym_upper:
            candidates.append((symbol, bar_count))
        if fallback is None or bar_count > (fallback[1] if fallback else 0):
            fallback = (symbol, bar_count)
    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]
    return fallback[0] if fallback else None


def get_prev_day_high_low(
    exchange: str,
    symbol: str,
    trade_date: date,
) -> Optional[Tuple[float, float]]:
    """Return (high, low) for previous trading day for symbol."""
    prev = trade_date - timedelta(days=1)
    start_dt = datetime.combine(prev, datetime.min.time())
    end_dt = datetime.combine(prev + timedelta(days=1), datetime.min.time())
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT high_price, low_price
        FROM multi_resolution_bars
        WHERE exchange = %s AND symbol = %s
          AND timestamp >= %s AND timestamp < %s
          AND resolution = ANY(%s)
        """,
        (exchange, symbol, start_dt, end_dt, list(RES_VARIANTS)),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)
    valid = [r for r in rows if r[0] is not None and r[1] is not None]
    if not valid:
        return None
    high = max(float(r[0]) for r in valid)
    low = min(float(r[1]) for r in valid)
    return (high, low)


def get_bars_for_day(
    exchange: str,
    symbol: str,
    trade_date: date,
) -> List[Dict[str, Any]]:
    """Return list of bars (timestamp, open, high, low, close) for trade_date."""
    start_dt = datetime.combine(trade_date, datetime.min.time())
    end_dt = datetime.combine(trade_date + timedelta(days=1), datetime.min.time())
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, open_price, high_price, low_price, close_price
        FROM multi_resolution_bars
        WHERE exchange = %s AND symbol = %s
          AND timestamp >= %s AND timestamp < %s
          AND resolution = ANY(%s)
        ORDER BY timestamp
        """,
        (exchange, symbol, start_dt, end_dt, list(RES_VARIANTS)),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)
    return [
        {
            "ts": row[0],
            "open": float(row[1]) if row[1] is not None else None,
            "high": float(row[2]) if row[2] is not None else None,
            "low": float(row[3]) if row[3] is not None else None,
            "close": float(row[4]) if row[4] is not None else None,
        }
        for row in rows
        if row[1] is not None and row[4] is not None
    ]


def fib_levels(high: float, low: float) -> Dict[str, float]:
    """Compute key Fib levels. Low=0, High=1."""
    r = high - low
    return {
        "low": low,
        "high": high,
        "range": r,
        "ret_382": low + r * 0.382,
        "ret_5": low + r * 0.5,
        "ret_618": low + r * 0.618,
        "ret_786": low + r * 0.786,
        "ext_111_above": high + r * 0.11,
        "ext_111_below": low - r * 0.11,
        "ext_1272_above": high + r * 0.272,
        "ext_1272_below": low - r * 0.272,
    }


# Entry level ratio -> key in fib dict
ENTRY_RATIO_KEYS = {0.382: "ret_382", 0.5: "ret_5", 0.618: "ret_618", 0.786: "ret_786"}
# Target extension ratio -> (above key, below key)
TARGET_EXT_KEYS = {1.11: ("ext_111_above", "ext_111_below"), 1.272: ("ext_1272_above", "ext_1272_below")}


def run_fib_day(
    bars: List[Dict[str, Any]],
    fib: Dict[str, float],
    stop_buffer_pts: float = 15.0,
    entry_ratio: float = 0.618,
    target_ext_ratio: float = 1.11,
    sides: str = "both",
) -> Tuple[float, Optional[str], Optional[str]]:
    """
    One trade per day: first touch of entry_level + bounce = long, rejection = short.
    entry_ratio: 0.382, 0.5, 0.618, 0.786. target_ext_ratio: 1.11 or 1.272. sides: both, long_only, short_only.
    Returns (pnl_points, side, note).
    """
    if not bars or fib["range"] <= 0:
        return 0.0, None, "no_bars_or_range"
    ret_key = ENTRY_RATIO_KEYS.get(entry_ratio, "ret_618")
    ret_level = fib[ret_key]
    ext_keys = TARGET_EXT_KEYS.get(target_ext_ratio, ("ext_111_above", "ext_111_below"))
    ext_above = fib[ext_keys[0]]
    ext_below = fib[ext_keys[1]]
    prev_high = fib["high"]
    prev_low = fib["low"]
    stop_long = ret_level - stop_buffer_pts
    stop_short = ret_level + stop_buffer_pts

    entry_price: Optional[float] = None
    side: Optional[str] = None
    target: Optional[float] = None

    for i, b in enumerate(bars):
        o, h, l, c = b["open"], b["high"], b["low"], b["close"]
        if o is None or c is None:
            continue
        if side is not None:
            if side == "long":
                if l <= stop_long:
                    return stop_long - entry_price, "long", "stop"
                if h >= target:
                    return target - entry_price, "long", "target"
            else:
                if h >= stop_short:
                    return entry_price - stop_short, "short", "stop"
                if l <= target:
                    return entry_price - target, "short", "target"
            continue

        allow_long = sides in ("both", "long_only")
        allow_short = sides in ("both", "short_only")
        if allow_long and l <= ret_level and c > o and c > ret_level:
            entry_price = c
            side = "long"
            target = min(ext_above, prev_high + 1)
            continue
        if allow_short and h >= ret_level and c < o and c < ret_level:
            entry_price = c
            side = "short"
            target = max(ext_below, prev_low - 1)
            continue

    if side is not None and entry_price is not None:
        if side == "long":
            return c - entry_price, "long", "eod"
        return entry_price - c, "short", "eod"
    return 0.0, None, "no_setup"


def load_all_days_data(
    exchange: str,
    start_date: date,
    end_date: date,
) -> List[Tuple[date, str, float, float, List[Dict[str, Any]]]]:
    """
    Pre-load (date, symbol, prev_high, prev_low, bars) for each trading day.
    Returns list of (d, symbol, prev_high, prev_low, bars).
    """
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=30), datetime.min.time())
    symbols_with_coverage = get_symbols_with_coverage(exchange, start_dt, end_dt)
    if not symbols_with_coverage:
        return []

    out: List[Tuple[date, str, float, float, List[Dict[str, Any]]]] = []
    d = start_date
    while d <= end_date:
        symbol = pick_symbol_for_date(exchange, d, symbols_with_coverage)
        if not symbol:
            d += timedelta(days=1)
            continue
        prev_hl = get_prev_day_high_low(exchange, symbol, d)
        if not prev_hl:
            d += timedelta(days=1)
            continue
        prev_high, prev_low = prev_hl
        bars = get_bars_for_day(exchange, symbol, d)
        if not bars:
            d += timedelta(days=1)
            continue
        out.append((d, symbol, prev_high, prev_low, bars))
        d += timedelta(days=1)
    return out


def backtest_exchange(
    exchange: str,
    start_date: date,
    end_date: date,
    entry_ratio: float = 0.618,
    target_ext_ratio: float = 1.11,
    stop_buffer: float = 15.0,
    sides: str = "both",
    days_data: Optional[List[Tuple[date, str, float, float, List[Dict[str, Any]]]]] = None,
) -> Tuple[Dict[date, float], Dict[date, str], Dict[date, Optional[str]], float, str]:
    """
    Backtest Fib prev-day strategy with given params.
    If days_data is provided, reuse it (for grid search). Returns (daily_pnl, daily_symbol, daily_side, total_pnl, last_symbol).
    """
    if days_data is None:
        days_data = load_all_days_data(exchange, start_date, end_date)
    if not days_data:
        return {}, {}, {}, 0.0, ""

    daily_pnl: Dict[date, float] = {}
    daily_symbol: Dict[date, str] = {}
    daily_side: Dict[date, Optional[str]] = {}
    total_pnl = 0.0
    last_symbol = ""

    for d, symbol, prev_high, prev_low, bars in days_data:
        fib = fib_levels(prev_high, prev_low)
        pnl, side, _ = run_fib_day(
            bars, fib,
            stop_buffer_pts=stop_buffer,
            entry_ratio=entry_ratio,
            target_ext_ratio=target_ext_ratio,
            sides=sides,
        )
        daily_pnl[d] = pnl
        daily_symbol[d] = symbol
        daily_side[d] = side
        total_pnl += pnl
        last_symbol = symbol

    return daily_pnl, daily_symbol, daily_side, total_pnl, last_symbol


def grid_search_best_intraday(
    exchange: str,
    start_date: date,
    end_date: date,
    quick: bool = False,
) -> Tuple[Dict[str, Any], List[Tuple[date, str, Optional[str], float]]]:
    """
    Grid search over entry_ratio, target_ext_ratio, stop_buffer, sides.
    Returns (best_params_dict, best_daily_list).
    """
    days_data = load_all_days_data(exchange, start_date, end_date)
    if not days_data:
        return {}, []

    if quick:
        entry_ratios = (0.5, 0.618)
        target_ratios = (1.11, 1.272)
        stop_buffers = (10, 15, 20)
        sides_list = ("both", "long_only", "short_only")
    else:
        entry_ratios = (0.382, 0.5, 0.618, 0.786)
        target_ratios = (1.11, 1.272)
        stop_buffers = (10, 15, 20, 25)
        sides_list = ("both", "long_only", "short_only")

    best_total = -1e9
    best_params: Dict[str, Any] = {}
    best_daily: Dict[date, float] = {}
    best_symbol: Dict[date, str] = {}
    best_side: Dict[date, Optional[str]] = {}

    for entry_ratio in entry_ratios:
        for target_ratio in target_ratios:
            for stop_buf in stop_buffers:
                for sides in sides_list:
                    daily_pnl, daily_symbol, daily_side, total_pnl, _ = backtest_exchange(
                        exchange, start_date, end_date,
                        entry_ratio=entry_ratio,
                        target_ext_ratio=target_ratio,
                        stop_buffer=stop_buf,
                        sides=sides,
                        days_data=days_data,
                    )
                    if total_pnl > best_total:
                        best_total = total_pnl
                        best_params = {
                            "entry_ratio": entry_ratio,
                            "target_ext_ratio": target_ratio,
                            "stop_buffer": stop_buf,
                            "sides": sides,
                            "total_pnl": total_pnl,
                            "trades": sum(1 for s in daily_side.values() if s),
                            "days": len(daily_pnl),
                        }
                        best_daily = dict(daily_pnl)
                        best_symbol = dict(daily_symbol)
                        best_side = dict(daily_side)

    daily_list = [(d, best_symbol[d], best_side[d], best_daily[d]) for d in sorted(best_daily.keys())]
    return best_params, daily_list


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest Fib previous-day H/L strategy on futures (Dec fut for Dec, Jan fut for Jan)"
    )
    parser.add_argument("--start", default="2025-12-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD (default: latest in DB)")
    parser.add_argument("--exchange", action="append", default=[], help="BSE or NSE (repeat for both)")
    parser.add_argument("--daily", action="store_true", help="Print daily PnL and symbol per exchange")
    parser.add_argument("--best", action="store_true", help="Grid search for best intraday params (default)")
    parser.add_argument("--no-best", action="store_true", help="Use fixed params instead of grid search")
    parser.add_argument("--quick", action="store_true", help="Fewer param combos for faster grid search")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_date = date.today()
        for ex in (args.exchange or ["NSE", "BSE"]):
            latest = get_latest_date_in_db(ex, start_dt)
            if latest:
                end_date = latest
                break

    if not args.exchange:
        args.exchange = ["NSE", "BSE"]
    run_best = not args.no_best  # default: grid search for best intraday

    print("Fib Previous-Day High/Low Backtest (futures: Dec→DEC, Jan→JAN)")
    print(f"Period: {start_date} to {end_date}")
    print(f"Exchanges: {', '.join(args.exchange)}")
    if run_best:
        print("Mode: best intraday (grid search over entry/target/stop/sides)\n")
    else:
        print("Mode: fixed params (entry=0.618, target=1.11, stop=15, both)\n")

    all_daily: Dict[str, Dict[date, float]] = {}
    all_best_params: Dict[str, Dict[str, Any]] = {}

    for exchange in args.exchange:
        try:
            if run_best:
                best_params, daily_list = grid_search_best_intraday(
                    exchange, start_date, end_date, quick=args.quick
                )
                if not best_params:
                    print(f"{exchange}: No data.\n")
                    continue
                all_best_params[exchange] = best_params
                daily_pnl = {d: pnl for d, _, _, pnl in daily_list}
                daily_symbol = {d: sym for d, sym, _, _ in daily_list}
                daily_side = {d: side for d, _, side, _ in daily_list}
                total_pnl = best_params["total_pnl"]
            else:
                daily_pnl, daily_symbol, daily_side, total_pnl, _ = backtest_exchange(
                    exchange, start_date, end_date
                )
        except Exception as e:
            print(f"{exchange}: Error - {e}\n")
            continue
        all_daily[exchange] = daily_pnl
        trades = sum(1 for s in daily_side.values() if s)
        print(f"========== {exchange} ==========")
        if run_best and exchange in all_best_params:
            p = all_best_params[exchange]
            print(f"  Best params: entry={p['entry_ratio']} target_ext={p['target_ext_ratio']} stop_buf={p['stop_buffer']} sides={p['sides']}")
        print(f"  Total PnL (points): {total_pnl:.2f}  Trades: {trades}  Days: {len(daily_pnl)}")
        if daily_pnl:
            wins = sum(1 for p in daily_pnl.values() if p > 0)
            print(f"  Winning days: {wins}  Losing days: {len(daily_pnl) - wins}")
        if args.daily and daily_pnl:
            print("\n  Daily outcome (date, symbol, side, PnL):")
            for d in sorted(daily_pnl.keys()):
                sym = daily_symbol.get(d, "")
                side = daily_side.get(d) or "-"
                pnl = daily_pnl[d]
                print(f"    {d}  {sym}  {side}  {pnl:+.2f}")
        print()

    if len(all_daily) >= 2 and "NSE" in all_daily and "BSE" in all_daily:
        print("---------- Combined daily (NSE + BSE) ----------")
        nse_d = all_daily["NSE"]
        bse_d = all_daily["BSE"]
        all_dates = sorted(set(nse_d) | set(bse_d))
        for d in all_dates:
            nse_pnl = nse_d.get(d, 0.0)
            bse_pnl = bse_d.get(d, 0.0)
            print(f"  {d}  NSE: {nse_pnl:+.2f}  BSE: {bse_pnl:+.2f}  Combined: {nse_pnl + bse_pnl:+.2f}")
        print(f"  NSE total: {sum(nse_d.values()):.2f}  BSE total: {sum(bse_d.values()):.2f}")
    print("Done.")


if __name__ == "__main__":
    main()
