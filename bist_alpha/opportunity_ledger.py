"""
Opportunity ledger for FIRSAT watchlist candidates.

Measurement-only:
- does not open trades
- does not alter F/portfolio state
- tracks forward 5d/21d outcomes for strong non-pick candidates
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config


MAX_SNAPSHOTS = 120
DECISION_MIN_21D = 20
REVIEW_MIN_UNIQUE_21D_TICKERS = 30
REVIEW_RELATIVE_MEDIAN_EDGE_PCT = 5.0
REVIEW_MIN_REGIME_COUNT = 2


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_path() -> Path:
    return _repo_root() / "docs" / "state" / "opportunity_ledger.json"


def _date_text(value) -> str:
    if hasattr(value, "date"):
        return str(value.date())
    return str(value)[:10]


def _last_date(data):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return None
    return prices.index[-1]


def _round(value, ndigits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return round(float(value), ndigits)
    except Exception:
        return None


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, str(path))


def _price_at(prices, ticker, date):
    if prices is None or ticker not in prices.columns:
        return None
    if date not in prices.index:
        return None
    return _safe_float(prices.loc[date, ticker])


def _index_pos(index, date_text):
    target = pd.Timestamp(date_text)
    pos = index.searchsorted(target)
    if pos >= len(index):
        return None
    if _date_text(index[pos]) != date_text:
        return None
    return int(pos)


def _forward_price(prices, ticker, entry_date, days):
    if prices is None or ticker not in prices.columns:
        return None
    entry_pos = _index_pos(prices.index, entry_date)
    if entry_pos is None:
        return None
    target_pos = entry_pos + int(days)
    if target_pos >= len(prices.index):
        return None
    return _safe_float(prices.iloc[target_pos][ticker])


def _age_trading_days(prices, entry_date, current_date):
    if prices is None or prices.empty:
        return None
    entry_pos = _index_pos(prices.index, entry_date)
    current_pos = _index_pos(prices.index, _date_text(current_date))
    if entry_pos is None or current_pos is None:
        return None
    return max(0, int(current_pos - entry_pos))


def _ret_pct(price, entry):
    price = _safe_float(price)
    entry = _safe_float(entry)
    if not price or not entry:
        return None
    return _round((price / entry - 1) * 100, 2)


def _volume_ratio(data, date, ticker):
    volumes = data.get("volumes") if data else None
    if volumes is None or volumes.empty or ticker not in volumes.columns:
        return None
    idx = volumes.index.searchsorted(date)
    if idx <= 0:
        return None
    v5 = volumes.iloc[max(0, idx - 4):idx + 1][ticker].dropna().mean()
    v20 = volumes.iloc[max(0, idx - 19):idx + 1][ticker].dropna().mean()
    if not v20 or pd.isna(v20):
        return None
    return _round(float(v5) / float(v20), 2)


def _upper_wick(data, date, ticker):
    prices = data.get("prices") if data else None
    mins = data.get("mins") if data else None
    maxs = data.get("maxs") if data else None
    aofs = data.get("aofs") if data else None
    if any(x is None for x in (prices, mins, maxs, aofs)):
        return None
    if ticker not in prices.columns or ticker not in mins.columns or ticker not in maxs.columns or ticker not in aofs.columns:
        return None
    idx = prices.index.searchsorted(date)
    if idx < 0:
        return None
    window = prices.index[max(0, idx - 4):idx + 1]
    vals = []
    for dt in window:
        high = _safe_float(maxs.loc[dt, ticker])
        low = _safe_float(mins.loc[dt, ticker])
        close = _safe_float(prices.loc[dt, ticker])
        aof = _safe_float(aofs.loc[dt, ticker])
        if high is None or low is None or close is None or aof is None:
            continue
        day_range = high - low
        if day_range <= 0:
            continue
        vals.append((high - max(aof, close)) / day_range)
    return _round(sum(vals) / len(vals), 3) if vals else None


def _close_strength(data, date, ticker):
    prices = data.get("prices") if data else None
    mins = data.get("mins") if data else None
    maxs = data.get("maxs") if data else None
    if any(x is None for x in (prices, mins, maxs)):
        return None
    if ticker not in prices.columns or ticker not in mins.columns or ticker not in maxs.columns:
        return None
    close = _safe_float(prices.loc[date, ticker]) if date in prices.index else None
    low = _safe_float(mins.loc[date, ticker]) if date in mins.index else None
    high = _safe_float(maxs.loc[date, ticker]) if date in maxs.index else None
    if close is None or low is None or high is None or high <= low:
        return None
    return _round((close - low) / (high - low), 3)


def _range_profile(data, date, ticker, lookback=252):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty or ticker not in prices.columns:
        return {}
    idx = prices.index.searchsorted(date)
    window = prices.iloc[max(0, idx - lookback + 1):idx + 1][ticker].dropna()
    current = _price_at(prices, ticker, date)
    if window.empty or current is None:
        return {}
    high = _safe_float(window.max())
    low = _safe_float(window.min())
    out = {"range_high": _round(high), "range_low": _round(low)}
    if high and high > 0:
        out["from_high_pct"] = _round((current / high - 1) * 100, 1)
        out["near_high"] = bool((current / high - 1) * 100 >= -2)
    if low and low > 0:
        out["from_low_pct"] = _round((current / low - 1) * 100, 1)
    return out


def _catalyst_info(report, ticker):
    ledger = report.get("catalyst_ledger") or {}
    candidates = ledger.get("latest_candidates") or []
    hits = [c for c in candidates if c.get("ticker") == ticker]
    return {
        "catalyst_present": bool(hits),
        "catalyst_types": sorted({h.get("type") for h in hits if h.get("type")}),
        "catalyst_source_tiers": sorted({h.get("source_tier") for h in hits if h.get("source_tier")}),
    }


def _sector_context(report, ticker, sector, date):
    return {
        "sector_context": {
            "sector": sector,
            "status": "self_sector_rs_pending",
            "role": "context_only",
            "note": "Broker/third-party sector scores are not used in the public opportunity ledger.",
        }
    }


def _f_not_selected_reason(item, top10):
    ticker = item.get("ticker")
    if ticker in {x.get("ticker") for x in top10}:
        return "already_in_f_top10"
    sector = item.get("sector")
    sector_count = sum(1 for x in top10 if x.get("sector") == sector)
    if sector and sector_count >= getattr(config, "SEKTOR_CAP", 2):
        return "sector_cap_or_slot_full"
    return "outside_f_top10_after_filters"


def _current_item(report, data, date, item):
    ticker = str(item.get("ticker") or "").strip()
    prices = data.get("prices") if data else None
    entry_price = _price_at(prices, ticker, date)
    row = {
        "ticker": ticker,
        "entry_date": _date_text(date),
        "entry_price": _round(entry_price),
        "sector": item.get("sector"),
        "source_layer": "firsat",
        "source_label": "FIRSAT",
        "reason": "strong_accumulation_not_f_pick",
        "f_not_selected_reason": _f_not_selected_reason(item, report.get("top10", [])),
        "sm_signal": item.get("display_signal") or item.get("sm_signal"),
        "m5": item.get("m5"),
        "m21": item.get("m21"),
        "m252": item.get("m252"),
        "volume_ratio": _volume_ratio(data, date, ticker),
        "upper_wick": _upper_wick(data, date, ticker),
        "close_strength": _close_strength(data, date, ticker),
        "quality": {
            "status": "pending_official_free_data",
            "kap_confirmed": None,
            "quality_score": None,
        },
        "macro": {
            "status": "pending_macro_surprise_ledger",
            "support": None,
        },
    }
    row.update(_range_profile(data, date, ticker))
    row.update(_catalyst_info(report, ticker))
    row.update(_sector_context(report, ticker, row.get("sector"), date))
    return row


def _entered_f_top10_later(ticker, entry_date, snapshots):
    for snap in snapshots:
        snap_date = snap.get("date")
        if not snap_date or snap_date <= entry_date:
            continue
        if ticker in set(snap.get("top10") or []):
            return True, snap_date
    return False, None


def _refresh_item(item, prices, current_date, snapshots):
    ticker = item.get("ticker")
    entry = item.get("entry_price")
    entry_date = item.get("entry_date")
    if not ticker or not entry or not entry_date:
        return item
    current_price = _price_at(prices, ticker, current_date)
    item["current_price"] = _round(current_price)
    item["age_trading_days"] = _age_trading_days(prices, entry_date, current_date)
    item["current_return_pct"] = _ret_pct(current_price, entry)
    for days in (5, 21):
        key = f"return_{days}d_pct"
        if item.get(key) is None:
            item[key] = _ret_pct(_forward_price(prices, ticker, entry_date, days), entry)
    entered, entered_date = _entered_f_top10_later(ticker, entry_date, snapshots)
    item["entered_f_top10_later"] = entered
    item["entered_f_top10_date"] = entered_date
    if item.get("return_21d_pct") is not None:
        item["status"] = "mature_21d"
    elif item.get("return_5d_pct") is not None:
        item["status"] = "mature_5d"
    else:
        item["status"] = "open"
    return item


def _refresh_snapshots(snapshots, data, current_date):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return snapshots
    for snap in snapshots:
        for item in snap.get("items", []) or []:
            _refresh_item(item, prices, current_date, snapshots)
    return snapshots


def _avg(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(values):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2


def _hit_rate(values):
    vals = [float(v) for v in values if v is not None]
    return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else None


def _summary(snapshots):
    events = [item for snap in snapshots for item in (snap.get("items", []) or [])]
    r5 = [e.get("return_5d_pct") for e in events if e.get("return_5d_pct") is not None]
    mature_21d_events = [e for e in events if e.get("return_21d_pct") is not None]
    r21 = [e.get("return_21d_pct") for e in mature_21d_events]
    unique_mature_21d = len({e.get("ticker") for e in mature_21d_events if e.get("ticker")})
    latest = snapshots[-1] if snapshots else {}
    latest_items = latest.get("items", []) or []
    entered = [e for e in events if e.get("entered_f_top10_later")]
    mature_21d = len(r21)
    if mature_21d < DECISION_MIN_21D:
        decision = "olcum_devam"
    elif unique_mature_21d < REVIEW_MIN_UNIQUE_21D_TICKERS:
        decision = "unique_ticker_yetersiz"
    else:
        decision = "benchmark_gerekli"
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "tracked_days": len(snapshots),
        "latest_date": latest.get("date"),
        "current_candidates": len(latest_items),
        "total_events": len(events),
        "unique_tickers": len({e.get("ticker") for e in events if e.get("ticker")}),
        "matured_5d": len(r5),
        "avg_5d_return_pct": _round(_avg(r5)),
        "hit_5d_pct": _round(_hit_rate(r5), 1),
        "matured_21d": mature_21d,
        "unique_matured_21d_tickers": unique_mature_21d,
        "avg_21d_return_pct": _round(_avg(r21)),
        "median_21d_return_pct": _round(_median(r21)),
        "hit_21d_pct": _round(_hit_rate(r21), 1),
        "entered_f_top10_later_count": len(entered),
        "entered_f_top10_later_pct": _round(len(entered) / len(events) * 100, 1) if events else None,
        "decision": decision,
        "min_mature_events_for_decision": DECISION_MIN_21D,
        "review_policy": {
            "unit_of_independence": "unique_ticker",
            "min_unique_21d_tickers": REVIEW_MIN_UNIQUE_21D_TICKERS,
            "requires_relative_benchmark": True,
            "benchmark": "median_21d_vs_F_median_21d",
            "required_median_edge_pct": REVIEW_RELATIVE_MEDIAN_EDGE_PCT,
            "requires_regime_coverage": True,
            "min_regime_count": REVIEW_MIN_REGIME_COUNT,
            "absolute_return_gate_allowed": False,
            "promotion_scope": "review_only_not_F_auto_change",
        },
        "benchmark_status": {
            "f_median_21d_available": False,
            "regime_coverage_available": False,
            "denominator_available": False,
            "note": "Firsat listesi yalniz kendi adaylarini olcer; F'in eledigi tum payda ayrica kurulmadan terfi kapisi sayilmaz.",
        },
        "latest_candidates": latest_items[:5],
        "notes": [
            "FIRSAT is measurement-only; it does not open trades.",
            "Quality/macro fields stay pending until free official data is connected.",
            "Decision gates are relative to F median and unique-ticker/regime coverage; absolute 21d return alone is not enough.",
        ],
    }


def update(report, data, path=None, max_snapshots=MAX_SNAPSHOTS):
    """Update opportunity ledger and return dashboard-ready summary."""
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    date = _last_date(data)
    if date is None:
        return {"error": "date missing"}
    date_s = _date_text(date)
    path = Path(path) if path else _default_path()
    ledger = _load(path)
    snapshots = [s for s in ledger.get("snapshots", []) if s.get("date") != date_s]
    items = [_current_item(report, data, date, item) for item in (report.get("firsatlar") or [])]
    snapshots.append({
        "date": date_s,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top10": [x.get("ticker") for x in report.get("top10", []) if x.get("ticker")],
        "items": items,
    })
    snapshots = snapshots[-max_snapshots:]
    snapshots = _refresh_snapshots(snapshots, data, date)
    summary = _summary(snapshots)
    _atomic_write(path, {"summary": summary, "snapshots": snapshots})
    return summary
