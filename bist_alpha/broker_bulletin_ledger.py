"""Broker bulletin ledger.

Measurement-only layer for broker research notes (Tera, ICBC, Bizim Menkul,
and local broker extracts). Raw third-party calls stay local. The public dashboard receives
only aggregate measurement so licensed/proprietary bulletin content is not
republished.
"""
from __future__ import annotations

import glob
import json
import math
import os
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (1, 5, 21, 63)
MAX_EVENTS = 1000
SOURCE_SCORE = {
    "official": 3,
    "primary": 3,
    "broker": 2,
    "data_vendor": 2,
    "social": 1,
    "rumor": 0,
}
BROKER_SOURCES = {
    "tera": {
        "name": "Tera Yatirim",
        "tier": "broker",
        "public_url": "https://www.terayatirim.com/research",
        "notes": "Market outlook, suggestion list, company reports.",
    },
    "icbc": {
        "name": "ICBC Turkey Yatirim",
        "tier": "broker",
        "public_url": "https://www.icbcyatirim.com.tr",
        "notes": "Daily/periodic research bulletins where publicly available.",
    },
    "bizim": {
        "name": "Bizim Menkul Degerler",
        "tier": "broker",
        "public_url": "https://www.bizimmenkul.com.tr",
        "notes": "Daily/periodic research bulletins where publicly available.",
    },
    "local_broker": {
        "name": "Local Broker Extract",
        "tier": "broker",
        "public_url": None,
        "notes": "Local-only comparison source. Raw/derived data is not public.",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _input_glob() -> str:
    return str(_repo_root() / "local" / "broker_bulletins" / "*.json")


def _private_path() -> Path:
    return _repo_root() / "local" / "broker_bulletin_ledger_private.json"


def _public_path() -> Path:
    return _repo_root() / "docs" / "state" / "broker_bulletin_ledger.json"


def _sources_path() -> Path:
    return _repo_root() / "docs" / "state" / "broker_bulletin_sources.json"


def _safe_float(value):
    try:
        if value is None or pd.isna(value):
            return None
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def _round(value, digits=2):
    value = _safe_float(value)
    if value is None:
        return None
    value = round(value, digits)
    return 0.0 if value == 0 else value


def _date_text(value):
    return str(value.date()) if hasattr(value, "date") else str(value)[:10]


def _norm_ticker(value):
    return str(value or "").split(".")[0].upper().strip()


def _slug(value):
    text = str(value or "").lower().strip()
    keep = []
    for ch in text:
        keep.append(ch if ch.isalnum() else "_")
    out = "".join(keep).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "unknown"


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
    os.replace(tmp, path)


def _load_inputs(pattern=None):
    files = sorted(glob.glob(pattern or _input_glob()))
    rows = []
    errors = []
    for file_name in files:
        path = Path(file_name)
        payload = _load_json(path, None)
        if payload is None:
            errors.append({"file": str(path), "error": "json_read_failed"})
            continue
        items = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            errors.append({"file": str(path), "error": "events_not_list"})
            continue
        for item in items:
            if isinstance(item, dict):
                item = dict(item)
                item["_input_file"] = str(path)
                rows.append(item)
    return rows, errors, len(files)


def _load_sources(path=None):
    payload = _load_json(Path(path) if path else _sources_path(), None)
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        return {str(s.get("id") or "").lower(): s for s in payload["sources"]}
    return BROKER_SOURCES


def _price_at_pos(prices, ticker, pos):
    if pos is None or pos < 0 or pos >= len(prices.index) or ticker not in prices.columns:
        return None
    value = prices.iloc[pos][ticker]
    value = _safe_float(value)
    return value if value and value > 0 else None


def _first_price_on_or_after(prices, ticker, date_s):
    if prices is None or prices.empty or ticker not in prices.columns or not date_s:
        return None, None, None
    pos = int(prices.index.searchsorted(pd.Timestamp(date_s), side="left"))
    while pos < len(prices.index):
        value = _price_at_pos(prices, ticker, pos)
        if value is not None:
            return value, _date_text(prices.index[pos]), pos
        pos += 1
    return None, None, None


def _event_key(event):
    explicit = event.get("event_id") or event.get("id")
    if explicit:
        return str(explicit)
    parts = [
        event.get("source_id"),
        event.get("event_date"),
        event.get("bulletin_type"),
        event.get("ticker"),
        event.get("action"),
    ]
    return "|".join(str(x or "") for x in parts)


def _normalize_event(row, sources):
    ticker = _norm_ticker(row.get("ticker") or row.get("symbol"))
    if not ticker:
        return None
    source_id = _slug(row.get("source_id") or row.get("source") or row.get("broker"))
    if "tera" in source_id:
        source_id = "tera"
    elif "icbc" in source_id:
        source_id = "icbc"
    elif "bizim" in source_id:
        source_id = "bizim"
    elif "deniz" in source_id:
        source_id = "local_broker"
    source_meta = sources.get(source_id, {})
    tier = str(row.get("source_tier") or source_meta.get("tier") or "broker").lower()
    score = SOURCE_SCORE.get(tier, 1)
    action = str(row.get("action") or row.get("recommendation") or row.get("call") or "izle").upper()
    event = {
        "source_id": source_id,
        "source_name": row.get("source_name") or source_meta.get("name") or source_id,
        "source_tier": tier,
        "source_score": int(score),
        "source_url": source_meta.get("public_url"),
        "event_date": str(row.get("event_date") or row.get("date") or ""),
        "bulletin_type": str(row.get("bulletin_type") or row.get("type") or "broker_bulletin"),
        "ticker": ticker,
        "action": action,
        "reason_type": row.get("reason_type") or row.get("theme") or row.get("category"),
        "official_confirmed": bool(row.get("official_confirmed", False)),
        "kap_confirmed": bool(row.get("kap_confirmed", False)),
        "opens_trade": False,
        "raw_storage": "local_only",
        "public_detail_allowed": bool(row.get("public_detail_allowed", False)),
        "input_file": row.get("_input_file"),
        # Kept only in private/local ledger, never in public aggregate output.
        "private_fields": {
            "target_price": row.get("target_price"),
            "previous_target_price": row.get("previous_target_price"),
            "upside_pct": row.get("upside_pct"),
            "note": row.get("note"),
            "url": row.get("url"),
        },
    }
    event["key"] = _event_key(event)
    return event


def _normalize_events(input_rows, sources):
    events = []
    seen = set()
    for row in input_rows:
        event = _normalize_event(row, sources)
        if not event or not event.get("event_date"):
            continue
        key = event["key"]
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    return events


def _refresh_event(event, prices, as_of_pos, top10, f_positions):
    ticker = event.get("ticker")
    entry = event.get("entry_price")
    entry_pos = event.get("entry_pos")
    if entry is None or entry_pos is None:
        entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, event.get("event_date"))
        event["entry_price"] = _round(entry)
        event["entry_date"] = entry_date
        event["entry_pos"] = entry_pos
    current = _price_at_pos(prices, ticker, as_of_pos)
    event["current_price"] = _round(current)
    event["f_top10_latest"] = ticker in top10
    event["f_position_latest"] = ticker in f_positions
    if entry_pos is None or entry is None or current is None:
        event["status"] = "missing_price"
        event["current_return_pct"] = None
        return event
    age = max(0, as_of_pos - int(entry_pos))
    event["age_trading_days"] = int(age)
    event["current_return_pct"] = _round((current / float(entry) - 1) * 100)
    for window in WINDOWS:
        key = f"return_{window}d_pct"
        if int(entry_pos) + window <= as_of_pos:
            px = _price_at_pos(prices, ticker, int(entry_pos) + window)
            event[key] = _round((px / float(entry) - 1) * 100) if px else None
        else:
            event[key] = None
    if event.get("return_63d_pct") is not None:
        event["status"] = "mature_63d"
    elif event.get("return_21d_pct") is not None:
        event["status"] = "mature_21d"
    elif event.get("return_5d_pct") is not None:
        event["status"] = "mature_5d"
    else:
        event["status"] = "open"
    return event


def _avg(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _hit(values):
    vals = [float(v) for v in values if v is not None]
    return sum(1 for v in vals if v > 0) / len(vals) * 100 if vals else None


def _bucket_summary(events, key_name):
    buckets = {}
    for event in events:
        name = event.get(key_name) or "unknown"
        row = buckets.setdefault(name, {"name": name, "n": 0, "ret5": [], "ret21": [], "ret63": []})
        row["n"] += 1
        for window in (5, 21, 63):
            value = event.get(f"return_{window}d_pct")
            if value is not None:
                row[f"ret{window}"].append(value)
    out = []
    for row in buckets.values():
        out.append({
            "name": row["name"],
            "n": row["n"],
            "matured_5d": len(row["ret5"]),
            "avg_5d_return_pct": _round(_avg(row["ret5"])),
            "hit_5d_pct": _round(_hit(row["ret5"]), 1),
            "matured_21d": len(row["ret21"]),
            "avg_21d_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(_hit(row["ret21"]), 1),
            "matured_63d": len(row["ret63"]),
            "avg_63d_return_pct": _round(_avg(row["ret63"])),
            "hit_63d_pct": _round(_hit(row["ret63"]), 1),
        })
    return sorted(out, key=lambda x: (-x["n"], str(x["name"])))


def _public_summary(events, input_count, input_errors, as_of, sources):
    ret5 = [e.get("return_5d_pct") for e in events if e.get("return_5d_pct") is not None]
    ret21 = [e.get("return_21d_pct") for e in events if e.get("return_21d_pct") is not None]
    ret63 = [e.get("return_63d_pct") for e in events if e.get("return_63d_pct") is not None]
    decision = "olcum_bekliyor"
    if len(ret21) >= 20:
        if (_avg(ret21) or 0) > 0 and (_hit(ret21) or 0) >= 50:
            decision = "izleme_degeri_var_resmi_teyit_sartiyla"
        else:
            decision = "terfi_yok"
    tier_counts = {}
    for src in sources.values():
        tier = str(src.get("tier", "broker")).lower()
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "input_files": input_count,
        "input_error_count": len(input_errors),
        "tracked_events": len(events),
        "unique_sources": len({e.get("source_id") for e in events}),
        "unique_tickers_private": len({e.get("ticker") for e in events}),
        "matured_5d": len(ret5),
        "avg_5d_return_pct": _round(_avg(ret5)),
        "hit_5d_pct": _round(_hit(ret5), 1),
        "matured_21d": len(ret21),
        "avg_21d_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(_hit(ret21), 1),
        "matured_63d": len(ret63),
        "avg_63d_return_pct": _round(_avg(ret63)),
        "hit_63d_pct": _round(_hit(ret63), 1),
        "decision": decision,
        "readiness": {
            "status": "active" if events else "empty",
            "data_status": "local_broker_input_waiting" if not events else "measuring",
            "message": (
                "Broker bulten sicili hazir; olcum icin public olmayan ozel event "
                "extract bekleniyor."
            ),
            "next_step": "Ilk broker bulten extract dosyasini private input alanina koy; public panel sadece agregayi gosterir.",
            "opens_trade": False,
            "promotion_gate": "closed_without_official_confirmation",
        },
        "min_mature_events_for_decision": 20,
        "by_source": _bucket_summary(events, "source_id"),
        "by_type": _bucket_summary(events, "bulletin_type"),
        "source_registry_count": len(sources),
        "source_registry_tiers": tier_counts,
        "source_registry_policy": "Source identities and URLs are private until dashboard is behind Access.",
        "public_detail_policy": "Raw broker calls, target prices, notes and per-ticker bulletin details stay private-only.",
        "detail_storage": "private_local_ledger",
        "opens_trade": False,
        "note": "Broker bulletin ledger measures source quality. It is not a trading engine and cannot promote without official/KAP/company confirmation.",
    }


def _public_payload(summary):
    return {"summary": summary}


def update(report, data, path=None, input_pattern=None, private_path=None, sources_path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    sources = _load_sources(sources_path)
    input_rows, input_errors, input_file_count = _load_inputs(input_pattern)
    private_file = Path(private_path) if private_path else _private_path()
    existing_events = _load_json(private_file, {"events": []}).get("events", [])
    merged = {str(e.get("key") or _event_key(e)): e for e in existing_events if isinstance(e, dict)}
    for event in _normalize_events(input_rows, sources):
        merged[event["key"]] = event
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    top10 = {_norm_ticker(r.get("ticker")) for r in (report or {}).get("top10", [])}
    f_positions = set()
    try:
        from . import config
        from . import portfolio as pf
        f_positions = {_norm_ticker(t) for t in pf.load("F", state_dir=config.STATE_DIR).get("positions", {})}
    except Exception:
        f_positions = set()
    events = [_refresh_event(event, prices, as_of_pos, top10, f_positions) for event in events]
    events.sort(key=lambda e: (e.get("event_date") or "", e.get("source_id") or "", e.get("ticker") or ""))
    private_payload = {
        "summary": _public_summary(events, input_file_count, input_errors, as_of, sources),
        "events": events,
        "private_warning": "Do not commit this file if it contains licensed broker bulletin details.",
    }
    _save_json(private_file, private_payload)
    public = _public_payload(private_payload["summary"])
    _save_json(Path(path) if path else _public_path(), public)
    return public["summary"]


def write_default_sources(path=None):
    payload = {
        "version": "2026-07-13",
        "policy": "Broker bulletins are measured as secondary sources. Raw bulletin content stays local.",
        "sources": [
            {"id": sid, **meta} for sid, meta in sorted(BROKER_SOURCES.items())
        ],
    }
    _save_json(Path(path) if path else _sources_path(), payload)
    return payload
