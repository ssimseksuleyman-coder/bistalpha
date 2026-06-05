#!/usr/bin/env python3
"""
BIST ALPHA v1.2 + OMEGA — Otonom Servis (daemon).
6 eksiği birleştiren ana orkestratör.

Kullanım:
  python daemon.py                  # sürekli çalış (scheduler döngüsü)
  python daemon.py --once acilis    # tek sefer çalıştır (cron için)
  python daemon.py --once kapanis

Akış (her tetiklemede):
  1. Deniz bültenini otomatik çek (eksik #5)
  2. Veriyi dinamik feed'den al (eksik #1)
  3. Bakım çalıştır (eksik #6)
  4. Sinyal raporu üret — top10 + al/sat/bekle/fırsat (eksik #2)
  5. E-posta + Telegram gönder (eksik #2)
  Zamanlama: scheduler 09:45/14:30/18:30 (eksik #3)
"""
import argparse
import sys
from datetime import datetime

from bist_alpha import config
from bist_alpha import datafeed
from bist_alpha import signals as sig_mod
from bist_alpha import reporter
from bist_alpha import notifier
from bist_alpha import deniz_fetcher
from bist_alpha import maintenance
from bist_alpha import scheduler
from bist_alpha import selfheal


def _telegram_ingest():
    """Telegram'a gönderilen dosyaları indir (Deniz/endeks/fiyat)."""
    from bist_alpha import telegram_ingest
    saved = telegram_ingest.fetch_uploads()
    if saved:
        print(f"[daemon] Telegram'dan {len(saved)} dosya alındı")
    return saved


def run_cycle(label="manuel"):
    """Tek tam döngü — self-heal korumalı."""
    ts = datetime.now().strftime("%H:%M")
    print(f"\n=== DÖNGÜ '{label}' @ {ts} ===")

    # 0) Telegram'dan manuel yüklenen veriyi al (Deniz bülten / endeks üyeliği / fiyat)
    selfheal.guarded(lambda: _telegram_ingest(), label="telegram veri alımı")

    # 1) Deniz bültenini otomatik güncelle (eksik #5) — korumalı
    bulletin = selfheal.guarded(
        lambda: deniz_fetcher.auto_update(),
        notify_fn=notifier.notify_all, label="Deniz çekme")

    # 2) Dinamik veri (eksik #1) — self-heal: çökerse gömülü yedeğe düş
    data = selfheal.safe_feed()
    feed = datafeed.get_feed()
    universe = feed.dynamic_universe(data)
    print(f"[daemon] Veri: {data['prices'].shape[1]} hisse, dinamik evren: {len(universe)}")

    # 3) Bakım (eksik #6) — veri sağlık + temp/log temizliği
    health = maintenance.run_maintenance(data)
    if not health["healthy"]:
        notifier.notify_all("⚠️ BIST Alpha — Veri Sorunu",
                            "\n".join(health["data_issues"]))

    # 4) Sinyaller + rapor (eksik #2, #4) — korumalı
    def _report():
        signals = sig_mod.compute_signals(data)
        report = reporter.generate_report(data, signals, mode=config.MODE,
                                           deniz_bulletin=bulletin)
        text = reporter.format_text(report)
        print(text)
        # 5) Bildirim (eksik #2)
        subject = f"📊 BIST Alpha {report['date']} ({label})"
        notifier.notify_all(subject, text)
        # 6) Web dashboard JSON (GitHub Pages için docs/state/)
        _write_dashboard_state(report, label)
        return report

    return selfheal.guarded(_report, notify_fn=notifier.notify_all, label="rapor")


def _write_dashboard_state(report, label):
    """docs/state/ altına dashboard JSON'u yaz."""
    import json
    import os
    from bist_alpha import portfolio as pf
    out_dir = os.path.join(os.path.dirname(__file__), "docs", "state")
    os.makedirs(out_dir, exist_ok=True)
    state = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "date": report.get("date"),
        "mode": report.get("mode"),
        "deniz_regime": report.get("deniz_regime"),
        "top10": report.get("top10", []),
        "accounts": {},
    }
    for acc in ["A", "B", "F"]:
        try:
            s = pf.load(acc, state_dir="portfolios")
            state["accounts"][acc] = {
                "n_positions": len(s.get("positions", {})),
                "cash": round(s.get("cash", 0), 4),
                "positions": [{"ticker": t, "entry": round(p["entry"], 2),
                               "peak": round(p["peak"], 2)}
                              for t, p in s.get("positions", {}).items()],
                "history": s.get("history", [])[-10:],
            }
        except Exception:
            state["accounts"][acc] = {"error": "yüklenemedi"}
    with open(os.path.join(out_dir, "dashboard.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)


def main():
    ap = argparse.ArgumentParser(description="BIST Alpha otonom servis")
    ap.add_argument("--once", metavar="LABEL", default=None,
                    help="Tek sefer çalıştır (cron için): acilis/gunici/kapanis")
    ap.add_argument("--optimize", action="store_true",
                    help="Disiplinli walk-forward parametre ÖNERİSİ üret (uygulamaz)")
    args = ap.parse_args()

    if args.optimize:
        from bist_alpha import optimizer, datafeed
        from bist_alpha import signals as sig_mod
        data = selfheal.safe_feed()
        signals = sig_mod.compute_signals(data)
        rep = optimizer.suggest(data, signals)
        print("Optimizatör önerileri (SADECE öneri, config değişmedi):")
        for s in rep["suggestions"]:
            print(f"  {s['param']}: {s['verdict']}")
        for w in rep["warnings"]:
            print(f"  ⚠️ {w}")
        print("→ optimizer_suggestions.json yazıldı. Hiçbiri otomatik uygulanmadı.")
        return

    if args.once:
        run_cycle(args.once)
    else:
        scheduler.run_loop(run_cycle)


if __name__ == "__main__":
    sys.exit(main())
