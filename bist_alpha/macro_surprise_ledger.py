"""Macro surprise ledger.

Measurement layer only. It follows manually or programmatically recorded macro
surprise events against broad BIST and F Top10 forward returns. It does not
open trades or modify the F production motor.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (1, 5, 21, 63)
MAX_EVENTS = 500


EVENT_TYPES = {
    "US_CPI": "external",
    "FED": "external",
    "NFP": "external",
    "DXY": "external",
    "US10Y": "external",
    "BRENT": "external",
    "TR_CPI": "turkey",
    "TCMB_RATE": "turkey",
    "PMI": "turkey",
    "INDUSTRIAL_PRODUCTION": "turkey",
    "RESERVES": "turkey",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "macro_surprise_ledger.json"


def _sources_path() -> Path:
    return _repo_root() / "docs" / "state" / "macro_surprise_sources.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _round(value, digits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        value = round(float(value), digits)
    except Exception:
        return None
    return 0.0 if value == 0 else value


def _date_text(value):
    return str(value.date()) if hasattr(value, "date") else str(value)


def _norm_ticker(ticker):
    return str(ticker or "").split(".")[0].upper().strip()


def _price_at_pos(prices, ticker, pos):
    if pos is None or pos < 0 or pos >= len(prices.index) or ticker not in prices.columns:
        return None
    value = prices.iloc[pos][ticker]
    if pd.isna(value) or value <= 0:
        return None
    return float(value)


def _first_pos_on_or_after(prices, date_s):
    if prices is None or prices.empty or not date_s:
        return None, None
    pos = int(prices.index.searchsorted(pd.Timestamp(date_s), side="left"))
    if pos >= len(prices.index):
        return None, None
    return pos, _date_text(prices.index[pos])


def _basket_return(prices, tickers, entry_pos, window):
    if entry_pos is None or int(entry_pos) + window >= len(prices.index):
        return None
    returns = []
    for ticker in tickers:
        start = _price_at_pos(prices, ticker, int(entry_pos))
        end = _price_at_pos(prices, ticker, int(entry_pos) + window)
        if start and end:
            returns.append((end / start - 1) * 100)
    return _round(sum(returns) / len(returns)) if returns else None


def _event_key(event):
    return "|".join([
        str(event.get("id") or event.get("source_id") or ""),
        str(event.get("date") or ""),
        str(event.get("type") or ""),
    ])


def _sources():
    payload = _load_json(_sources_path(), {"sources": []})
    return payload.get("sources", []) if isinstance(payload, dict) else []


def _source_events(sources):
    events = []
    for source in sources:
        if source.get("disabled"):
            continue
        event_type = str(source.get("type") or "").upper()
        event_date = source.get("date")
        if not event_type or not event_date:
            continue
        group = EVENT_TYPES.get(event_type, source.get("group") or "unknown")
        actual = source.get("actual")
        expected = source.get("expected")
        surprise = source.get("surprise")
        if surprise is None and actual is not None and expected not in (None, 0):
            try:
                surprise = float(actual) - float(expected)
            except Exception:
                surprise = None
        events.append({
            "key": _event_key(source),
            "id": source.get("id") or _event_key(source),
            "date": str(event_date),
            "type": event_type,
            "group": group,
            "source": source.get("source"),
            "source_url": source.get("source_url"),
            "actual": actual,
            "expected": expected,
            "surprise": _round(surprise, 4),
            "unit": source.get("unit"),
            "direction": source.get("direction", "unknown"),
            "note": source.get("note"),
            "opens_trade": False,
        })
    return events


def _refresh_event(event, report, prices, as_of_pos):
    entry_pos = event.get("entry_pos")
    if entry_pos is None:
        entry_pos, entry_date = _first_pos_on_or_after(prices, event.get("date"))
        event["entry_pos"] = entry_pos
        event["entry_date"] = entry_date
    if entry_pos is None:
        event["status"] = "future_or_missing_price"
        return event
    age = max(0, int(as_of_pos - int(entry_pos)))
    event["age_trading_days"] = age
    all_tickers = [c for c in prices.columns if c]
    f_tickers = [_norm_ticker(r.get("ticker")) for r in (report or {}).get("top10", [])]
    f_tickers = [t for t in f_tickers if t in prices.columns]
    for window in WINDOWS:
        event[f"market_return_{window}d_pct"] = _basket_return(prices, all_tickers, entry_pos, window)
        event[f"f_top10_return_{window}d_pct"] = _basket_return(prices, f_tickers, entry_pos, window)
    mature = [w for w in WINDOWS if event.get(f"market_return_{w}d_pct") is not None]
    event["status"] = f"mature_{max(mature)}d" if mature else "open"
    return event


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _hit(values):
    values = [float(v) for v in values if v is not None]
    return sum(1 for v in values if v > 0) / len(values) * 100 if values else None


def _summary(events, as_of, sources):
    ret21 = [e.get("market_return_21d_pct") for e in events]
    ret63 = [e.get("market_return_63d_pct") for e in events]
    by_group = {}
    for event in events:
        group = event.get("group") or "unknown"
        row = by_group.setdefault(group, {"group": group, "n": 0, "ret21": []})
        row["n"] += 1
        row["ret21"].append(event.get("market_return_21d_pct"))
    group_rows = []
    for row in by_group.values():
        group_rows.append({
            "group": row["group"],
            "n": row["n"],
            "avg_21d_market_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(_hit(row["ret21"]), 1),
        })
    decision = "olay_bekliyor" if not events else "olcum_devam"
    if len([r for r in ret21 if r is not None]) >= 20 and _avg(ret21) is not None:
        decision = "izleme_degeri_var" if _avg(ret21) > 0 and (_hit(ret21) or 0) >= 50 else "kenarda_tut"
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "tracked_events": len(events),
        "source_count": len([s for s in sources if not s.get("disabled")]),
        "opens_trade": False,
        "matured_21d": len([e for e in events if e.get("market_return_21d_pct") is not None]),
        "matured_63d": len([e for e in events if e.get("market_return_63d_pct") is not None]),
        "avg_21d_market_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(_hit(ret21), 1),
        "avg_63d_market_return_pct": _round(_avg(ret63)),
        "hit_63d_pct": _round(_hit(ret63), 1),
        "decision": decision,
        "by_group": sorted(group_rows, key=lambda x: x["group"]),
        "latest_events": sorted(events, key=lambda e: e.get("date") or "", reverse=True)[:10],
        "event_types": EVENT_TYPES,
        "note": "Macro Surprise defteri olcer; fiyat sinyalinden bagimsizdir ve F motoruna emir uretmez.",
    }


def update(report, data, path=None, sources_path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    sources = _sources() if sources_path is None else _load_json(Path(sources_path), {"sources": []}).get("sources", [])
    ledger_path = Path(path) if path else _ledger_path()
    existing = _load_json(ledger_path, {"events": []}).get("events", [])
    merged = {_event_key(e): e for e in existing}
    for event in _source_events(sources):
        old = merged.get(_event_key(event), {})
        old.update({k: v for k, v in event.items() if v is not None or k not in old})
        merged[_event_key(event)] = old
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    events = [_refresh_event(event, report, prices, as_of_pos) for event in events]
    events.sort(key=lambda e: (e.get("date") or "", e.get("type") or ""))
    payload = {
        "summary": _summary(events, as_of, sources),
        "events": events,
    }
    _save_json(ledger_path, payload)
    return payload["summary"]
