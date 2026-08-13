#!/usr/bin/env python3
"""
LIVENESS TARAYICI — "olmasi gereken ama olmayan olay"i gorunur kilar.

NEDEN: rebalance-bug (2026-07-17) 6 hafta sessiz kaldi cunku hicbir kontrol
"son ne zaman calisti?" diye sormuyordu. Tum denetim aparatimiz var-olani
dogruluyordu; olmasi-gerekeni degil. Bu tarayici o eksik ekseni kapatir.

TASARIM ILKELERI (hepsi o bug'in dersinden):
  1. REGISTRY-GUDUMLU: yeni dis-kaynak eklenip damga yazmazsa tarayici KIRMIZI der.
     (Yoksa "yeni kaynak eklendi, liveness'i yok" = bug'in dogus kosulu tekrarlanir.)
  2. "YOK" ile "GOREMIYORUM" AYRI: events==0 gordugunde girdi-yolunun VARLIGINI da
     dogrular. Yol yoksa -> config-kirik (kirmizi), yol var+bos -> beklenen (sari).
     (Yoksa tarayici kirik-path'i "beklenen-bos" sanip yanlis-yesil uretir.)
  3. expected=active|planned: hic kurulmamis ozellik (KAP-parser, broker-input)
     surekli-kirmizi olmaz -> ALARM-KORLUGU onlenir. Kurulunca active'e cek.
  4. KENDI DAMGASINI yazar (updated_at) -> "izleyeni izleyen yok" regresyonu
     bir seviyede durur; o tek alani gozunle gor.
  5. F'e SIFIR dokunus: bist_alpha import etmez, yalniz JSON okur, docs/state'e yazar.

Kullanim:  python scripts/liveness_scan.py [--json]
Cikis:     0 = kirmizi yok, 1 = en az bir KIRMIZI (workflow alarmi icin)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "state" / "liveness.json"

# ---------------------------------------------------------------------------
# TAKVIM-FARKINDA BAYATLIK (2026-07-18 revizyon)
#
# ESKI: sabit 72h ("son kosudan N saat"). IKI YONDE de yanlisti:
#   - Hafta-ici bir kirilmayi ~2 GUN gizliyordu (Pzt sabahi dusen daemon Carsamba
#     gorunurdu).
#   - Hafta-sonu icin gevsetilmisti, yani gevseklik yapisal degil kaba-ayardi.
#
# YENI: "bir sonraki BEKLENEN kosu" hesabi. Uye-basina takvim (hafta-gunu + slot
# saatleri, UTC). Kacirilan-slot SAYILIR:
#   0 kacik -> GREEN | 1 kacik -> YELLOW (gecici olabilir) | >=2 -> RED (durdu)
# Hafta-sonu YAPISAL olarak atlanir (o gunlerde slot tanimli degil) -> Cumartesi
# bayat-dashboard dogru sekilde GREEN kalir (yanlis-alarm yok), ama hafta-ici
# 2 slot kacinca ayni gun RED olur.
#
# TZ: tum hesap UTC (bkz _age_hours TZ notu). GitHub cron gecikmesi gozlemlendi
# (6:45 cron -> 08:56 kosu) -> grace saatleri o gecikmeye toleransli.
# ---------------------------------------------------------------------------
# Uretici damgalarinin ekseni. daemon.py `datetime.now()` yaziyor ve ilgili
# workflow adimlarinda TZ: Europe/Istanbul set edili (bist-alpha.yml, precise.yml,
# catalyst.yml) -> damgalar TR saati = UTC+3. Tarayici UTC ekseninde hesaplar.
# Uretici DEGISTIRILMEZ (F zincirine yakin); tuketiciye eksen BILDIRILIR.
# Bir workflow'un TZ ayari degisirse BURASI da degismeli (bilinen kirilganlik,
# slot-saati hard-code ile ayni sinif -- bkz ACIK_ISLER #3).
PRODUCER_TZ_OFFSET_H = 3.0

# ---------------------------------------------------------------------------
# SLOT KAYNAGI — TEK-KAYNAK + CAPRAZ-KONTROL (#3'un kalici cozumu, 2026-08-06)
#
# ESKI HALI: slots_utc = (7, 12, 16) — GOZLENEN kosu saatlerinden elle turetilmis
# SAAT-hassas sabitler. Gercek kosu 15:40'ta yazdigi icin `last_run(15:40) <
# slot(16:00)` -> saglikli kapanis KENDI SLOTUNU tatmin etmiyordu -> her gece
# 20:00 UTC'den (slot+grace) sonra 10 uye SAHTE YELLOW. Sinif: sabit, gercegin
# proxy'si (rebalance-bug'in birebir sinifi).
#
# 🔴 KAYITTAKI PLAN ("cron'dan turet") OLCULDU VE YANLIS CIKTI (2026-08-06):
# HIC BIR workflow cron'u hedef saati temsil ETMIYOR — ikisi de kasten oyle:
#   precise.yml   : cron '0 2','30 7','0 12'  -> is HEDEFE KADAR UYUR (GitHub cron
#                   saatlerce gecikebiliyor; erken tetikle + uyu deseni)
#   bist-alpha.yml: 30 ayri cron (6:45..7:30, 11:30..12:20, 15:40..16:30) saciyor,
#                   gercek kapi `scripts/report_gate.py check` (due_slot)
# Cron'dan turetseydik daemon slotlari 02:00/07:30/12:00 olurdu -> slot COK ERKEN
# -> gercek kacik gizlenir = SAHTE YESIL (kaydin kendi uyardigi tehlikeli yon).
#
# GERCEK KAYNAK KODDA, ve UC KOPYASI var (ucuncusu bu dosyaydi, yanlis kodlanmis):
#   1. scripts/report_gate.SLOTS      (TR)  <- KANONIK sectik: bist-alpha kapisi
#   2. precise_runner.SLOT_TR         (TR)  <- capraz-kontrol
#   3. liveness_scan.slots_utc        (UTC) <- ARTIK TURETILIYOR (bu blok)
# Uretici DEGISTIRILMEZ (ikisi de canli kosuyu tetikleyen kapi). Tuketici turetir,
# ve kalan iki kopyayi KARSILASTIRIR: uyusmazlik -> tarayicinin KENDISI RED verir
# ("koruma kendini korumadan muaf sanir" panzehiri; `slot_source` uyesi).
# NOT: ikisi de `bist_alpha` import ETMIYOR (precise_runner daemon'u subprocess'le
# cagirir) -> tasarim ilkesi 5 ("F'e sifir dokunus") korunuyor.
_SLOT_ISSUES: list[str] = []
# Import/parse cokerse izleme olmesin: son-bilinen-iyi degerlere dus, AMA sessizce
# degil -> _SLOT_ISSUES doldugu icin `slot_source` uyesi RED verir.
_FALLBACK_SLOTS_TR = {"acilis": (9, 45), "gunici": (14, 30), "kapanis": (18, 40)}


def _load_slots_tr() -> dict:
    """report_gate.SLOTS = KANONIK; precise_runner.SLOT_TR ile capraz-kontrol."""
    canon = {}
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import report_gate  # noqa: E402  (yalniz SLOTS okunur, state'e dokunulmaz)
        canon = {str(lbl): (int(t.hour), int(t.minute)) for lbl, t in report_gate.SLOTS}
    except Exception as exc:
        _SLOT_ISSUES.append(f"KANONIK kaynak okunamadi (report_gate.SLOTS): {exc!r}")
        return dict(_FALLBACK_SLOTS_TR)
    if not canon:
        _SLOT_ISSUES.append("KANONIK kaynak BOS (report_gate.SLOTS)")
        return dict(_FALLBACK_SLOTS_TR)
    try:
        sys.path.insert(0, str(ROOT))
        import precise_runner  # noqa: E402
        other = {str(k): (int(v[0]), int(v[1])) for k, v in precise_runner.SLOT_TR.items()}
    except Exception as exc:
        _SLOT_ISSUES.append(f"capraz-kontrol kaynagi okunamadi (precise_runner.SLOT_TR): {exc!r}")
        return canon
    if other != canon:
        _SLOT_ISSUES.append(
            f"SLOT KAYNAKLARI UYUSMUYOR — report_gate.SLOTS={canon} vs "
            f"precise_runner.SLOT_TR={other} (biri degistirilmis, digeri unutulmus)")
    return canon


def _tr_to_utc(hm: tuple) -> tuple:
    """TR (saat,dakika) -> UTC (saat,dakika). Turkiye kalici UTC+3, DST yok."""
    total = hm[0] * 60 + hm[1] - int(round(PRODUCER_TZ_OFFSET_H * 60))
    total %= 24 * 60
    return (total // 60, total % 60)


def _cron_slots_utc(workflow: str) -> tuple:
    """workflow yml'indeki `- cron: 'M H ...'` satirlarindan (saat,dakika) UTC uret.

    GitHub Actions cron'u HER ZAMAN UTC'dir (workflow'un TZ: ayari cron'u
    ETKILEMEZ; yalniz uretici damgalarinin eksenini degistirir).
    Bu yalniz UYUYAN/KAPILI OLMAYAN uretici icin gecerlidir (catalyst.yml) —
    precise/bist-alpha icin cron hedef DEGIL (yukaridaki blok).
    """
    import re
    p = ROOT / ".github" / "workflows" / workflow
    try:
        txt = p.read_text(encoding="utf-8")
    except Exception as exc:
        _SLOT_ISSUES.append(f"cron okunamadi ({workflow}): {exc!r}")
        return ()
    out = []
    for m in re.finditer(r"^\s*-\s*cron:\s*['\"]([^'\"]+)['\"]", txt, re.M):
        parts = m.group(1).split()
        if len(parts) < 2:
            continue
        for mi in parts[0].split(","):
            for ho in parts[1].split(","):
                try:
                    out.append((int(ho), int(mi)))
                except ValueError:
                    pass
    if not out:
        _SLOT_ISSUES.append(f"cron bulunamadi ({workflow})")
    return tuple(sorted(set(out)))


_SLOTS_TR = _load_slots_tr()
_DAEMON_SLOTS = tuple(sorted(_tr_to_utc(v) for v in _SLOTS_TR.values()))
_CLOSE_SLOTS = ((_tr_to_utc(_SLOTS_TR["kapanis"]),) if "kapanis" in _SLOTS_TR
                else _DAEMON_SLOTS[-1:])
_KAP_SLOTS = _cron_slots_utc("catalyst.yml") or ((16, 10),)

SCHEDULES = {
    # daemon (bist-alpha.yml + precise.yml) hafta-ici 3 slot -> report_gate.SLOTS'tan
    # TURETILDI (06:45/11:30/15:40 UTC); gozlenen gecikme ~2h icin grace 4h.
    "daemon_cycle": {"weekdays": (0, 1, 2, 3, 4), "slots_utc": _DAEMON_SLOTS, "grace_h": 4},
    # catalyst.yml '10 16 * * 1-5' -> gunluk tek slot, CRON'DAN turetildi.
    # Burada cron GERCEKTEN kaynak: catalyst.yml uyumuyor, kod-kapisi yok.
    # OLCULDU (2026-08-06, 6 gun): yazim 17:37-18:04 UTC — yani cron'dan 1.5-2h
    # SONRA (Actions kuyrugu + scrape suresi). Slot=cron oldugu icin yazim daima
    # slot'tan sonra -> yapica tatmin. (#3-EK tablosu bu satirda YANLISTI: "gercek
    # 15:40, ayni kusur" diyordu; kap_daily AYRI workflow ve hic bozuk degildi.)
    "kap_daily":    {"weekdays": (0, 1, 2, 3, 4), "slots_utc": _KAP_SLOTS,    "grace_h": 6},
    # SADECE KAPANIS SLOTU (#0l). daemon_cycle UC slotu BIRLIKTE sayar -> yalniz
    # kapanis kacarsa 11:30 damgayi tazeler ve kacak GIZLENIR (satir ~297'deki
    # "alarm korlugu" uyarisi). #0l sonrasi stop YALNIZ kapanista degerlendirildigi
    # icin bu gizlenme "o gun stop yok" demek olur -> kapanis kendi programiyla
    # ayri izlenir. Kalici cozum: yml-parser partisi (SCHEDULES cron'dan turetilince
    # her slot dogal olarak ayrisir).
    # ELLE (15,) YAMASI KALKTI — artik report_gate.SLOTS["kapanis"]'tan turetiliyor
    # (15:40 UTC, DAKIKA-hassas). Eski yama dogruydu ama hala elle sabitti ve
    # kirilgandi: "15 calisiyor cunku 15:00 <= 15:40; kapanis 15:00 oncesine
    # kayarsa sahte alarm geri gelir" (#3-EK). Turetilmis slot bu kirilganligi
    # KALDIRIR — hedef degisirse slot da degisir.
    "close_only":   {"weekdays": (0, 1, 2, 3, 4), "slots_utc": _CLOSE_SLOTS, "grace_h": 4},
}


def _missed_slots(last_run, now, sched):
    """
    last_run'dan bu yana KACIRILAN zamanlanmis slot sayisi.
    Hafta-sonu/tatil yapisal olarak atlanir (o gunler weekdays'te yok).
    grace: GitHub cron gecikmesine tolerans (slot + grace gecmeden 'kacti' sayilmaz).
    """
    cutoff = now - timedelta(hours=sched["grace_h"])
    if last_run >= cutoff:
        return 0
    n = 0
    day = last_run.date()
    end = cutoff.date()
    while day <= end:
        if day.weekday() in sched["weekdays"]:
            # DAKIKA-hassas: slotlar artik (saat, dakika) — saat-yuvarlama, saglikli
            # kosuyu kendi slotunun ONUNE dusuruyordu (sahte YELLOW ureteci).
            for hm in sched["slots_utc"]:
                h, mi = (hm if isinstance(hm, tuple) else (hm, 0))
                slot = datetime(day.year, day.month, day.day, h, mi)
                if last_run < slot <= cutoff:
                    n += 1
        day += timedelta(days=1)
    return n

# ---------------------------------------------------------------------------
# REGISTRY — hangi mekanizma canli olmali, damgasini nereye yazmali.
# YENI DIS-KAYNAK EKLERKEN BURAYA DA EKLE. Eklenmezse izlenmez (bug dogus kosulu).
#
# YENI UYE KURALI (2026-07-22): bir uye eklendiginde damga dosyasi henuz YOKTUR.
# Bu, "durmus is" DEGILDIR -> otomatik olarak SARI raporlanir ("YENI UYE: henuz
# hic yazilmadi"), ilk yazimdan sonra normal (KIRMIZI-yapabilen) rejime gecer.
# Gecis OTOMATIK: `_ever_written_map()` bir onceki liveness.json'dan tasir.
# ELLE yapilmaz -- biri unutursa uye sonsuza dek "yeni" kalir ve gercekten
# kirildiginda da SARI gorunurdu = yeni bir sessiz korluk.
# Bu, defterlerdeki "BOS-normal vs KIRIK" ayriminin REGISTRY hali.
# ---------------------------------------------------------------------------
REGISTRY = {
    # ---- URETICILER (disariya cikan: scrape/API) ----
    "kap_feed": {
        "kind": "producer",
        "expected": "active",
        "file": "docs/state/kap_status.json",
        "ts_keys": ["updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "kap_daily",   # catalyst.yml: '10 16 * * 1-5' (gunluk tek slot)
        "ok_key": "status",
        "ok_value": "ok",
        "note": "catalyst_feed -> KAP scrape; gunluk 16:10 UTC cron (catalyst.yml)",
    },
    "market_data": {
        "kind": "producer",
        "expected": "active",
        "file": "docs/state/dashboard.json",
        "ts_keys": ["timestamp", "updated_at", "date"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "ok_key": "bist_data_ok",
        "ok_value": True,
        "note": "yfinance/datafeed; daemon her dongude",
    },
    # ---- TUKETICILER (local defter; daemon her dongude yazar) ----
    "forward_test": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/forward_test.json",
        "ts_keys": ["updated_at", "summary.updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["tracked_count", "days_tracked"],
        "input_paths": [],
    },
    # NOT: sayac-anahtari defterden deftere FARKLI (tracked_days/total_events/
    # hot_missed_count/tracked_count/tracked_events) — konvansiyon YOK. Yanlis anahtar
    # okumak "0 kayit" sanip yanlis-SARI uretir (ilk surumde 3 defterde aynen oldu).
    "performance_ledger": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/performance_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_days", "summary.latest_events"],
        "input_paths": [],
    },
    "opportunity_ledger": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/opportunity_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_days", "summary.total_events"],
        "input_paths": [],
    },
    "catalyst_ledger": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/catalyst_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["docs/state/catalysts.json"],
    },
    # ── #0j-EK ③ (2026-08-06): flow ve quality defterleri IKI YARIYA BOLUNDU ──
    # SEBEP: tek kayit iki yariyi (CALISAN akis + KURULMAMIS parser) birlestiriyordu
    # -> `expected:"planned"` etiketi BAYAT kaldi (uretiyor ama "planned"). Uretim
    # DURSA sistem "zaten kurulmamisti" (YELLOW) derdi; dogrusu "uretiyordu, durdu"
    # (RED). Bolununce her yari kendi dogru etiketini ve kendi girdi-yolunu alir.
    #
    # ⚠️ AKTIF YARILARIN input_paths'i BOS — VE BU BILINCLI (olculdu 2026-08-06):
    # #0j-EK "aktif yariya catalysts.json'i girdi ver, olay 0'a dusunce RED versin"
    # diyordu. OLCUM BUNU CURUTTU: catalysts.json ~35 gunluk KAYAN pencere ve
    # buyback PATLAMALI — 24 gunun yalniz 5'inde var, 07-02..07-28 arasi 19 gun
    # SIFIR. Yani "0 buyback" MESRU bir durum; RED yapmak yanlis-alarm olurdu —
    # tam da bu satirin eski yorumunun uyardigi hata ("girdi var" != "ILGILI girdi
    # var"; ilk surumde catalysts.json'i girdi sayip yanlis-KIRMIZI uretilmisti).
    # Aktif yarinin GERCEK canlilik sinyali olay-sayisi DEGIL TAZELIK: defter her
    # dongude yeniden yazilir, uretici durursa damga bayatlar -> slot makinesi RED
    # verir. Ust-akis zaten kendi dugumunde (kap_feed) izleniyor.
    "flow_kap_buyback": {
        "kind": "consumer", "expected": "active",    # KAP geri-alim taramasi CALISIYOR
        "file": "docs/state/flow_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.kap_buyback_events"],
        "input_paths": [],
        "upstream": ["docs/state/catalysts.json (kap_feed dugumunde izleniyor)"],
    },
    "flow_foreign_inputs": {
        "kind": "consumer", "expected": "planned",   # yabanci/takas: ucretli, girdi yok
        "file": "docs/state/flow_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.foreign_flow_events", "summary.takas_events"],
        "input_paths": ["local/flow_inputs"],
    },
    "quality_kap_events": {
        "kind": "consumer", "expected": "active",    # KAP finansal olay akisi CALISIYOR
        "file": "docs/state/quality_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.source_meta.kap_financial_events"],
        "input_paths": [],
        "upstream": ["docs/state/catalysts.json (kap_feed dugumunde izleniyor)"],
    },
    "quality_metrics_parser": {
        "kind": "consumer", "expected": "planned",   # KAP finansal tablo parser YAZILMADI
        "file": "docs/state/quality_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.source_meta.n_companies"],
        "input_paths": ["local/kap_financials", "local/kap_financial_actuals.json"],
    },
    "macro_surprise_ledger": {
        # 2026-08-13: "planned" -> "active". Etiket BAYATTI: 08-06'da 259 olay
        # yuklendi (`macro_surprise_sources.json`), uye GREEN uretiyor.
        # ⚠️ SADECE ETIKET DOGRULUGU — DAVRANIS DEGISMEZ (izole test edildi):
        #   girdi VAR -> active/planned ikisi de GREEN
        #   girdi YOK -> ikisi de YELLOW "YARIM CALISIYOR: 259 kayit uretiyor
        #                ama girdi-yolu yok"
        # Cunku `expected`a bakan dal YALNIZ kayit SIFIRKEN calisir; 259 kayitli
        # uye oraya hic ulasmaz. Ilk gerekcem ("kaybolursa RED verir") YANLISTI.
        "kind": "consumer", "expected": "active",
        "file": "docs/state/macro_surprise_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["docs/state/macro_surprise_sources.json"],
    },
    "broker_bulletin_ledger": {
        "kind": "consumer", "expected": "planned",   # private input hic konmadi
        "file": "docs/state/broker_bulletin_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["local/broker_bulletins"],
    },
    "missed_opportunities": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/missed_opportunities.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "tz": PRODUCER_TZ_OFFSET_H,
        "schedule": "daemon_cycle",
        "count_keys": ["summary.tracked_days", "summary.hot_missed_count"],
        "input_paths": [],
    },
    # ---- IZLEYENIN IZLEYENI (12. uye, 2026-07-22) ----
    # Bekci 40 kosuda 0 kez calisti ve kimse fark etmedi: bekcinin heartbeat'i
    # yoktu, sessizligi "saglikli/olu/kurulmamis" arasinda ayrilamiyordu.
    # Artik bekci her kosuda kendi izini yaziyor; burasi onu izler.
    # KABA + BAGIMSIZ kontrol (check_mode=raw_age): paylasilan slot/TZ mantigi
    # KULLANILMAZ -> ortak-mod ariza yok (ikisi ayni yonde yanilip birbirini
    # onaylayamaz). tz=0: bekci utcnow ile yazar, daemon damgalarindan farkli eksen.
    "watchdog": {
        "kind": "watchdog",
        "expected": "active",
        "file": "docs/state/watchdog.json",
        "ts_keys": ["updated_at"],
        "tz": 0.0,
        "check_mode": "raw_age",
        "raw_max_age_h": 72,
        "note": "bekci (liveness_watchdog.py) her precise kosusunda yazar; "
                "yazmiyorsa izleyeni-izleyen katmani olu",
    },
    # ---- ANLAMLILIK TARAYICISI (13. uye, 2026-07-22, HENUZ BAGLANMADI) ----
    # content_sanity.py: canlilik degil ANLAMLILIK olcer (uretilen veri dolu+
    # tutarli mi). RS_GUN_5 tatil-deligi bugun panelin 3 bolumunu bosaltti ve
    # hicbir canlilik-gostergesi bunu gormedi -> bu tarayici o eksigi kapatir.
    # expected="planned": HENUZ BIR WORKFLOW'A BAGLANMADI (bkz ACIK_ISLER #0g ①).
    # Bagli olmadigi surece dosya YOK -> _ever_written ile SARI "yeni uye" (gorunur,
    # unutulmaz). Baglanip ilk yazdiginda kendi verdict'ini yansitir; DOGRULANINCA
    # active'e cekilir (otomatik degil -- expected statik alan, elle flip).
    # NOT: "yazinca otomatik active" YANLIS varsayimdi; otomatik olan yalniz
    # _ever_written'in yeni-uye-SARI'si.
    "content_sanity": {
        "kind": "scanner",
        # 2026-08-13: "planned" -> "active". Not BAYATTI: `precise.yml:87`
        # (`python3 scripts/content_sanity.py`) ile workflow'a BAGLI ve uretiyor.
        # Yukaridaki "active'e cekilir (elle flip)" talimati unutulmustu — satir
        # ~659'un uyardigi "biri unutur, uye sonsuza dek planned kalir" vakasi.
        # DAVRANIS DEGISMEZ: `input_paths` YOK -> `_input_state` "n/a" doner ->
        # `expected` hicbir dala girmez. Bu duzeltme YALNIZ yaniltici etiketi
        # kaldirir (kozmetik). Girdi-yolu eklenirse davranissal hale gelir.
        "expected": "active",
        "file": "docs/state/content_sanity.json",
        "ts_keys": ["updated_at"],
        "tz": 0.0,                     # content_sanity utcnow ile yazar
        "check_mode": "own_verdict",
        "raw_max_age_h": 72,
        "note": "anlamlilik denetimi; precise.yml ile kosuyor (aktif)",
    },
    # 14. UYE — STOP-DEGERLENDIRME IZI (#0l ile BIRLIKTE dogar).
    #
    # NEDEN AYRI PROGRAM (close_only): #0l sonrasi stop YALNIZ kapanis kosusunda
    # degerlendirilir. `daemon_cycle` uc slotu birlikte saydigi icin, yalniz
    # kapanis kacarsa 11:30 kosusu diger damgalari tazeler ve kacak GORUNMEZ --
    # ama o gun stop HIC degerlendirilmemis olur. Stop = ayi korumasinin tek
    # kolonu (#0m) -> bu, tasiyici kolonda sessiz bosluk demekti.
    #
    # NEDEN AYRI DOSYA (portfolio_F degil): F-state'e uretici-damgasi yazmak
    # F-yakinlik sinirini asardi (schema_version dersi). Damga IZ'dir, KARAR
    # DEGIL -- hicbir kod buna bakip davranis degistirmez.
    #
    # ILK GECIS: dosya ilk kapanis kosusuna kadar YOK -> _ever_written sayesinde
    # "YENI UYE ... henuz hic yazilmadi" = SARI (sahte KIRMIZI uretmez).
    "stop_eval": {
        "kind": "producer",
        "expected": "active",
        "file": "docs/state/stop_eval.json",
        "ts_keys": ["updated_at"],
        "tz": 0.0,                     # shadow._write_stop_eval utcnow ile yazar
        "schedule": "close_only",
        "note": "stop en son ne zaman/hangi bar icin degerlendirildi (#0l izi)",
    },
}



def _get(d, dotted):
    """'summary.updated_at' gibi noktali anahtari cozer."""
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _first(d, keys):
    for k in keys:
        v = _get(d, k)
        if v not in (None, "", []):
            return v, k
    return None, None


def _age_hours(ts, tz_offset_h=0.0):
    """
    ISO ya da YYYY-MM-DD damgasini saat-yasina cevirir. Hesap UTC ekseninde.

    tz_offset_h: damganin yazildigi eksenin UTC'ye gore ofseti (TR = +3).
    Damga naive; UTC'ye cevirmek icin ofset CIKARILIR.

    ---------------------------------------------------------------------------
    TZ NOTU (2026-07-18 yazildi, 2026-07-22 CURUTULDU -- ders burada)

    ESKI IDDIA: "tum damgalar CLOUD'da (GitHub Actions = UTC) uretiliyor ->
    naive ama fiilen UTC" -> bu yuzden utcnow ile karsilastir.

    NEDEN YANLISTI: uretici damgalari `daemon.py` icinde `datetime.now()` ile
    yaziliyor VE o workflow adiminda `TZ: Europe/Istanbul` set edilmis
    (bist-alpha.yml, precise.yml, catalyst.yml). Yani damgalar TR saati (UTC+3).
    Runner'in VARSAYILANINA baktim, workflow'un ACIK gecersiz kilmasina degil --
    ara-gostergeye bakip ground-truth'u atlamak. Ustelik now()->utcnow()
    degisikligi CI'da hicbir seyi degistirmedi (ikisi de UTC'ydi orada); yalniz
    yerel davranisi degistirdi. Gercek uyusmazlik hep oradaydi.

    SONUCU: 11 uyenin hepsinde yas 3 SAAT EKSIK. 5h araliktaki slotlarda
    (7/12/16 UTC, grace 4h) bu bir KACAN SLOTU GIZLEYEBILIR = alarm korlugu.

    DUZELTME: registry her uyenin `tz` alanini tasir; hesap burada UTC'ye
    normalize edilir. Uretici (daemon.py) DEGISTIRILMEZ -- F zincirine yakin.
    ---------------------------------------------------------------------------
    NEGATIF YAS = IMKANSIZLIK, SUSTURULMAZ (2026-07-22)

    Eskiden `max(0.0, ...)` vardi: negatif yasi 0.0'a kirpiyordu. Bu, YUKARIDAKI
    TZ bug'ini "0.0h = yepyeni = GREEN" diye raporladi -- yani bir KORUMA, baska
    bir BUG'I GIZLEDI ve bug'i en-saglikli gosterdi. Negatif yas gelecekten-damga
    demektir: TZ hatasi, saat kaymasi ya da veri bozulmasi isareti. Artik
    kirpilmaz; None yerine negatif deger dondurulur ve check() bunu RED yapar.
    ---------------------------------------------------------------------------
    COZUNURLUK NOTU (2026-07-18): tarih-only damga ("2026-07-17") 00:00
    sayilirsa, o GUNUN kendi slotlari "kacmis" gorunur -> sahte-KIRMIZI. Cozum:
    saat bilinmiyorsa GUN-SONU'na yorumla (en-lehte okuma).
    Kayit-defterinde her zaman once SAAT-HASSAS alani yaz (ts_keys sirasi).
    """
    if not ts:
        return None
    s = str(ts).strip()
    now = datetime.utcnow()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:len(now.strftime(fmt))], fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=23, minute=59, second=59)
            dt -= timedelta(hours=tz_offset_h)       # damga ekseni -> UTC
            return (now - dt).total_seconds() / 3600.0   # NEGATIF KIRPILMAZ
        except ValueError:
            continue
    return None


def _raw_age_hours(ts):
    """
    KABA + BAGIMSIZ yas hesabi. `_age_hours`'i BILEREK KULLANMAZ.

    NEDEN AYRI (ortak-mod ariza onleme, 2026-07-22): bekci tarayiciyi izliyor,
    tarayici da bekciyi izleyecek. Ikisi AYNI yas/TZ mantigini paylasirsa, o
    mantik bozuldugunda ikisi de AYNI YONDE yanilir ve birbirini "dogru" diye
    onaylar -- bu turda birebir yasandi (TZ hatasi hem tarayiciyi hem bekcinin
    B3'unu vurdu, cunku ayni eksen varsayimini paylasiyorlardi).

    Bu yuzden: slot kutuphanesi YOK, tz-ofset YOK, gun-sonu yorumu YOK.
    Yalniz "ISO damga, UTC kabul, kac saat gecti". Bekci dosyayi utcnow ile
    yazdigi icin ofset sorusu zaten dogmaz.
    """
    try:
        dt = datetime.strptime(str(ts).strip()[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None
    return (datetime.utcnow() - dt).total_seconds() / 3600.0


def _check_scanner_verdict(name, cfg, d, row):
    """
    KENDI VERDICT'INI yazan tarayici uyesi (content_sanity gibi). KABA + BAGIMSIZ
    yas (watchdog ile ayni ortak-mod onlemesi: paylasilan _age_hours/slot mantigi
    KULLANILMAZ). tz=0 varsayilir (bu tarayicilar utcnow ile yazar).

    Iki katman: (1) tarayici CANLI mi (yas < esik, negatif degil), (2) tarayicinin
    KENDI verdict'i ne (GREEN/YELLOW/RED). Olu tarayici -> RED; canli+RED-diyor ->
    RED; canli+YELLOW -> YELLOW; canli+GREEN -> GREEN.
    """
    age = _raw_age_hours(row.get("timestamp"))
    row["age_hours"] = round(age, 1) if age is not None else None
    row["check_mode"] = "own_verdict (kaba+bagimsiz)"
    if age is None:
        row.update(status="RED", reason=f"damga cozulemedi: {row.get('timestamp')!r}")
        return row
    if age < -0.2:
        row.update(status="RED", reason=f"damga GELECEKTEN: {age:.1f}h")
        return row
    if age > cfg["raw_max_age_h"]:
        row.update(status="RED",
                   reason=f"TARAYICI DURDU: son iz {age:.0f}h once (> {cfg['raw_max_age_h']}h)")
        return row
    v = d.get("verdict")
    row["scanner_verdict"] = v
    row["scanner_problems"] = [p[0] if isinstance(p, list) else p for p in (d.get("problems") or [])]
    if v == "RED":
        row.update(status="RED", reason=f"tarayici RED: {', '.join(row['scanner_problems']) or '?'}")
    elif v == "YELLOW":
        row.update(status="YELLOW", reason=f"tarayici YELLOW: {', '.join(row['scanner_problems']) or '?'}")
    elif v == "GREEN":
        row.update(status="GREEN", reason=f"tarayici canli ({age:.0f}h once), verdict=GREEN")
    else:
        row.update(status="RED", reason=f"gecersiz verdict: {v!r}")
    return row


def _check_watchdog(name, cfg, d, row):
    """
    12. UYE: bekcinin kendi izi. KABA esik (B3 dersinin tekrari: kabalik ozellik).

    ESIK NEDEN 72h: bekci precise.yml'de hafta-ici 3 slot kosar (06:45/11:30/
    15:40 UTC). En uzun MESRU bosluk Cuma 15:40 -> Pzt 06:45 = ~63h. 72h, hicbir
    hafta-sonunun yanlis-alarm uretmeyecegi ilk guvenli esik. Hafta-ici bir
    olumu ~3 gunde yakalar: YAVAS ama BAGIMSIZ -- ve bu bir IKINCIL hatti
    (daemon olumu tarayicidan ~22h'te, tarayici olumu bekciden ayni gun cikar).
    Hizli+paylasilan-mantik yerine yavas+bagimsiz TERCIH EDILDI.
    """
    age = _raw_age_hours(row.get("timestamp"))
    row["age_hours"] = round(age, 1) if age is not None else None
    row["check_mode"] = "raw_age (kaba+bagimsiz)"
    if age is None:
        row.update(status="RED", reason=f"bekci damgasi cozulemedi: {row.get('timestamp')!r}")
        return row
    if age < -0.2:
        row.update(status="RED", reason=f"bekci damgasi GELECEKTEN: {age:.1f}h")
        return row
    lim = cfg["raw_max_age_h"]
    if age > lim:
        row.update(status="RED",
                   reason=f"BEKCI DURDU: son iz {age:.0f}h once (> {lim}h) — "
                          f"izleyeni-izleyen katmani olu")
        return row
    # Bekci calisiyor. Kendi raporladigi sonucu da yansit (sessiz mi, alarm mi).
    sonuc = d.get("sonuc")
    gord = d.get("gordugu") or {}
    row["watchdog_sonuc"] = sonuc
    row["watchdog_gordugu"] = gord
    if sonuc == "ALARM":
        row.update(status="RED",
                   reason=f"bekci ALARM veriyor: {', '.join(d.get('problem_kodlari') or [])}")
        return row
    neg = gord.get("negatif_yas_sayisi")
    if isinstance(neg, int) and neg > 0:
        row.update(status="RED",
                   reason=f"bekci sessiz AMA {neg} uyede negatif yas gormus — sahte-yesil")
        return row
    row.update(status="GREEN",
               reason=f"bekci canli ({age:.0f}h once), sonuc={sonuc}, "
                      f"gordugu: liveness verdict={gord.get('liveness_verdict')} "
                      f"{gord.get('liveness_checks')} uye")
    return row


def _input_state(paths):
    """
    'YOK' ile 'GOREMIYORUM' ayrimi — negatif-kanit zayiftir.
    Returns: ("missing"|"empty"|"present", detay)
    """
    if not paths:
        return "n/a", ""
    seen_present = False
    missing = []
    for p in paths:
        fp = ROOT / p
        if not fp.exists():
            missing.append(p)
            continue
        if fp.is_dir():
            if any(fp.iterdir()):
                seen_present = True
        else:
            try:
                raw = json.loads(fp.read_text(encoding="utf-8"))
                if raw and (not isinstance(raw, dict) or any(
                        isinstance(v, list) and v for v in raw.values())):
                    seen_present = True
            except Exception:
                seen_present = True  # okunamiyor ama VAR -> bos sayma
    if seen_present:
        return "present", "girdi mevcut"
    if missing and len(missing) == len(paths):
        return "missing", "girdi-yolu YOK: " + ", ".join(missing)
    return "empty", "girdi-yolu var, icerik bos"


def _ever_written_map():
    """
    "HIC YAZILMADI" ile "YAZIYORDU, DURDU" ayrimi icin kalici hafiza.

    NEDEN (2026-07-22): 12. uye (watchdog) eklendiginde damga dosyasi henuz
    yoktu -> KIRMIZI + "bir zamanlanmis is DURMUS olabilir" alarmi gitti. Ama
    duran bir is YOKTU; uye yeniydi ve ilk yazimini bekliyordu. Bu, defterlerde
    zaten cozdugumuz "BOS-normal vs KIRIK" ayriminin REGISTRY hali -- ust
    katmanda cozulmemisti. Registry'ye eklenecek her yeni uye (scheduler-last-run,
    G1-reentry...) ayni yaniltici KIRMIZI'yi uretecekti.

    NEDEN OTOMATIK: gecisi elle yapmak (planned -> active) yeni bir SESSIZ
    KORLUK kaynagi olurdu -- biri unutur, uye sonsuza dek "planned" kalir ve
    gercekten kirildiginda da SARI gorunur. Bu yuzden turetiliyor.

    NEDEN DOSYA-VARLIGI YETMEZ: "dosya var mi" ile bakarsak, bir kez yazip
    sonra SILINEN dosya tekrar "yeni uye" sayilir ve sessizlesir. Bu yuzden
    hafiza bir onceki liveness.json'dan tasiniyor (o dosya her kosuda commit
    edilir, yani kalicidir).
    """
    prev = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        for c in old.get("checks", []):
            nm = c.get("name")
            if not nm:
                continue
            # Ya acikca isaretlenmis, ya da o kosuda gecerli damgasi vardi.
            prev[nm] = bool(c.get("ever_written") or c.get("timestamp"))
    except Exception:
        pass
    return prev


def check(name, cfg, ever_prev=None):
    f = ROOT / cfg["file"]
    row = {"name": name, "kind": cfg["kind"], "expected": cfg["expected"],
           "file": cfg["file"], "note": cfg.get("note", "")}
    ever = bool((ever_prev or {}).get(name))

    if not f.exists():
        row["ever_written"] = ever
        if not ever:
            # HIC yazilmadi: yeni kayitli uye, ilk yazimini bekliyor. SARI.
            # (Sessiz degil -- gorunur kalir; ama KIRMIZI degil -- alarm-korlugu
            #  uretmez ve "durmus is" diye yanlis okunmaz.)
            row.update(status="YELLOW",
                       reason="YENI UYE: henuz hic yazilmadi, ilk yazimini bekliyor "
                              "(durmus is DEGIL)")
            return row
        # Daha once yaziyordu, simdi dosya YOK -> gercek arıza.
        row.update(status="RED",
                   reason="daha once yaziyordu, damga dosyasi ARTIK YOK -> "
                          "uretici DURDU ya da dosya silindi")
        return row
    row["ever_written"] = True

    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        row.update(status="RED", reason=f"damga dosyasi okunamadi: {e}")
        return row

    ts, ts_key = _first(d, cfg["ts_keys"])
    row.update(timestamp=ts, ts_key=ts_key)

    if ts is None:
        row.update(status="RED", reason="zaman damgasi YOK (canlilik olculemez)")
        return row

    # --- 12. uye (bekci): KABA + BAGIMSIZ yol ---------------------------------
    # DALLANMA BURADA, _age_hours'DAN ONCE. Sonraya koyulursa bagimsizlik
    # SAHTE olur: paylasilan yas/TZ mantigi bozuldugunda bu uye de ona takilip
    # RED verir -> tarayici ile bekci AYNI YONDE yanilir = ortak-mod ariza,
    # yani onlemek icin kurdugumuz seyin ta kendisi.
    # (2026-07-22: ilk yazimda dallanma _age_hours'tan SONRAYDI; ortak-mod
    #  mutasyon testi bunu yakaladi.)
    if cfg.get("check_mode") == "raw_age":
        return _check_watchdog(name, cfg, d, row)
    if cfg.get("check_mode") == "own_verdict":
        return _check_scanner_verdict(name, cfg, d, row)

    tz_off = cfg.get("tz", 0.0)
    age = _age_hours(ts, tz_off)
    row.update(tz_offset_h=tz_off,
               age_hours=(round(age, 1) if age is not None else None))
    if age is None:
        row.update(status="RED", reason=f"damga cozulemedi: {ts!r}")
        return row
    # NEGATIF YAS = GELECEKTEN DAMGA = IMKANSIZLIK -> susturma, BAGIR.
    # (2026-07-22: eskiden max(0.0,..) ile kirpiliyordu; o kirpma TZ bug'ini
    #  "0.0h = yepyeni = GREEN" diye gizledi. Bir koruma baska bir bug'i orttu.)
    # -0.2h tolerans: uretici ile tarayici arasindaki saniyelik saat kaymasi.
    if age < -0.2:
        row.update(status="RED",
                   reason=f"GELECEKTEN damga: yas {age:.1f}h < 0 (damga {ts}, "
                          f"tz-ofset {tz_off}h) — TZ hatasi/saat kaymasi/veri bozulmasi")
        return row
    age = max(0.0, age)
    # --- TAKVIM-FARKINDA BAYATLIK: kacirilan SLOT say (sabit saat esigi DEGIL) ---
    sched = SCHEDULES[cfg["schedule"]]
    last_dt = datetime.utcnow() - timedelta(hours=age)
    missed = _missed_slots(last_dt, datetime.utcnow(), sched)
    row["schedule"] = cfg["schedule"]
    row["missed_slots"] = missed
    who = "kaynak" if cfg["kind"] == "producer" else "daemon/defter"
    if missed >= 2:
        row.update(status="RED",
                   reason=f"{missed} zamanlanmis slot KACTI ({who} durdu) "
                          f"[{cfg['schedule']}, yas {age:.0f}h]")
        return row
    if missed == 1:
        row.update(status="YELLOW",
                   reason=f"1 slot kacti — gecici olabilir, izle [{cfg['schedule']}, yas {age:.0f}h]")
        return row

    # Uretici: ok-alani da olculmus olmali
    if cfg["kind"] == "producer":
        okk = cfg.get("ok_key")
        if okk:
            val = _get(d, okk)
            if val != cfg.get("ok_value"):
                row.update(status="RED", reason=f"uretici hata bildiriyor: {okk}={val!r}")
                return row
        row.update(status="GREEN", reason="taze + saglikli")
        return row

    # Tuketici: bosluk-anlami (yok vs goremiyorum)
    n, _ = _first(d, cfg.get("count_keys", []))
    n = n if isinstance(n, int) else 0
    row["events"] = n
    inp, detail = _input_state(cfg.get("input_paths", []))
    row["input_state"] = inp
    if n > 0:
        # #0j-EK ② (2026-08-06): `n > 0` ESKIDEN her seyi KISA DEVRE yapiyordu —
        # input_state kayda yaziliyor ama KARARA girmiyordu. Sonuc: YARIM calisan
        # defter YESIL gorunuyordu (flow'un yabanci-akis yarisi yok, yine GREEN).
        # Artik girdi-yolu beyan edilmis ama YOKSA sari: "uretiyor ama yarim".
        # NOT: girdi-yolu beyan etmeyen uyeler etkilenmez (_input_state([]) -> "n/a").
        if inp == "missing":
            row.update(status="YELLOW",
                       reason=f"YARIM CALISIYOR: {n} kayit uretiyor ama {detail}")
        else:
            row.update(status="GREEN", reason=f"taze, {n} kayit")
    elif inp == "missing":
        if cfg["expected"] == "active":
            row.update(status="RED", reason=f"CONFIG-KIRIK: {detail}")
        else:
            row.update(status="YELLOW", reason=f"kurulmadi (planned): {detail}")
    elif inp == "present":
        row.update(status="RED",
                   reason="SESSIZ-YUTMA SUPHESI: girdi VAR ama events=0")
    else:
        row.update(status="YELLOW", reason=f"beklenen bosluk ({detail or 'girdi yok'})")
    return row


def _slot_source_row():
    """SLOT KAYNAGININ KENDISI izlenir — "koruma kendini korumadan muaf sanir"
    panzehiri. Slot artik turetiliyor, ama turetme ZINCIRI de bozulabilir:
    kaynak import edilemez, cron silinir, ya da iki uretici kopyasi AYRISIR
    (biri degistirilip digeri unutulur). Bunlarin hicbiri damga birakmaz —
    "yoklugun imzasi yok" -> ayri bir uye olarak GORUNUR yapiliyor.
    """
    row = {"name": "slot_source", "kind": "meta", "expected": "active",
           "file": "(kod) scripts/report_gate.SLOTS <-> precise_runner.SLOT_TR",
           "ever_written": True, "schedule": None, "missed_slots": None,
           "slots_utc": {"daemon_cycle": [list(x) for x in _DAEMON_SLOTS],
                         "close_only": [list(x) for x in _CLOSE_SLOTS],
                         "kap_daily": [list(x) for x in _KAP_SLOTS]}}
    if _SLOT_ISSUES:
        row.update(status="RED", reason="SLOT KAYNAGI BOZUK: " + " | ".join(_SLOT_ISSUES))
    else:
        row.update(status="GREEN",
                   reason=(f"slot kaynagi tek ve tutarli (TR {_SLOTS_TR} -> UTC "
                           f"{list(_DAEMON_SLOTS)}; kap cron {list(_KAP_SLOTS)})"))
    return row


def main():
    # "hic yazilmadi" vs "yaziyordu durdu" ayrimi icin onceki taramanin hafizasi
    ever_prev = _ever_written_map()
    rows = [check(n, c, ever_prev) for n, c in REGISTRY.items()]
    rows.append(_slot_source_row())
    red = [r for r in rows if r["status"] == "RED"]
    yellow = [r for r in rows if r["status"] == "YELLOW"]
    payload = {
        # Tarayicinin KENDI damgasi — "izleyeni izleyen yok" regresyonu burada durur.
        # UTC (naive): tum uretici damgalari CI/UTC; ayni eksende olsun (bkz _age_hours TZ notu).
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "tz": "UTC",
        "scanner": "scripts/liveness_scan.py",
        "verdict": "RED" if red else ("YELLOW" if yellow else "GREEN"),
        "red_count": len(red), "yellow_count": len(yellow), "total": len(rows),
        "checks": rows,
        "note": "Zamanlanmis her mekanizmanin 'son ne zaman calisti' denetimi. "
                "Registry-gudumlu: yeni dis-kaynak eklenip damga yazmazsa RED.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        icon = {"GREEN": "OK ", "YELLOW": "?? ", "RED": "!! "}
        for r in sorted(rows, key=lambda x: {"RED": 0, "YELLOW": 1, "GREEN": 2}[x["status"]]):
            age = f"{r['age_hours']}h" if r.get("age_hours") is not None else "-"
            print(f"  {icon[r['status']]}{r['name']:<24} [{r['kind'][:4]}/{r['expected'][:6]}] "
                  f"yas={age:<7} {r['reason']}")
        print(f"\nHEALTH: liveness verdict={payload['verdict']} "
              f"red={len(red)} yellow={len(yellow)} total={len(rows)}")
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
