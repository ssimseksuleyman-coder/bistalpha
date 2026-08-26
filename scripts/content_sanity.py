#!/usr/bin/env python3
"""
İÇERİK-ANOMALİ TARAYICI — "canlilik degil, ANLAMLILIK".

NEDEN (2026-07-22): tatil-deligi (RS_GUN_5) bir karar gununu vurdu -> score()
valid=2 -> top10 BOSALDI, radar erken-cikti, panelin UC bolumu birden bos
kaldi. VE HICBIR ALARM CALMADI: bist_data_ok=true, price_count=612, son satir
%0 NaN, evren=100 -- her canlilik gostergesi YESILDI. Kullanici panele bakip
fark etti, sistem degil.

Mevcut izleme (liveness/bekci) bunu goremez cunku hepsi CANLILIK olcer (damga
taze mi, mekanizma kostu mu). Bu tarayici ANLAMLILIK olcer: uretilen veri DOLU
ve TUTARLI mi. Ayri eksen, ayri tarayici.

TASARIM (blast-radius dersinden):
  - GUARD GIRDI TARAFINDA (kok), cikti tarafinda DEGIL. Delik hem select'i hem
    radar'i vurdu; radar select KULLANMIYOR ama ayni bar-geçerliligine dayaniyor.
    Ortak kok = GECERLI-BAR sayisi (select_valid_count). Onu izle -> ikisini de
    yakala. Cikti-guard'i (yalniz top10) radar'i kacirirdi.
  - BIRINCIL: select_valid_count (kok, reporter yazar). Esik alti -> RED.
  - IKINCIL/TEYIT: uretim-bos AMA veri-saglikli CELISKISI (top10=0 iken
    bist_data_ok=true + price_count normal). Iki bagimsiz gosterge capraz-dogrular.
  - watchlists anahtar sayisi (tam 7 / erken-cikis 4) ek imza -- ORANSAL/varlik,
    sabit "7" DEGIL (config degisirse kayar = slot-hard-code sinifi).

F'e SIFIR dokunus: yalniz docs/state/dashboard.json okur, docs/state'e yazar.
Cikis: 0 = anomali yok, 1 = anomali (workflow/daemon alarmi icin).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "docs" / "state" / "dashboard.json"
OUT = ROOT / "docs" / "state" / "content_sanity.json"

# --- ORANSAL esikler (MUTLAK DEGIL, 2026-07-23) -------------------------------
# ESKI: VALID_MIN=100 mutlak. Sorun: sabit, gercegin (evren-boyutu) proxy'si;
# evren kuculurse yanlislanir = slot-hard-code/TZ-ofset sinifi. ORANSAL cozum:
# olculen taban valid/price = 581/612 = %95; tatil-deligi <%3 -> %50 devasa marj,
# evren-boyutundan BAGIMSIZ.
VALID_RATIO_MIN = 0.5        # PAY: valid/price_count -- veri-TAMLIK (RS5 deligi)

# PAYDA KOR-NOKTASI (kullanici, 2026-07-23): oran pay+payda BIRLIKTE cokerse kor
# kalir. yfinance 612->20 doner, 19 gecerli -> valid/price=%95 -> GREEN, ama F
# 20 hisselik evrenden secim yapiyor = kirik. Gosterge olctugu seyle birlikte
# hareket edebiliyor (bugunun 5. tekrari). COZUM: BAGIMSIZ payda referansi.
# source_pool_count (TradingView taramasi) yfinance-fiyatlarindan AYRI kaynak ->
# yfinance cokse bile pool ~614 kalir -> price/pool=%3 -> RED. Mutlak sabit YOK.
COVERAGE_RATIO_MIN = 0.5     # PAYDA: price_count/source_pool_count -- fetch-KAPSAMA
# KALAN BOSLUK (bir sonraki tur, KAYITLI): ikisi de coker (tarama+yfinance
# birlikte) -> price/pool sabit -> yine kor. Gercek cozum: kendi-gecmis-medyani
# (source_pool_count'un son N kosu medyani). Bugun ertelendi -- ACIK_ISLER #0g.

# ZAMANA-BAGLI None kurali: select_valid_count propagation duzeltmesi (24526c7)
# 2026-07-23 canli dustu. Bu tarihten SONRA her dashboard alani TASIMALI; yoksa
# = propagation KIRIK. Oncesi (eski state) = normal, sessiz. "Ayni yokluk,
# duzeltme oncesi normal / sonrasi ariza" = yok!=kirik'in zamana-bagli hali.
# 07-24: alan bugun (07-23) dustu; bugunku GECIS dashboard'larinin bir kismi
# fix-oncesi. 07-24'ten emin.
FIX_ANCHOR = "2026-07-24"

# Tam radar cikitisi bu anahtarlari tasir; erken-cikista duser. Sabit sayi
# KARAR VERMEZ (config-kirilgan); yalnizca ANAHTAR VARLIGI teyit-edici.
RADAR_FULL_KEYS = ("radar_universe_count", "trade_universe_count")


def _ratio(num, den):
    if isinstance(num, (int, float)) and isinstance(den, (int, float)) and den:
        return num / den
    return None


def check(d):
    problems = []
    valid = d.get("select_valid_count")
    top10 = d.get("top10")
    top10_n = len(top10) if isinstance(top10, list) else None
    wl = d.get("watchlists") or {}
    data_ok = d.get("bist_data_ok")
    price_count = d.get("price_count")
    pool = d.get("source_pool_count")
    dash_date = str(d.get("date") or d.get("timestamp") or "")[:10]

    valid_ratio = _ratio(valid, price_count)
    coverage_ratio = _ratio(price_count, pool)
    semantic = d.get("semantic_health") or (d.get("operation_health") or {}).get("semantic_health") or {}
    semantic_blocked = (
        isinstance(semantic, dict)
        and str(semantic.get("verdict", "")).lower() == "red"
        and bool(semantic.get("blocked", False))
    ) or bool(d.get("top10_suppressed")) or bool((wl or {}).get("suppressed"))

    # --- BIRINCIL (PAY): veri-TAMLIK, oransal ---
    if valid_ratio is not None:
        if valid_ratio < VALID_RATIO_MIN:
            problems.append(("B/VALID_DUSUK",
                f"valid/price={valid_ratio:.2f} < {VALID_RATIO_MIN} "
                f"(valid={valid}/price={price_count}): gecerli-bar cokmus "
                f"(tatil-deligi?) -> secim coplerle karar verebilir"))
    elif valid is None and dash_date >= FIX_ANCHOR:
        # ZAMANA-BAGLI None kurali: alan FIX_ANCHOR sonrasi olmali; yoksa kirik.
        problems.append(("B/METRIK_YOK",
            f"select_valid_count YOK ama dashboard {dash_date} >= {FIX_ANCHOR} "
            f"-> propagation KIRIK (reporter->daemon zinciri)"))
    # (valid None ve dash_date < FIX_ANCHOR: eski state, SESSIZ -- yok!=kirik)

    # --- PAYDA KOR-NOKTASI: fetch-KAPSAMA (bagimsiz referans) ---
    if coverage_ratio is not None and coverage_ratio < COVERAGE_RATIO_MIN:
        problems.append(("B/EVREN_COKTU",
            f"price/pool={coverage_ratio:.2f} < {COVERAGE_RATIO_MIN} "
            f"(price={price_count}/pool={pool}): veri kaynagi cokmus, evren "
            f"kuculdu -> F kucuk evrenden TOP_N seciyor (oran-kor-noktasi)"))

    # --- IKINCIL/TEYIT: uretim BOS ama veri SAGLIKLI celiskisi ---
    # (canlilik-yesil + anlamlilik-kirmizi = tam bugunku durum)
    veri_saglikli = bool(data_ok) and isinstance(price_count, int) and price_count >= 50
    if top10_n == 0 and veri_saglikli and not semantic_blocked:
        problems.append(("C/CELISKI",
                        f"top10 BOS ama veri saglikli gorunuyor "
                        f"(bist_data_ok={data_ok}, price_count={price_count}) "
                        f"-> URETIM coktu, CANLILIK gostergeleri bunu gizliyor"))

    # --- EK IMZA: radar erken-cikis (oransal, sabit-sayi degil) ---
    if wl:
        eksik = [k for k in RADAR_FULL_KEYS if k not in wl]
        listeler_bos = all(
            (not v) for k, v in wl.items() if isinstance(v, list)
        )
        if eksik and listeler_bos and not semantic_blocked:
            problems.append(("D/RADAR_ERKEN_CIKIS",
                            f"radar tam kosmadi: {', '.join(eksik)} yok ve tum "
                            f"izleme listeleri bos -> build_watchlists erken cikti"))

    return problems, {"select_valid_count": valid, "price_count": price_count,
                      "source_pool_count": pool,
                      "valid_ratio": round(valid_ratio, 3) if valid_ratio is not None else None,
                      "coverage_ratio": round(coverage_ratio, 3) if coverage_ratio is not None else None,
                      "top10": top10_n,
                      "semantic_blocked": semantic_blocked,
                      "semantic_reason": semantic.get("reason") if isinstance(semantic, dict) else None,
                      "watchlists_keys": sorted(wl.keys()) if wl else [],
                      "bist_data_ok": data_ok}


def main():
    now = datetime.utcnow().isoformat(timespec="seconds")
    if not DASH.exists():
        payload = {"updated_at": now, "tz": "UTC", "verdict": "RED",
                   "problems": [["A/DASHBOARD_YOK", "dashboard.json yok"]]}
        _write(payload)
        print("!! dashboard.json YOK")
        return 1

    d = json.loads(DASH.read_text(encoding="utf-8"))
    problems, gozlem = check(d)
    verdict = "RED" if any(k[0].startswith(("B/", "C/")) for k in problems) else \
              ("YELLOW" if problems else "GREEN")
    payload = {"updated_at": now, "tz": "UTC", "scanner": "scripts/content_sanity.py",
               "verdict": verdict, "gozlem": gozlem,
               "problems": [[k, m] for k, m in problems],
               "note": "Anlamlilik denetimi (canlilik DEGIL): uretilen veri dolu+tutarli mi."}
    _write(payload)

    icon = {"GREEN": "OK ", "YELLOW": "?? ", "RED": "!! "}[verdict]
    print(f"{icon}content_sanity: {verdict} | valid/price={gozlem['valid_ratio']} "
          f"price/pool={gozlem['coverage_ratio']} top10={gozlem['top10']}")
    for k, m in problems:
        print(f"   [{k}] {m}")
    # RED -> ANINDA Telegram: liveness gunde 1x tarar (17:00, kor-pencere #0h),
    # ama icerik-anomali rebalans-gununde SABAH kritik -> beklenemez. RED-yoksa
    # sus (gunluk liveness heartbeat zaten tasir; ek gurultu yok).
    if verdict == "RED":
        tail = ("\n(normal sinyal bilincli bloklandi; canlilik-yesil olsa da anlamlilik-kirmizi. "
                "Rebalans gunuyse kirli secim yayinlanmaz.)"
                if gozlem.get("semantic_blocked") else
                "\n(uretilen veri COKMUS; canlilik-yesil ama anlamlilik-kirmizi. "
                "Rebalans gunuyse copler-le karar riski.)")
        _notify("🔴 ANLAMLILIK ALARMI — content_sanity\n"
                + "\n".join(f"• [{k}] {m}" for k, m in problems)
                + tail)
    # RED -> exit 1 (rebalans-durdur / alarm icin); YELLOW -> gorunur ama bloklamaz
    return 1 if verdict == "RED" else 0


def _notify(text):
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


def _write(payload):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
