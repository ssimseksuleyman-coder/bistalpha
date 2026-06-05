"""
Backtest motoru + performans metrikleri.
Rebalance gününde tüm pozisyonlar satılıp weighted yeniden alınır (düzeltilmiş mantık).
"""
import numpy as np
import pandas as pd
from . import config
from .signals import lot_multiplier
from .strategy import select


def _rebal_dates(prices):
    all_dates = list(prices.index)
    out = []
    i = config.MOM_GUN
    while i < len(all_dates):
        out.append(all_dates[i])
        i += config.REBAL_GUN
    return out


def run(data, signals, mode=None, slippage=0.0, verbose=False):
    """
    Backtest çalıştırır.
    mode: "A"/"B"/"F" (None -> config.MODE)
    slippage: her alım/satımda ek kayma (round-trip = 2x)
    Returns: dict (ret, dd, sharpe, calmar, n_stops, equity_curve)
    """
    mode = mode or config.MODE
    prices = data['prices']
    friction = config.COMMISSION / 2 + slippage
    rebal_dates = _rebal_dates(prices)
    if len(rebal_dates) < 2:
        return None

    positions = {}
    cash = 1.0
    daily = []
    n_stops = 0
    start_idx = prices.index.searchsorted(rebal_dates[0])

    for d_idx in range(start_idx, len(prices.index)):
        today = prices.index[d_idx]

        # 1) STOP KONTROL
        to_close = []
        for tic, pos in list(positions.items()):
            if tic not in prices.columns:
                continue
            pt = prices.loc[today, tic]
            if pd.isna(pt):
                continue
            if pt > pos['peak']:
                pos['peak'] = pt
            gain = pos['peak'] / pos['entry'] - 1
            trail = (config.TRAIL_TIGHT if gain >= 0.30
                     else config.TRAIL_MID if gain >= 0.15
                     else config.TRAIL_WIDE)
            stop = max(pos['entry'] * (1 - config.ABS_STOP_PCT), pos['peak'] * (1 - trail))
            if pt < stop:
                to_close.append((tic, pt))
        for tic, ep in to_close:
            cash += positions[tic]['shares'] * ep * (1 - friction)
            del positions[tic]
            n_stops += 1

        # 2) REBALANCE
        if today in rebal_dates:
            total = cash
            for tic, pos in positions.items():
                p = prices.loc[today, tic] if tic in prices.columns and not pd.isna(prices.loc[today, tic]) else pos['entry']
                total += pos['shares'] * p

            picks, sig_map, _ = select(data, signals, today, mode=mode)

            # Lot ağırlıkları
            if mode in ("B", "F"):
                weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
            else:
                weights = {t: 1.0 for t in picks}
            tw = sum(weights.values())

            # Tüm pozisyonları sat
            for tic, pos in list(positions.items()):
                p = prices.loc[today, tic] if tic in prices.columns and not pd.isna(prices.loc[today, tic]) else pos['entry']
                cash += pos['shares'] * p * (1 - friction)
                del positions[tic]

            # Weighted yeniden al
            if tw > 0:
                for tic in picks:
                    if tic in prices.columns:
                        ep = prices.loc[today, tic]
                        if pd.notna(ep) and ep > 0:
                            alloc = total * (weights[tic] / tw) * (1 - friction)
                            positions[tic] = {'entry': ep, 'peak': ep, 'shares': alloc / ep}
                            cash -= alloc

            if verbose:
                print(f"{today.date()} picks={picks}")

        # 3) GÜN SONU değer
        total = cash
        for tic, pos in positions.items():
            if tic in prices.columns:
                p = prices.loc[today, tic]
                total += pos['shares'] * (p if pd.notna(p) else pos['entry'])
        daily.append(total)

    return _metrics(np.array(daily), n_stops)


def _metrics(v, n_stops):
    ret = (v[-1] - 1) * 100
    peak = np.maximum.accumulate(v)
    dd = ((v - peak) / peak * 100).min()
    dr = np.diff(v) / v[:-1]
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0.0
    return {
        'ret': round(float(ret), 2),
        'dd': round(float(dd), 2),
        'sharpe': round(float(sharpe), 2),
        'calmar': round(float(abs(ret / dd)), 2) if dd != 0 else 0.0,
        'n_stops': int(n_stops),
        'equity_curve': v.tolist(),
    }
