#!/usr/bin/env python3
"""
Interactive ITM OI + Volume dashboard using TradingView Lightweight Charts.

Features:
- Select exchange (NSE / BSE)
- Select date range (from / to)
- Plots:
  - ITM CE / PE OI % change vs time
  - ITM CE / PE Volume % change vs time

Run from project root:
    python scripts/oi_volume_dashboard.py

Then open in browser:
    http://127.0.0.1:7000/
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, Response, jsonify, request

# Project root = OI_Dashboard (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database as db  # noqa: E402

app = Flask(__name__)

try:
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = None


def _to_utc_epoch_seconds(ts: datetime) -> int:
    if ts is None:
        return 0
    if ts.tzinfo is None:
        if IST is not None:
            ts = ts.replace(tzinfo=IST).astimezone(timezone.utc)
        else:
            ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return int(ts.timestamp())


def _parse_date(s: str, default: date) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return default


def _parse_int(s: str, default: int) -> int:
    try:
        return int(s)
    except Exception:
        return default


@app.route("/api/itm_oi_volume")
def api_itm_oi_volume() -> Response:
    """Return ITM CE/PE OI% and Volume% time series for given exchange and date range."""
    exchange = request.args.get("exchange", "NSE").upper()
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=5)
    start_date = _parse_date(request.args.get("start", ""), default_start)
    end_date = _parse_date(request.args.get("end", ""), today)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    conn = db.get_db_connection()
    cur = conn.cursor()

    query = """
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
    """
    cur.execute(query, (exchange, start_dt, end_dt))
    rows = cur.fetchall()
    db.release_db_connection(conn)

    points: List[Dict[str, Any]] = []
    for ts, ce_oi, pe_oi, payload in rows:
        ce_vol = None
        pe_vol = None
        if payload:
            try:
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if isinstance(payload, dict):
                    ce_vol = payload.get("itm_volume_ce_pct_change_3m_wavg")
                    pe_vol = payload.get("itm_volume_pe_pct_change_3m_wavg")
            except Exception:
                pass

        t = _to_utc_epoch_seconds(ts)
        points.append(
            {
                "time": t,
                "ce_oi_pct": float(ce_oi) if ce_oi is not None else None,
                "pe_oi_pct": float(pe_oi) if pe_oi is not None else None,
                "ce_vol_pct": float(ce_vol) if ce_vol is not None else None,
                "pe_vol_pct": float(pe_vol) if pe_vol is not None else None,
            }
        )

    return jsonify(
        {
            "exchange": exchange,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "points": points,
        }
    )


@app.route("/api/bars_1m")
def api_bars_1m() -> Response:
    """Return 1-minute OHLCV (and OI) bars from multi_resolution_bars for a symbol."""
    exchange = request.args.get("exchange", "NSE").upper()
    symbol = (request.args.get("symbol") or "").strip()
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=5)
    start_date = _parse_date(request.args.get("start", ""), default_start)
    end_date = _parse_date(request.args.get("end", ""), today)
    limit = _parse_int(request.args.get("limit", ""), 5000)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    conn = db.get_db_connection()
    cur = conn.cursor()

    res_variants = ("1m", "1", "1min", "minute", "MINUTE", "ONE_MINUTE")

    chosen_symbol = symbol
    if not chosen_symbol:
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
            (exchange, start_dt, end_dt, list(res_variants)),
        )
        row = cur.fetchone()
        if row and row[0]:
            chosen_symbol = row[0]

    bars: List[Dict[str, Any]] = []
    if chosen_symbol:
        cur.execute(
            """
            SELECT
              timestamp,
              open_price, high_price, low_price, close_price,
              volume, oi
            FROM multi_resolution_bars
            WHERE exchange = %s
              AND symbol = %s
              AND timestamp >= %s
              AND timestamp < %s
              AND resolution = ANY(%s)
            ORDER BY timestamp
            LIMIT %s
            """,
            (exchange, chosen_symbol, start_dt, end_dt, list(res_variants), limit),
        )
        rows = cur.fetchall()
        for ts, o, h, low, c, v, oi in rows:
            bars.append(
                {
                    "time": _to_utc_epoch_seconds(ts),
                    "open": float(o) if o is not None else None,
                    "high": float(h) if h is not None else None,
                    "low": float(low) if low is not None else None,
                    "close": float(c) if c is not None else None,
                    "volume": int(v) if v is not None else None,
                    "oi": int(oi) if oi is not None else None,
                }
            )

    db.release_db_connection(conn)
    return jsonify(
        {
            "exchange": exchange,
            "symbol": chosen_symbol,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "bars": bars,
        }
    )


@app.route("/api/trade_logs")
def api_trade_logs() -> Response:
    """
    Return trade data from views only (no paper_trading_metrics):
    - daily_pnl_report_view: daily summary (trade_date, exchange, reason, pnl, trades)
    - paper_trades_signal_changes_view: BUY/SELL signal changes for chart markers
    """
    exchange = (request.args.get("exchange") or "").upper().strip()
    symbol = (
        request.args.get("symbol") or ""
    ).strip()  # signal_changes view has no symbol; kept for API compat
    outcome = (request.args.get("outcome") or "all").strip().lower()
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=5)
    start_date = _parse_date(request.args.get("start", ""), default_start)
    end_date = _parse_date(request.args.get("end", ""), today)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    conn = db.get_db_connection()
    cur = conn.cursor()

    # 1) Daily summary from daily_pnl_report_view
    daily_summary: List[Dict[str, Any]] = []
    view_query = """
        SELECT trade_date, exchange, reason, pnl, trades
        FROM daily_pnl_report_view
        WHERE trade_date >= %s AND trade_date <= %s
    """
    view_params = [start_date, end_date]
    if exchange:
        view_query += " AND exchange = %s"
        view_params.append(exchange)
    view_query += " ORDER BY trade_date, exchange, reason"
    try:
        cur.execute(view_query, view_params)
        for row in cur.fetchall():
            daily_summary.append(
                {
                    "trade_date": row[0].isoformat()
                    if hasattr(row[0], "isoformat")
                    else str(row[0]),
                    "exchange": row[1],
                    "reason": row[2],
                    "pnl": float(row[3]) if row[3] is not None else None,
                    "trades": int(row[4]) if row[4] is not None else 0,
                }
            )
    except Exception:
        pass

    # 2) BUY/SELL signals from paper_trades_signal_changes_view (view only; no paper_trading_metrics)
    trades: List[Dict[str, Any]] = []
    signal_query = """
        SELECT timestamp, exchange, signal, pnl, reason
        FROM paper_trades_signal_changes_view
        WHERE timestamp >= %s AND timestamp < %s
    """
    signal_params = [start_dt, end_dt]
    if exchange:
        signal_query += " AND exchange = %s"
        signal_params.append(exchange)
    signal_query += " ORDER BY timestamp"
    try:
        cur.execute(signal_query, signal_params)
        for ts, ex, signal, pnl_val, reason in cur.fetchall():
            side = str(signal or "BUY").upper().strip()
            if side not in ("BUY", "SELL"):
                continue
            try:
                pnl_float = float(pnl_val) if pnl_val is not None else None
            except Exception:
                pnl_float = None
            if outcome == "profit" and not (pnl_float is not None and pnl_float > 0):
                continue
            if outcome == "loss" and not (pnl_float is not None and pnl_float < 0):
                continue
            t_epoch = _to_utc_epoch_seconds(ts)
            trades.append(
                {
                    "symbol": None,
                    "exchange": ex,
                    "side": side,
                    "entry_time": t_epoch,
                    "exit_time": None,
                    "entry_price": None,
                    "exit_price": None,
                    "pnl": pnl_float,
                    "exit_reason": str(reason) if reason else None,
                }
            )
    except Exception:
        pass

    db.release_db_connection(conn)

    return jsonify(
        {
            "exchange": exchange or None,
            "symbol": symbol or None,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "daily_summary": daily_summary,
            "trades": trades,
        }
    )


@app.route("/api/paper_trading_signals")
def api_paper_trading_signals() -> Response:
    """Return BUY/SELL signals from paper_trades_signal_changes_view (view only)."""
    exchange = (request.args.get("exchange") or "").upper().strip()
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=5)
    start_date = _parse_date(request.args.get("start", ""), default_start)
    end_date = _parse_date(request.args.get("end", ""), today)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    conn = db.get_db_connection()
    cur = conn.cursor()

    query = """
        SELECT timestamp, exchange, signal, executed, confidence, reason
        FROM paper_trades_signal_changes_view
        WHERE timestamp >= %s AND timestamp < %s
    """
    params = [start_dt, end_dt]
    if exchange:
        query += " AND exchange = %s"
        params.append(exchange)
    query += " ORDER BY timestamp"

    cur.execute(query, params)
    rows = cur.fetchall()
    db.release_db_connection(conn)

    signals: List[Dict[str, Any]] = []
    for ts, ex, signal, executed, confidence, reason in rows:
        signal_str = str(signal or "").upper().strip()
        if signal_str not in ("BUY", "SELL"):
            continue
        signals.append(
            {
                "time": _to_utc_epoch_seconds(ts),
                "signal": signal_str,
                "executed": bool(executed) if executed is not None else False,
                "confidence": float(confidence) if confidence is not None else None,
                "reason": str(reason) if reason else None,
                "symbol": None,
            }
        )

    return jsonify(
        {
            "exchange": exchange or None,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "signals": signals,
        }
    )


@app.route("/api/symbols")
def api_symbols() -> Response:
    """Return list of available symbols from multi_resolution_bars."""
    exchange = request.args.get("exchange", "NSE").upper()
    today = datetime.utcnow().date()
    default_start = today - timedelta(days=5)
    start_date = _parse_date(request.args.get("start", ""), default_start)
    end_date = _parse_date(request.args.get("end", ""), today)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    res_variants = ("1m", "1", "1min", "minute", "MINUTE", "ONE_MINUTE")

    conn = db.get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT symbol, COUNT(*) AS bar_count
        FROM multi_resolution_bars
        WHERE exchange = %s
          AND timestamp >= %s
          AND timestamp < %s
          AND resolution = ANY(%s)
          AND symbol IS NOT NULL
        GROUP BY symbol
        ORDER BY bar_count DESC, symbol ASC
        LIMIT 100
        """,
        (exchange, start_dt, end_dt, list(res_variants)),
    )
    rows = cur.fetchall()
    db.release_db_connection(conn)

    symbols = [{"symbol": row[0], "bar_count": row[1]} for row in rows]
    return jsonify(
        {
            "exchange": exchange,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "symbols": symbols,
        }
    )


@app.route("/")
def index() -> str:
    """Serve a single-page dashboard using TradingView Lightweight Charts."""
    html = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>ITM OI + Volume Dashboard</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 0; background: #0b1622; color: #e0e6f0; }
      .container { padding: 16px; max-width: 1200px; margin: 0 auto; }
      .controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
      .controls label { font-size: 13px; margin-right: 4px; }
      .controls input, .controls select, .controls button { font-size: 13px; padding: 4px 6px; border-radius: 4px; border: 1px solid #2b3a4a; background: #111827; color: #e0e6f0; }
      .controls button { cursor: pointer; background: #2563eb; border-color: #2563eb; }
      .controls button:disabled { opacity: 0.5; cursor: default; }
      .chart-row { display: flex; flex-direction: column; gap: 8px; }
      .chart-title { font-size: 14px; margin-top: 8px; margin-bottom: 4px; }
      #chart-1m { height: 400px; }
      #chart-subpanel { height: 300px; }
      .status { font-size: 12px; margin-top: 6px; color: #9ca3af; }
      .hover-info { font-size: 12px; margin-top: 4px; color: #e5e7eb; white-space: pre-line; }
      a { color: #60a5fa; }
    </style>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
  </head>
  <body>
    <div class="container">
      <h2>ITM CE/PE OI &amp; Volume % Change (TradingView Lightweight Charts)</h2>
      <div class="controls">
        <label for="exchange">Exchange:</label>
        <select id="exchange">
          <option value="NSE">NSE</option>
          <option value="BSE">BSE</option>
        </select>
        <label for="symbol">Symbol:</label>
        <select id="symbol">
          <option value="">(Auto-select)</option>
        </select>
        <label for="tradeFilter">Trades:</label>
        <select id="tradeFilter">
          <option value="all">All</option>
          <option value="profit">Profit only</option>
          <option value="loss">Loss only</option>
        </select>
        <label for="start">From:</label>
        <input type="date" id="start" />
        <label for="end">To:</label>
        <input type="date" id="end" />
        <button id="load-btn">Load</button>
        <span class="status" id="status"></span>
      </div>
      <div class="hover-info" id="hover-info"></div>
      <div class="chart-row">
        <div class="chart-title">1m Candles + Trade Markers</div>
        <div id="chart-1m"></div>
        <div class="chart-title">ITM CE/PE OI % Change (3m wavg) &amp; Volume % Change (3m wavg)</div>
        <div id="chart-subpanel"></div>
      </div>
    </div>
    <script>
      const statusEl = document.getElementById('status');
      const startInput = document.getElementById('start');
      const endInput = document.getElementById('end');
      const exchangeSelect = document.getElementById('exchange');
      const symbolSelect = document.getElementById('symbol');
      const tradeFilterSelect = document.getElementById('tradeFilter');
      const loadBtn = document.getElementById('load-btn');
      const hoverInfoEl = document.getElementById('hover-info');

      let oiVolumePoints = [];

      async function loadSymbols() {
        const ex = exchangeSelect.value || 'NSE';
        const start = startInput.value;
        const end = endInput.value;
        if (!start || !end) return;
        try {
          const params = new URLSearchParams({ exchange: ex, start, end });
          const resp = await fetch('/api/symbols?' + params.toString());
          if (!resp.ok) return;
          const data = await resp.json();
          const symbols = data.symbols || [];
          symbolSelect.innerHTML = '<option value="">(Auto-select)</option>';
          for (const s of symbols) {
            const opt = document.createElement('option');
            opt.value = s.symbol;
            opt.textContent = s.symbol + (s.bar_count ? ` (${s.bar_count} bars)` : '');
            symbolSelect.appendChild(opt);
          }
        } catch (err) { console.debug('loadSymbols error:', err); }
      }

      exchangeSelect.addEventListener('change', loadSymbols);
      startInput.addEventListener('change', loadSymbols);
      endInput.addEventListener('change', loadSymbols);
      tradeFilterSelect.addEventListener('change', () => loadData());

      (function initDates() {
        const today = new Date();
        const endStr = today.toISOString().slice(0, 10);
        const start = new Date(today.getTime() - 4 * 24 * 60 * 60 * 1000);
        const startStr = start.toISOString().slice(0, 10);
        startInput.value = startStr;
        endInput.value = endStr;
        setTimeout(loadSymbols, 100);
      })();

      const chart1m = LightweightCharts.createChart(document.getElementById('chart-1m'), {
        layout: { background: { color: '#0b1622' }, textColor: '#d1d5db' },
        grid: { vertLines: { color: '#1f2933' }, horzLines: { color: '#1f2933' } },
        timeScale: { borderColor: '#374151', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#374151' },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      });
      const candleSeries = chart1m.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
      });

      const chartSubpanelContainer = document.getElementById('chart-subpanel');
      const chartSubpanel = LightweightCharts.createChart(chartSubpanelContainer, {
        layout: { background: { color: '#0b1622' }, textColor: '#d1d5db' },
        grid: { vertLines: { color: '#1f2933' }, horzLines: { color: '#1f2933' } },
        timeScale: { borderColor: '#374151', timeVisible: true, secondsVisible: false },
        rightPriceScale: { borderColor: '#374151' },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      });
      const ceOiSeries = chartSubpanel.addLineSeries({ color: '#22c55e', lineWidth: 2, title: 'CE OI %' });
      const ceVolSeries = chartSubpanel.addLineSeries({ color: '#22c55e', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dotted, title: 'CE Vol %' });
      const peOiSeries = chartSubpanel.addLineSeries({ color: '#ef4444', lineWidth: 2, title: 'PE OI %' });
      const peVolSeries = chartSubpanel.addLineSeries({ color: '#ef4444', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dotted, title: 'PE Vol %' });
      const zeroSeries = chartSubpanel.addLineSeries({ color: '#ffffff', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed });

      let isSyncing = false;
      function isValidRange(range) { return !!(range && range.from != null && range.to != null); }
      function syncTimeScale(sourceChart, targetChart) {
        if (isSyncing) return;
        const range = sourceChart.timeScale().getVisibleRange();
        if (!isValidRange(range)) return;
        isSyncing = true;
        try { targetChart.timeScale().setVisibleRange(range); } catch (e) {}
        finally { isSyncing = false; }
      }
      chart1m.timeScale().subscribeVisibleTimeRangeChange(() => syncTimeScale(chart1m, chartSubpanel));
      chartSubpanel.timeScale().subscribeVisibleTimeRangeChange(() => syncTimeScale(chartSubpanel, chart1m));

      function setStatus(msg) { statusEl.textContent = msg || ''; }
      function setHoverInfo(text) { hoverInfoEl.textContent = text || ''; }
      function formatValue(v) {
        if (v === null || v === undefined) return '--';
        const num = Number(v);
        return !isFinite(num) ? '--' : num.toFixed(2);
      }
      function findNearestOiVolPoint(time) {
        if (!oiVolumePoints.length || time == null) return null;
        let best = null, bestDiff = Infinity;
        for (const p of oiVolumePoints) {
          const diff = Math.abs(p.time - time);
          if (diff < bestDiff) { bestDiff = diff; best = p; }
        }
        return best;
      }

      async function loadData() {
        const ex = exchangeSelect.value || 'NSE';
        const sym = (symbolSelect.value || '').trim();
        const tradeFilter = (tradeFilterSelect.value || 'all').trim();
        const start = startInput.value;
        const end = endInput.value;
        if (!start || !end) { setStatus('Please select both start and end dates.'); return; }
        loadBtn.disabled = true;
        setStatus('Loading...');
        let candleCount = 0;
        try {
          {
            const params = new URLSearchParams({ exchange: ex, start, end });
            if (sym) params.set('symbol', sym);
            const resp = await fetch('/api/bars_1m?' + params.toString());
            if (!resp.ok) throw new Error('Bars HTTP ' + resp.status);
            const data = await resp.json();
            const bars = data.bars || [];
            const candleData = bars
              .filter(b => b.open != null && b.high != null && b.low != null && b.close != null)
              .map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
            candleCount = candleData.length;
            candleSeries.setData(candleData);
            if (data.symbol && !sym) symbolSelect.value = data.symbol;
          }

          const markers = [];
          let tradeCount = 0;
          {
            const params = new URLSearchParams({ start, end });
            if (ex) params.set('exchange', ex);
            params.set('outcome', tradeFilter);
            const resp = await fetch('/api/trade_logs?' + params.toString());
            if (resp.ok) {
              const data = await resp.json();
              const trades = data.trades || [];
              tradeCount = trades.length;
              for (const t of trades) {
                if (t.entry_time) {
                  markers.push({
                    time: t.entry_time, position: t.side === 'SELL' ? 'aboveBar' : 'belowBar',
                    color: t.side === 'SELL' ? '#f97316' : '#22c55e',
                    shape: t.side === 'SELL' ? 'arrowDown' : 'arrowUp',
                    text: (t.side === 'BUY' ? 'B ' : 'S ') + (t.symbol || '').slice(-12),
                  });
                }
                if (t.exit_time) {
                  markers.push({
                    time: t.exit_time, position: 'aboveBar',
                    color: (t.pnl != null && t.pnl < 0) ? '#ef4444' : '#22c55e',
                    shape: 'circle',
                    text: 'X ' + (t.pnl != null ? (t.pnl > 0 ? '+' : '') + t.pnl.toFixed(0) : ''),
                  });
                }
              }
            }
          }
          candleSeries.setMarkers(markers);

          const params = new URLSearchParams({ exchange: ex, start, end });
          const resp = await fetch('/api/itm_oi_volume?' + params.toString());
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          const data = await resp.json();
          const points = data.points || [];
          oiVolumePoints = points;
          if (!points.length) {
            ceOiSeries.setData([]); peOiSeries.setData([]);
            ceVolSeries.setData([]); peVolSeries.setData([]);
            zeroSeries.setData([]);
            setStatus('No data for this range.');
            setHoverInfo('');
            return;
          }

          const ceOiData = [], peOiData = [], ceVolData = [], peVolData = [];
          for (const p of points) {
            if (p.ce_oi_pct != null) ceOiData.push({ time: p.time, value: p.ce_oi_pct });
            if (p.pe_oi_pct != null) peOiData.push({ time: p.time, value: p.pe_oi_pct });
            if (p.ce_vol_pct != null) ceVolData.push({ time: p.time, value: p.ce_vol_pct });
            if (p.pe_vol_pct != null) peVolData.push({ time: p.time, value: p.pe_vol_pct });
          }
          const firstTime = points[0].time, lastTime = points[points.length - 1].time;
          zeroSeries.setData([{ time: firstTime, value: 0 }, { time: lastTime, value: 0 }]);
          ceOiSeries.setData(ceOiData);
          peOiSeries.setData(peOiData);
          ceVolSeries.setData(ceVolData);
          peVolSeries.setData(peVolData);

          setStatus(`1m: ${candleCount} candles, ${tradeCount} trades (${markers.length} markers). OI/Vol: ${points.length} points ${data.start}–${data.end}.`);
        } catch (err) {
          console.error(err);
          setStatus('Error loading data: ' + err.message);
        } finally {
          loadBtn.disabled = false;
        }
      }

      loadBtn.addEventListener('click', loadData);
      chart1m.subscribeCrosshairMove(param => {
        if (!param || param.time === undefined) { setHoverInfo(''); return; }
        const t = typeof param.time === 'number' ? param.time : param.time;
        const p = findNearestOiVolPoint(t);
        if (!p) { setHoverInfo(''); return; }
        const dt = new Date(t * 1000);
        const timeLabel = dt.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
        setHoverInfo(`Time: ${timeLabel}\nCE OI %: ${formatValue(p.ce_oi_pct)}   CE Vol %: ${formatValue(p.ce_vol_pct)}\nPE OI %: ${formatValue(p.pe_oi_pct)}   PE Vol %: ${formatValue(p.pe_vol_pct)}`);
      });
      window.addEventListener('load', loadData);
    </script>
  </body>
</html>
    """
    return html


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "7000"))
    app.run(host=host, port=port, debug=False)
