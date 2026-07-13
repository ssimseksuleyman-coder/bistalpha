"""Fundamental quality ledger.

Measurement layer only. It records quality/fundamental observations, follows
their forward returns, and keeps them separate from the F production motor.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (5, 21, 63)
MAX_EVENTS = 500


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "quality_ledger.json"


def _kap_events_path() -> Path:
    return _repo_root() / "docs" / "state" / "catalysts.json"


def _local_official_path() -> Path:
    return _repo_root() / "local" / "kap_financial_actuals.json"


def _roe_shadow_path() -> Path:
    return _repo_root() / "reports" / "roe_shadow_ledger.json"


def _source_meta():
    kap_payload = _load_json(_kap_events_path(), {})
    kap_events = kap_payload.get("events", []) if isinstance(kap_payload, dict) else []
    financial_events = [e for e in kap_events if _is_financial_disclosure(e)]
    local_payload = _load_json(_local_official_path(), {})
    local_companies = local_payload.get("companies", []) if isinstance(local_payload, dict) else []
    local_meta = local_payload.get("_meta", {}) if isinstance(local_payload, dict) else {}
    available = bool(financial_events or local_companies)
    return {
        "source_name": "KAP resmi finansal bildirimleri",
        "source_file": _kap_events_path().relative_to(_repo_root()).as_posix(),
        "local_metrics_file": _local_official_path().relative_to(_repo_root()).as_posix(),
        "extracted_at": local_meta.get("extracted_at") or local_meta.get("extracted"),
        "n_companies": len(local_companies) or None,
        "kap_financial_events": len(financial_events),
        "data_available": available,
        "source_status": "kap_event_stream_active" if _kap_events_path().exists() else "kap_event_stream_missing",
        "public_repo_policy": "official_events_public; detailed_metric_extracts_local_only",
        "kap_financial_parser": "event_release_active_metrics_pending",
        "opens_trade": False,
        "third_party_bulletin_policy": (
            "Ucuncu taraf bulten verisi deftere yazilmaz. En fazla alarm/yer-gosterici olabilir; "
            "finansal gercekler KAP/sirket/BIST resmi kaynagindan yeniden dogrulanir."
        ),
    }


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


def _first_price_on_or_after(prices, ticker, date_s):
    if prices is None or prices.empty or ticker not in prices.columns or not date_s:
        return None, None, None
    target = pd.Timestamp(date_s)
    pos = int(prices.index.searchsorted(target, side="left"))
    while pos < len(prices.index):
        value = _price_at_pos(prices, ticker, pos)
        if value is not None:
            return value, _date_text(prices.index[pos]), pos
        pos += 1
    return None, None, None


def _event_key(event):
    return "|".join([
        str(event.get("source_id") or ""),
        str(event.get("release_date") or ""),
        str(event.get("ticker") or ""),
    ])


def _metric(data, *names):
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return None


def _is_financial_disclosure(event):
    if not isinstance(event, dict):
        return False
    typ = str(event.get("type") or "").lower()
    title = str(event.get("title") or "").lower()
    if typ in {"bilanco", "finansal", "financial_report"}:
        return True
    keys = (
        "finansal rapor",
        "finansal tablo",
        "bilanço",
        "bilanco",
        "faaliyet raporu",
        "gelir tablosu",
        "nakit akış",
        "nakit akis",
    )
    return any(k in title for k in keys)


def _quality_flags(event):
    flags = []
    roe = event.get("roe_pct")
    yoy = event.get("profit_yoy_pct")
    surprise = event.get("surprise_pct")
    if roe is not None and roe >= 20:
        flags.append("roe_guclu")
    if yoy is not None and yoy >= 20:
        flags.append("kar_buyumesi")
    if surprise is not None and surprise >= 5:
        flags.append("beklenti_ustu")
    if event.get("target_price_change_pct") is not None and event["target_price_change_pct"] >= 5:
        flags.append("hedef_yukari")
    missing = []
    for key in ("roe_pct", "profit_yoy_pct", "revenue_mio", "net_debt_ebitda"):
        if event.get(key) is None:
            missing.append(key)
    return flags, missing


def _event_from_official_row(row, payload, prices):
    ticker = _norm_ticker(row.get("ticker"))
    release_date = row.get("release_date") or row.get("date")
    if not ticker or not release_date:
        return None
    entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, release_date)
    event = {
        "source_id": row.get("source_id") or "local_kap_financial_actuals",
        "source": payload.get("_meta", {}).get("source", "KAP/company official financial extract"),
        "source_tier": "primary",
        "requires_kap_confirmation": False,
        "kap_confirmed": True,
        "opens_trade": False,
        "ticker": ticker,
        "release_date": str(release_date),
        "entry_date": entry_date,
        "entry_price": _round(entry),
        "entry_pos": entry_pos,
        "metric": row.get("metric", "net_kar"),
        "result": row.get("result"),
        "recommendation": row.get("recommendation") or row.get("recommendation_new"),
        "surprise_pct": _round(row.get("surprise_pct"), 1),
        "roe_pct": _round(row.get("roe_pct"), 1),
        "profit_yoy_pct": _round(_metric(row, "profit_yoy_pct", "yoy_pct"), 1),
        "profit_qoq_pct": _round(_metric(row, "profit_qoq_pct", "qoq_pct"), 1),
        "revenue_mio": _round(_metric(row, "revenue_mio", "actual_revenue_mio_try", "actual_revenue_mio_usd", "actual_revenue_mio_eur"), 1),
        "favok_mio": _round(_metric(row, "favok_mio", "actual_favok_mio_try", "actual_favok_mio_usd", "actual_favok_mio_eur"), 1),
        "net_debt_ebitda": _round(row.get("net_debt_ebitda"), 2),
        "target_price_change_pct": _round(row.get("target_price_change_pct"), 1),
        "note": row.get("note"),
        "official_source_url": row.get("official_source_url") or row.get("url"),
        "financial_metrics_status": "official_metrics_loaded",
    }
    flags, missing = _quality_flags(event)
    event["quality_flags"] = flags
    event["missing_quality_fields"] = missing
    return event


def _local_official_events(prices):
    payload = _load_json(_local_official_path(), {})
    companies = payload.get("companies", []) if isinstance(payload, dict) else []
    events = []
    for row in companies:
        event = _event_from_official_row(row, payload, prices)
        if event:
            events.append(event)
    return events


def _kap_financial_events(prices):
    payload = _load_json(_kap_events_path(), {})
    rows = payload.get("events", []) if isinstance(payload, dict) else []
    events = []
    for row in rows:
        if not _is_financial_disclosure(row):
            continue
        ticker = _norm_ticker(row.get("ticker"))
        release_date = row.get("date") or row.get("release_date")
        if not ticker or not release_date:
            continue
        entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, release_date)
        event = {
            "source_id": "kap_financial_disclosure",
            "source": "KAP resmi finansal tablo bildirimi",
            "source_tier": "primary",
            "requires_kap_confirmation": False,
            "kap_confirmed": True,
            "opens_trade": False,
            "ticker": ticker,
            "release_date": str(release_date),
            "entry_date": entry_date,
            "entry_price": _round(entry),
            "entry_pos": entry_pos,
            "metric": "financial_report_release",
            "result": "kap_finansal_tablo",
            "recommendation": None,
            "surprise_pct": None,
            "roe_pct": None,
            "profit_yoy_pct": None,
            "profit_qoq_pct": None,
            "revenue_mio": None,
            "favok_mio": None,
            "net_debt_ebitda": None,
            "target_price_change_pct": None,
            "note": row.get("title"),
            "official_source_url": row.get("url"),
            "financial_metrics_status": "pending_table_parse",
        }
        flags, missing = _quality_flags(event)
        event["quality_flags"] = flags
        event["missing_quality_fields"] = missing
        events.append(event)
    return events


def _official_quality_events(prices):
    return _kap_financial_events(prices) + _local_official_events(prices)


def _refresh_event(event, prices, as_of_pos):
    ticker = event.get("ticker")
    entry = event.get("entry_price")
    entry_pos = event.get("entry_pos")
    if entry is None and event.get("release_date"):
        entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, event.get("release_date"))
        event["entry_price"] = _round(entry)
        event["entry_date"] = entry_date
        event["entry_pos"] = entry_pos
    current = _price_at_pos(prices, ticker, as_of_pos)
    event["current_price"] = _round(current)
    if entry is None or entry_pos is None or current is None:
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
    mature = [w for w in WINDOWS if event.get(f"return_{w}d_pct") is not None]
    event["status"] = f"mature_{max(mature)}d" if mature else "open"
    return event


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _hit(values):
    values = [float(v) for v in values if v is not None]
    return sum(1 for v in values if v > 0) / len(values) * 100 if values else None


def _roe_shadow_summary():
    ledger = _load_json(_roe_shadow_path(), [])
    if not isinstance(ledger, list):
        return {"records": 0}
    matured = [e for e in ledger if e.get("fwd")]
    edges = [e.get("fwd", {}).get("edge") for e in matured]
    return {
        "records": len(ledger),
        "matured": len(matured),
        "avg_edge_pct": _round(_avg(edges)),
        "note": "ROE shadow is isolated; it measures, does not trade.",
    }


def _summary(events, as_of):
    rows = {}
    for event in events:
        result = event.get("result") or "unknown"
        row = rows.setdefault(result, {"result": result, "n": 0, "ret21": [], "wins": 0})
        row["n"] += 1
        ret = event.get("return_21d_pct")
        if ret is not None:
            row["ret21"].append(ret)
            row["wins"] += 1 if float(ret) > 0 else 0
    by_result = []
    for row in rows.values():
        n = len(row["ret21"])
        by_result.append({
            "result": row["result"],
            "n": row["n"],
            "mature_21d": n,
            "avg_21d_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(row["wins"] / n * 100, 1) if n else None,
        })
    ret5 = [e.get("return_5d_pct") for e in events]
    ret21 = [e.get("return_21d_pct") for e in events]
    ret63 = [e.get("return_63d_pct") for e in events]
    mature21 = [e for e in events if e.get("return_21d_pct") is not None]
    confirmed = [e for e in events if e.get("kap_confirmed")]
    decision = "resmi_finansal_olay_bekliyor" if not events else "olcum_devam"
    if events and not confirmed:
        decision = "kap_teyidi_bekliyor"
    if len(mature21) >= 20 and _avg(ret21) is not None and _avg(ret21) > 0 and (_hit(ret21) or 0) >= 50 and confirmed:
        decision = "izleme_degeri_var"
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "source_meta": _source_meta(),
        "tracked_events": len(events),
        "kap_confirmed": len(confirmed),
        "opens_trade": False,
        "matured_5d": len([e for e in events if e.get("return_5d_pct") is not None]),
        "matured_21d": len(mature21),
        "matured_63d": len([e for e in events if e.get("return_63d_pct") is not None]),
        "avg_5d_return_pct": _round(_avg(ret5)),
        "hit_5d_pct": _round(_hit(ret5), 1),
        "avg_21d_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(_hit(ret21), 1),
        "avg_63d_return_pct": _round(_avg(ret63)),
        "hit_63d_pct": _round(_hit(ret63), 1),
        "decision": decision,
        "roe_shadow": _roe_shadow_summary(),
        "latest_candidates": sorted(events, key=lambda e: e.get("release_date") or "", reverse=True)[:10],
        "by_result": sorted(by_result, key=lambda x: x["result"]),
        "note": (
            "Temel kalite defteri olcer; yalnizca KAP/sirket/BIST gibi resmi kaynakla "
            "dogrulanan veri kullanir. F motoruna emir uretmez."
        ),
    }


def update(report, data, path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    ledger_path = Path(path) if path else _ledger_path()
    existing = _load_json(ledger_path, {"events": []}).get("events", [])
    merged = {_event_key(e): e for e in existing}
    for event in _official_quality_events(prices):
        old = merged.get(_event_key(event), {})
        if old.get("kap_confirmed") is True and event.get("kap_confirmed") is False:
            event["kap_confirmed"] = True
        old.update({k: v for k, v in event.items() if v is not None or k not in old})
        merged[_event_key(event)] = old
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    events = [_refresh_event(event, prices, as_of_pos) for event in events]
    events.sort(key=lambda e: (e.get("release_date") or "", e.get("ticker") or ""))
    payload = {
        "summary": _summary(events, as_of),
        "events": events,
    }
    _save_json(ledger_path, payload)
    return payload["summary"]
