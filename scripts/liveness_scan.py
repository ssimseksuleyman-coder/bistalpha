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

# Hafta-sonu toleransi: daemon yalniz hafta-ici kosar (cron 1-5).
# Cuma 18:40 -> Pazartesi 06:45 ~= 60 saat. 72h esigi hafta-sonu yanlis-alarmini onler.
WEEKEND_TOLERANT_HOURS = 72

# ---------------------------------------------------------------------------
# REGISTRY — hangi mekanizma canli olmali, damgasini nereye yazmali.
# YENI DIS-KAYNAK EKLERKEN BURAYA DA EKLE. Eklenmezse izlenmez (bug dogus kosulu).
# ---------------------------------------------------------------------------
REGISTRY = {
    # ---- URETICILER (disariya cikan: scrape/API) ----
    "kap_feed": {
        "kind": "producer",
        "expected": "active",
        "file": "docs/state/kap_status.json",
        "ts_keys": ["updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "ok_key": "status",
        "ok_value": "ok",
        "note": "catalyst_feed -> KAP scrape; gunluk 16:10 UTC cron (catalyst.yml)",
    },
    "market_data": {
        "kind": "producer",
        "expected": "active",
        "file": "docs/state/dashboard.json",
        "ts_keys": ["date", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "ok_key": "bist_data_ok",
        "ok_value": True,
        "note": "yfinance/datafeed; daemon her dongude",
    },
    # ---- TUKETICILER (local defter; daemon her dongude yazar) ----
    "forward_test": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/forward_test.json",
        "ts_keys": ["updated_at", "summary.updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
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
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_days", "summary.latest_events"],
        "input_paths": [],
    },
    "opportunity_ledger": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/opportunity_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_days", "summary.total_events"],
        "input_paths": [],
    },
    "catalyst_ledger": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/catalyst_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["docs/state/catalysts.json"],
    },
    "flow_ledger": {
        "kind": "consumer", "expected": "planned",   # buyback-event henuz gelmedi
        "file": "docs/state/flow_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_events"],
        # SADECE OZEL girdi. Paylasilan ust-akis (catalysts.json) buraya KONMAZ:
        # "girdi var" != "ILGILI girdi var" -> ilk surumde catalysts.json'i (25 event,
        # ici buyback-YOK) girdi sayip yanlis-KIRMIZI urettim. Ust-akis kendi
        # dugumunde (kap_feed) izlenir; burada tekrar izlemek gurultu uretir.
        "input_paths": ["local/flow_inputs"],
        "upstream": ["docs/state/catalysts.json (kap_feed dugumunde izleniyor)"],
    },
    "quality_ledger": {
        "kind": "consumer", "expected": "planned",   # KAP finansal parser YAZILMADI
        "file": "docs/state/quality_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["local/kap_financials", "local/kap_financial_actuals.json"],
    },
    "macro_surprise_ledger": {
        "kind": "consumer", "expected": "planned",   # sources.json'a event girilmedi
        "file": "docs/state/macro_surprise_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["docs/state/macro_surprise_sources.json"],
    },
    "broker_bulletin_ledger": {
        "kind": "consumer", "expected": "planned",   # private input hic konmadi
        "file": "docs/state/broker_bulletin_ledger.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_events"],
        "input_paths": ["local/broker_bulletins"],
    },
    "missed_opportunities": {
        "kind": "consumer", "expected": "active",
        "file": "docs/state/missed_opportunities.json",
        "ts_keys": ["summary.updated_at", "updated_at"],
        "max_age_hours": WEEKEND_TOLERANT_HOURS,
        "count_keys": ["summary.tracked_days", "summary.hot_missed_count"],
        "input_paths": [],
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


def _age_hours(ts):
    """ISO ya da YYYY-MM-DD damgasini saat-yasina cevirir."""
    if not ts:
        return None
    s = str(ts).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
            return (datetime.now() - dt).total_seconds() / 3600.0
        except ValueError:
            continue
    return None


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


def check(name, cfg):
    f = ROOT / cfg["file"]
    row = {"name": name, "kind": cfg["kind"], "expected": cfg["expected"],
           "file": cfg["file"], "note": cfg.get("note", "")}

    if not f.exists():
        # Registry'de var ama damga dosyasi YOK -> uretici damga yazmiyor.
        row.update(status="RED", reason="registry'de kayitli ama damga dosyasi YOK "
                                        "(uretici/tuketici damga yazmiyor)")
        return row

    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        row.update(status="RED", reason=f"damga dosyasi okunamadi: {e}")
        return row

    ts, ts_key = _first(d, cfg["ts_keys"])
    age = _age_hours(ts)
    row.update(timestamp=ts, ts_key=ts_key,
               age_hours=(round(age, 1) if age is not None else None))

    if ts is None:
        row.update(status="RED", reason="zaman damgasi YOK (canlilik olculemez)")
        return row
    if age is None:
        row.update(status="RED", reason=f"damga cozulemedi: {ts!r}")
        return row
    if age > cfg["max_age_hours"]:
        row.update(status="RED",
                   reason=f"BAYAT: {age:.0f}h > {cfg['max_age_hours']}h "
                          f"({'kaynak durdu' if cfg['kind']=='producer' else 'daemon/defter durdu'})")
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


def main():
    rows = [check(n, c) for n, c in REGISTRY.items()]
    red = [r for r in rows if r["status"] == "RED"]
    yellow = [r for r in rows if r["status"] == "YELLOW"]
    payload = {
        # Tarayicinin KENDI damgasi — "izleyeni izleyen yok" regresyonu burada durur.
        "updated_at": datetime.now().isoformat(timespec="seconds"),
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
