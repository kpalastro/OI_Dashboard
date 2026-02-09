#!/usr/bin/env python3
"""
Backtest option strategy using ITM CE/PE OI % Change (3m wavg) and Volume % Change (3m wavg).
Ignores existing paper_trades signals; finds best rule set day-by-day from OI/Vol only.

Usage (from project root):
    python scripts/backtest_oi_vol_strategy.py
    python scripts/backtest_oi_vol_strategy.py --start 2026-01-19 --end 2026-01-31
    python scripts/backtest_oi_vol_strategy.py --exchange BSE --exchange NSE
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database as db  # noqa: E402

# Resolutions treated as 1m
RES_VARIANTS = ("1m", "1", "1min", "minute", "MINUTE", "ONE_MINUTE")


def load_oi_vol(exchange: str, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Load ml_features (OI/Vol % change) for exchange and range."""
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            timestamp,
            itm_oi_ce_pct_change_3m_wavg AS ce_oi_pct,
            itm_oi_pe_pct_change_3m_wavg AS pe_oi_pct,
            feature_payload
        FROM ml_features
        WHERE exchange = %s
          AND timestamp >= %s
          AND timestamp < %s
        ORDER BY timestamp
        """,
        (exchange, start_dt, end_dt),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)

    records = []
    for ts, ce_oi, pe_oi, payload in rows:
        ce_vol = pe_vol = None
        if payload:
            try:
                p = json.loads(payload) if isinstance(payload, str) else payload
                if isinstance(p, dict):
                    ce_vol = p.get("itm_volume_ce_pct_change_3m_wavg")
                    pe_vol = p.get("itm_volume_pe_pct_change_3m_wavg")
            except Exception:
                pass
        records.append(
            {
                "timestamp": ts,
                "ce_oi_pct": float(ce_oi) if ce_oi is not None else None,
                "pe_oi_pct": float(pe_oi) if pe_oi is not None else None,
                "ce_vol_pct": float(ce_vol) if ce_vol is not None else None,
                "pe_vol_pct": float(pe_vol) if pe_vol is not None else None,
            }
        )

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_bars_1m(
    exchange: str, start_dt: datetime, end_dt: datetime, symbol: Optional[str] = None
) -> Tuple[Optional[str], pd.DataFrame]:
    """Load 1m OHLC bars; if symbol not given, pick symbol with most bars. Returns (symbol, df)."""
    conn = db.get_db_connection()
    cur = conn.cursor()

    chosen = symbol
    if not chosen:
        cur.execute(
            """
            SELECT symbol, COUNT(*) AS c
            FROM multi_resolution_bars
            WHERE exchange = %s
              AND timestamp >= %s
              AND timestamp < %s
              AND resolution = ANY(%s)
              AND symbol IS NOT NULL
            GROUP BY symbol
            ORDER BY c DESC
            LIMIT 1
            """,
            (exchange, start_dt, end_dt, list(RES_VARIANTS)),
        )
        row = cur.fetchone()
        if row and row[0]:
            chosen = row[0]

    bars = []
    if chosen:
        cur.execute(
            """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume, oi
            FROM multi_resolution_bars
            WHERE exchange = %s AND symbol = %s
              AND timestamp >= %s AND timestamp < %s
              AND resolution = ANY(%s)
            ORDER BY timestamp
            """,
            (exchange, chosen, start_dt, end_dt, list(RES_VARIANTS)),
        )
        for row in cur.fetchall():
            bars.append(
                {
                    "timestamp": row[0],
                    "open": float(row[1]) if row[1] is not None else None,
                    "high": float(row[2]) if row[2] is not None else None,
                    "low": float(row[3]) if row[3] is not None else None,
                    "close": float(row[4]) if row[4] is not None else None,
                    "volume": row[5],
                    "oi": row[6],
                }
            )
    db.release_db_connection(conn)

    if not bars:
        return chosen, pd.DataFrame()
    bdf = pd.DataFrame(bars)
    bdf["timestamp"] = pd.to_datetime(bdf["timestamp"], utc=True)
    return chosen, bdf


def merge_oi_vol_into_bars(oi_df: pd.DataFrame, bars_df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill OI/Vol onto each bar by timestamp (merge_asof)."""
    if oi_df.empty or bars_df.empty:
        return pd.DataFrame()
    oi_df = oi_df.sort_values("timestamp")
    bars_df = bars_df.sort_values("timestamp")
    merged = pd.merge_asof(
        bars_df,
        oi_df,
        on="timestamp",
        direction="backward",
        suffixes=("", "_oi"),
    )
    return merged


def compute_signal_row(row: pd.Series, rule: str, thresh: float, vol_weight: float = 0.5) -> int:
    """
    Return 1 = BUY (long), -1 = SELL (short), 0 = flat.
    rule: 'oi_spread' | 'vol_spread' | 'oi_plus_vol' | 'pe_dominance' | 'ce_dominance'
    """
    ce_oi = row.get("ce_oi_pct")
    pe_oi = row.get("pe_oi_pct")
    ce_vol = row.get("ce_vol_pct")
    pe_vol = row.get("pe_vol_pct")

    def safe(x):
        return float(x) if x is not None and pd.notna(x) else 0.0

    if rule == "oi_spread":
        # CE OI % - PE OI %: positive = call buildup (bullish), negative = put buildup (bearish)
        s = safe(ce_oi) - safe(pe_oi)
    elif rule == "vol_spread":
        s = safe(ce_vol) - safe(pe_vol)
    elif rule == "oi_plus_vol":
        s = (safe(ce_oi) - safe(pe_oi)) + vol_weight * (safe(ce_vol) - safe(pe_vol))
    elif rule == "pe_dominance":
        # PE > CE => bearish
        s = safe(pe_oi) - safe(ce_oi)
    elif rule == "ce_dominance":
        s = safe(ce_oi) - safe(pe_oi)
    else:
        s = safe(ce_oi) - safe(pe_oi)

    if s > thresh:
        return 1
    if s < -thresh:
        return -1
    return 0


def backtest_day(
    day_df: pd.DataFrame,
    rule: str,
    thresh: float,
    hold_bars: int,
    vol_weight: float = 0.5,
    min_bars_after_signal: int = 1,
) -> Tuple[float, int, List[Dict[str, Any]]]:
    """
    Run single-day backtest. Enters at bar open after signal, exits after hold_bars or opposite signal.
    Returns (total_pnl_points, num_trades, list of trade dicts).
    """
    trades: List[Dict[str, Any]] = []
    position = 0  # 1 long, -1 short, 0 flat
    entry_bar_idx: Optional[int] = None
    entry_price: Optional[float] = None

    for i in range(len(day_df)):
        row = day_df.iloc[i]
        open_p = row.get("open")
        close_p = row.get("close")
        if open_p is None or close_p is None:
            continue

        sig = compute_signal_row(row, rule, thresh, vol_weight)

        if position != 0:
            # Check exit: hold_bars elapsed or opposite signal
            bars_held = i - entry_bar_idx if entry_bar_idx is not None else 0
            exit_signal = (sig == -position) or (hold_bars > 0 and bars_held >= hold_bars)
            if exit_signal and entry_price is not None:
                exit_price = open_p  # exit at open of current bar (or use close for same bar)
                if position == 1:
                    pnl = exit_price - entry_price
                else:
                    pnl = entry_price - exit_price
                trades.append(
                    {
                        "entry_bar": entry_bar_idx,
                        "exit_bar": i,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "side": "long" if position == 1 else "short",
                        "pnl_points": pnl,
                    }
                )
                position = 0
                entry_bar_idx = None
                entry_price = None

        if position == 0 and sig != 0 and i + min_bars_after_signal < len(day_df):
            # Enter at next bar open
            next_open = day_df.iloc[i + 1].get("open") if i + 1 < len(day_df) else None
            if next_open is not None:
                position = sig
                entry_bar_idx = i + 1
                entry_price = next_open

    # Unclosed position: mark to market at last close
    if position != 0 and entry_price is not None and len(day_df) > 0:
        last_close = day_df.iloc[-1].get("close")
        if last_close is not None:
            pnl = (last_close - entry_price) if position == 1 else (entry_price - last_close)
            trades.append(
                {
                    "entry_bar": entry_bar_idx,
                    "exit_bar": len(day_df) - 1,
                    "entry_price": entry_price,
                    "exit_price": last_close,
                    "side": "long" if position == 1 else "short",
                    "pnl_points": pnl,
                }
            )

    total_pnl = sum(t["pnl_points"] for t in trades)
    return total_pnl, len(trades), trades


def backtest_exchange(
    exchange: str,
    start_date: date,
    end_date: date,
    rule: str,
    thresh: float,
    hold_bars: int,
    vol_weight: float = 0.5,
) -> Tuple[Dict[date, float], float, int, Dict]:
    """Backtest over date range, day-by-day. Returns (daily_pnl, total_pnl, total_trades, best_day_detail)."""
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    oi_df = load_oi_vol(exchange, start_dt, end_dt)
    symbol, bars_df = load_bars_1m(exchange, start_dt, end_dt, symbol=None)

    if oi_df.empty or bars_df.empty:
        return {}, 0.0, 0, {}

    merged = merge_oi_vol_into_bars(oi_df, bars_df)
    merged["date"] = merged["timestamp"].dt.date

    daily_pnl: Dict[date, float] = {}
    all_trades: List[Dict] = []
    best_day_detail: Dict = {}

    for d, day_df in merged.groupby("date"):
        day_df = day_df.sort_values("timestamp").reset_index(drop=True)
        pnl, num_trades, trades = backtest_day(
            day_df, rule=rule, thresh=thresh, hold_bars=hold_bars, vol_weight=vol_weight
        )
        daily_pnl[d] = pnl
        all_trades.extend(trades)

    total_pnl = sum(daily_pnl.values())
    total_trades = len(all_trades)

    # Best day (max PnL)
    if daily_pnl:
        best_date = max(daily_pnl, key=daily_pnl.get)
        best_day_detail = {"date": best_date, "pnl": daily_pnl[best_date]}

    return daily_pnl, total_pnl, total_trades, best_day_detail


def grid_search(
    exchange: str,
    start_date: date,
    end_date: date,
    rules: Optional[List[str]] = None,
    thresholds: Optional[List[float]] = None,
    hold_bars_list: Optional[List[int]] = None,
    vol_weights: Optional[List[float]] = None,
    quick: bool = False,
) -> List[Dict[str, Any]]:
    """Try combinations of rule, thresh, hold_bars, vol_weight; return sorted by total PnL."""
    if quick:
        rules = rules or ["oi_spread", "oi_plus_vol", "vol_spread"]
        thresholds = thresholds or [0.2, 0.5, 1.0]
        hold_bars_list = hold_bars_list or [5, 15, 30]
        vol_weights = vol_weights or [0.5]
    else:
        rules = rules or ["oi_spread", "oi_plus_vol", "vol_spread", "pe_dominance"]
        thresholds = thresholds or [0.0, 0.2, 0.5, 1.0, 1.5, 2.0]
        hold_bars_list = hold_bars_list or [3, 5, 10, 15, 30]
        vol_weights = vol_weights or [0.3, 0.5, 0.7]

    results = []
    for rule in rules:
        for thresh in thresholds:
            for hold_bars in hold_bars_list:
                if rule == "oi_plus_vol":
                    for vw in vol_weights:
                        daily, total_pnl, num_trades, best = backtest_exchange(
                            exchange, start_date, end_date, rule, thresh, hold_bars, vol_weight=vw
                        )
                        results.append(
                            {
                                "rule": rule,
                                "thresh": thresh,
                                "hold_bars": hold_bars,
                                "vol_weight": vw,
                                "total_pnl_points": round(total_pnl, 2),
                                "num_trades": num_trades,
                                "daily_pnl": daily,
                                "best_day": best,
                            }
                        )
                else:
                    daily, total_pnl, num_trades, best = backtest_exchange(
                        exchange, start_date, end_date, rule, thresh, hold_bars
                    )
                    results.append(
                        {
                            "rule": rule,
                            "thresh": thresh,
                            "hold_bars": hold_bars,
                            "vol_weight": None,
                            "total_pnl_points": round(total_pnl, 2),
                            "num_trades": num_trades,
                            "daily_pnl": daily,
                            "best_day": best,
                        }
                    )

    results.sort(key=lambda x: (-x["total_pnl_points"], -x["num_trades"]))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Backtest OI/Vol strategy day-by-day (ignore paper signals)"
    )
    parser.add_argument("--start", default="2026-01-19", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="2026-01-31", help="End date YYYY-MM-DD")
    parser.add_argument(
        "--exchange", action="append", default=[], help="Exchange (BSE/NSE); repeat for both"
    )
    parser.add_argument("--top", type=int, default=10, help="Show top N strategies per exchange")
    parser.add_argument("--daily", action="store_true", help="Print daily PnL for best strategy")
    parser.add_argument(
        "--quick", action="store_true", help="Fewer rule/thresh/hold combos (faster)"
    )
    args = parser.parse_args()

    if not args.exchange:
        args.exchange = ["BSE", "NSE"]

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    print(
        f"Backtest: {args.start} to {args.end} using ITM CE/PE OI % & Volume % (3m wavg) only (no paper signals)\n"
    )

    for exchange in args.exchange:
        print(f"========== {exchange} ==========")
        try:
            results = grid_search(exchange, start_date, end_date, quick=args.quick)
        except Exception as e:
            print(f"  Error: {e}\n")
            continue

        if not results:
            print("  No data for this exchange/range.\n")
            continue

        best = results[0]
        print(
            f"  Best strategy: rule={best['rule']} thresh={best['thresh']} hold_bars={best['hold_bars']}",
            end="",
        )
        if best.get("vol_weight") is not None:
            print(f" vol_weight={best['vol_weight']}", end="")
        print(f"  => total PnL = {best['total_pnl_points']} points in {best['num_trades']} trades")
        if best.get("best_day"):
            print(
                f"  Best day: {best['best_day'].get('date')} PnL = {best['best_day'].get('pnl', 0):.2f} points"
            )

        print(f"\n  Top {args.top} strategies:")
        for i, r in enumerate(results[: args.top], 1):
            vw = f" vol_weight={r['vol_weight']}" if r.get("vol_weight") is not None else ""
            print(
                f"    {i}. {r['rule']} thresh={r['thresh']} hold={r['hold_bars']}{vw} => {r['total_pnl_points']} pts ({r['num_trades']} trades)"
            )

        if args.daily and best.get("daily_pnl"):
            print("\n  Daily PnL (best strategy):")
            for d in sorted(best["daily_pnl"].keys()):
                print(f"    {d}: {best['daily_pnl'][d]:.2f} points")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
