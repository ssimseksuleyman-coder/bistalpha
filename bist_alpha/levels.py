"""
İŞLEV EKSİĞİ — Destek/Direnç seviyeleri (OMEGA'da vardı, pakette yoktu).

İki kaynak:
  1. Pivot-bazlı (klasik): son günün H/L/C'sinden hesaplanır (her zaman çalışır)
  2. Deniz S/R: bültenden gelirse kullanılır (opsiyonel)

Hisse bazlı analiz raporuna eklenir.
"""
import pandas as pd


def pivot_levels(data, ticker, date=None):
    """
    Klasik pivot destek/direnç (son günün max/min/kapanış'ından).
    Returns: dict {pivot, r1, r2, s1, s2}
    """
    prices = data['prices']
    maxs = data['maxs']
    mins = data['mins']
    if ticker not in prices.columns:
        return None
    if date is None:
        date = prices.index[-1]
    idx = prices.index.searchsorted(date)
    h = maxs.iloc[idx][ticker]
    l = mins.iloc[idx][ticker]
    c = prices.iloc[idx][ticker]
    if pd.isna(h) or pd.isna(l) or pd.isna(c):
        return None
    pivot = (h + l + c) / 3
    return {
        "pivot": round(float(pivot), 2),
        "r1": round(float(2 * pivot - l), 2),
        "r2": round(float(pivot + (h - l)), 2),
        "s1": round(float(2 * pivot - h), 2),
        "s2": round(float(pivot - (h - l)), 2),
    }


def position_in_range(data, ticker, date=None):
    """
    Fiyat destek-direnç bandının neresinde? (0=destekte, 1=dirençte)
    Basit yorumlama için.
    """
    lv = pivot_levels(data, ticker, date)
    if not lv:
        return None
    prices = data['prices']
    if date is None:
        date = prices.index[-1]
    idx = prices.index.searchsorted(date)
    c = prices.iloc[idx][ticker]
    if pd.isna(c):
        return None
    lo, hi = lv["s2"], lv["r2"]
    if hi <= lo:
        return None
    return round(float((c - lo) / (hi - lo)), 2)


def close_window_liquidity_ok(data, ticker, position_tl, date=None,
                              close_fraction=0.15, max_participation=0.10):
    """
    TESPİT 2 — Kapanış/TWAP penceresinde likidite sıkışması kontrolü.

    Kapanış seansı tipik günlük hacmin ~%15'i. Pozisyon, kapanış penceresi
    hacminin max_participation'ından (%10) büyükse sıkışma riski (kademe çizme).

    Returns: dict {ok, daily_tl, close_window_tl, max_safe_tl, warning}
    """
    prices = data['prices']
    volumes = data['volumes']
    if ticker not in prices.columns:
        return None
    if date is None:
        date = prices.index[-1]
    idx = prices.index.searchsorted(date)
    win = slice(max(0, idx - 20), idx + 1)
    avg_price = prices.iloc[win][ticker].mean()
    avg_vol = volumes.iloc[win][ticker].mean()
    if pd.isna(avg_price) or pd.isna(avg_vol) or avg_vol <= 0:
        return {"ok": True, "warning": "hacim verisi yok"}
    daily_tl = float(avg_price * avg_vol)
    close_window_tl = daily_tl * close_fraction
    max_safe_tl = close_window_tl * max_participation
    ok = position_tl <= max_safe_tl
    return {
        "ok": ok,
        "daily_tl": round(daily_tl, 0),
        "close_window_tl": round(close_window_tl, 0),
        "max_safe_tl": round(max_safe_tl, 0),
        "warning": None if ok else f"Pozisyon kapanış likiditesini aşıyor (max ~{max_safe_tl/1e6:.1f}mn TL)",
    }
