#!/usr/bin/env python3
"""
BIST Alpha v1.2 — Ana çalıştırma scripti.

Kullanım:
    python run_backtest.py                    # config.MODE ile çalıştır
    python run_backtest.py --mode F           # belirli mod
    python run_backtest.py --compare          # A/B/F karşılaştır
    python run_backtest.py --slippage 0.004   # slippage cezası ekle
    python run_backtest.py --picks            # son rebalance pick'lerini göster
"""
import argparse
import sys
from bist_alpha import data as data_mod
from bist_alpha import signals as sig_mod
from bist_alpha import strategy as strat_mod
from bist_alpha import backtest as bt_mod
from bist_alpha import config


def _configure_console():
    """Windows cp1252 konsolda Turkce cikti UnicodeEncodeError vermesin."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main():
    _configure_console()
    ap = argparse.ArgumentParser(description="BIST Alpha v1.2 backtest")
    ap.add_argument("--data", default=config.DATA_PATH, help="Excel veri yolu")
    ap.add_argument("--mode", default=config.MODE, choices=["A", "B", "F"])
    ap.add_argument("--slippage", type=float, default=0.0, help="Her yönde ek kayma (ör 0.004)")
    ap.add_argument("--compare", action="store_true", help="A/B/F karşılaştır")
    ap.add_argument("--picks", action="store_true", help="Son rebalance pick'lerini göster")
    args = ap.parse_args()

    print("Veri yükleniyor...")
    data = data_mod.load_data(path=args.data)
    print(f"  {data['prices'].shape[1]} hisse x {data['prices'].shape[0]} gün")

    print("Sinyaller hesaplanıyor...")
    signals = sig_mod.compute_signals(data)

    if args.picks:
        # Son rebalance tarihinde pick'ler
        rebal = bt_mod._rebal_dates(data['prices'])
        last = rebal[-1]
        picks, sig_map, exc = strat_mod.select(data, signals, last, mode=args.mode)
        print(f"\nSon rebalance ({last.date()}) — mode={args.mode}:")
        for t in picks:
            mark = " [VİZE]" if t in exc else ""
            print(f"  {t:8s} {sig_map.get(t,''):16s}{mark}")
        return

    if args.compare:
        print(f"\n{'Mode':6s} {'Getiri':>9s} {'MaxDD':>8s} {'Sharpe':>7s} {'Calmar_y':>8s} {'Stop':>5s}")
        print("-" * 50)
        for m in ["A", "B", "F"]:
            r = bt_mod.run(data, signals, mode=m, slippage=args.slippage)
            print(f"{m:6s} %{r['ret']:>7.1f} %{r['dd']:>6.2f} {r['sharpe']:>6.2f} {r['calmar_annual']:>7.2f} {r['n_stops']:>5d}")
        return

    r = bt_mod.run(data, signals, mode=args.mode, slippage=args.slippage)
    print(f"\n=== SONUÇ (mode={args.mode}, slippage={args.slippage*100:.2f}%) ===")
    print(f"  Getiri : %{r['ret']}")
    print(f"  Max DD : %{r['dd']}")
    print(f"  Sharpe : {r['sharpe']}")
    print(f"  Calmar : {r['calmar_annual']}  (YILLIK getiri/DD — karar metrigi)")
    print(f"           {r['calmar_total']}  (toplam/DD — eski formul, {r['years']} yillik backtest)")
    print(f"  Stop # : {r['n_stops']}")


if __name__ == "__main__":
    sys.exit(main())
