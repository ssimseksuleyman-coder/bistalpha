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
from bist_alpha.catalyst_feed import CatalystFeed


def main() -> int:
    cf = CatalystFeed(state_dir="docs/state")
    try:
        added = cf.accumulate()
    except Exception as e:
        print(f"[run_catalyst] HATA: {type(e).__name__}: {e}")
        return 1
    total = len(cf.get_events())
    print(f"[run_catalyst] +{added} yeni katalizor | toplam {total} olay "
          f"(docs/state/catalysts.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
