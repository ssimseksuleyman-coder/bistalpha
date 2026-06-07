"""
Forward-test ledger.

Her rapor calismasinda Top 10 sinyali kaydedilir, sonraki calismalarda ayni
sinyalin bugunku fiyata gore ne kadar ilerledigi hesaplanir. Bu gercek emir
degil; sinyal kalitesini 30 gun boyunca olcmek icin izleme defteridir.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


MAX_SNAPSHOTS = 45


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_path() -> Path:
    return _repo_root() / "docs" / "state" / "forward_test.json"


def _round(value, digits=2):
    if value is None or pd.isna(value):
        return None
    rounded = round(float(value), digits)
    return 0.0 if rounded == 0 else rounded


def _last_price_map(data):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {}, None, None
    last_date = prices.index[-1]
    row = prices.loc[last_date]
    latest = {t: float(v) for t, v in row.items() if not pd.isna(v) and v > 0}
    return latest, prices, last_date


def _trading_age(prices, entry_date, last_date):
    if prices is None or entry_date is None or last_date is None:
        return None
    try:
        idx0 = prices.index.searchsorted(pd.Timestamp(entry_date))
        idx1 = prices.index.searchsorted(pd.Timestamp(last_date))
        return max(0, int(idx1 - idx0))
    except Exception:
        return None


def _load(path):
    if not path.exists():
        return {"snapshots": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": []}


def _snapshot_from_report(report):
    items = []
    for row in report.get("top10", []):
        entry = row.get("mevcut_fiyat") or row.get("giris_fiyati")
        items.append({
            "rank": row.get("rank"),
            "ticker": row.get("ticker"),
            "action": row.get("action"),
            "signal": row.get("sm_signal"),
            "sector": row.get("sector"),
            "entry_price": _round(entry),
            "m5": row.get("m5"),
            "m21": row.get("m21"),
            "m252": row.get("m252"),
            "target_1": row.get("hedef_1"),
            "target_2": row.get("hedef_2"),
            "stop": row.get("stop"),
        })
    return {
        "date": report.get("date"),
        "generated_at": report.get("generated_at"),
        "mode": report.get("mode"),
        "source": report.get("source"),
        "last_data_date": report.get("last_data_date"),
        "items": items,
    }


def _merge_same_day_snapshot(existing, current):
    """
    Gunde birden fazla kosu olabilir. Ilk giris fiyati forward-test'in
    referansidir; sonraki kosular sadece metadata ve izlenecek listeyi tazeler.
    """
    if not existing:
        return current
    old_items = {item.get("ticker"): item for item in existing.get("items", [])}
    merged_items = []
    for item in current.get("items", []):
        old = old_items.get(item.get("ticker"))
        if old and old.get("entry_price"):
            item = {**item, "entry_price": old.get("entry_price")}
        merged_items.append(item)
    merged = {**current, "items": merged_items}
    merged["first_generated_at"] = existing.get("first_generated_at") or existing.get("generated_at")
    merged["generated_at"] = existing.get("generated_at") or current.get("generated_at")
    merged["last_generated_at"] = current.get("generated_at")
    return merged


def _refresh_snapshot(snapshot, latest_prices, prices, last_date):
    returns = []
    winners = 0
    for item in snapshot.get("items", []):
        ticker = item.get("ticker")
        entry = item.get("entry_price")
        current = latest_prices.get(ticker)
        item["current_price"] = _round(current)
        if entry and current:
            ret = (current / float(entry) - 1) * 100
            ret_rounded = _round(ret)
            item["return_pct"] = ret_rounded
            returns.append(ret)
            if ret_rounded is not None and ret_rounded > 0:
                winners += 1
        else:
            item["return_pct"] = None
    snapshot["as_of"] = str(last_date.date()) if hasattr(last_date, "date") else str(last_date)
    snapshot["age_trading_days"] = _trading_age(prices, snapshot.get("date"), last_date)
    snapshot["avg_return_pct"] = _round(sum(returns) / len(returns)) if returns else None
    snapshot["hit_rate_pct"] = _round(winners / len(returns) * 100, 1) if returns else None
    snapshot["tracked_count"] = len(returns)
    return snapshot


def update(report, data=None, path=None, max_snapshots=MAX_SNAPSHOTS):
    """Forward-test dosyasini guncelle ve dashboard icin ozet dondur."""
    path = Path(path) if path else _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    ledger = _load(path)
    snapshots = ledger.get("snapshots", [])
    current = _snapshot_from_report(report)
    current_date = current.get("date")

    existing_today = next((s for s in snapshots if s.get("date") == current_date), None)
    current = _merge_same_day_snapshot(existing_today, current)
    snapshots = [s for s in snapshots if s.get("date") != current_date]
    snapshots.append(current)
    snapshots = snapshots[-max_snapshots:]

    latest_prices, prices, last_date = _last_price_map(data)
    if latest_prices:
        snapshots = [_refresh_snapshot(s, latest_prices, prices, last_date) for s in snapshots]

    latest = snapshots[-1] if snapshots else None
    summary = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "days_tracked": len(snapshots),
        "latest_date": latest.get("date") if latest else None,
        "latest_avg_return_pct": latest.get("avg_return_pct") if latest else None,
        "latest_hit_rate_pct": latest.get("hit_rate_pct") if latest else None,
        "latest_age_trading_days": latest.get("age_trading_days") if latest else None,
        "tracked_count": latest.get("tracked_count") if latest else None,
        "recent": snapshots[-7:],
    }

    ledger = {
        "updated_at": summary["updated_at"],
        "days_tracked": summary["days_tracked"],
        "summary": summary,
        "snapshots": snapshots,
    }
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary
