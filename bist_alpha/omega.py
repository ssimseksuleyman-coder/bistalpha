"""
OMEGA shadow selector.

This module is deliberately additive: it does not change the production F
engine. The O account uses the same shadow execution path as A/B/F, while its
selection score blends F's proven momentum score with measured radar signals.
"""
from __future__ import annotations

import pandas as pd

from . import config
from .sectors import get_sector
from .signals import signal_for, lot_multiplier
from .strategy import last_n_return, score


def _round(value, digits=2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _trade_universe(data, date):
    if data.get("_dynamic_universe"):
        return set(data["_dynamic_universe"])
    mcaps = data.get("mcaps")
    if date is not None and mcaps is not None and not mcaps.empty and date in mcaps.index:
        mc = mcaps.loc[date].dropna()
        if len(mc) >= config.UNIVERSE_SIZE:
            return set(mc.nlargest(config.UNIVERSE_SIZE).index.tolist())
    prices = data.get("prices")
    return set(prices.columns) if prices is not None else set()


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
    return float(v5 / v20)


def _near_high(data, date, ticker):
    prices = data.get("prices")
    if prices is None or ticker not in prices.columns:
        return False
    idx = prices.index.searchsorted(date)
    if idx < 0:
        return False
    current = prices.iloc[idx][ticker]
    window = prices.iloc[max(0, idx - config.MOM_GUN + 1):idx + 1][ticker].dropna()
    if pd.isna(current) or current <= 0 or window.empty:
        return False
    high = window.max()
    return bool(high > 0 and (float(current) / float(high) - 1) * 100 >= -2)


def _candidate_frame(data, date):
    base_score, m252 = score(data, date)
    if base_score is None or m252 is None:
        return pd.DataFrame()
    universe = _trade_universe(data, date)
    rows = []
    for ticker in sorted(universe):
        if ticker not in base_score.index:
            continue
        m1y = m252.get(ticker)
        m1a = last_n_return(data, date, ticker, config.RS_GUN_30)
        m1h = last_n_return(data, date, ticker, config.RS_GUN_5)
        if m1y is None or m1a is None or m1h is None or pd.isna(m1y) or pd.isna(m1a) or pd.isna(m1h):
            continue
        rows.append({
            "ticker": ticker,
            "base_score": float(base_score[ticker]),
            "m252": float(m1y),
            "m21": float(m1a),
            "m5": float(m1h),
        })
    df = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
    if df.empty:
        return df
    df["rank_1y"] = df["m252"].rank(ascending=False, method="min")
    df["rank_1a"] = df["m21"].rank(ascending=False, method="min")
    df["rank_1h"] = df["m5"].rank(ascending=False, method="min")
    df["acceleration"] = df["rank_1y"] - df[["rank_1a", "rank_1h"]].min(axis=1)
    return df


def _omega_score(data, signals, date, ticker, row):
    sig = signal_for(signals, date, ticker)
    vr = _volume_ratio(data, date, ticker)

    transform = (
        row["m21"] >= 8 and row["m5"] >= 0 and row["acceleration"] >= 25 and
        (row["rank_1a"] <= 45 or row["rank_1h"] <= 45)
    )
    quiet = (
        sig in ("GÜÇLÜ_BİRİKİM", "Birikim") and vr is not None and vr >= 1.15 and
        -10 <= row["m21"] <= 35 and -5 <= row["m5"] <= 18
    )
    slowing = row["rank_1y"] <= 30 and row["rank_1h"] >= row["rank_1y"] + 15
    distribution = sig in ("DAĞITIM", "Üst_fitil_UYARI", "Üst_fitil_dağıtım")

    layer_bonus = 0.0
    reasons = []
    if transform:
        layer_bonus += min(35.0, row["acceleration"] * 0.45)
        layer_bonus += max(0.0, 20.0 - row["rank_1a"] * 0.25)
        reasons.append("donusum")
    if quiet:
        layer_bonus += min(28.0, (vr or 0) * 8.0)
        layer_bonus += {"GÜÇLÜ_BİRİKİM": 14.0, "Birikim": 8.0}.get(sig, 0.0)
        reasons.append("sessiz_birikim")

    risk_penalty = 0.0
    if _near_high(data, date, ticker):
        risk_penalty += 12.0
        reasons.append("zirve_yakini")
    if slowing:
        risk_penalty += 10.0
        reasons.append("ivme_yavasliyor")
    if distribution:
        risk_penalty += 8.0
        reasons.append("risk_sinyali")

    eligible = row["m252"] > config.DUAL_THRESHOLD or transform or quiet
    total = row["base_score"] + layer_bonus - risk_penalty
    return {
        "score": float(total),
        "signal": sig,
        "volume_ratio": _round(vr, 2),
        "reasons": reasons or ["f_taban"],
        "eligible": bool(eligible),
    }


def select(data, signals, date, top_n=None):
    """Return OMEGA shadow picks with diagnostics."""
    top_n = top_n or config.TOP_N
    df = _candidate_frame(data, date)
    if df.empty:
        return [], {}, []

    rows = []
    for ticker, row in df.iterrows():
        details = _omega_score(data, signals, date, ticker, row)
        if not details["eligible"]:
            continue
        rows.append({
            "ticker": ticker,
            "sector": get_sector(ticker),
            **details,
        })
    ranked = sorted(rows, key=lambda item: (-item["score"], item["ticker"]))

    selected = []
    sig_map = {}
    diagnostics = []
    sector_counts = {}
    for item in ranked:
        sector = item["sector"]
        if sector_counts.get(sector, 0) >= config.SEKTOR_CAP:
            diagnostics.append({**item, "status": "sector_cap_skip"})
            continue
        ticker = item["ticker"]
        selected.append(ticker)
        sig_map[ticker] = item["signal"]
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        diagnostics.append({**item, "status": "selected"})
        if len(selected) >= top_n:
            break
    return selected, sig_map, diagnostics


def weights(picks, sig_map):
    """O uses the same smart-money lot multipliers as B/F."""
    return {ticker: lot_multiplier(sig_map.get(ticker, "Nötr")) for ticker in picks}
