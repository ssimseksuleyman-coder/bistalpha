#!/usr/bin/env python3
"""run_catalyst.py — KAP katalizor olaylarini GUNLUK cek + biriktir (standalone).

F'e/daemon'a DOKUNMAZ — ayri, additive is. Gunde 1 kez calistir (cron/GitHub
Actions/Surface). Her calisma bugunku KAP bildirimlerini ceker, classify_title
ile katalizor turune esler (rutin ELENIR), docs/state/catalysts.json'a DEDUP-merge
eder. Haftalar icinde event_study'ye yetecek katalizor gecmisi birikir.

GEREKSINIM: pip install playwright && python -m playwright install chromium
  (KAP Next.js RSC + WAF -> requests calismaz, gercek tarayici sart.)

Sonraki adim (aktivasyon): bu script'i gunluk zamanla. GitHub Actions icin
workflow'a 'playwright install chromium' adimi + gunluk cron + catalysts.json'i
commit et (kalicilik). event_study yeterli olay birikince ilk hukmu verir.
"""
import sys
import json
from datetime import datetime
from pathlib import Path

from bist_alpha.catalyst_feed import CatalystFeed


STATUS_PATH = Path("docs/state/kap_status.json")


def _write_status(payload):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATUS_PATH)


def main() -> int:
    cf = CatalystFeed(state_dir="docs/state")
    try:
        added = cf.accumulate()
    except Exception as e:
        _write_status({
            "status": "error",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "error_type": type(e).__name__,
            "error": str(e),
            "opens_trade": False,
            "note": "KAP resmi kaynak toplayici hatasi; F motoruna emir uretmez.",
        })
        print(f"[run_catalyst] HATA: {type(e).__name__}: {e}")
        return 1
    payload = cf._load("catalysts.json")
    events = payload.get("events", [])
    total = len(events)
    latest_event_date = max((e.get("date") for e in events if e.get("date")), default=None)
    _write_status({
        "status": "ok",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "added": added,
        "total_events": total,
        "latest_event_date": latest_event_date,
        # SESSIZ-DUSURME TESHISI (2026-07-29): siniflandirilamayan basliklar
        # artik GORUNUR. Eskiden iz birakmadan dusuyorlardi -> KAP kategori adi
        # degisince (ya da yeni kategori gelince) sessizce veri kaybi olurdu ve
        # kimse fark etmezdi (buyback'ler haftalarca boyle kayboldu).
        # Bu alanlar yeni bir anahtar-boslugunun ERKEN UYARISIDIR: sayi surekli
        # yuksekse ya da ornekte tanidik bir katalizor turu goruyorsan -> anahtar ekle.
        "unclassified_count": getattr(cf, "last_unclassified_count", 0),
        "unclassified_sample": getattr(cf, "last_unclassified", []),
        "opens_trade": False,
        "note": "KAP resmi kaynak defteri; olcer, F motoruna emir uretmez.",
    })
    print(f"[run_catalyst] +{added} yeni katalizor | toplam {total} olay "
          f"(docs/state/catalysts.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
