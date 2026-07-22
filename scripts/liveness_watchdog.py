#!/usr/bin/env python3
"""
SEVIYE-2 BEKCI: daemon -> tarayici. ("Izleyenin izleyeni")

NEDEN VAR
Tarayici (liveness_scan) daemon'u izler. Ama tarayicinin KENDISI, izledigi hata
sinifina karsi korumasizdi: sessizce durursa kimse fark etmez. Heartbeat
"sessizlik = alarm" der ama uygulamasi INSANIN bir mesajin yoklugunu fark
etmesine dayanir -- ki bu, tum bu isin ortadan kaldirmak icin kuruldugu bilissel
hatanin ta kendisi (rebalance-bug 45 tur boyle kacti). Bu modul o boslugu
PASIF-sessizlikten AKTIF-sinyale cevirir.

TOPOLOJI (dongusel degil): tarayici daemon'un ciktilarini okur, daemon
tarayicinin ciktisini okur. Iki AYRI workflow, iki AYRI cron. Olu tarayici kendi
olumunu bildiremez -- ama canli daemon bildirebilir.

IKI BASARISIZLIK MODU, IKI AYRI KONTROL (2026-07-18 dersi: "kosuyor" != "dogru")
  Mod-1 tarayici KOSMUYOR      -> liveness.json bayatlar   -> A) canlilik kontrolu
  Mod-2 tarayici KOSUYOR ama YANLIS (bos yaziyor, hep-GREEN, uye dusuruyor)
                               -> liveness.json TAZE, icerik cop -> B) tutarlilik
Yalniz yas bakan bir bekci Mod-2'yi kacirir. Bu turda birebir yasandi: tarayici
kosuyordu (canli) ama market_data'yi yanlis-RED verdi; updated_at tazeydi.

NEREDE DURUYOR (dururken durustce)
Seviye-2 tek-nokta-arizasini kapatir: biri olurse digeri bagirir. KORELASYONLU
ariza (Actions kesintisi, faturalama, 60-gun-auto-disable) IKISINI BIRDEN
susturur -> repo-disi pinger gerekir, HENUZ YOK. Bkz local/ACIK_ISLER.md #4.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from liveness_scan import (  # noqa: E402
    REGISTRY, PRODUCER_TZ_OFFSET_H, _age_hours, _missed_slots,
)

# EKSEN NOTU (2026-07-22): liveness.json'i TARAYICI yazar (liveness.yml'de TZ yok
# -> utcnow -> UTC) => ofset 0. dashboard.json'i DAEMON yazar (precise.yml'de
# TZ: Europe/Istanbul -> datetime.now() -> TR) => ofset +3. Ayni fonksiyona iki
# FARKLI eksen giriyor; karistirilirsa capraz-kontrol 3h yaniltir.

ROOT = Path(__file__).resolve().parents[1]
LIVENESS = ROOT / "docs" / "state" / "liveness.json"
DASHBOARD = ROOT / "docs" / "state" / "dashboard.json"
STATE = ROOT / "docs" / "state" / "watchdog.json"      # bekcinin KENDI izi

# Tarayicinin KENDI takvimi (liveness.yml: '0 17 * * 1-5').
# grace 5h: gozlenen GitHub cron gecikmesi ~2h; 5h rahat pay birakir.
# NOT: bu da slot-hard-code -- ayni bilinen-kirilganlik (ACIK_ISLER #3).
SCANNER_SCHEDULE = {"weekdays": (0, 1, 2, 3, 4), "slots_utc": (17,), "grace_h": 5}

# B3 icin KABA ve DIK sinir. Bilerek slot-kutuphanesini KULLANMAZ: paylasilan
# takvim mantigi bozulursa hem tarayici hem capraz-kontrol ayni sekilde
# yanilirdi (ortak-mod ariza). En uzun mesru bosluk Cuma17->Pzt07 = 62h ~ 2.6
# gun; 4 gun, resmi-tatil dahil hicbir takvim yorumunun "saglikli" diyemeyecegi
# bir esik. Kabalik burada OZELLIK: yanlis-alarm riski ~0, ortogonalligi tam.
ANCIENT_DAYS = 4


def _fail(problems, code, msg):
    problems.append((code, msg))


def check():
    problems = []
    now = datetime.utcnow()

    # --- A) CANLILIK: tarayici zamanlanmis taramasini kacirdi mi ---------------
    if not LIVENESS.exists():
        _fail(problems, "A/YOK", "docs/state/liveness.json YOK — tarayici hic yazmadi")
        return problems, None
    try:
        lv = json.loads(LIVENESS.read_text(encoding="utf-8"))
    except Exception as e:
        _fail(problems, "A/BOZUK", f"liveness.json okunamadi: {e}")
        return problems, None

    age = _age_hours(lv.get("updated_at"))
    if age is None:
        _fail(problems, "A/DAMGASIZ", f"liveness.json updated_at cozulemedi: {lv.get('updated_at')!r}")
    else:
        missed = _missed_slots(now - timedelta(hours=age), now, SCANNER_SCHEDULE)
        if missed >= 1:
            _fail(problems, "A/BAYAT",
                  f"tarayici {missed} zamanlanmis taramayi KACIRDI "
                  f"(liveness.json yasi {age:.0f}h) — cron tetiklenmiyor olabilir")

    # --- B) TUTARLILIK: kosuyor ama dogru mu ---------------------------------
    checks = lv.get("checks")
    if not isinstance(checks, list) or not checks:
        _fail(problems, "B1/BOS", "liveness.json 'checks' bos/gecersiz — tarayici bos yaziyor")
        return problems, lv

    # B1: kapsam dusmesi. Uye sessizce duserse "izlenmiyor" = gorunmez bosluk.
    if len(checks) < len(REGISTRY):
        eksik = sorted(set(REGISTRY) - {c.get("name") for c in checks})
        _fail(problems, "B1/KAPSAM",
              f"tarayici {len(checks)}/{len(REGISTRY)} uye raporladi — DUSEN: {', '.join(eksik)}")

    # B2: sema akli. Gecersiz/eksik durum = sessiz istisna yutulmus olabilir.
    gecersiz = [c.get("name") for c in checks
                if c.get("status") not in ("GREEN", "YELLOW", "RED")]
    if gecersiz:
        _fail(problems, "B2/SEMA", f"gecersiz status alani: {', '.join(map(str, gecersiz))}")

    # B3: ORTOGONAL CELISKI — "saglikli" derken veri fosil mi?
    # Mod-2'nin (hep-GREEN bug) asil yakalayicisi.
    verdict = lv.get("verdict")
    if DASHBOARD.exists():
        try:
            db = json.loads(DASHBOARD.read_text(encoding="utf-8"))
            db_age = _age_hours(db.get("timestamp") or db.get("date"),
                                PRODUCER_TZ_OFFSET_H)   # daemon damgasi = TR ekseni
            if db_age is not None and db_age > ANCIENT_DAYS * 24 and verdict != "RED":
                _fail(problems, "B3/CELISKI",
                      f"tarayici '{verdict}' diyor ama dashboard {db_age/24:.1f} GUN bayat "
                      f"(>{ANCIENT_DAYS}g) — tarayici kosuyor ama YANLIS calisiyor")
        except Exception as e:
            _fail(problems, "B3/OKUNAMADI", f"dashboard.json capraz-kontrolu yapilamadi: {e}")

    # B4: ZAMAN-YOLCULUGU — tarayicinin kaydettigi damga, dosyadaki gercek
    # damgadan YENI olamaz. Olursa: bozulma, elle-duzenleme ya da yanlis kaynak.
    if DASHBOARD.exists():
        row = next((c for c in checks if c.get("name") == "market_data"), None)
        if row and row.get("timestamp"):
            try:
                db = json.loads(DASHBOARD.read_text(encoding="utf-8"))
                gercek = db.get(row.get("ts_key") or "timestamp")
                if gercek and str(row["timestamp"]) > str(gercek):
                    _fail(problems, "B4/ZAMAN",
                          f"tarayici market_data icin {row['timestamp']} kaydetmis ama "
                          f"dosyada {gercek} var — ileri-tarihli damga (bozulma?)")
            except Exception:
                pass

    return problems, lv


def notify(text):
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        print("[notify] TELEGRAM_TOKEN/CHAT_ID yok — atlandi")
        return
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        print("[notify] gonderildi")
    except Exception as e:
        print(f"[notify] HATA {e}")


def _write_state(problems, lv):
    """
    BEKCININ KENDI IZI — "bekciyi kim izliyor?" bosluğunu kapatir.

    NEDEN (2026-07-22 bulgusu): bekci 40 kosuda 0 KEZ calisti ve kimse fark
    etmedi. Sebep yapisal: tarayicinin heartbeat'i var (her kosuda mesaj ->
    SESSIZLIK = ALARM), bekcinin YOK -- bekci yalniz sorun-varsa konusuyordu.
    Dolayisiyla bekcinin sessizligi UC ayri sey demekti: saglikli / olu /
    hic-kurulmamis. Ayirt edilemiyordu.

    COZUM: bekci her kosuda BU DOSYAYI yazar; tarayici onu registry'nin 12.
    uyesi olarak izler. Dosya yazilmissa bekci CALISMIS demektir (adim-varligi
    degil, adim-CIKTISI = ground-truth). Bayatlarsa tarayici KIRMIZI der ve
    durum zaten gunluk gelen heartbeat'e binmis olur -- ek Telegram gurultusu
    YOK.

    EKSEN: utcnow() ile yazilir. precise.yml adiminda TZ: Europe/Istanbul set
    edili, yani datetime.now() TR verirdi; utcnow diyerek bu dosyanin eksenini
    daemon damgalarindan AYIRIYORUZ -> tarayici tarafinda tz-ofset 0, TZ sorusu
    bu dosyada hic dogmaz.
    """
    payload = {
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "tz": "UTC",
        "writer": "scripts/liveness_watchdog.py",
        "sonuc": "ALARM" if problems else "SESSIZ",
        "problem_kodlari": [k for k, _ in problems],
        "problemler": [f"[{k}] {m}" for k, m in problems],
        # Bekcinin NE GORDUGU — katman-2/3/4'un otomatik kaydi:
        # sessiz kaldiysa "sessizlik dogru muydu" bu alanlardan denetlenir.
        "gordugu": {
            "liveness_updated_at": (lv or {}).get("updated_at"),
            "liveness_verdict": (lv or {}).get("verdict"),
            "liveness_checks": len((lv or {}).get("checks", [])),
            "liveness_red": (lv or {}).get("red_count"),
            "liveness_yellow": (lv or {}).get("yellow_count"),
            # tarayicinin uygulandigini bildirdigi tz-ofset (fix devrede mi)
            "tz_offset_gorunuyor": sorted({
                c.get("tz_offset_h") for c in (lv or {}).get("checks", [])
                if "tz_offset_h" in c
            }),
            "negatif_yas_sayisi": sum(
                1 for c in (lv or {}).get("checks", [])
                if isinstance(c.get("age_hours"), (int, float)) and c["age_hours"] < 0
            ),
        },
        "note": "Bekcinin kendi izi. Tarayici bunu 12. uye olarak KABA esikle "
                "izler (paylasilan slot/TZ mantigi KULLANILMAZ -> ortak-mod ariza yok).",
    }
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
        print(f"[state] {STATE.name} yazildi (sonuc={payload['sonuc']})")
    except Exception as e:
        print(f"[state] YAZILAMADI: {e}")


def main():
    problems, lv = check()
    _write_state(problems, lv)   # her kosuda -- alarm olsun olmasin
    if not problems:
        v = (lv or {}).get("verdict", "?")
        print(f"OK bekci: tarayici canli + tutarli (liveness verdict={v}, "
              f"{len((lv or {}).get('checks', []))} uye)")
        return 0

    # Bekci SESSIZ-degil: sorun varsa AKTIF sinyal (insanin yoklugu fark
    # etmesine birakmaz). Sorun yoksa susar -- cunku daemon'un kendi raporu
    # zaten her donguda geliyor, yani daemon'un canliligi ayrica kanitli.
    satirlar = [f"• [{k}] {m}" for k, m in problems]
    msg = ("🔴 BEKCI ALARMI — liveness tarayicisi\n"
           + "\n".join(satirlar)
           + "\n(daemon -> tarayici capraz-kontrolu; daemon calisiyor, tarayici sorunlu)")
    print(msg)
    notify(msg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
