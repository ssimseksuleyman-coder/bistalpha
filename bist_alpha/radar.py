"""
Discovery radar and missed-opportunity ledger.

The primary F engine stays untouched. This module adds additive watchlists:
- transformation radar: stocks whose recent rank is rising fast
- quiet accumulation: accumulation signals before they become 1Y leaders
- peak/explain-skip: leaders that are consciously avoided or need caution
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


HOT_RETURN_THRESHOLD_PCT = 15.0
REVIEW_MIN_UNIQUE_TICKERS = 30
REVIEW_RELATIVE_MEDIAN_EDGE_PCT = 5.0
REVIEW_MIN_REGIME_COUNT = 2


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
    df = df.dropna(subset=["rank_1y", "rank_1a", "rank_1h"])
    if df.empty:
        return df
    df["acceleration"] = df["rank_1y"] - df[["rank_1a", "rank_1h"]].min(axis=1)
    return df


def _universe(data, date=None):
    if data.get("_dynamic_universe"):
        return set(data["_dynamic_universe"])
    mcaps = data.get("mcaps")
    if date is not None and mcaps is not None and not mcaps.empty and date in mcaps.index:
        mc = mcaps.loc[date].dropna()
        if len(mc) >= config.UNIVERSE_SIZE:
            return set(mc.nlargest(config.UNIVERSE_SIZE).index.tolist())
    prices = data.get("prices")
    return set(prices.columns) if prices is not None else set()


def _radar_universe(data, date):
    size = getattr(config, "RADAR_UNIVERSE_SIZE", config.UNIVERSE_SIZE)
    base = _universe(data, date)
    prices = data.get("prices")
    volumes = data.get("volumes")
    if prices is not None and not prices.empty and volumes is not None and not volumes.empty:
        idx = prices.index.searchsorted(date)
        if idx >= 0:
            p_window = prices.iloc[max(0, idx - 19):idx + 1]
            v_window = volumes.reindex(p_window.index).reindex(columns=p_window.columns)
            turnover = (p_window * v_window).mean().dropna()
            turnover = turnover[turnover > 0]
            if not turnover.empty:
                # Radar daha genis bakar, ama islem evrenindeki hisseleri dislamaz.
                return base | set(turnover.nlargest(size).index.tolist())
    return set(sorted(base)[:size])


def _range_profile(data, date, ticker):
    prices = data.get("prices")
    if prices is None or ticker not in prices.columns:
        return {}
    idx = prices.index.searchsorted(date)
    if idx < 0 or idx >= len(prices.index):
        return {}
    current = prices.iloc[idx][ticker]
    window = prices.iloc[max(0, idx - config.MOM_GUN + 1):idx + 1][ticker].dropna()
    if pd.isna(current) or current <= 0 or window.empty:
        return {}
    high = window.max()
    low = window.min()
    out = {"range_high": _round(high), "range_low": _round(low)}
    if high and high > 0:
        out["from_high_pct"] = _round((float(current) / float(high) - 1) * 100, 1)
    if low and low > 0:
        out["from_low_pct"] = _round((float(current) / float(low) - 1) * 100, 1)
    return out


def _display_signal(sig):
    if sig in ("Üst_fitil_dağıtım", "Üst_fitil_UYARI"):
        return "Üst_fitil_UYARI"
    return sig


def _tag(label, severity="info", note=None):
    out = {"label": label, "severity": severity}
    if note:
        out["note"] = note
    return out


def _top_sector_counts(report):
    counts = {}
    for row in report.get("top10", []):
        sector = row.get("sector") or get_sector(row.get("ticker"))
        counts[sector] = counts.get(sector, 0) + 1
    return counts


def _risk_tags(data, date, ticker, values, sig, sector_counts, top10):
    tags = []
    sector = get_sector(ticker)
    profile = _range_profile(data, date, ticker)
    if profile.get("from_high_pct") is not None and profile["from_high_pct"] >= -2:
        tags.append(_tag("zirveye_yakin", "warn", "52 haftalik tepeye cok yakin"))
    if values["rank_1y"] <= 30 and values["rank_1h"] >= values["rank_1y"] + 15:
        tags.append(_tag("ivme_yavasliyor", "warn", "1Y liderligi var ama 1H sirasi geri"))
    if sig == "DAĞITIM":
        tags.append(_tag("dagitim_bilgi", "warn", "eleme degil; tepe/yorulma etiketi"))
    if sig in ("Üst_fitil_dağıtım", "Üst_fitil_UYARI"):
        tags.append(_tag("ust_fitil_uyari", "warn", "ust fitil var; adini dagitim gibi okuma"))
    if ticker not in top10 and sector_counts.get(sector, 0) >= config.SEKTOR_CAP:
        tags.append(_tag("sektor_cap_dolu", "info", "Top10 icinde sektor kotasi dolu"))
    if values["m21"] >= 25 and values["m5"] < 0:
        tags.append(_tag("aylik_pump_soguyor", "warn", "1A guclu ama 1H negatif"))
    if values["m21"] <= 0 and values["m5"] < 0:
        tags.append(_tag("duseni_tutma_riski", "warn", "kisa ve orta vade guc yok"))
    return tags, profile


def _row(data, signals, date, ticker, values, kind, reason, score):
    sig = signal_for(signals, date, ticker)
    trade_universe = _universe(data, date)
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
        "display_signal": _display_signal(sig),
        "radar_only": ticker not in trade_universe,
    }


def build_watchlists(data, signals, report, date=None, limit=8):
    prices = data.get("prices")
    if prices is None or prices.empty:
        return {"transformation": [], "quiet_accumulation": [], "peak_risks": []}
    date = date or prices.index[-1]
    top10 = {r.get("ticker") for r in report.get("top10", [])}
    trade_universe = _universe(data, date)
    radar_universe = _radar_universe(data, date)
    sector_counts = _top_sector_counts(report)
    df = _candidate_frame(data, date, radar_universe)
    if df.empty:
        return {"transformation": [], "quiet_accumulation": [], "peak_risks": []}

    transform = []
    quiet = []
    peak_risks = []
    for ticker, values in df.iterrows():
        if ticker in top10:
            continue
        sig = signal_for(signals, date, ticker)
        sm_bonus = {"GÜÇLÜ_BİRİKİM": 18, "Birikim": 10, "Nötr": 2}.get(sig, 0)
        tags, profile = _risk_tags(data, date, ticker, values, sig, sector_counts, top10)

        if (values["m21"] >= 8 and values["m5"] >= 0 and
                values["acceleration"] >= 25 and
                (values["rank_1a"] <= 45 or values["rank_1h"] <= 45)):
            score = values["acceleration"] + max(0, 60 - values["rank_1a"]) + max(0, 50 - values["rank_1h"]) + sm_bonus
            item = _row(data, signals, date, ticker, values, "donusum",
                        "1Y orta/zayif, 1A-1H hizlaniyor", score)
            item.update(profile)
            item["tags"] = list(tags)
            transform.append(item)

        vr = _volume_ratio(data, date, ticker)
        if (sig in ("GÜÇLÜ_BİRİKİM", "Birikim") and vr is not None and vr >= 1.15 and
                -10 <= values["m21"] <= 35 and -5 <= values["m5"] <= 18):
            score = (vr * 20) + sm_bonus + max(0, values["m21"]) + max(0, values["acceleration"] / 2)
            item = _row(data, signals, date, ticker, values, "sessiz_birikim",
                        "birikim + hacim artisi, henuz Top 10 degil", score)
            item.update(profile)
            item["tags"] = list(tags)
            quiet.append(item)

        risk_labels = {t["label"] for t in tags}
        if (risk_labels.intersection({"zirveye_yakin", "ivme_yavasliyor", "dagitim_bilgi", "ust_fitil_uyari", "aylik_pump_soguyor"}) and
                (values["rank_1y"] <= 40 or values["m252"] >= 80 or values["rank_1a"] <= 30)):
            score = max(0, 70 - values["rank_1y"]) + max(0, values["m252"] / 5) + len(risk_labels) * 8
            item = _row(data, signals, date, ticker, values, "tepe_riski",
                        "guc var ama alim icin risk etiketi tasiyor", score)
            item.update(profile)
            item["tags"] = list(tags)
            peak_risks.append(item)

    transform = sorted(transform, key=lambda x: (-x["score"], x["ticker"]))[:limit]
    quiet = sorted(quiet, key=lambda x: (-x["score"], x["ticker"]))[:limit]
    peak_risks = sorted(peak_risks, key=lambda x: (-x["score"], x["ticker"]))[:limit]
    date_s = _date_text(date)
    transform = _apply_quarantine(transform, "transformation", date_s)
    quiet = _apply_quarantine(quiet, "quiet_accumulation", date_s)
    return {
        "transformation": transform,
        "quiet_accumulation": quiet,
        "peak_risks": peak_risks,
        "radar_universe_count": len(radar_universe),
        "trade_universe_count": len(trade_universe),
        "radar_note": "Top10/F motoru 100 evrenle kalir; radar 150 hisseyi izleme amacli tarar.",
    }


def _load_ledger(path):
    if not path.exists():
        return {"snapshots": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": []}


def _prior_watch_days(snapshots, ticker, list_name, date_s):
    days = 0
    for snap in reversed(snapshots or []):
        if snap.get("date") == date_s:
            continue
        tickers = {
            item.get("ticker")
            for item in snap.get("items", [])
            if item.get("kind") == list_name
        }
        if ticker not in tickers:
            break
        days += 1
    return days


def _apply_quarantine(items, list_name, date_s):
    ledger = _load_ledger(_ledger_path())
    snapshots = ledger.get("snapshots", [])
    for item in items:
        watch_days = _prior_watch_days(snapshots, item.get("ticker"), list_name, date_s) + 1
        item["watch_days"] = watch_days
        if watch_days < 3:
            item["quarantine_status"] = "karantina"
            item.setdefault("tags", []).append(
                _tag("karantina_1_3_gun", "info", "yeni radar adayi; teyit bekliyor")
            )
        else:
            item["quarantine_status"] = "teyitli_izleme"
    return items


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
                if item["return_pct"] is not None and item["return_pct"] >= HOT_RETURN_THRESHOLD_PCT:
                    hot.append({
                        "date": snap.get("date"),
                        "ticker": item.get("ticker"),
                        "kind": item.get("kind"),
                        "return_pct": item.get("return_pct"),
                        "reason": item.get("reason"),
                    })
    return hot


def _hot_diagnostics(hot, snapshots, window_days=5):
    by_ticker = {}
    by_kind = {}
    for event in hot:
        ticker = event.get("ticker")
        kind = event.get("kind") or "unknown"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        row = by_ticker.setdefault(ticker, {
            "ticker": ticker,
            "count": 0,
            "max_return_pct": None,
            "avg_return_pct": 0.0,
            "first_date": event.get("date"),
            "last_date": event.get("date"),
            "kinds": {},
        })
        row["count"] += 1
        ret = event.get("return_pct")
        row["avg_return_pct"] += float(ret or 0)
        row["max_return_pct"] = ret if row["max_return_pct"] is None else max(row["max_return_pct"], ret)
        row["last_date"] = event.get("date")
        row["kinds"][kind] = row["kinds"].get(kind, 0) + 1
    rows = []
    for row in by_ticker.values():
        row["avg_return_pct"] = _round(row["avg_return_pct"] / row["count"], 2) if row["count"] else None
        rows.append(row)
    rows = sorted(rows, key=lambda x: (-(x.get("max_return_pct") or 0), x.get("ticker") or ""))[:10]

    recent_dates = {s.get("date") for s in snapshots[-window_days:]}
    recent_hot = [event for event in hot if event.get("date") in recent_dates]
    recent_unique = sorted({event.get("ticker") for event in recent_hot if event.get("ticker")})
    signal = "normal"
    if len(recent_unique) >= 3:
        signal = "rotasyon_riski"
    elif len(recent_unique) >= 2:
        signal = "rotasyon_izle"
    return {
        "hot_unique_count": len(by_ticker),
        "hot_by_kind": by_kind,
        "hot_by_ticker": rows,
        "recent_window_days": window_days,
        "recent_hot_events": len(recent_hot),
        "recent_hot_unique_count": len(recent_unique),
        "recent_hot_unique": recent_unique,
        "regime_signal": signal,
    }


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
        if not isinstance(items, list) or kind == "peak_risks":
            continue
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
    diagnostics = _hot_diagnostics(hot, snapshots)
    recent_hot = [event for event in hot if event.get("date") in {s.get("date") for s in snapshots[-diagnostics["recent_window_days"]:]}][-10:]
    summary = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "tracked_days": len(snapshots),
        "current_candidates": len(current_items),
        "hot_missed_count": len(hot),
        "hot_return_threshold_pct": HOT_RETURN_THRESHOLD_PCT,
        **diagnostics,
        "recent_hot": recent_hot,
        "statistical_sample": {
            "event_count": len(hot),
            "unique_ticker_count": diagnostics.get("hot_unique_count"),
            "independence_unit": "unique_ticker",
            "note": "Ayni hissenin tekrar eden sicak olaylari bagimsiz ornek sayilmaz.",
        },
        "denominator_status": {
            "status": "hot_only_denominator_missing",
            "note": "Bu defter sadece sicak kacanlari toplar; F'in eledigi ve sonradan dusen/duz kalan tum payda burada yoktur.",
        },
        "review_policy": {
            "eligible_for_promotion": False,
            "reason": "Payda eksik ve sicak olaylar hindsight-secimli; tani/teshis icindir.",
            "required_before_review": {
                "all_rejected_universe_denominator": True,
                "min_unique_tickers": REVIEW_MIN_UNIQUE_TICKERS,
                "relative_to_f_median_21d": True,
                "required_median_edge_pct": REVIEW_RELATIVE_MEDIAN_EDGE_PCT,
                "min_regime_count": REVIEW_MIN_REGIME_COUNT,
            },
            "absolute_hot_return_gate_allowed": False,
        },
    }
    ledger = {"summary": summary, "snapshots": snapshots}
    import os as _os
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _os.replace(tmp, str(path))
    return summary
