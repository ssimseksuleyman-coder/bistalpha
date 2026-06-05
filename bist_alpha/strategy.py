"""
Strateji / seçim modülü.
v1.2 skorlama + evren filtresi + sektör cap + (mode'a göre) koşullu vize.

Opsiyonel forensik filtreler (Day 30 bulguları — VARSAYILAN KAPALI):
  - LATE_ENTRY_FILTER : son 5g >%X yükselenleri atla (bizim veride zararlı)
  - SIDEWAYS_SCALING  : yatay piyasada pozisyonu küçült (risk azaltma)
Bunlar tek tek shadow'da test edilmeden açılmamalı.
"""
import pandas as pd
from . import config
from .sectors import get_sector
from .signals import signal_for


def last_n_return(data, date, ticker, n):
    """Hissenin son n günlük getirisi (%)."""
    prices = data['prices']
    idx = prices.index.searchsorted(date)
    if idx - n < 0:
        return None
    p_now = prices.iloc[idx][ticker]
    p_then = prices.iloc[idx - n][ticker]
    if pd.isna(p_now) or pd.isna(p_then) or p_then <= 0:
        return None
    return (p_now / p_then - 1) * 100


def regime_scale(data, date):
    """
    Day 30 Bulgu 2 — rejim tespiti. Yatay piyasada pozisyon ölçeği döner.
    KAPALIysa 1.0 döner. Açıksa sideways'te SIDEWAYS_SCALE.
    """
    if not getattr(config, "SIDEWAYS_SCALING", False):
        return 1.0
    bist = data.get('bist')
    if bist is None or len(bist) < 6:
        return 1.0
    bi = bist.index.searchsorted(date)
    if bi < 5:
        return 1.0
    xu5 = (bist.iloc[bi] / bist.iloc[bi - 5] - 1) * 100
    if abs(xu5) < getattr(config, "SIDEWAYS_THRESHOLD", 1.0):
        return getattr(config, "SIDEWAYS_SCALE", 0.5)
    return 1.0


def pump_pattern(data, date, ticker, days=3, daily_thr=3.0):
    """
    Day 30 Bulgu 3 — pump pattern. Son `days` gün üst üste her biri
    >%daily_thr ise True (aşırı ısınmış, 4. günde alma).
    """
    prices = data['prices']
    idx = prices.index.searchsorted(date)
    if idx < days:
        return False
    for k in range(days):
        p1 = prices.iloc[idx - k][ticker]
        p0 = prices.iloc[idx - k - 1][ticker]
        if pd.isna(p1) or pd.isna(p0) or p0 <= 0:
            return False
        if (p1 / p0 - 1) * 100 < daily_thr:
            return False
    return True


def score(data, date):
    """Verilen tarihte tüm geçerli hisselerin skorunu ve M252'sini döner."""
    prices = data['prices']
    idx = prices.index.searchsorted(date)
    if idx < config.MOM_GUN:
        return None, None
    p_now = prices.iloc[idx]
    p_mom = prices.iloc[max(0, idx - config.MOM_GUN)]
    p_30 = prices.iloc[max(0, idx - config.RS_GUN_30)]
    p_5 = prices.iloc[max(0, idx - config.RS_GUN_5)]
    valid = (p_now > 0) & (p_mom > 0) & (p_30 > 0) & (p_5 > 0) & p_now.notna() & p_mom.notna()
    m252 = (p_now / p_mom - 1) * 100
    rs30 = (p_now / p_30 - 1) * 100
    rs5 = (p_now / p_5 - 1) * 100
    s = (config.W_M252 * m252 + config.W_RS30 * rs30 + config.W_RS5 * rs5)[valid].dropna()
    return s, m252[valid]


def select(data, signals, date, mode=None):
    """
    Verilen tarihte pick listesini döner.
    mode: "A"/"B" normal cap=2; "F" koşullu vize ile 3. hisse istisnası.
    Returns: (selected_list, signal_dict, exceptions_list)
    """
    mode = mode or config.MODE
    s, m252 = score(data, date)
    if s is None:
        return [], {}, []

    if data.get('_dynamic_universe'):
        universe = set(data['_dynamic_universe'])
    else:
        mcaps = data['mcaps']
        mc = mcaps.loc[date].dropna() if date in mcaps.index else pd.Series(dtype=float)
        if len(mc) < 50:
            return [], {}, []
        universe = set(mc.nlargest(config.UNIVERSE_SIZE).index.tolist())
    s = s[s.index.isin(universe)]
    valid_dual = m252[m252 > config.DUAL_THRESHOLD].index.tolist()
    s = s[s.index.isin(valid_dual)]

    ranked = s.sort_values(ascending=False)
    selected, sektor_sayisi, sig_map, exceptions = [], {}, {}, []

    # Day 30 Bulgu 1 — geç giriş filtresi (VARSAYILAN KAPALI)
    late_on = getattr(config, "LATE_ENTRY_FILTER", False)
    late_thr = getattr(config, "LATE_ENTRY_THRESHOLD", 20.0)
    # Day 30 Bulgu 3 — pump veto (VARSAYILAN KAPALI)
    pump_on = getattr(config, "SECTOR_PUMP_VETO", False)

    for tic in ranked.index:
        if late_on:
            r5 = last_n_return(data, date, tic, 5)
            if r5 is not None and r5 > late_thr:
                continue  # tepe yakını — atla
        if pump_on and pump_pattern(data, date, tic):
            continue  # aşırı ısınmış — atla
        sec = get_sector(tic)
        sig = signal_for(signals, date, tic)
        sig_map[tic] = sig

        if sektor_sayisi.get(sec, 0) >= config.SEKTOR_CAP:
            # Cap dolu — F modunda koşullu vize
            if mode == "F" and sektor_sayisi.get(sec, 0) == config.SEKTOR_CAP \
                    and sig == "GÜÇLÜ_BİRİKİM":
                selected.append(tic)
                sektor_sayisi[sec] += 1
                exceptions.append(tic)
                if len(selected) >= config.TOP_N:
                    break
            continue

        selected.append(tic)
        sektor_sayisi[sec] = sektor_sayisi.get(sec, 0) + 1
        if len(selected) >= config.TOP_N:
            break

    return selected, sig_map, exceptions
