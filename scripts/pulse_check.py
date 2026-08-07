#!/usr/bin/env python3
"""
REPO-DISI PINGER — "izleme sisteminin kendisi oldu mu?" sorusunu disaridan sorar.

NEDEN (korelasyonlu ariza, 2026-08-06'da FIILEN yasandi): karsilikli izleme
(tarayici <-> bekci) yalniz TEK-NOKTA arizasini kapatir. Actions runner kesintisi
/ faturalama / repo arsivleme / 60-gun-auto-disable IKISINI BIRDEN susturur; o
anda kimse bagirmaz ve sistem YANLIS-GUVEN verir. 08-06 aksami tam bu oldu:
5 kosu dustu (3'u bizim), tarayici da bekci de susdu, ve kesintiyi GitHub'in
kendi hata-maili haber verdi — bizim sistemimiz degil.

BU DOSYA GITHUB ACTIONS'TA KOSMAZ. Kosarsa amacini kaybeder (izledigi altyapinin
icinde olur). Kullanici kendi makinesinde / disarida bir zamanlayicida kosturur.
Depoya SIFIR bagimlilik: tek dosya, yalniz standart kutuphane -> kopyalanip
herhangi bir yerde calisir (repo private olsa bile).

--- IKI KURAL, IKISI DE OLCUMDEN GELIYOR ---

1) VARLIK DEGIL ILERLEME (runbook 2b):
       YANLIS: GET -> 200 mu?                  (ara-gosterge)
       DOGRU : updated_at > son_gordugum mu?   (ground-truth)
   Neden kritik: 60-gun-auto-disable'da repo ERISILEBILIR kalir, yalniz damga
   DONAR. Durumsuz bir kontrol (UptimeRobot vb. anahtar-kelime/HTTP-durum) tam
   o vakada SUSAR. Bu yuzden son gorulen damga DISKTE saklanir.

2) HATA TIPLERI ESIT DEGILDIR (#4'teki 403 dersi):
       403/429 rate-limit -> BEKLENEN gecici  -> SAYMA, bekle
       timeout/5xx/DNS    -> BEKLENMEYEN      -> SAY, esigi asinca bagir
   Ayrilmazsa: ya her rate-limit penceresinde yanlis bagirir (alarm korlugu, ve
   o korluk GERCEK kopmayi gizler), ya da hepsini yutar (yoklugun imzasi yok).

--- ALARM = GELIS, SESSIZLIK DEGIL ---
08-06 ampirik dersi: heartbeat sustu ve KIMSE FARK ETMEDI; is goren sey GitHub'in
anomali-maili oldu. Insan GELEN mesaji fark eder, GELMEYENI etmez. Bu yuzden bu
betik "her sey yolunda" spam'i atmaz; yalniz ANOMALIDE bagirir. Zincirin insanda
bittigini kabul ediyoruz — ama son halka bir GELIS.

Kullanim:
  python scripts/pulse_check.py                 # tek yoklama
  python scripts/pulse_check.py --dry-run URL   # alarmi bastir, kararı yazdir
Cikis: 0 = sessiz (saglikli) | 1 = ALARM | 2 = yapilandirma hatasi
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Access ONCESI: liveness.json zaten public (dogrulandi 2026-08-07, raw 200).
# Access SONRASI: bu URL `.../state/pulse.json` olur (dar sema + tek-dosya bypass,
# runbook 2b). Degisiklik TEK SATIR — "pinger iki kez kurulur" maliyeti budur.
DEFAULT_URL = ("https://raw.githubusercontent.com/ssimseksuleyman-coder/"
               "bistalpha/main/docs/state/liveness.json")

STATE_PATH = Path(os.environ.get("PULSE_STATE", Path.home() / ".bistalpha_pulse.json"))
# Uretim takvimi: liveness.yml cron '0 17 * * 1-5' (hafta-ici 17:00 UTC).
# Grace: Actions kuyrugu + kosu suresi (08-05/08-06 gozlemi: yazim ~18:14 UTC).
PROD_HOUR_UTC = int(os.environ.get("PULSE_PROD_HOUR", "17"))
GRACE_H = float(os.environ.get("PULSE_GRACE_H", "5"))
# 1 kacan slot GECICI olabilir (tek kosu duser, ertesi gun toparlar) -> 2'de bagir.
# liveness_scan'in kendi semantigiyle ayni: 1 kacik=YELLOW, >=2=RED.
MISS_THRESHOLD = int(os.environ.get("PULSE_MISS_THRESHOLD", "2"))
FAIL_THRESHOLD = int(os.environ.get("PULSE_FAIL_THRESHOLD", "3"))
TIMEOUT = 20


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    except Exception as exc:
        print(f"[pulse] UYARI: durum yazilamadi ({exc!r}) — ilerleme takibi bozulur")


def fetch(url: str):
    """(payload|None, hata_sinifi) — hata_sinifi: None | 'gecici' | 'beklenmeyen'."""
    req = urllib.request.Request(url, headers={"User-Agent": "bistalpha-pulse/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        # 403/429 = kota/rate-limit -> BEKLENEN, saymayiz (yoksa her pencerede
        # yanlis alarm -> alarm korlugu -> gercek kopma gizlenir).
        # 5xx = altyapi -> BEKLENMEYEN. 404 de beklenmeyen: dosya kayboldu.
        return None, ("gecici" if e.code in (403, 429) else "beklenmeyen")
    except Exception:
        # timeout / DNS / baglanti -> BEKLENMEYEN
        return None, "beklenmeyen"


def _parse(ts: str):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "")).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def check(url: str, now=None) -> tuple[bool, str, dict]:
    """(alarm?, mesaj, yeni_durum) — SAF: I/O yapmaz disinda, test edilebilir."""
    now = now or datetime.now(timezone.utc)
    st = _load_state()
    payload, hata = fetch(url)

    if hata == "gecici":
        # Sayma. Ama sessizce de gecme: son basarili yoklama COK eskiyse
        # "surekli rate-limit" de bir arizadir -> bayatlik kontrolu yine isler.
        st["last_transient"] = now.isoformat(timespec="seconds")
        return _bayatlik_hukmu(st, now, "gecici hata (403/429) — sayilmadi")

    if hata == "beklenmeyen":
        st["fail_streak"] = int(st.get("fail_streak", 0)) + 1
        st["last_fail"] = now.isoformat(timespec="seconds")
        n = st["fail_streak"]
        if n >= FAIL_THRESHOLD:
            return True, (f"ULASILAMIYOR: {n} ardisik beklenmeyen hata "
                          f"(esik {FAIL_THRESHOLD}) — URL/ag/repo erisimi"), st
        return False, f"beklenmeyen hata ({n}/{FAIL_THRESHOLD}) — henuz esik altinda", st

    st["fail_streak"] = 0
    damga = _parse((payload or {}).get("updated_at"))
    if damga is None:
        # Ulasilabilir ama SEMA BOZUK — 200 gormek yetmez (Dogrulama Yasasi).
        st["fail_streak"] = int(st.get("fail_streak", 0)) + 1
        return True, "SEMA BOZUK: updated_at okunamadi (200 doniyor ama icerik gecersiz)", st

    onceki = _parse(st.get("last_seen"))
    if onceki is None or damga > onceki:
        st["last_seen"] = damga.isoformat(timespec="seconds")
        st["last_progress_at"] = now.isoformat(timespec="seconds")
        return False, f"ilerledi: {damga:%Y-%m-%d %H:%M} UTC", st

    # DAMGA ILERLEMEDI — "fosil ama ulasilabilir". Asil yakalamak istedigimiz hal.
    return _bayatlik_hukmu(st, now, f"damga ILERLEMEDI ({damga:%Y-%m-%d %H:%M} UTC)")


def _kacan_slotlar(ref, now):
    """ref'ten now'a KACIRILAN hafta-ici uretim slotu sayisi.

    SAAT-TABANLI ESIK YANLIS OLURDU (bu projede yanilmis sinif): uretici
    hafta-ici kosuyor (liveness.yml cron '0 17 * * 1-5'). Cuma 17:00'de damga
    ilerler, Ctesi/Pazar kosu YOK -> Pazartesi sabahi saat-farki 60h+ olur ve
    saat-esigi HER HAFTA SONU yanlis bagirirdi. Haftada bir bagiran izleyici
    terk edilir -> hic izleyici olmamasindan KOTU (alarm korlugu).
    `liveness_scan._missed_slots` ayni problemi ayni sekilde cozuyor; burada da
    hafta-sonu YAPISAL olarak atlanir.
    """
    # GRACE `now` TARAFINA uygulanir, slot'a DEGIL (liveness_scan._missed_slots
    # ile ayni hiza). Tersi yapilirsa uretici KENDI slotunu kacirmis sayilir:
    # yazim ~17:05'te olur, slot+grace 22:00 -> `17:05 < 22:00` TRUE -> sahte
    # kacik. Ilk surumde tam bu hata vardi ve hafta-sonu testi ele verdi.
    cutoff = now - timedelta(hours=GRACE_H)
    n = 0
    gun = ref.date()
    while gun <= now.date():
        if gun.weekday() < 5:                       # 0-4 = Pzt-Cum
            slot = datetime(gun.year, gun.month, gun.day, PROD_HOUR_UTC,
                            tzinfo=timezone.utc)
            if ref < slot <= cutoff:
                n += 1
        gun += timedelta(days=1)
    return n


def _bayatlik_hukmu(st, now, ek):
    ref = _parse(st.get("last_progress_at")) or _parse(st.get("last_seen"))
    if ref is None:
        return False, f"{ek} — referans yok, ilk kosu sayiliyor", st
    kacan = _kacan_slotlar(ref, now)
    yas = (now - ref).total_seconds() / 3600.0
    if kacan >= MISS_THRESHOLD:
        return True, (f"FOSIL: {kacan} hafta-ici uretim slotu KACTI "
                      f"(yas {yas:.0f}h) — {ek}"), st
    return False, f"{ek} — kacan slot {kacan}/{MISS_THRESHOLD} (yas {yas:.0f}h)", st


def notify(baslik: str, mesaj: str) -> None:
    """Telegram — token/chat env'den. Yoksa sessizce atla (stdout zaten yazdi)."""
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[pulse] TELEGRAM_TOKEN/CHAT_ID yok — bildirim atlandi")
        return
    try:
        data = json.dumps({"chat_id": chat, "text": f"{baslik}\n\n{mesaj}"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                     data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
    except Exception as exc:
        print(f"[pulse] bildirim gonderilemedi: {exc!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("PULSE_URL", DEFAULT_URL))
    ap.add_argument("--dry-run", action="store_true", help="alarm gonderme, karari yazdir")
    a = ap.parse_args()

    alarm, mesaj, st = check(a.url)
    print(f"[pulse] {'ALARM' if alarm else 'sessiz'} — {mesaj}")
    if not a.dry_run:
        _save_state(st)
        if alarm:
            notify("🔴 BISTALPA PULSE — izleme zinciri sessiz", mesaj + f"\n\nURL: {a.url}")
    return 1 if alarm else 0


if __name__ == "__main__":
    sys.exit(main())
