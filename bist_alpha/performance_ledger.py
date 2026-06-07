"""
Role-aware performance ledger.

This is the promotion gate for additive layers. It does not change the F engine;
it records what each layer signaled, the market regime at the time, and how that
signal behaved later.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config
from . import portfolio as pf


MAX_SNAPSHOTS = 90
RISK_DOWN_THRESHOLD = -3.0
RISK_UP_THRESHOLD = 3.0
DISCOVERY_UP_THRESHOLD = 5.0
DISCOVERY_DOWN_THRESHOLD = -3.0


LAYER_META = {
    "F_top10": {
        "role": "return",
        "label": "F Top10",
        "metric": "forward_return_hit_rate",
    },
    "F_shadow": {
        "role": "return",
        "label": "F Shadow",
        "metric": "forward_return_hit_rate",
    },
    "O_shadow": {
        "role": "return",
        "label": "OMEGA Shadow",
        "metric": "forward_return_hit_rate",
    },
    "O_minus_F": {
        "role": "swap",
        "label": "OMEGA Swap",
        "metric": "two_leg_divergence_edge",
    },
    "transformation": {
        "role": "discovery",
        "label": "Donusum Radari",
        "metric": "captured_alpha_false_positive",
    },
    "quiet_accumulation": {
        "role": "discovery",
        "label": "Sessiz Birikim",
        "metric": "captured_alpha_false_positive",
    },
    "peak_risks": {
        "role": "risk",
        "label": "Tepe Riski",
        "metric": "saved_loss_opportunity_cost",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_path() -> Path:
    return _repo_root() / "docs" / "state" / "performance_ledger.json"


def _round(value, digits=2):
    if value is None or pd.isna(value):
        return None
    rounded = round(float(value), digits)
    return 0.0 if rounded == 0 else rounded


def _date_text(date):
    return str(date.date()) if hasattr(date, "date") else str(date)


def _load(path):
    if not path.exists():
        return {"snapshots": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snapshots": []}


def _price_at(data, date, ticker):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty or ticker not in prices.columns:
        return None
    if date not in prices.index:
        idx = prices.index.searchsorted(pd.Timestamp(date))
        if idx <= 0:
            return None
        date = prices.index[min(idx, len(prices.index) - 1)]
    value = prices.loc[date, ticker]
    return float(value) if not pd.isna(value) and value > 0 else None


def _last_date(data):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return None
    return prices.index[-1]


def _market_regime(data, date):
    bist = data.get("bist") if data else None
    if bist is None or len(bist) < 22:
        return {"name": "unknown", "xu5": None, "xu21": None}
    idx = bist.index.searchsorted(pd.Timestamp(date))
    if idx < 21 or idx >= len(bist):
        return {"name": "unknown", "xu5": None, "xu21": None}
    now = bist.iloc[idx]
    p5 = bist.iloc[idx - 5]
    p21 = bist.iloc[idx - 21]
    if pd.isna(now) or pd.isna(p5) or pd.isna(p21) or p5 <= 0 or p21 <= 0:
        return {"name": "unknown", "xu5": None, "xu21": None}
    xu5 = (now / p5 - 1) * 100
    xu21 = (now / p21 - 1) * 100
    if xu5 <= -3 or xu21 <= -8:
        name = "bear"
    elif abs(xu5) < 1 and abs(xu21) < 4:
        name = "sideways"
    elif xu5 >= 3 or xu21 >= 8:
        name = "bull"
    else:
        name = "mixed"
    return {"name": name, "xu5": _round(xu5, 1), "xu21": _round(xu21, 1)}


def _tag_labels(item):
    labels = []
    for tag in item.get("tags") or []:
        if isinstance(tag, dict):
            label = tag.get("label")
        else:
            label = str(tag)
        if label and label not in labels:
            labels.append(label)
    return labels


def _event(layer, ticker, entry, date_s, source_item=None):
    meta = LAYER_META[layer]
    source_item = source_item or {}
    return {
        "layer": layer,
        "label": meta["label"],
        "role": meta["role"],
        "metric": meta["metric"],
        "ticker": ticker,
        "entry_price": _round(entry),
        "current_price": _round(entry),
        "return_pct": 0.0,
        "entry_date": date_s,
        "reason": source_item.get("reason"),
        "signal": source_item.get("display_signal") or source_item.get("sm_signal"),
        "tags": _tag_labels(source_item),
    }


def _events_from_report(report, watchlists, date_s):
    events = []
    seen = set()
    for row in report.get("top10", []):
        ticker = row.get("ticker")
        entry = row.get("mevcut_fiyat") or row.get("giris_fiyati")
        if ticker and entry:
            events.append(_event("F_top10", ticker, entry, date_s, row))
            seen.add(("F_top10", ticker))

    for layer in ("transformation", "quiet_accumulation", "peak_risks"):
        for item in (watchlists or {}).get(layer, []) or []:
            ticker = item.get("ticker")
            entry = item.get("price")
            key = (layer, ticker)
            if ticker and entry and key not in seen:
                events.append(_event(layer, ticker, entry, date_s, item))
                seen.add(key)
    return events


def _events_from_shadow(state_dir, date_s):
    events = []
    states = {}
    for account in ("F", "O"):
        try:
            states[account] = pf.load(account, state_dir=state_dir)
        except Exception:
            states[account] = {"positions": {}}

    f_positions = (states.get("F") or {}).get("positions", {})
    o_positions = (states.get("O") or {}).get("positions", {})
    f_tickers = set(f_positions.keys())
    o_tickers = set(o_positions.keys())
    for account, layer in (("F", "F_shadow"), ("O", "O_shadow")):
        positions = (states.get(account) or {}).get("positions", {})
        for ticker, pos in sorted(positions.items()):
            entry = pos.get("entry")
            if not entry:
                continue
            source = {
                "reason": f"{account} shadow portfoy",
                "display_signal": account,
            }
            event = _event(layer, ticker, entry, date_s, source)
            event["account"] = account
            event["shares"] = _round(pos.get("shares"), 6)
            events.append(event)

            if account == "O" and ticker not in f_tickers:
                diff_event = _event("O_minus_F", ticker, entry, date_s, {
                    "reason": "O aldi, F almadi",
                    "display_signal": "O-F",
                })
                diff_event["account"] = "O"
                diff_event["leg"] = "o_only"
                diff_event["shares"] = _round(pos.get("shares"), 6)
                events.append(diff_event)
    for ticker in sorted(f_tickers - o_tickers):
        pos = f_positions.get(ticker) or {}
        entry = pos.get("entry")
        if not entry:
            continue
        diff_event = _event("O_minus_F", ticker, entry, date_s, {
            "reason": "F aldi, O disarida birakti",
            "display_signal": "F-only",
        })
        diff_event["account"] = "F"
        diff_event["leg"] = "f_only"
        diff_event["shares"] = _round(pos.get("shares"), 6)
        events.append(diff_event)
    return events


def _merge_same_day(existing, current):
    if not existing:
        return current
    old_events = {(e.get("layer"), e.get("ticker"), e.get("leg")): e for e in existing.get("events", [])}
    merged_events = []
    for event in current.get("events", []):
        old = old_events.get((event.get("layer"), event.get("ticker"), event.get("leg")))
        if old and old.get("entry_price"):
            event = {**event, "entry_price": old.get("entry_price")}
        merged_events.append(event)
    merged = {**current, "events": merged_events}
    merged["generated_at"] = existing.get("generated_at") or current.get("generated_at")
    merged["last_generated_at"] = current.get("generated_at")
    return merged


def _score_event(event, current_price):
    entry = event.get("entry_price")
    event["current_price"] = _round(current_price)
    if not entry or not current_price:
        event["return_pct"] = None
        return event
    ret = (float(current_price) / float(entry) - 1) * 100
    event["return_pct"] = _round(ret, 2)
    role = event.get("role")
    if role == "risk":
        event["saved_loss_pct"] = _round(abs(min(ret, 0)), 2)
        event["opportunity_cost_pct"] = _round(max(ret, 0), 2)
        event["verdict"] = (
            "saved_loss" if ret <= RISK_DOWN_THRESHOLD
            else "false_alarm" if ret >= RISK_UP_THRESHOLD
            else "neutral"
        )
    elif role == "discovery":
        event["captured_alpha_pct"] = _round(max(ret, 0), 2)
        event["false_positive_loss_pct"] = _round(abs(min(ret, 0)), 2)
        event["verdict"] = (
            "hit" if ret >= DISCOVERY_UP_THRESHOLD
            else "false_positive" if ret <= DISCOVERY_DOWN_THRESHOLD
            else "neutral"
        )
    else:
        event["verdict"] = "hit" if ret > 0 else "loss" if ret < 0 else "flat"
    return event


def _refresh_snapshots(snapshots, data, as_of):
    for snap in snapshots:
        for event in snap.get("events", []):
            current = _price_at(data, as_of, event.get("ticker"))
            _score_event(event, current)
    return snapshots


def _aggregate(snapshots):
    buckets = {}
    for snap in snapshots:
        regime = (snap.get("regime") or {}).get("name", "unknown")
        for event in snap.get("events", []):
            if event.get("layer") == "O_minus_F":
                continue
            ret = event.get("return_pct")
            if ret is None:
                continue
            key = (event.get("layer"), event.get("role"), regime)
            bucket = buckets.setdefault(key, {
                "layer": event.get("layer"),
                "label": event.get("label"),
                "role": event.get("role"),
                "regime": regime,
                "n": 0,
                "sum_return": 0.0,
                "wins": 0,
                "saved_loss": 0.0,
                "opportunity_cost": 0.0,
                "captured_alpha": 0.0,
                "false_positive_loss": 0.0,
                "saved_events": 0,
                "false_alarm_events": 0,
                "discovery_hits": 0,
                "discovery_false_positive": 0,
            })
            bucket["n"] += 1
            bucket["sum_return"] += float(ret)
            bucket["wins"] += 1 if ret > 0 else 0
            bucket["saved_loss"] += float(event.get("saved_loss_pct") or 0)
            bucket["opportunity_cost"] += float(event.get("opportunity_cost_pct") or 0)
            bucket["captured_alpha"] += float(event.get("captured_alpha_pct") or 0)
            bucket["false_positive_loss"] += float(event.get("false_positive_loss_pct") or 0)
            bucket["saved_events"] += 1 if event.get("verdict") == "saved_loss" else 0
            bucket["false_alarm_events"] += 1 if event.get("verdict") == "false_alarm" else 0
            bucket["discovery_hits"] += 1 if event.get("verdict") == "hit" and event.get("role") == "discovery" else 0
            bucket["discovery_false_positive"] += 1 if event.get("verdict") == "false_positive" else 0

    out = []
    for bucket in buckets.values():
        n = bucket["n"]
        role = bucket["role"]
        item = {
            "layer": bucket["layer"],
            "label": bucket["label"],
            "role": role,
            "regime": bucket["regime"],
            "n": n,
            "avg_return_pct": _round(bucket["sum_return"] / n),
            "hit_rate_pct": _round(bucket["wins"] / n * 100, 1),
        }
        if role == "risk":
            item.update({
                "saved_loss_pct": _round(bucket["saved_loss"]),
                "opportunity_cost_pct": _round(bucket["opportunity_cost"]),
                "net_saved_pct": _round(bucket["saved_loss"] - bucket["opportunity_cost"]),
                "saved_events": bucket["saved_events"],
                "false_alarm_events": bucket["false_alarm_events"],
            })
        elif role == "discovery":
            item.update({
                "captured_alpha_pct": _round(bucket["captured_alpha"]),
                "false_positive_loss_pct": _round(bucket["false_positive_loss"]),
                "net_discovery_pct": _round(bucket["captured_alpha"] - bucket["false_positive_loss"]),
                "hit_events": bucket["discovery_hits"],
                "false_positive_events": bucket["discovery_false_positive"],
            })
        out.append(item)
    return sorted(out, key=lambda x: (x["role"], x["layer"], x["regime"]))


def _summary(snapshots):
    latest = snapshots[-1] if snapshots else {}
    aggregate = _aggregate(snapshots)
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "tracked_days": len(snapshots),
        "latest_date": latest.get("date"),
        "latest_regime": (latest.get("regime") or {}).get("name"),
        "latest_events": len(latest.get("events", [])),
        "by_layer_regime": aggregate,
        "shadow_comparison": _shadow_comparison(snapshots),
        "role_notes": {
            "return": "Getiri katmanlari forward getiri ve hit-rate ile olculur.",
            "discovery": "Kesif katmanlari yakalanan alpha eksi false-positive kaybi ile olculur.",
            "risk": "Risk katmanlari saved-loss eksi firsat maliyeti ile olculur.",
        },
    }


def _shadow_comparison(snapshots):
    layers = {layer: [] for layer in ("F_shadow", "O_shadow", "O_minus_F")}
    for snap in snapshots:
        for event in snap.get("events", []):
            layer = event.get("layer")
            ret = event.get("return_pct")
            if layer in layers and ret is not None:
                layers[layer].append(float(ret))

    out = {}
    for layer, returns in layers.items():
        if returns:
            out[layer] = {
                "n": len(returns),
                "avg_return_pct": _round(sum(returns) / len(returns)),
                "hit_rate_pct": _round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            }
        else:
            out[layer] = {"n": 0, "avg_return_pct": None, "hit_rate_pct": None}
    f_avg = out["F_shadow"].get("avg_return_pct")
    o_avg = out["O_shadow"].get("avg_return_pct")
    out["O_edge_vs_F_pct"] = _round(o_avg - f_avg) if o_avg is not None and f_avg is not None else None
    out["divergence"] = _divergence_summary(snapshots)
    return out


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _divergence_summary(snapshots):
    periods = []
    for snap in snapshots:
        f_returns = {}
        o_returns = {}
        for event in snap.get("events", []):
            if event.get("layer") == "O_minus_F":
                continue
            ret = event.get("return_pct")
            if ret is None:
                continue
            ticker = event.get("ticker")
            if event.get("layer") == "F_shadow":
                f_returns[ticker] = float(ret)
            elif event.get("layer") == "O_shadow":
                o_returns[ticker] = float(ret)
        if not f_returns and not o_returns:
            continue
        f_set = set(f_returns)
        o_set = set(o_returns)
        union = f_set | o_set
        common = f_set & o_set
        o_only = sorted(o_set - f_set)
        f_only = sorted(f_set - o_set)
        o_avg = _avg(o_returns[t] for t in o_only)
        f_avg = _avg(f_returns[t] for t in f_only)
        edge = (o_avg - f_avg) if o_avg is not None and f_avg is not None else None
        periods.append({
            "date": snap.get("date"),
            "regime": (snap.get("regime") or {}).get("name"),
            "overlap_pct": _round(len(common) / len(union) * 100, 1) if union else None,
            "swap_n": min(len(o_only), len(f_only)),
            "o_only_count": len(o_only),
            "f_only_count": len(f_only),
            "o_only_avg_return_pct": _round(o_avg),
            "f_only_avg_return_pct": _round(f_avg),
            "divergence_edge_pct": _round(edge),
            "swap_hit": bool(edge > 0) if edge is not None else None,
            "o_only": [{"ticker": t, "return_pct": _round(o_returns[t])} for t in o_only],
            "f_only": [{"ticker": t, "return_pct": _round(f_returns[t])} for t in f_only],
        })

    scored = [p for p in periods if p.get("divergence_edge_pct") is not None]
    edges = [p["divergence_edge_pct"] for p in scored]
    o_avgs = [p["o_only_avg_return_pct"] for p in scored]
    f_avgs = [p["f_only_avg_return_pct"] for p in scored]
    overlap = [p["overlap_pct"] for p in periods if p.get("overlap_pct") is not None]
    return {
        "samples": len(scored),
        "avg_overlap_pct": _round(_avg(overlap), 1),
        "avg_swap_n": _round(_avg(p.get("swap_n") for p in periods), 1),
        "o_only_avg_return_pct": _round(_avg(o_avgs)),
        "f_only_avg_return_pct": _round(_avg(f_avgs)),
        "divergence_edge_pct": _round(_avg(edges)),
        "swap_hit_rate_pct": _round(sum(1 for p in scored if p.get("swap_hit")) / len(scored) * 100, 1) if scored else None,
        "latest": periods[-1] if periods else None,
    }


def update(report, data, watchlists=None, path=None, max_snapshots=MAX_SNAPSHOTS,
           shadow_state_dir=None):
    """Update the role-aware ledger and return dashboard-ready summary."""
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    date = _last_date(data)
    date_s = _date_text(date)
    path = Path(path) if path else _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    ledger = _load(path)
    snapshots = ledger.get("snapshots", [])
    current = {
        "date": date_s,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "regime": _market_regime(data, date),
        "source": report.get("source") or data.get("_source"),
        "events": (
            _events_from_report(report, watchlists or report.get("watchlists", {}), date_s) +
            _events_from_shadow(shadow_state_dir or config.STATE_DIR, date_s)
        ),
    }
    existing = next((s for s in snapshots if s.get("date") == date_s), None)
    current = _merge_same_day(existing, current)
    snapshots = [s for s in snapshots if s.get("date") != date_s]
    snapshots.append(current)
    snapshots = snapshots[-max_snapshots:]
    snapshots = _refresh_snapshots(snapshots, data, date)

    summary = _summary(snapshots)
    ledger = {"summary": summary, "snapshots": snapshots}
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary
