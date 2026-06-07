"""
Discovery radar and missed-opportunity ledger.

The primary F engine stays untouched. This module adds additive watchlists:
- transformation radar: stocks whose recent rank is rising fast
- quiet accumulation: accumulation signals before they become 1Y leaders
- missed ledger: candidates that were outside Top 10 and later moved
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from .sectors import get_sector
from .signals import signal_for
from .strategy import last_n_return


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "missed_opportunities.json"


def _round(value, digits=2):
    if value is None or pd.isna(value):
        return None
    rounded = round(float(value), digits)
    return 0.0 if rounded == 0 else rounded


def _date_text(date):
    return str(date.date()) if hasattr(date, "date") else str(date)


def _price_at(data, date, ticker):
    prices = data.get("prices")
    if prices is None or ticker not in prices.columns or date not in prices.index:
        return None
    value = prices.loc[date, ticker]
    return _round(value) if not pd.isna(value) and value > 0 else None


def _volume_ratio(data, date, ticker):
    volumes = data.get("volumes")
    if volumes is None or volumes.empty or ticker not in volumes.columns:
        return None
    idx = volumes.index.searchsorted(date)
    if idx < 20:
        return None
    v5 = volumes.iloc[max(0, idx - 4):idx + 1][ticker].dropna().mean()
    v20 = volumes.iloc[max(0, idx - 19):idx + 1][ticker].dropna().mean()
    if pd.isna(v5) or pd.isna(v20) or v20 <= 0:
        return None
    return _round(v5 / v20, 2)


def _candidate_frame(data, date, universe):
    rows = []
    for ticker in sorted(universe):
        m252 = last_n_return(data, date, ticker, config.MOM_GUN)
        m21 = last_n_return(data, date, ticker, config.RS_GUN_30)
        m5 = last_n_return(data, date, ticker, config.RS_GUN_5)
        if m252 is None or m21 is None or m5 is None:
            continue
        rows.append({"ticker": ticker, "m252": m252, "m21": m21, "m5": m5})
    df = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
    if df.empty:
        return df
    df["rank_1y"] = df["m252"].rank(ascending=False, method="min")
    df["rank_1a"] = df["m21"].rank(ascending=False, method="min")
    df["rank_1h"] = df["m5"].rank(ascending=False, method="min")
    df["acceleration"] = df["rank_1y"] - df[["rank_1a", "rank_1h"]].min(axis=1)
    return df


def _universe(data):
    if data.get("_dynamic_universe"):
        return set(data["_dynamic_universe"])
    prices = data.get("prices")
    return set(prices.columns) if prices is not None else set()


def _row(data, signals, date, ticker, values, kind, reason, score):
    sig = signal_for(signals, date, ticker)
    return {
        "ticker": ticker,
        "kind": kind,
        "reason": reason,
        "sector": get_sector(ticker),
        "score": _round(score, 1),
        "price": _price_at(data, date, ticker),
        "m5": _round(values["m5"], 1),
        "m21": _round(values["m21"], 1),
        "m252": _round(values["m252"], 1),
        "rank_1y": int(values["rank_1y"]),
        "rank_1a": int(values["rank_1a"]),
        "rank_1h": int(values["rank_1h"]),
        "acceleration": int(values["acceleration"]),
        "volume_ratio": _volume_ratio(data, date, ticker),
        "sm_signal": sig,
    }


def build_watchlists(data, signals, report, date=None, limit=8):
    prices = data.get("prices")
    if prices is None or prices.empty:
        return {"transformation": [], "quiet_accumulation": []}
    date = date or prices.index[-1]
    top10 = {r.get("ticker") for r in report.get("top10", [])}
    df = _candidate_frame(data, date, _universe(data))
    if df.empty:
        return {"transformation": [], "quiet_accumulation": []}

    transform = []
    quiet = []
    for ticker, values in df.iterrows():
        if ticker in top10:
            continue
        sig = signal_for(signals, date, ticker)
        sm_bonus = {"GÜÇLÜ_BİRİKİM": 18, "Birikim": 10, "Nötr": 2}.get(sig, 0)

        if (values["m21"] >= 8 and values["m5"] >= 0 and
                values["acceleration"] >= 25 and
                (values["rank_1a"] <= 45 or values["rank_1h"] <= 45)):
            score = values["acceleration"] + max(0, 60 - values["rank_1a"]) + max(0, 50 - values["rank_1h"]) + sm_bonus
            transform.append(_row(data, signals, date, ticker, values, "donusum",
                                  "1Y orta/zayif, 1A-1H hizlaniyor", score))

        vr = _volume_ratio(data, date, ticker)
        if (sig in ("GÜÇLÜ_BİRİKİM", "Birikim") and vr is not None and vr >= 1.15 and
                -10 <= values["m21"] <= 35 and -5 <= values["m5"] <= 18):
            score = (vr * 20) + sm_bonus + max(0, values["m21"]) + max(0, values["acceleration"] / 2)
            quiet.append(_row(data, signals, date, ticker, values, "sessiz_birikim",
                              "birikim + hacim artisi, henuz Top 10 degil", score))

    transform = sorted(transform, key=lambda x: (-x["score"], x["ticker"]))[:limit]
    quiet = sorted(quiet, key=lambda x: (-x["score"], x["ticker"]))[:limit]
    return {"transformation": transform, "quiet_accumulation": quiet}


def _load_ledger(path):
    if not path.exists():
        return {"snapshots": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": []}


def _refresh_snapshots(snapshots, data, as_of):
    hot = []
    for snap in snapshots:
        for item in snap.get("items", []):
            current = _price_at(data, as_of, item.get("ticker"))
            item["current_price"] = current
            entry = item.get("entry_price")
            if current and entry:
                ret = (current / entry - 1) * 100
                item["return_pct"] = _round(ret, 2)
                if item["return_pct"] is not None and item["return_pct"] >= 15:
                    hot.append({
                        "date": snap.get("date"),
                        "ticker": item.get("ticker"),
                        "kind": item.get("kind"),
                        "return_pct": item.get("return_pct"),
                        "reason": item.get("reason"),
                    })
    return hot


def update_missed_ledger(data, watchlists, report, date=None, max_snapshots=90):
    prices = data.get("prices")
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    date = date or prices.index[-1]
    date_s = _date_text(date)
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = _load_ledger(path)

    current_items = []
    for kind, items in watchlists.items():
        for item in items:
            copied = dict(item)
            copied["kind"] = kind
            copied["entry_price"] = copied.get("price")
            copied["current_price"] = copied.get("price")
            copied["return_pct"] = 0.0
            current_items.append(copied)

    snapshots = [s for s in ledger.get("snapshots", []) if s.get("date") != date_s]
    snapshots.append({
        "date": date_s,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top10": [r.get("ticker") for r in report.get("top10", [])],
        "items": current_items,
    })
    snapshots = snapshots[-max_snapshots:]
    hot = _refresh_snapshots(snapshots, data, date)
    recent_hot = hot[-10:]
    regime = "rotasyon_riski" if len(recent_hot) >= 3 else "normal"
    summary = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "tracked_days": len(snapshots),
        "current_candidates": len(current_items),
        "hot_missed_count": len(hot),
        "regime_signal": regime,
        "recent_hot": recent_hot,
    }
    ledger = {"summary": summary, "snapshots": snapshots}
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary
