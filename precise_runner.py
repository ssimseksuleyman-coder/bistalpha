#!/usr/bin/env python3
"""precise_runner.py — GitHub cron GECIKMESINI yener: tam slot saatine kadar uyu,
sonra daemon'u calistir. Rapor GEC degil, TAM ZAMANINDA cikar.

NEDEN: GitHub scheduled cron saatlerce gecikebilir (gozlem: acilis 06:45 hedef ->
09:47'de tetiklendi). Cozum: cron'u slot'tan SAATLER ONCE tetikle; job tam slot
saatine kadar UYUR, sonra calisir. Repo PUBLIC -> Actions dakikasi SINIRSIZ ->
uyku bedava. Dis hesap/PAT GEREKMEZ (built-in token + native cron).

Slot bandi (UTC saatine gore hangi slot hedefleniyor — gecikmeye dayanikli):
  UTC < 07:00        -> acilis (hedef 06:45 UTC = 09:45 TR)
  07:00 <= UTC < 12  -> gunici (hedef 11:30 UTC = 14:30 TR)
  UTC >= 12:00       -> kapanis (hedef 15:40 UTC = 18:40 TR)

report_gate ile koordine: zaten gonderilmisse uyumaz/atlar (native cron fallback).
"""
from __future__ import annotations
import subprocess
import sys
import time as _time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_TR = ZoneInfo("Europe/Istanbul")
TZ_UTC = ZoneInfo("UTC")

# slot -> TR (saat, dakika)
SLOT_TR = {"acilis": (9, 45), "gunici": (14, 30), "kapanis": (18, 40)}
MAX_WAIT_H = 5.5   # 6h job limitinin altinda kal


def target_slot(now_utc: datetime) -> str:
    h = now_utc.hour + now_utc.minute / 60.0
    if h < 7.0:
        return "acilis"
    if h < 12.0:
        return "gunici"
    return "kapanis"


def plan(now_utc: datetime | None = None):
    """Uyumadan: (label, hedef_TR_datetime, bekleme_saniye). Test edilebilir."""
    now_utc = now_utc or datetime.now(TZ_UTC)
    now_tr = now_utc.astimezone(TZ_TR)
    label = target_slot(now_utc)
    h, m = SLOT_TR[label]
    target = now_tr.replace(hour=h, minute=m, second=0, microsecond=0)
    wait = (target - now_tr).total_seconds()
    return label, target, wait


def already_sent(label: str) -> bool:
    """report_gate state'inden bugun bu slot gonderilmis mi."""
    try:
        sys.path.insert(0, "scripts")
        import report_gate as G
        now = G._now_istanbul()
        key = G._marker_key(now, label)
        return G._record_blocks(G._load_state().get("sent", {}).get(key), now)
    except Exception:
        return False


def sync_latest_state() -> None:
    """Pull latest committed state before gate checks; failure is non-fatal."""
    try:
        subprocess.run(["git", "pull", "--rebase", "--autostash"], check=False)
    except Exception as exc:
        print(f"[precise] git pull atlandi: {exc}")


def claim_slot(label: str) -> bool:
    try:
        sys.path.insert(0, "scripts")
        import report_gate as G
        return G.claim(label)
    except Exception as exc:
        print(f"[precise] claim hatasi: {exc}")
        return False


def release_slot(label: str) -> None:
    try:
        sys.path.insert(0, "scripts")
        import report_gate as G
        G.release(label)
    except Exception as exc:
        print(f"[precise] release hatasi: {exc}")


def main(argv) -> int:
    dry = "--dry" in argv
    label, target, wait = plan()
    print(f"[precise] hedef slot={label} @ {target:%Y-%m-%d %H:%M} TR | bekleme={wait/60:.0f}dk")

    sync_latest_state()
    if already_sent(label):
        print(f"[precise] {label} bugun zaten gonderilmis -> cik"); return 0
    if wait > MAX_WAIT_H * 3600:
        print(f"[precise] cok uzak ({wait/3600:.1f}h > {MAX_WAIT_H}h) -> cik"); return 0
    if dry:
        print("[precise] --dry: uyku+calistirma atlandi"); return 0

    if wait > 0:
        print(f"[precise] {wait/60:.0f}dk uyunuyor -> tam saatte calisacak")
        _time.sleep(wait)

    sync_latest_state()
    if already_sent(label):
        print(f"[precise] {label} uyku sonrasi zaten gonderilmis -> cik"); return 0
    if not claim_slot(label):
        print(f"[precise] {label} baska workflow tarafindan ayrilmis -> cik"); return 0

    print(f"[precise] {label} CALISTIRILIYOR @ {datetime.now(TZ_TR):%H:%M:%S} TR")
    try:
        subprocess.run([sys.executable, "daemon.py", "--once", label], check=True)
        subprocess.run([sys.executable, "scripts/report_gate.py", "mark", label], check=True)
    except Exception:
        release_slot(label)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
