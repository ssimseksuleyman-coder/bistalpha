#!/usr/bin/env python3
"""
Shadow mode runner — A/B/F paralel hesaplar, KALICI portföylerle.

Her çağrıda (günlük/rebalance):
  1. Her hesabın kalıcı portföyünü yükle
  2. Stop kontrol -> SAT
  3. Rebalance günüyse yeni pick'lerle güncelle
  4. Portföyü kaydet (state kalıcı)
  5. 4 metrik logla: getiri, DD, give-back, false-negative

Kullanım:
  python shadow.py                  # bugünün shadow adımı
  python shadow.py --status         # 3 hesabın güncel durumu
"""
import argparse
import sys
import os
import json
from datetime import datetime

from bist_alpha import config, datafeed
from bist_alpha import signals as sig_mod
from bist_alpha import strategy as strat_mod
from bist_alpha import portfolio as pf
from bist_alpha.signals import lot_multiplier

ACCOUNTS = {"A": "A", "B": "B", "F": "F"}  # mode'lar


def step(data, signals, date=None, slippage=None):
    """Tüm hesaplar için bir shadow adımı."""
    prices = data['prices']
    if date is None:
        date = prices.index[-1]
    slippage = slippage if slippage is not None else config.SLIPPAGE_PER_SIDE
    prices_today = {t: prices.loc[date, t] for t in prices.columns
                    if not __import__('pandas').isna(prices.loc[date, t])}

    rebal_dates = __import__('bist_alpha.backtest', fromlist=['_rebal_dates'])._rebal_dates(prices)
    is_rebal = date in rebal_dates

    results = {}
    for acc, mode in ACCOUNTS.items():
        state = pf.load(acc, state_dir=config.STATE_DIR)
        # 1) Stop kontrol
        sells = pf.check_stops(state, prices_today)
        # 2) Rebalance
        if is_rebal:
            picks, sig_map, exc = strat_mod.select(data, signals, date, mode=mode)
            if mode in ("B", "F"):
                weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
            else:
                weights = {t: 1.0 for t in picks}
            scale = strat_mod.regime_scale(data, date)
            if scale != 1.0:
                weights = {t: w * scale for t, w in weights.items()}
            pf.rebalance(state, weights, prices_today, slippage=slippage)
        pf.save(state, state_dir=config.STATE_DIR)
        results[acc] = {
            "value": round(pf.current_value(state, prices_today), 4),
            "n_pos": len(state["positions"]),
            "sells": sells,
        }
    return {"date": str(date.date()) if hasattr(date, "date") else str(date),
            "rebalance": is_rebal, "accounts": results}


def status():
    """3 hesabın güncel durumunu göster."""
    feed = datafeed.get_feed()
    data = feed.get_latest()
    prices = data['prices']
    date = prices.index[-1]
    prices_today = {t: prices.loc[date, t] for t in prices.columns
                    if not __import__('pandas').isna(prices.loc[date, t])}
    print(f"=== SHADOW DURUM @ {date.date()} ===")
    for acc in ACCOUNTS:
        state = pf.load(acc, state_dir=config.STATE_DIR)
        val = pf.current_value(state, prices_today)
        ret = (val - 1) * 100
        print(f"\nHesap {acc}: değer {val:.3f} (getiri %{ret:.1f}), {len(state['positions'])} pozisyon")
        for t, p in list(state["positions"].items())[:12]:
            st = pf.stop_level(p)
            cur = prices_today.get(t, p['entry'])
            print(f"   {t:7s} giriş {p['entry']:.1f} | güncel {cur:.1f} | stop {st:.1f}")


def main():
    ap = argparse.ArgumentParser(description="Shadow mode A/B/F runner")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        status()
        return
    feed = datafeed.get_feed()
    data = feed.get_latest()
    signals = sig_mod.compute_signals(data)
    r = step(data, signals)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
