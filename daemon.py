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


def _prices_today(data):
    prices_today = {}
    if data is not None and data.get("prices") is not None:
        try:
            pd = __import__("pandas")
            prices = data["prices"]
            last = prices.index[-1]
            prices_today = {t: float(prices.loc[last, t]) for t in prices.columns
                            if not pd.isna(prices.loc[last, t])}
        except Exception:
            prices_today = {}
    return prices_today


def _shadow_summary(data):
    """A/B/F shadow performansını rapor ve dashboard için özetler."""
    from bist_alpha import portfolio as pf
    prices_today = _prices_today(data)
    accounts = {}
    for acc in ["A", "B", "F"]:
        try:
            s = pf.load(acc, state_dir=config.STATE_DIR)
            value = float(pf.current_value(s, prices_today))
            last_event = s.get("history", [])[-1] if s.get("history") else None
            accounts[acc] = {
                "value": round(value, 4),
                "return_pct": round((value - 1) * 100, 2),
                "n_positions": len(s.get("positions", {})),
                "cash": round(s.get("cash", 0), 4),
                "last_event": last_event,
            }
        except Exception as e:
            accounts[acc] = {"error": str(e)}
    return accounts


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
    data['_dynamic_universe'] = universe
    data['_dynamic_universe_method'] = 'likidite_fiyat_x_hacim' if data.get('_source') in ('yahoo', 'borsapy') else 'piyasa_degeri'
    print(f"[daemon] Kaynak: {data.get('_source', config.DATA_SOURCE)}")
    print(f"[daemon] Veri: {data['prices'].shape[1]} hisse, dinamik evren: {len(universe)}")

    # 3) Bakım (eksik #6) — veri sağlık + temp/log temizliği
    health = maintenance.run_maintenance(data)
    if not health["healthy"]:
        notifier.notify_all("⚠️ BIST Alpha — Veri Sorunu",
                            "\n".join(health["data_issues"]))

    # 4) Sinyaller + rapor (eksik #2, #4) — korumalı
    def _report():
        signals = sig_mod.compute_signals(data)
        held_positions = {}
        try:
            from bist_alpha import portfolio as pf
            held_positions = pf.load(config.MODE, state_dir=config.STATE_DIR).get("positions", {})
        except Exception:
            held_positions = {}
        report = reporter.generate_report(data, signals, mode=config.MODE,
                                           deniz_bulletin=bulletin,
                                           held_positions=held_positions)
        report["shadow_accounts"] = _shadow_summary(data)
        try:
            from bist_alpha import radar
            report["watchlists"] = radar.build_watchlists(data, signals, report)
        except Exception as e:
            report["watchlists"] = {"error": str(e)}
        text = reporter.format_text(report)
        print(text)
        # 5) Bildirim (eksik #2)
        subject = f"📊 BIST Alpha {report['date']} ({label})"
        notifier.notify_all(subject, text)
        # 6) Web dashboard JSON (GitHub Pages için docs/state/)
        _write_dashboard_state(report, label, data=data, universe=universe)
        return report

    return selfheal.guarded(_report, notify_fn=notifier.notify_all, label="rapor")


def _write_dashboard_state(report, label, data=None, universe=None):
    """docs/state/ altına dashboard JSON'u yaz."""
    import json
    import os
    from bist_alpha import portfolio as pf
    from bist_alpha import forward_test
    from bist_alpha import missed_log
    out_dir = os.path.join(os.path.dirname(__file__), "docs", "state")
    os.makedirs(out_dir, exist_ok=True)
    prices_today = {}
    if data is not None and data.get("prices") is not None:
        try:
            pd = __import__("pandas")
            prices = data["prices"]
            last = prices.index[-1]
            prices_today = {t: prices.loc[last, t] for t in prices.columns
                            if not pd.isna(prices.loc[last, t])}
        except Exception:
            prices_today = {}
    state = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "date": report.get("date"),
        "mode": report.get("mode"),
        "source": report.get("source") or (data or {}).get("_source"),
        "source_pool_count": report.get("source_pool_count") or (data or {}).get("_source_pool_count"),
        "source_pool_method": report.get("source_pool_method") or (data or {}).get("_source_pool_method"),
        "source_pool_fallback": report.get("source_pool_fallback") if report.get("source_pool_fallback") is not None else (data or {}).get("_source_pool_fallback"),
        "last_data_date": report.get("last_data_date"),
        "price_count": report.get("price_count"),
        "dynamic_universe_count": len(universe) if universe is not None else report.get("dynamic_universe_count"),
        "dynamic_universe_method": (data or {}).get("_dynamic_universe_method"),
        "deniz_regime": report.get("deniz_regime"),
        "top10": report.get("top10", []),
        "watchlists": report.get("watchlists", {}),
        "accounts": {},
    }
    try:
        state["forward_test"] = forward_test.update(report, data=data)
    except Exception as e:
        state["forward_test"] = {"error": str(e)}
    try:
        state["missed_opportunities"] = missed_log.update(
            data, report.get("watchlists", {}), report)
    except Exception as e:
        state["missed_opportunities"] = {"error": str(e)}
    for acc in ["A", "B", "F"]:
        try:
            s = pf.load(acc, state_dir="portfolios")
            positions = []
            for t, p in s.get("positions", {}).items():
                cur = prices_today.get(t, p["entry"])
                stop = pf.stop_level(p)
                positions.append({
                    "ticker": t,
                    "entry": round(p["entry"], 2),
                    "peak": round(p["peak"], 2),
                    "current": round(cur, 2),
                    "stop": round(stop, 2),
                    "pnl_pct": round((cur / p["entry"] - 1) * 100, 2),
                    "shares": round(p.get("shares", 0), 6),
                })
            state["accounts"][acc] = {
                "n_positions": len(s.get("positions", {})),
                "cash": round(s.get("cash", 0), 4),
                "value": round(pf.current_value(s, prices_today), 4),
                "positions": positions,
                "history": s.get("history", [])[-10:],
                "last_event": s.get("history", [])[-1] if s.get("history") else None,
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
        result = run_cycle(args.once)
        if result is None:
            raise SystemExit(1)
    else:
        scheduler.run_loop(run_cycle)


if __name__ == "__main__":
    sys.exit(main())
