"""Canonical market regime classification shared by reports and ledgers."""
from __future__ import annotations

import pandas as pd


def _round(value, digits=1):
    if value is None or pd.isna(value):
        return None
    rounded = round(float(value), digits)
    return 0.0 if rounded == 0 else rounded


def classify(data, date):
    """Classify the BIST index using one shared 5/21-session definition."""
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
    return {"name": name, "xu5": _round(xu5), "xu21": _round(xu21)}
