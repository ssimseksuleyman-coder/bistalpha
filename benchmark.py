#!/usr/bin/env python3
"""
BIST Alpha — Performans Karşılaştırma Benchmarkı

Mevcut F-mode baseline'ı şu senaryolarla karşılaştırır:
  1. Baseline F (şu anki sistem)
  2. F + Spike filtresi (son 5g >%20 çıkanı atla)
  3. F + Sideways ölçekleme (yatay piyasada 0.5× pozisyon)
  4. F + Spike + Sideways (kombinasyon)
  5. F + Düşük slippage (iyimser senaryo)
  6. F + Yüksek slippage (gerçekçi senaryo)

Kullanım:
  python benchmark.py               # varsayılan (Excel veri)
  python benchmark.py --slippage    # ek slippage senaryoları da ekle
  python benchmark.py --chart       # matplotlib equity curve çiz
"""
import argparse
import time
import sys
import copy

from bist_alpha import data as data_mod
from bist_alpha import signals as sig_mod
from bist_alpha import backtest as bt_mod
from bist_alpha import config


# ──────────────────────────────────────────────
# Config override yardımcısı
# ──────────────────────────────────────────────
def _patch(cfg_module, **kwargs):
    """Config modülündeki değerleri geçici olarak değiştir, eski değerleri döndür."""
    old = {}
    for k, v in kwargs.items():
        old[k] = getattr(cfg_module, k, None)
        setattr(cfg_module, k, v)
    return old

def _restore(cfg_module, old):
    for k, v in old.items():
        setattr(cfg_module, k, v)


def run_scenario(data, signals, label, mode="F", slippage=0.0, **cfg_overrides):
    """Tek bir senaryo çalıştır, süreyle birlikte döndür."""
    old = _patch(config, **cfg_overrides)
    t0 = time.time()
    r = bt_mod.run(data, signals, mode=mode, slippage=slippage)
    elapsed = time.time() - t0
    _restore(config, old)
    r["label"] = label
    r["elapsed"] = elapsed
    return r


# ──────────────────────────────────────────────
# Tablo yazdırıcı
# ──────────────────────────────────────────────
COLS = [
    ("Senaryo",       "label",   "<34", ""),
    ("Getiri %",      "ret",     ">9",  "%"),
    ("Max DD %",      "dd",      ">9",  "%"),
    ("Sharpe",        "sharpe",  ">8",  ""),
    ("Calmar_y",      "calmar_annual", ">8", ""),
    ("Stop #",        "n_stops", ">7",  ""),
    ("Süre(s)",       "elapsed", ">8",  ""),
]

def _fmt(v, suffix):
    if isinstance(v, float):
        return f"{v:.2f}{suffix}"
    return f"{v}{suffix}"

def print_table(results, baseline_ret):
    hdr = "  ".join(f"{col:{fmt}}" for col, _, fmt, _ in COLS)
    print("\n" + "=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        row = "  ".join(
            f"{_fmt(r.get(key, ''), suf):{fmt}}"
            for _, key, fmt, suf in COLS
        )
        delta = r["ret"] - baseline_ret
        arrow = f"  ({'↑' if delta >= 0 else '↓'}{abs(delta):.1f}pp)" if r["label"] != results[0]["label"] else ""
        print(row + arrow)
    print("=" * len(hdr))


# ──────────────────────────────────────────────
# Equity eğrisi çizici
# ──────────────────────────────────────────────
def plot_curves(results, prices_index):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("\n[benchmark] matplotlib kurulu değil — 'pip install matplotlib'")
        return

    start_idx = len(prices_index) - len(results[0]["equity_curve"])
    dates = prices_index[start_idx:]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

    for i, r in enumerate(results):
        eq = r["equity_curve"]
        label = f"{r['label']} %{r['ret']:.1f}"
        ax1.plot(dates, eq, label=label, linewidth=1.8, color=colors[i % len(colors)])

    ax1.set_ylabel("Portföy Değeri (başlangıç=1.0)")
    ax1.set_title("BIST Alpha — Senaryo Karşılaştırması")
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)

    # Drawdown — sadece baseline ve en iyi senaryo
    for i, r in enumerate([results[0], max(results[1:], key=lambda x: x["ret"])]):
        eq = r["equity_curve"]
        import numpy as np
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100
        ax2.fill_between(dates, dd, alpha=0.3, color=colors[i if i == 0 else results.index(r)],
                         label=r["label"])

    ax2.set_ylabel("Drawdown %")
    ax2.set_xlabel("Tarih")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

    plt.tight_layout()
    out = "benchmark_result.png"
    plt.savefig(out, dpi=150)
    print(f"\n[benchmark] Grafik kaydedildi: {out}")
    plt.show()


# ──────────────────────────────────────────────
# Ana fonksiyon
# ──────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="BIST Alpha Performans Benchmarkı")
    ap.add_argument("--data", default=config.DATA_PATH)
    ap.add_argument("--slippage", action="store_true", help="Slippage senaryolarını da ekle")
    ap.add_argument("--chart", action="store_true", help="Equity curve grafiği çiz")
    ap.add_argument("--mode", default="F", choices=["A", "B", "F"], help="Test edilecek mod")
    args = ap.parse_args()

    print("=" * 60)
    print("  BIST Alpha — Performans Karşılaştırma Benchmarkı")
    print("=" * 60)
    print(f"\nVeri yükleniyor: {args.data}")
    data = data_mod.load_data(path=args.data)
    prices = data["prices"]
    print(f"  {prices.shape[1]} hisse × {prices.shape[0]} gün "
          f"({prices.index[0].date()} → {prices.index[-1].date()})")

    print("Sinyaller hesaplanıyor...")
    signals = sig_mod.compute_signals(data)

    base_slip = 0.0  # backtest.run slippage ayrı tutuluyor, commission config'de
    scenarios = []

    # ── 1. Baseline ──────────────────────────────────────
    print("\nSenaryolar çalıştırılıyor...")
    print("  [1/6] Baseline F...")
    s = run_scenario(data, signals, "Baseline F (mevcut)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=False, SIDEWAYS_SCALING=False, SECTOR_PUMP_VETO=False)
    scenarios.append(s)
    baseline_ret = s["ret"]

    # ── 2. Spike filtresi ─────────────────────────────────
    print("  [2/6] F + Spike filtresi (son5g>%20)...")
    s = run_scenario(data, signals, "F + Spike filtresi (5g>20%)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=True, LATE_ENTRY_THRESHOLD=20.0,
                     SIDEWAYS_SCALING=False, SECTOR_PUMP_VETO=False)
    scenarios.append(s)

    # ── 3. Sideways ölçekleme ─────────────────────────────
    print("  [3/6] F + Sideways ölçekleme (0.5×)...")
    s = run_scenario(data, signals, "F + Sideways ölçekleme (0.5×)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=False,
                     SIDEWAYS_SCALING=True, SIDEWAYS_THRESHOLD=1.0, SIDEWAYS_SCALE=0.5,
                     SECTOR_PUMP_VETO=False)
    scenarios.append(s)

    # ── 4. Kombinasyon ────────────────────────────────────
    print("  [4/6] F + Spike + Sideways (kombinasyon)...")
    s = run_scenario(data, signals, "F + Spike + Sideways (kombo)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=True, LATE_ENTRY_THRESHOLD=20.0,
                     SIDEWAYS_SCALING=True, SIDEWAYS_THRESHOLD=1.0, SIDEWAYS_SCALE=0.5,
                     SECTOR_PUMP_VETO=False)
    scenarios.append(s)

    # ── 5. Pump veto ──────────────────────────────────────
    print("  [5/6] F + Pump veto (3g üst üste >%3)...")
    s = run_scenario(data, signals, "F + Pump veto (3g>3%)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=False, SIDEWAYS_SCALING=False,
                     SECTOR_PUMP_VETO=True)
    scenarios.append(s)

    # ── 6. Agresif spike eşiği ────────────────────────────
    print("  [6/6] F + Spike filtresi (%15 eşiği)...")
    s = run_scenario(data, signals, "F + Spike filtresi (5g>15%)",
                     mode=args.mode, slippage=base_slip,
                     LATE_ENTRY_FILTER=True, LATE_ENTRY_THRESHOLD=15.0,
                     SIDEWAYS_SCALING=False, SECTOR_PUMP_VETO=False)
    scenarios.append(s)

    # ── Slippage senaryoları (opsiyonel) ──────────────────
    if args.slippage:
        print("  [+] Slippage senaryoları...")
        for slip_label, slip_val in [("düşük (%0.2)", 0.002), ("yüksek (%0.8)", 0.008)]:
            s = run_scenario(data, signals, f"Baseline F + slippage {slip_label}",
                             mode=args.mode, slippage=slip_val,
                             LATE_ENTRY_FILTER=False, SIDEWAYS_SCALING=False)
            scenarios.append(s)

    # ── Tablo ─────────────────────────────────────────────
    print_table(scenarios, baseline_ret)

    # ── Özet analiz ───────────────────────────────────────
    best = max(scenarios[1:], key=lambda x: x["ret"])
    safest = min(scenarios[1:], key=lambda x: x["dd"])  # en az drawdown
    best_sharpe = max(scenarios[1:], key=lambda x: x["sharpe"])

    print(f"\n  En yüksek getiri : {best['label']}  → %{best['ret']:.2f}")
    print(f"  En düşük DD      : {safest['label']}  → %{safest['dd']:.2f}")
    print(f"  En iyi Sharpe    : {best_sharpe['label']}  → {best_sharpe['sharpe']:.2f}")

    delta_ret = best["ret"] - baseline_ret
    delta_dd = abs(safest["dd"]) - abs(scenarios[0]["dd"])
    print(f"\n  Baseline'a göre max getiri farkı : {'+'if delta_ret>=0 else ''}{delta_ret:.2f}pp")
    print(f"  Baseline'a göre max DD iyileşme  : {'+'if delta_dd<=0 else ''}{delta_dd:.2f}pp")

    if delta_ret < -5:
        print("\n  ⚠  Tüm filtreler baseline'ı düşürüyor — veri setinde filtreler zararlı olabilir.")
    elif delta_ret > 0:
        print(f"\n  ✓  {best['label']} baseline'ı geçiyor — shadow'da test edilmeye değer.")

    if args.chart:
        plot_curves(scenarios[:4], prices.index)

    return 0


if __name__ == "__main__":
    sys.exit(main())
