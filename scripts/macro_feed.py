#!/usr/bin/env python3
"""
MAKRO BESLEYICI — `docs/state/macro_surprise_sources.json`'i doldurur.

NEDEN: makro defteri (`macro_surprise_ledger.py`) iskelet olarak HAZIRDI ama
YAZICISI hic yoktu -> `sources: []` -> defter 20+ gundur bos. Iki tikac vardi:
  Tikac-1 (besleyici)  -> BU DOSYA cozer.
  Tikac-2 (konsensus)  -> EVDS PKA serileri cozer, ama ZAMAN SERISI ANAHTAR ISTER.

BU SURUM ANAHTARSIZ KOSAR ve YALNIZ `actual` uretir. `expected` alani
TAKILABILIR birakildi: anahtar konunca (EVDS_API_KEY) ayni betik doldurur.
=> Defter HUKUM URETMEZ (surprise yok). Bu bilinclidir ve gorunur:
   `expected_status` alani ve ozet sayaclari durumu acikca yazar.

F'E SIFIR DOKUNUS: `bist_alpha` import edilmez, yalnizca docs/state'e yazar.

Kullanim:
  python scripts/macro_feed.py --probe      # hicbir sey yazma, ne uretecegini goster
  python scripts/macro_feed.py --backfill   # seri basindan tam arsiv (idempotent)
  python scripts/macro_feed.py --verify     # bagimsiz kaynakla capraz-kontrol
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs" / "state" / "macro_surprise_sources.json"

# ── TUIK YAYIN TAKVIMI ───────────────────────────────────────────────────────
# Olayin tarihi = REFERANS AYI DEGIL, YAYIN GUNU. Forward-getiri yayindan
# itibaren olculur; referans ayini kullanmak ~1 ay look-ahead demek olurdu.
# TUIK TUFE'yi izleyen ayin 3'unde 10:00'da yayimlar; 3'u hafta sonuna
# denk gelirse ilk is gunune kayar.
# DOGRULANDI (2026-08-06, bagimsiz kaynak): EconomicCalendar 2026-08-03'te
# "Enflasyon Orani (Aylik) %1,78 / (Yillik) %31,75" gosteriyor; Inflation()
# ayni degerleri referans ayi 2026-07 icin veriyor -> esleme 1 gercek noktada
# dogrulandi. (Tek nokta; --verify daha fazlasini kontrol eder.)
TUIK_CPI_RELEASE_DAY = 3


def _release_date(ref_month: date) -> date:
    """Referans ayi -> TUFE yayin gunu (izleyen ayin 3'u, hafta sonu ileri kayar)."""
    y, m = (ref_month.year + 1, 1) if ref_month.month == 12 else (ref_month.year, ref_month.month + 1)
    d = date(y, m, TUIK_CPI_RELEASE_DAY)
    while d.weekday() >= 5:            # 5=Cmt, 6=Paz
        d += timedelta(days=1)
    return d


def _load_sources() -> dict:
    try:
        return json.loads(SOURCES.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[macro] HATA: {SOURCES} okunamadi: {exc!r}")
        sys.exit(2)


def _fetch_cpi():
    """TR TUFE — ANAHTARSIZ. Dönen: [(ref_month:date, monthly_pct, yearly_pct)]"""
    import borsapy
    t = borsapy.Inflation().tufe
    df = t() if callable(t) else t
    out = []
    for idx, row in df.iterrows():
        try:
            ref = idx.date() if hasattr(idx, "date") else datetime.fromisoformat(str(idx)[:10]).date()
            mo, yr = row.get("MonthlyInflation"), row.get("YearlyInflation")
            if mo is None:
                continue
            out.append((ref, float(mo), None if yr is None else float(yr)))
        except Exception:
            continue
    out.sort(key=lambda r: r[0])
    return out


def _expected_status() -> tuple[str, str]:
    """`expected` kaynagi kullanilabilir mi. Anahtari OKUMAZ, yalnizca VARLIGINI sorar."""
    if os.environ.get("EVDS_API_KEY"):
        return "key_present_not_implemented", "EVDS_API_KEY var; PKA cekimi bu surumde YAZILMADI"
    if (ROOT / "local" / "evds_key.txt").exists():
        return "key_present_not_implemented", "local/evds_key.txt var; PKA cekimi bu surumde YAZILMADI"
    return "blocked_no_key", ("EVDS PKA zaman serisi ANAHTAR ister (TP.BEK.S01.A.M / "
                             "TP.PKAUO.S04.A.U). Anahtar konunca doldurulur.")


def build_events():
    """Olay listesi + yutma istatistikleri. HICBIR SEY YAZMAZ."""
    exp_status, exp_note = _expected_status()
    events, dropped = [], []
    seen = set()

    for ref, monthly, yearly in _fetch_cpi():
        ev_date = _release_date(ref)
        eid = f"TR_CPI-{ref:%Y-%m}"
        # DEDUP: takvim kaynagi ayni olayi birden fazla satirda verebiliyor
        # (2026-08-03 TUFE iki kez gorundu) -> id bazli tekillestirme ZORUNLU.
        if eid in seen:
            dropped.append({"id": eid, "reason": "duplicate"})
            continue
        # GELECEK olay yutulmaz (yayimlanmamis veri = actual yok demektir)
        if ev_date > date.today():
            dropped.append({"id": eid, "reason": "yayin_tarihi_gelecekte"})
            continue
        seen.add(eid)
        ev = {
            "id": eid,
            "date": ev_date.isoformat(),          # YAYIN gunu (referans ayi DEGIL)
            "reference_period": f"{ref:%Y-%m}",
            "type": "TR_CPI",
            "actual": round(monthly, 4),          # AYLIK % degisim
            "actual_yearly": None if yearly is None else round(yearly, 4),
            # --- expected: TAKILABILIR, su an BOS ---
            "expected": None,
            "survey_date": None,
            "expected_backfilled": False,
            "expected_status": exp_status,
            "surprise": None,
            "unit": "pct",
            # yon, surprise'in ISARETINDEN turer; surprise yokken "unknown"
            # yazmak dogrudur. Olculmemis bir haritalama iddia edilmiyor.
            "direction": "unknown",
            "source": "TCMB/TUIK (borsapy.Inflation)",
            "source_url": "https://evds3.tcmb.gov.tr",
            "note": "aylik TUFE % degisim; PKA 1A beklentisi ayni birimde (% degisim)",
        }
        events.append(ev)

    # ── PIT GUARD: survey_date < date. IHLAL -> DUSUR + SAY + ORNEKLE ──────
    # Su an expected yok -> survey_date yok -> guard tetiklenmez. Ama kod
    # SIMDI yaziliyor: sonradan eklenirse "guard nerede" diye aranmaz ve
    # anahtar gelince ilk kosuda devrede olur. (Kayittaki zorunluluk.)
    kept = []
    for ev in events:
        sd, ed = ev.get("survey_date"), ev.get("date")
        if sd and ed and str(sd) >= str(ed):
            dropped.append({"id": ev["id"], "reason": "PIT_ihlali_survey>=event",
                            "survey_date": sd, "event_date": ed})
            continue
        kept.append(ev)

    stats = {
        "built_at": datetime.utcnow().isoformat(timespec="seconds"),
        "n_events": len(kept),
        "n_dropped": len(dropped),
        "dropped_reasons": {r: sum(1 for d in dropped if d["reason"] == r)
                            for r in sorted({d["reason"] for d in dropped})},
        "dropped_sample": dropped[:5],       # SESSIZ DUSURME YOK: ornekle
        "types_built": sorted({e["type"] for e in kept}),
        "expected_status": exp_status,
        "expected_note": exp_note,
        # Neden TCMB_RATE yok: faiz serisi YALNIZ DEGISIMLERI tutuyor; ondan
        # olay turetmek orneklemi SONUCA GORE secmek olur (yalniz faizin
        # degistigi toplantilar) -> surprise->getiri olcumu kokten bozulur.
        # PPK takvimi gelmeden uretilmez. Ayrica borsapy TCMB().policy_rate
        # SKALERI BOZUK (7.0 doner, gercek 37.0) -> yalniz history() guvenilir.
        "types_deferred": {"TCMB_RATE": "PPK takvimi yok; degisim-serisinden "
                                        "uretmek secim-yanliligi olur"},
    }
    return kept, stats


def write(events, stats):
    payload = _load_sources()
    # Semaya EKSIK OLAN alanlar (kayittaki zorunluluk): survey_date + backfill izi
    sch = payload.setdefault("source_schema", {})
    sch["survey_date"] = "YYYY-MM-DD — konsensusun DERLENDIGI an; date'ten KUCUK olmali (PIT)"
    sch["expected_backfilled"] = "true ise expected geriye donuk dolduruldu -> hukumde ayristir"
    sch["expected_status"] = "blocked_no_key | key_present_not_implemented | ok"
    sch["reference_period"] = "YYYY-MM — verinin ait oldugu donem (yayin gunu 'date' alaninda)"
    sch["actual_yearly"] = "yillik % (ikincil; birincil 'actual' aylik %)"

    eski = {e.get("id"): e for e in payload.get("sources", []) if isinstance(e, dict)}
    for ev in events:
        onceki = eski.get(ev["id"])
        if onceki:
            # ELLE girilmis expected/survey_date KORUNUR — besleyici ezmez.
            for k in ("expected", "survey_date", "expected_backfilled", "note"):
                if onceki.get(k) not in (None, "", False):
                    ev[k] = onceki[k]
        eski[ev["id"]] = ev
    payload["sources"] = sorted(eski.values(), key=lambda e: (str(e.get("date")), str(e.get("id"))))
    payload["feed"] = stats
    SOURCES.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[macro] {SOURCES.relative_to(ROOT)} yazildi — {len(payload['sources'])} olay")


def verify(events):
    """BAGIMSIZ kaynakla capraz-kontrol: takvimdeki yayin gunu + degeri tutuyor mu.
    Ic tutarlilik degil DIS gerceklik testi (KAP buyback dersinin uygulamasi)."""
    import borsapy
    cal = borsapy.EconomicCalendar()
    try:
        d = cal.events(start="2026-08-01", end="2026-08-06", country="TR")
    except Exception as exc:
        print(f"[verify] takvim okunamadi: {exc!r}"); return
    rows = d[d["Event"].astype(str).str.contains("Enflasyon", na=False)] if len(d) else d
    print(f"[verify] takvimde {len(rows)} enflasyon satiri (pencere 08-01..08-06)")
    idx = {e["date"]: e for e in events}
    for _, r in rows.iterrows():
        gun = str(r["Date"])[:10]
        bizim = idx.get(gun)
        ours = "YOK" if not bizim else "{} actual={}".format(bizim["id"], bizim["actual"])
        olay = str(r["Event"])[:34]
        print("   takvim {} | {:34} actual={:>8} || bizim: {}".format(
            gun, olay, str(r["Actual"]), ours))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="yazma, ne uretecegini goster")
    ap.add_argument("--backfill", action="store_true", help="seri basindan yaz (idempotent)")
    ap.add_argument("--verify", action="store_true", help="bagimsiz kaynakla capraz-kontrol")
    a = ap.parse_args()
    if not (a.probe or a.backfill or a.verify):
        ap.error("--probe | --backfill | --verify birini ver")

    events, stats = build_events()
    print(f"[macro] uretilen olay: {stats['n_events']} | dusen: {stats['n_dropped']} "
          f"{stats['dropped_reasons'] or ''}")
    print(f"[macro] expected durumu: {stats['expected_status']} — {stats['expected_note']}")
    if events:
        print(f"[macro] aralik: {events[0]['date']} ({events[0]['reference_period']}) "
              f"-> {events[-1]['date']} ({events[-1]['reference_period']})")
        print(f"[macro] ornek (en yeni): {json.dumps(events[-1], ensure_ascii=False)[:200]}")
    if a.verify:
        verify(events)
    if a.backfill:
        write(events, stats)
    elif a.probe:
        print("[macro] PROBE — hicbir sey yazilmadi")


if __name__ == "__main__":
    main()
