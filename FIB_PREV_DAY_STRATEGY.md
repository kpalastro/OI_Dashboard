# Fibonacci Previous Day High/Low — Next Day Strategy

Analysis of your Nifty 50 Index 5m charts with Fib drawn from **previous day top and bottom** to trade the **next day**. This document distils the best “killing” (high-probability) rules from your setups.

---

## 1. Setup (What You’re Doing)

- **Anchor:** Previous trading day’s **high** and **low**.
- **Range:** `Prev_Low` = 0, `Prev_High` = 1 (or vice versa for a down move).
- **Levels used:** Retracements (0.27, 0.382, 0.5, 0.618, 0.786) and extensions (1.11, 1.272, 1.618, 2.618, 3.618, 4.236).

Your charts show that **next-day** price repeatedly reacts at these levels: bounces, rejections, and breakouts toward the next Fib.

---

## 2. What Your Charts Show

- **Retracements (0.382, 0.5, 0.618, 0.786)**  
  - Act as **support** when price pulls back into the range.  
  - Act as **resistance** when price retraces down from above.  
  - 0.618 and 0.5 are where price often **consolidates** before the next leg.

- **Extensions**  
  - **1.11, 1.272:** Strong reaction zones — targets for breakouts and often reversal/consolidation.  
  - **1.618:** Strong trend continuation target when level is broken with momentum.  
  - **2.618+:** Used when trend extends sharply (e.g. Feb 1 drop toward deeper extensions).

- **Confluence**  
  - Where **multiple Fib sets** (e.g. different days’ pivots) align (e.g. 25,300–25,400, 25,100–25,200), support/resistance is **stronger**.

- **Break of level**  
  - Clean break of a retracement (e.g. below 0.618) often leads to **continuation** toward the next extension (1.11, 1.272).

---

## 3. Best “Killing” Strategy — Rules

### 3.1 Pre-market

1. Compute **previous day high (PDH)** and **previous day low (PDL)**.
2. Calculate all Fib levels (retracements + 1.11, 1.272, 1.618, 2.618).
3. Mark **confluence zones** if you keep multiple days’ Fib (e.g. PD-1, PD-2).

### 3.2 Long bias (next day)

| Condition | Action |
|----------|--------|
| Price holds **above** 0.618 or 0.5 of prev range (support) and shows a bounce (e.g. bullish candle/close) | **Long** with target **1** (prev high) or **1.11 / 1.272**. |
| Stop | Just **below** the Fib level that held (e.g. below 0.618). |
| Break **above 1** (prev high) with momentum | Hold for **1.11** then **1.272**; trail stop below recent swing. |

### 3.3 Short bias (next day)

| Condition | Action |
|----------|--------|
| Price rejects **at or below** 0.618 / 0.5 (resistance) and shows rejection (e.g. bearish close) | **Short** with target **0** (prev low) or **1.11 / 1.272 extension below**. |
| Stop | Just **above** the Fib level that rejected. |
| Break **below 0** (prev low) with momentum | Target **1.11**, then **1.272** below; trail stop above recent swing. |

### 3.4 Confluence

- **Stronger entries:** Prefer entries where your **prev-day Fib** aligns with another structure (e.g. another day’s 0.618, or a round number).
- **Stronger exits:** When price reaches a **confluence** of two or more Fib levels (e.g. 1.272 of one set and 0.618 of another), consider partial exit or full exit.

### 3.5 Risk

- One risk unit per trade (e.g. 0.5–1% of capital).
- **Stop:** Always defined by the level (above/below the Fib that defined the trade).
- **Targets:** First target = next Fib (1.11 or 1.272); then trail or move stop to breakeven.

---

## 4. Level Formulas (for automation)

With **Low = PDL** and **High = PDH**, range `R = PDH - PDL`:

- **Retracements (from low):**  
  `Level = PDL + R * ratio`  
  Ratios: 0.27, 0.382, 0.5, 0.618, 0.786.

- **Extensions above high:**  
  `Level = PDH + R * (ratio - 1)`  
  Ratios: 1.11, 1.272, 1.618, 2.618.

- **Extensions below low:**  
  `Level = PDL - R * ratio`  
  Same ratios (1.11, 1.272, 1.618, 2.618, …).

(If you anchor High=0 and Low=1 for a down move, same math, just map 0→PDH and 1→PDL.)

---

## 5. Summary

| Element | Best “killing” usage |
|--------|-----------------------|
| **Entry (long)** | Bounce at 0.5 or 0.618 support (prev range) with confirmation. |
| **Entry (short)** | Rejection at 0.5 or 0.618 resistance with confirmation. |
| **Targets** | 1 (prev high/low), then 1.11, then 1.272. |
| **Stop** | Beyond the Fib level that defined the trade. |
| **Edge** | Confluence of multiple Fib levels; break of level = continuation to next Fib. |

Use the script `scripts/fib_prev_day_levels.py` to get **yesterday’s high/low** and **all Fib levels** for Nifty 50 (or any symbol) so you can mark them on your 5m chart and apply these rules the next day.
