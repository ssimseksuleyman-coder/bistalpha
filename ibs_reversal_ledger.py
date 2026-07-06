"""
ibs_reversal_ledger.py - izole IBS/RSI/ADX tepki radari.

F motoruna, portfoylere ve dashboard.json'a dokunmaz. Amac "IBS dusuk +
RSI zayif + ADX uygun" fikrinin 1/3/5/10 gun ileri getiride gercekten
tepki uretip uretmedigini olcmek.

Terfi protokolu:
  defter -> forward istatistik -> gerekirse paper R hesabi -> terfi adayi
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from bist_alpha import datafeed


REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "ibs_reversal_ledger.json")

IBS_MAX = 0.15
RSI_MAX = 35.0
ADX_MIN = 18.0
MAX_EVENTS_PER_RUN = 30
LOOKAHEAD_DAYS = (1, 3, 5, 10)
LIVE_ENV = "IBS_LEDGER_LIVE"
SCAN_DAYS_ENV = "IBS_LEDGER_SCAN_DAYS"
COOLDOWN_DAYS = 5


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    high = pd.to_numeric(high, errors="coerce")
    low = pd.to_numeric(low, errors="coerce")
    close = pd.to_numeric(close, errors="coerce")
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def _load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _event_key(event: dict) -> str:
    return f"{event['signal_date']}:{event['ticker']}"


def _forward_returns(prices: pd.DataFrame, ticker: str, idx: int) -> dict:
    out = {}
    entry = prices[ticker].iloc[idx]
    if not entry or pd.isna(entry):
        return out
    for days in LOOKAHEAD_DAYS:
        j = idx + days
        key = f"fwd_{days}d_pct"
        if j < len(prices.index):
            out[key] = round((prices[ticker].iloc[j] / entry - 1) * 100, 2)
        else:
            out[key] = None
    return out


def _current_universe(feed, data, date) -> set[str]:
    try:
        return set(feed.dynamic_universe(data, date=date))
    except Exception:
        return set(data["prices"].columns)


def _default_feed():
    """Keep this measurement light: local file by default, live only when explicit."""
    if os.environ.get(LIVE_ENV, "").lower() in ("1", "true", "yes", "evet"):
        return datafeed.get_feed()
    return datafeed.FileFeed()


def _events_for_date(feed, data, prices, highs, lows, vols, date) -> list[dict]:
    idx = prices.index.get_loc(date)
    universe = _current_universe(feed, data, date)

    rows = []
    for ticker in sorted(universe):
        if ticker not in prices.columns or ticker not in highs.columns or ticker not in lows.columns:
            continue
        close = prices[ticker].dropna()
        high = highs[ticker].reindex(close.index)
        low = lows[ticker].reindex(close.index)
        if date not in close.index or len(close) < 40:
            continue
        pos = close.index.get_loc(date)
        if pos < 20:
            continue
        c = close.iloc[pos]
        h = high.iloc[pos]
        l = low.iloc[pos]
        rng = h - l
        if not rng or pd.isna(rng):
            continue
        ibs = float((c - l) / rng)
        rsi = float(_rsi(close).iloc[pos])
        adx = float(_adx(high.reindex(close.index), low.reindex(close.index), close).iloc[pos])
        if pd.isna(ibs) or pd.isna(rsi) or pd.isna(adx):
            continue
        if not (ibs <= IBS_MAX and rsi <= RSI_MAX and adx >= ADX_MIN):
            continue
        ret_5 = (close.iloc[pos] / close.iloc[max(0, pos - 5)] - 1) * 100
        vol_ratio = None
        if ticker in vols.columns:
            v = vols[ticker].reindex(close.index)
            base = v.iloc[max(0, pos - 20):pos].mean()
            if base and not pd.isna(base):
                vol_ratio = round(float(v.iloc[pos] / base), 2)
        event = {
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "signal_date": str(pd.Timestamp(date).date()),
            "ticker": ticker,
            "close": round(float(c), 4),
            "ibs": round(ibs, 3),
            "rsi14": round(rsi, 1),
            "adx14": round(adx, 1),
            "ret_5d_pct": round(float(ret_5), 2),
            "volume_ratio20": vol_ratio,
        }
        event.update(_forward_returns(prices, ticker, pos))
        rows.append(event)

    rows.sort(key=lambda x: (x["ibs"], x["rsi14"], -x["adx14"]))
    return rows


def _scan_dates(prices: pd.DataFrame, date=None, scan_days: int = 1) -> list[pd.Timestamp]:
    if prices.empty:
        return []
    date = pd.Timestamp(date) if date is not None else prices.index[-1]
    idx = prices.index.searchsorted(date)
    if idx >= len(prices.index):
        idx = len(prices.index) - 1
    if idx <= 20:
        return []
    start = max(21, idx - max(1, int(scan_days)) + 1)
    return list(prices.index[start:idx + 1])


def find_events(data=None, date=None, scan_days: int | None = None) -> list[dict]:
    feed = _default_feed()
    data = data or feed.get_latest()
    prices = data["prices"].sort_index()
    highs = data["maxs"].reindex_like(prices)
    lows = data["mins"].reindex_like(prices)
    vols = data.get("volumes", pd.DataFrame()).reindex_like(prices)
    if scan_days is None:
        scan_days = int(os.environ.get(SCAN_DAYS_ENV, "1") or "1")

    rows = []
    for scan_date in _scan_dates(prices, date=date, scan_days=scan_days):
        rows.extend(_events_for_date(feed, data, prices, highs, lows, vols, scan_date))

    rows.sort(key=lambda x: (x["signal_date"], x["ibs"], x["rsi14"], -x["adx14"]))
    return rows[:MAX_EVENTS_PER_RUN]


def append_events(events: list[dict], ledger_path: str = LEDGER) -> dict:
    ledger = _load_json(ledger_path, {"events": []})
    existing = {_event_key(e) for e in ledger.get("events", [])}
    added = 0
    for event in events:
        if _event_key(event) in existing:
            continue
        ledger.setdefault("events", []).append(event)
        existing.add(_event_key(event))
        added += 1
    ledger["events"].sort(key=lambda e: (e.get("signal_date", ""), e.get("ticker", "")))
    ledger["summary"] = summarize(ledger["events"])
    _save_json(ledger_path, ledger)
    return {"added": added, "total": len(ledger["events"]), "summary": ledger["summary"]}


def _horizon_stats(events: list[dict]) -> dict:
    stats = {}
    for days in LOOKAHEAD_DAYS:
        key = f"fwd_{days}d_pct"
        vals = [e[key] for e in events if e.get(key) is not None]
        if not vals:
            stats[key] = {"n": 0, "avg": None, "hit_rate": None}
            continue
        stats[key] = {
            "n": len(vals),
            "avg": round(sum(vals) / len(vals), 2),
            "hit_rate": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        }
    return stats


def _cooldown_events(events: list[dict], cooldown_days: int = COOLDOWN_DAYS) -> list[dict]:
    kept = []
    last_signal = {}
    for event in sorted(events, key=lambda e: (e.get("signal_date", ""), e.get("ticker", ""))):
        ticker = event.get("ticker")
        date = pd.Timestamp(event.get("signal_date"))
        prev = last_signal.get(ticker)
        if prev is not None and (date - prev).days < cooldown_days:
            continue
        kept.append(event)
        last_signal[ticker] = date
    return kept


def summarize(events: list[dict]) -> dict:
    cooldown = _cooldown_events(events)
    summary = {
        "n_events": len(events),
        "unique_tickers": len({e.get("ticker") for e in events}),
    }
    summary.update(_horizon_stats(events))
    summary[f"cooldown_{COOLDOWN_DAYS}d"] = {
        "n_events": len(cooldown),
        "unique_tickers": len({e.get("ticker") for e in cooldown}),
        **_horizon_stats(cooldown),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated IBS/RSI/ADX reversal ledger.")
    parser.add_argument(
        "--scan-days",
        type=int,
        default=int(os.environ.get(SCAN_DAYS_ENV, "1") or "1"),
        help="Number of recorded trading days to scan; default: 1.",
    )
    args = parser.parse_args()
    events = find_events(scan_days=args.scan_days)
    result = append_events(events)
    print("IBS/RSI/ADX TEPKI RADARI (izole; F'e dokunmaz)")
    print(f"Taranan gun: {max(1, args.scan_days)}")
    print(f"Yeni olay: {result['added']} | toplam: {result['total']}")
    for days in LOOKAHEAD_DAYS:
        stat = result["summary"].get(f"fwd_{days}d_pct", {})
        print(f"  {days}g: n={stat.get('n')} avg={stat.get('avg')} hit%={stat.get('hit_rate')}")
    cooldown = result["summary"].get(f"cooldown_{COOLDOWN_DAYS}d", {})
    if cooldown:
        print(f"Cooldown {COOLDOWN_DAYS}g: olay={cooldown.get('n_events')}")
        for days in LOOKAHEAD_DAYS:
            stat = cooldown.get(f"fwd_{days}d_pct", {})
            print(
                f"  cd {days}g: n={stat.get('n')} "
                f"avg={stat.get('avg')} hit%={stat.get('hit_rate')}"
            )
    print(f"Defter: {os.path.relpath(LEDGER, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
