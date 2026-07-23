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
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "docs" / "state" / "dashboard.json"
OUT = ROOT / "docs" / "state" / "content_sanity.json"

# Esikler. Normal select_valid_count ~581; tatil-deligi ~2-17'ye dusuruyor.
# 100: normal ile anomali arasinda genis guvenli bant (gozlenen en yuksek
# zehirli deger 17, en dusuk normal ~200+). Kaba ve emin -- taban-lock/DSTKF
# esiklerindeki gibi kabalik OZELLIK.
VALID_MIN = 100
# Tam radar cikitisi bu anahtarlari tasir; erken-cikista duser. Sabit sayi
# KARAR VERMEZ (config-kirilgan); yalnizca ANAHTAR VARLIGI teyit-edici.
RADAR_FULL_KEYS = ("radar_universe_count", "trade_universe_count")


def check(d):
    problems = []
    valid = d.get("select_valid_count")
    top10 = d.get("top10")
    top10_n = len(top10) if isinstance(top10, list) else None
    wl = d.get("watchlists") or {}
    data_ok = d.get("bist_data_ok")
    price_count = d.get("price_count")

    # --- BIRINCIL: kok metrik (yeterli gecerli bar) ---
    # valid None ise: alan henuz yok (reporter guncellenmeden yazilmis eski
    # state). Bu TEK BASINA anomali DEGIL -- yalniz "kok metrigi goremiyorum"
    # demek; ikincil sinyaller (C/celiski, D/radar) zaten uretim-cokusunu
    # yakaliyor. Kosulsuz YELLOW yanlis-alarm olurdu (saglikli eski state'lerde
    # de tetiklenir). "YOK" ile "KIRIK" ayrimi (bugunun tekrar eden dersi):
    # alan-yoklugu susmayi degil, ikincile-birakmayi gerektirir.
    if isinstance(valid, (int, float)) and valid < VALID_MIN:
        problems.append(("B/VALID_DUSUK",
                        f"select_valid_count={valid} < {VALID_MIN}: gecerli-bar "
                        f"cokmus (tatil-deligi?) -> secim coplerle karar verebilir"))

    # --- IKINCIL/TEYIT: uretim BOS ama veri SAGLIKLI celiskisi ---
    # (canlilik-yesil + anlamlilik-kirmizi = tam bugunku durum)
    veri_saglikli = bool(data_ok) and isinstance(price_count, int) and price_count >= 50
    if top10_n == 0 and veri_saglikli:
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
        if eksik and listeler_bos:
            problems.append(("D/RADAR_ERKEN_CIKIS",
                            f"radar tam kosmadi: {', '.join(eksik)} yok ve tum "
                            f"izleme listeleri bos -> build_watchlists erken cikti"))

    return problems, {"select_valid_count": valid, "top10": top10_n,
                      "watchlists_keys": sorted(wl.keys()) if wl else [],
                      "bist_data_ok": data_ok, "price_count": price_count}


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
    print(f"{icon}content_sanity: {verdict} | valid={gozlem['select_valid_count']} "
          f"top10={gozlem['top10']} watchlists_keys={len(gozlem['watchlists_keys'])}")
    for k, m in problems:
        print(f"   [{k}] {m}")
    # RED -> exit 1 (rebalans-durdur / alarm icin); YELLOW -> gorunur ama bloklamaz
    return 1 if verdict == "RED" else 0


def _write(payload):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
