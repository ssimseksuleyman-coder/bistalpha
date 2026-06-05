#!/usr/bin/env python3
"""
EKSİK #4 — İstenildiği zaman hisse bazlı analiz (on-demand).

Kullanım:
  python analyze_stock.py TERA            # tek hisse
  python analyze_stock.py TERA ASELS KTLEV  # çoklu
  python analyze_stock.py --report        # anlık tam rapor (top10 + fırsat)
"""
import argparse
import json
import sys
from bist_alpha import datafeed, config
from bist_alpha import signals as sig_mod
from bist_alpha import reporter


def main():
    ap = argparse.ArgumentParser(description="Hisse bazlı on-demand analiz")
    ap.add_argument("tickers", nargs="*", help="Hisse kodları")
    ap.add_argument("--report", action="store_true", help="Anlık tam rapor")
    ap.add_argument("--json", action="store_true", help="JSON çıktı")
    args = ap.parse_args()

    feed = datafeed.get_feed()
    data = feed.get_latest()
    signals = sig_mod.compute_signals(data)

    if args.report:
        rep = reporter.generate_report(data, signals, mode=config.MODE)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            print(reporter.format_text(rep))
        return

    if not args.tickers:
        print("Hisse kodu ver: python analyze_stock.py TERA")
        return

    for t in args.tickers:
        a = reporter.analyze_stock(data, signals, t.upper())
        if args.json:
            print(json.dumps(a, ensure_ascii=False, indent=2))
        else:
            if "error" in a:
                print(f"\n{t}: {a['error']}")
                continue
            print(f"\n=== {a['ticker']} ({a['sector']}) — {a['date']} ===")
            print(f"  Fiyat       : {a['fiyat']}")
            print(f"  Getiri      : 5g %{a['getiri']['5g']} | 30g %{a['getiri']['30g']} | 252g %{a['getiri']['252g']}")
            print(f"  Skor        : {a['skor']}  (evrende: {a['evrende_mi']})")
            print(f"  SM sinyal   : {a['sm_signal']}")
            print(f"  CPR/Acc/Wick: {a['cpr']} / {a['acc_ratio']} / {a['upper_wick']}")
            lv = a.get('destek_direnc')
            if lv:
                print(f"  Direnç      : R1 {lv['r1']} | R2 {lv['r2']}")
                print(f"  Pivot       : {lv['pivot']}")
                print(f"  Destek      : S1 {lv['s1']} | S2 {lv['s2']}")
                if a.get('banttaki_yeri') is not None:
                    print(f"  Banttaki yer: {a['banttaki_yeri']} (0=destek, 1=direnç)")


if __name__ == "__main__":
    sys.exit(main())
