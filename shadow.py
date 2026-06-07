#!/usr/bin/env python3
"""
Shadow mode runner — A/B/F/O paralel hesaplar, KALICI portföylerle.

Her çağrıda (günlük/rebalance):
  1. Her hesabın kalıcı portföyünü yükle
  2. Stop kontrol -> SAT
  3. Rebalance günüyse yeni pick'lerle güncelle
  4. Portföyü kaydet (state kalıcı)
  5. 4 metrik logla: getiri, DD, give-back, false-negative

Kullanım:
  python shadow.py                  # bugünün shadow adımı
  python shadow.py --status         # hesapların güncel durumu
"""
import argparse
import sys
import os
import json
from datetime import datetime

from bist_alpha import config, datafeed
from bist_alpha import notifier
from bist_alpha import signals as sig_mod
from bist_alpha import strategy as strat_mod
from bist_alpha import omega as omega_mod
from bist_alpha import portfolio as pf
from bist_alpha.signals import lot_multiplier

ACCOUNTS = {"A": "A", "B": "B", "F": "F", "O": "O"}  # mode'lar


def _attach_dynamic_universe(feed, data):
    """Stratejinin canlı feed'in seçtiği dinamik evreni kullanmasını sağlar."""
    universe = feed.dynamic_universe(data)
    data['_dynamic_universe'] = universe
    data['_dynamic_universe_method'] = (
        'likidite_fiyat_x_hacim'
        if data.get('_source') in ('yahoo', 'borsapy')
        else 'piyasa_degeri'
    )
    print(f"[shadow] Kaynak: {data.get('_source', config.DATA_SOURCE)}")
    print(f"[shadow] Dinamik evren: {len(universe)}")
    return data


def _format_trade_notice(result):
    """Sadece gerçekleşen shadow işlemleri için kısa bildirim metni üretir."""
    lines = []
    for acc, info in result.get("accounts", {}).items():
        event = info.get("last_event") or {}
        trades = info.get("new_trades") or []
        if not trades:
            continue
        lines.append(f"Hesap {acc} | {event.get('event', 'islem')} | değer {info.get('value')} | pozisyon {info.get('n_pos')}")
        for tr in trades[:12]:
            extra = f" | P/L %{tr['pnl_pct']}" if tr.get("pnl_pct") is not None else ""
            lines.append(f"  {tr.get('type')} {tr.get('ticker')} @ {tr.get('price')}{extra}")
        if len(trades) > 12:
            lines.append(f"  ... {len(trades) - 12} işlem daha")
    if not lines:
        return None
    return f"Tarih: {result.get('date')}\n\n" + "\n".join(lines)


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
    trade_date = str(date.date()) if hasattr(date, "date") else str(date)

    results = {}
    for acc, mode in ACCOUNTS.items():
        state = pf.load(acc, state_dir=config.STATE_DIR)
        # 1) Stop kontrol
        sells = pf.check_stops(state, prices_today)
        stop_trades = pf.close_positions(state, sells, prices_today,
                                         slippage=slippage, trade_date=trade_date)
        new_trades = list(stop_trades)
        # 2) Rebalance
        initial_entry = not state.get("positions") and not state.get("history")
        should_rebalance = is_rebal or initial_entry
        if should_rebalance:
            if mode == "O":
                picks, sig_map, exc = omega_mod.select(data, signals, date)
                weights = omega_mod.weights(picks, sig_map)
            else:
                picks, sig_map, exc = strat_mod.select(data, signals, date, mode=mode)
                if mode in ("B", "F"):
                    weights = {t: lot_multiplier(sig_map.get(t, "Nötr")) for t in picks}
                else:
                    weights = {t: 1.0 for t in picks}
            scale = strat_mod.regime_scale(data, date)
            if scale != 1.0:
                weights = {t: w * scale for t, w in weights.items()}
            reason = "initial_entry" if initial_entry else "rebalance"
            pf.rebalance(state, weights, prices_today, slippage=slippage,
                         trade_date=trade_date, reason=reason)
            new_trades.extend((state.get("history", [])[-1] or {}).get("trades", []))
        pf.save(state, state_dir=config.STATE_DIR)
        results[acc] = {
            "value": round(pf.current_value(state, prices_today), 4),
            "n_pos": len(state["positions"]),
            "sells": sells,
            "stop_trades": stop_trades,
            "rebalance": should_rebalance,
            "initial_entry": initial_entry,
            "new_trades": new_trades,
            "last_event": state.get("history", [])[-1] if state.get("history") else None,
        }
    return {"date": str(date.date()) if hasattr(date, "date") else str(date),
            "rebalance": is_rebal, "accounts": results}


def status():
    """Hesapların güncel durumunu göster."""
    feed = datafeed.get_feed()
    data = feed.get_latest()
    data = _attach_dynamic_universe(feed, data)
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
    ap = argparse.ArgumentParser(description="Shadow mode A/B/F/O runner")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        status()
        return
    feed = datafeed.get_feed()
    data = feed.get_latest()
    data = _attach_dynamic_universe(feed, data)
    signals = sig_mod.compute_signals(data)
    r = step(data, signals)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    notice = _format_trade_notice(r)
    if notice:
        notifier.notify_all("📌 BIST Alpha Shadow İşlem", notice)


if __name__ == "__main__":
    sys.exit(main())
