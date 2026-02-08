# OI Dashboard

ITM OI + Volume dashboard using TradingView Lightweight Charts. Based on `OI_Newdb_v2/scripts/oi_volume_dashboard.py`.

## Features

- **Exchange**: NSE / BSE
- **Date range**: From / To
- **Charts**:
  - 1m candlesticks + trade markers (entry/exit)
  - ITM CE/PE OI % change (3m wavg) and Volume % change (3m wavg)
- **Trade filter**: All / Profit only / Loss only

## Setup

1. Copy `.env` and set PostgreSQL and Flask options:

   ```env
   OI_TRACKER_DB_TYPE=postgres
   OI_TRACKER_DB_HOST=localhost
   OI_TRACKER_DB_PORT=5432
   OI_TRACKER_DB_NAME=oi_db_live
   OI_TRACKER_DB_USER=root
   OI_TRACKER_DB_PASSWORD=password

   FLASK_HOST=0.0.0.0
   FLASK_PORT=5055
   ```

   Optional: point trade logs to the other project:

   ```env
   OI_TRACKER_TRADE_LOG_DIR=/path/to/OI_Newdb_v2/trade_logs
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Run

From the project root (`OI_Dashboard`):

```bash
python scripts/oi_volume_dashboard.py
```

Then open in the browser:

- **http://127.0.0.1:5055/** (or the host/port from `.env`)

## Database

Expects the same schema as OI_Newdb_v2:

- `ml_features` (timestamp, exchange, itm_oi_ce_pct_change_3m_wavg, itm_oi_pe_pct_change_3m_wavg, feature_payload)
- `multi_resolution_bars` (timestamp, exchange, symbol, resolution, open_price, high_price, low_price, close_price, volume, oi)
- Views: `daily_pnl_report_view` (daily summary), `paper_trades_signal_changes_view` (BUY/SELL signals for chart markers; no direct use of `paper_trading_metrics`)

Trade markers are loaded from CSV files under `trade_logs/` (or `OI_TRACKER_TRADE_LOG_DIR`), e.g. `trade_logs/trades_YYYY-MM-DD.csv`.

## Backtest Fib previous-day strategy (futures)

Backtest the Fibonacci previous-day high/low strategy on **futures** (December future for December, January for January, etc.) from 1 December to latest data in DB, for both BSE and NSE:

```bash
python scripts/backtest_fib_prev_day.py --start 2025-12-01
python scripts/backtest_fib_prev_day.py --start 2025-12-01 --daily
```

- **Best intraday (default):** Grid search over entry level (0.382, 0.5, 0.618, 0.786), target extension (1.11, 1.272), stop buffer (10–25 pts), and sides (both / long_only / short_only). Reports the best params and PnL per exchange. Use `--no-best` for fixed params (0.618, 1.11, 15, both). Use `--quick` for fewer combos.
- Uses `multi_resolution_bars` (1m/5m) for prev day H/L and intraday bars.
- Picks symbol by month: DEC future for Dec, JAN for Jan, etc.; falls back to symbol with data if no month match.
- One trade per day: first Fib-level bounce = long, first rejection = short; target 1.11/1.272 extension, stop at entry level ± buffer.
- `--daily` prints each day’s outcome (symbol, side, PnL) and combined NSE+BSE.

## Backtest OI/Vol strategy (no paper signals)

Find the best rule-based strategy using **only** ITM CE/PE OI % Change (3m wavg) and Volume % Change (3m wavg), day-by-day, ignoring existing paper-trade signals:

```bash
python scripts/backtest_oi_vol_strategy.py --start 2026-01-19 --end 2026-01-31 --exchange BSE --exchange NSE --top 5 --daily
```

- **`--quick`**: fewer rule/threshold/hold combinations (faster).
- **Rules tried**: `oi_spread` (CE OI % − PE OI %), `vol_spread`, `oi_plus_vol`, `pe_dominance`.
- **Output**: best strategy (rule, threshold, hold_bars) and total/daily PnL in points; optionally daily breakdown with `--daily`.
