"""
Catalyst ledger.

This is a measurement layer, not a trading engine. It records external
catalyst/theme tags, follows their forward returns, and keeps them separate
from the F production account.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (5, 21)
MAX_EVENTS = 500


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "catalyst_ledger.json"


def _sources_path() -> Path:
    return _repo_root() / "docs" / "state" / "catalyst_sources.json"


def _policy_path() -> Path:
    return _repo_root() / "docs" / "state" / "catalyst_policy.json"


def _round(value, digits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    value = round(float(value), digits)
    return 0.0 if value == 0 else value


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


def _first_price_on_or_after(prices, ticker, date_s):
    if prices is None or prices.empty or ticker not in prices.columns:
        return None, None, None
    target = pd.Timestamp(date_s)
    pos = int(prices.index.searchsorted(target, side="left"))
    while pos < len(prices.index):
        value = _price_at_pos(prices, ticker, pos)
        if value is not None:
            return value, _date_text(prices.index[pos]), pos
        pos += 1
    return None, None, None


def _position_of_date(prices, date_s):
    if prices is None or prices.empty or not date_s:
        return None
    target = pd.Timestamp(date_s)
    pos = int(prices.index.searchsorted(target, side="left"))
    if pos >= len(prices.index):
        return len(prices.index) - 1
    return pos


def _event_key(event):
    return "|".join([
        str(event.get("source_id") or ""),
        str(event.get("type") or ""),
        str(event.get("event_date") or ""),
        str(event.get("ticker") or ""),
    ])


def _source_key(source, ticker):
    return "|".join([
        str(source.get("id") or source.get("source") or "source"),
        str(source.get("type") or "catalyst"),
        str(source.get("date") or ""),
        ticker,
    ])


def _load_sources(path=None):
    payload = _load_json(Path(path) if path else _sources_path(), {"sources": []})
    return payload.get("sources", []) if isinstance(payload, dict) else []


def _load_policy(path=None):
    return _load_json(Path(path) if path else _policy_path(), {})


def _source_quality(source, policy):
    confidence = str(source.get("confidence") or "").lower()
    source_text = " ".join([
        str(source.get("source") or ""),
        str(source.get("source_url") or ""),
        str(source.get("label") or ""),
        str(source.get("note") or ""),
    ]).lower()
    tier = source.get("source_tier")
    if not tier:
        if confidence in ("primary", "official"):
            tier = "primary"
        elif "kap" in source_text or "borsaistanbul" in source_text or "spk" in source_text:
            tier = "primary"
        elif any(x in source_text for x in ("stockeys", "finnet", "investing", "tradingview", "bigpara")):
            tier = "data_vendor"
        elif "x.com" in source_text or "twitter" in source_text:
            tier = "social"
        else:
            tier = "social" if confidence == "secondary" else "data_vendor"
    source_tiers = policy.get("source_tiers", {}) if isinstance(policy, dict) else {}
    rule = source_tiers.get(tier, {})
    score = rule.get("score", 1)
    risk_types = policy.get("risk_types", {}) if isinstance(policy, dict) else {}
    risk_only = source.get("risk_only") or source.get("type") in risk_types
    requires_confirmation = tier != "primary"
    return {
        "source_tier": tier,
        "source_score": int(score),
        "source_rule": rule.get("rule"),
        "requires_confirmation": bool(requires_confirmation),
        "risk_only": bool(risk_only),
    }


def _source_events(report, data, existing_events, sources, policy=None):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return []
    as_of = _date_text(prices.index[-1])
    top10 = {_norm_ticker(r.get("ticker")) for r in (report or {}).get("top10", [])}
    f_positions = set()
    try:
        from . import portfolio as pf
        from . import config
        f_positions = {_norm_ticker(t) for t in pf.load("F", state_dir=config.STATE_DIR).get("positions", {})}
    except Exception:
        f_positions = set()
    existing = {_event_key(e): e for e in existing_events}
    events = []
    for source in sources:
        if source.get("disabled"):
            continue
        quality = _source_quality(source, policy or {})
        event_date = source.get("date")
        if not event_date or str(event_date) > as_of:
            continue
        tickers = [_norm_ticker(t) for t in source.get("tickers", [])]
        for ticker in [t for t in tickers if t]:
            key = _source_key(source, ticker)
            old = existing.get(key)
            if old:
                events.append(old)
                continue
            entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, event_date)
            events.append({
                "key": key,
                "source_id": source.get("id"),
                "source": source.get("source"),
                "source_url": source.get("source_url"),
                "source_confidence": source.get("confidence", "secondary"),
                "source_tier": quality["source_tier"],
                "source_score": quality["source_score"],
                "source_rule": quality["source_rule"],
                "requires_confirmation": quality["requires_confirmation"],
                "risk_only": quality["risk_only"],
                "type": source.get("type", "catalyst"),
                "label": source.get("label") or source.get("type") or "catalyst",
                "event_date": str(event_date),
                "ticker": ticker,
                "entry_date": entry_date,
                "entry_price": _round(entry),
                "entry_pos": entry_pos,
                "f_top10_at_entry": ticker in top10,
                "f_position_at_entry": ticker in f_positions,
                "opens_trade": False,
                "keywords": source.get("keywords", []),
                "note": source.get("note"),
            })
    return events


def _refresh_event(event, prices, as_of_pos):
    ticker = event.get("ticker")
    entry = event.get("entry_price")
    entry_pos = event.get("entry_pos")
    if entry_pos is None and event.get("entry_date"):
        entry_pos = _position_of_date(prices, event.get("entry_date"))
        event["entry_pos"] = entry_pos
    current = _price_at_pos(prices, ticker, as_of_pos)
    event["current_price"] = _round(current)
    if entry_pos is None or entry is None or current is None:
        event["status"] = "missing_price"
        event["current_return_pct"] = None
        return event
    age = max(0, int(as_of_pos - int(entry_pos)))
    event["age_trading_days"] = age
    event["current_return_pct"] = _round((current / float(entry) - 1) * 100)
    for window in WINDOWS:
        key = f"return_{window}d_pct"
        if int(entry_pos) + window <= as_of_pos:
            px = _price_at_pos(prices, ticker, int(entry_pos) + window)
            event[key] = _round((px / float(entry) - 1) * 100) if px else None
        else:
            event[key] = None
    if event.get("return_21d_pct") is not None:
        ret21 = float(event["return_21d_pct"])
        event["status"] = "mature_21d"
        event["verdict_21d"] = "hit" if ret21 > 0 else "loss" if ret21 < 0 else "flat"
    elif event.get("return_5d_pct") is not None:
        event["status"] = "mature_5d"
        event["verdict_21d"] = "open"
    else:
        event["status"] = "open"
        event["verdict_21d"] = "open"
    return event


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _summary(events, sources, as_of, policy=None):
    latest_source = None
    if sources:
        active = [s for s in sources if not s.get("disabled")]
        latest_source = sorted(active, key=lambda s: str(s.get("date", "")))[-1] if active else None
    mature21 = [e for e in events if e.get("return_21d_pct") is not None]
    mature5 = [e for e in events if e.get("return_5d_pct") is not None]
    latest_events = []
    if latest_source:
        sid = latest_source.get("id")
        latest_events = [e for e in events if e.get("source_id") == sid]
    current_returns = [e.get("current_return_pct") for e in events]
    ret21 = [e.get("return_21d_pct") for e in mature21]
    ret5 = [e.get("return_5d_pct") for e in mature5]
    f_overlap = [e for e in latest_events if e.get("f_top10_at_entry") or e.get("f_position_at_entry")]
    by_type = {}
    for event in events:
        typ = event.get("type", "catalyst")
        bucket = by_type.setdefault(typ, {"type": typ, "n": 0, "mature_21d": 0, "ret21": [], "wins21": 0})
        bucket["n"] += 1
        if event.get("return_21d_pct") is not None:
            bucket["mature_21d"] += 1
            bucket["ret21"].append(event.get("return_21d_pct"))
            bucket["wins21"] += 1 if float(event.get("return_21d_pct")) > 0 else 0
    type_rows = []
    for bucket in by_type.values():
        n21 = bucket["mature_21d"]
        type_rows.append({
            "type": bucket["type"],
            "n": bucket["n"],
            "mature_21d": n21,
            "avg_21d_return_pct": _round(_avg(bucket["ret21"])),
            "hit_21d_pct": _round(bucket["wins21"] / n21 * 100, 1) if n21 else None,
        })
    quality_rows = {}
    for event in events:
        tier = event.get("source_tier") or "unknown"
        row = quality_rows.setdefault(tier, {"tier": tier, "n": 0, "mature_21d": 0, "ret21": [], "wins21": 0})
        row["n"] += 1
        if event.get("return_21d_pct") is not None:
            row["mature_21d"] += 1
            row["ret21"].append(event.get("return_21d_pct"))
            row["wins21"] += 1 if float(event.get("return_21d_pct")) > 0 else 0
    source_quality = []
    for row in quality_rows.values():
        n21 = row["mature_21d"]
        source_quality.append({
            "tier": row["tier"],
            "n": row["n"],
            "mature_21d": n21,
            "avg_21d_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(row["wins21"] / n21 * 100, 1) if n21 else None,
        })
    policy = policy or {}
    global_rules = policy.get("global_rules", {}) if isinstance(policy, dict) else {}
    decision = "olcum_devam"
    min_events = int(global_rules.get("minimum_mature_events_for_decision", 20) or 20)
    if len(mature21) >= min_events:
        avg21 = _avg(ret21)
        hit21 = sum(1 for r in ret21 if r > 0) / len(ret21) * 100 if ret21 else None
        if avg21 is not None and avg21 > 0 and hit21 is not None and hit21 >= 50:
            decision = "izleme_degeri_var"
        else:
            decision = "kenarda_tut"
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "source_count": len([s for s in sources if not s.get("disabled")]),
        "tracked_events": len(events),
        "latest_source_id": latest_source.get("id") if latest_source else None,
        "latest_source_label": latest_source.get("label") if latest_source else None,
        "latest_source_date": latest_source.get("date") if latest_source else None,
        "latest_events": len(latest_events),
        "latest_f_overlap": len(f_overlap),
        "open_21d": len([e for e in events if e.get("return_21d_pct") is None]),
        "matured_5d": len(mature5),
        "matured_21d": len(mature21),
        "avg_current_return_pct": _round(_avg(current_returns)),
        "avg_5d_return_pct": _round(_avg(ret5)),
        "hit_5d_pct": _round(sum(1 for r in ret5 if r > 0) / len(ret5) * 100, 1) if ret5 else None,
        "avg_21d_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(sum(1 for r in ret21 if r > 0) / len(ret21) * 100, 1) if ret21 else None,
        "decision": decision,
        "policy_version": policy.get("version"),
        "min_mature_events_for_decision": min_events,
        "source_quality": sorted(source_quality, key=lambda x: x["tier"]),
        "latest_candidates": [
            {
                "ticker": e.get("ticker"),
                "type": e.get("type"),
                "source_tier": e.get("source_tier"),
                "entry_price": e.get("entry_price"),
                "current_return_pct": e.get("current_return_pct"),
                "age_trading_days": e.get("age_trading_days"),
                "f_overlap": bool(e.get("f_top10_at_entry") or e.get("f_position_at_entry")),
            }
            for e in latest_events[:12]
        ],
        "by_type": sorted(type_rows, key=lambda x: x["type"]),
        "note": "Olcum katmani; F motoruna emir uretmez. Ikincil sosyal kaynaklar KAP/temel veri ile dogrulanmadan terfi etmez.",
    }


def update(report, data, path=None, sources_path=None, policy_path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    ledger_path = Path(path) if path else _ledger_path()
    sources = _load_sources(sources_path)
    policy = _load_policy(policy_path)
    ledger = _load_json(ledger_path, {"events": []})
    existing_events = ledger.get("events", [])
    new_events = _source_events(report, data, existing_events, sources, policy)
    merged = {_event_key(e): e for e in existing_events}
    for event in new_events:
        merged[_event_key(event)] = event
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    events = [_refresh_event(event, prices, as_of_pos) for event in events]
    events.sort(key=lambda e: (e.get("event_date") or "", e.get("source_id") or "", e.get("ticker") or ""))
    payload = {
        "summary": _summary(events, sources, as_of, policy),
        "events": events,
    }
    _save_json(ledger_path, payload)
    return payload["summary"]
