#!/usr/bin/env python3
"""precise_runner.py — Erken gelen GitHub cron'unu tam slot saatine kadar bekletir;
gec gelen kosumda ise rapor slotunun kimligini korur.

NEDEN: GitHub scheduled cron saatlerce gecikebilir (gozlem: acilis 06:45 hedef ->
09:47'de tetiklendi). Erken kosum hedefe kadar uyur; gec kosum duvar saatinden
yeni bir slot uydurmak yerine report_gate'in hala acik olan en erken slotunu
devralir. Repo PUBLIC -> Actions dakikasi SINIRSIZ -> uyku bedava. Dis hesap/PAT
GEREKMEZ (built-in token + native cron).

Slot sahipligi: report_gate.select_slot, gonderim kaydi ve kanonik pencereye gore
vadesi gelmis/gonderilmemis en erken slotu; o yoksa siradaki gelecek slotu secer.
Kapanmis pencere baska bir slot etiketiyle telafi edilmez.

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


def select_slot(now_utc: datetime, sent: dict | None = None) -> str | None:
    """Select the earliest due/future slot through the canonical report gate."""
    sys.path.insert(0, "scripts")
    import report_gate as G
    now_tr = now_utc.astimezone(TZ_TR)
    return G.select_slot(now_tr, sent)


def target_slot(now_utc: datetime) -> str:
    """Compatibility label; the plan uses ``select_slot`` for real decisions."""
    return select_slot(now_utc) or "kapanis"


def plan(now_utc: datetime | None = None, sent: dict | None = None):
    """Uyumadan: (label, hedef_TR_datetime, bekleme_saniye). Test edilebilir."""
    now_utc = now_utc or datetime.now(TZ_UTC)
    now_tr = now_utc.astimezone(TZ_TR)
    label = select_slot(now_utc, sent)
    if label is None:
        return None, None, 0
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


def _trace_begin(label):
    # Daemon kendi begin()'ini atar (ayni slot, ustune yazar). Buradaki begin
    # daemon'un begin'e HIC ULASAMADIGI durum icin (import/sozdizimi hatasi):
    # o zaman onceki kosumun izi bu kosumunmus gibi commit'lenirdi.
    try:
        from bist_alpha import run_trace as _rt
        _rt.begin(label)
    except Exception as exc:
        # BILEREK YUTULUR (C10 kaydi 2026-09-11): iz katmani runner'i dusuremez
        # (fail-safe 1). begin() zaten _guvenli; bu blok yalniz import'u korur.
        print(f"[precise] iz begin hatasi: {exc}")


def _trace_phase(name):
    try:
        from bist_alpha import run_trace as _rt
        _rt.phase(name)
    except Exception as exc:
        print(f"[precise] iz phase hatasi: {exc}")


def _trace_end(status, err=None):
    # Daemon dustuyse izi kendisi FAILED@<faz> + gercek hata ile kapatmistir;
    # buradaki CalledProcessError ("exit status 1") onu EZMEMELI. Iz zaten
    # FAILED ise dokunma; RUNNING (daemon sinyalle oldu, end kosmadi) veya
    # OK (daemon bitti, mark dustu) ise kapat.
    try:
        from bist_alpha import run_trace as _rt
        cur = _rt.read() or {}
        if cur.get("status") == "FAILED":
            return
        _rt.end(status, err)
    except Exception as exc:
        print(f"[precise] iz end hatasi: {exc}")


def claim_slot(label: str) -> bool:
    proc = subprocess.run(
        [sys.executable, "scripts/report_claim.py", "claim", label],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args)
    return "claimed=true" in proc.stdout


def release_slot(label: str) -> None:
    try:
        sys.path.insert(0, "scripts")
        import report_gate as G
        G.release(label)
    except Exception as exc:
        print(f"[precise] release hatasi: {exc}")


def main(argv) -> int:
    dry = "--dry" in argv
    sync_latest_state()
    label, target, wait = plan()
    if label is None:
        print("[precise] acik report slot yok -> cik")
        return 0
    print(f"[precise] hedef slot={label} @ {target:%Y-%m-%d %H:%M} TR | bekleme={wait/60:.0f}dk")

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
    _trace_begin(label)
    try:
        subprocess.run([sys.executable, "daemon.py", "--once", label], check=True)
        # P0.5: mark ayri bir asama — Telegram gitti ama isaretlenmedi (senaryo D)
        # sonraki tick'te CIFT rapor demek; izde ayri gorunmeli.
        _trace_phase("mark")
        subprocess.run([sys.executable, "scripts/report_gate.py", "mark", label], check=True)
    except Exception as _exc:
        # daemon kendi izini kapatir; buradaki end() yalniz mark asamasindaki
        # ariza icin gerekli (daemon OK dedi, mark dustu -> FAILED@mark).
        _trace_end("FAILED", _exc)
        release_slot(label)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
