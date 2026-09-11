"""P0.5 — KOSUM IZI: her uretici kosumu ne yaptigini yazar, basari da ariza da.

NEDEN VAR (olculdu 2026-09-11):
  precise.yml'de daemon adimi kosulsuz, state commit `if: always()`. Daemon yari
  yolda duserse commit yine kosar ve diskte ne varsa origin'e gider — hepsi
  "precise state HHMM" etiketiyle, sanki basarili kosummus gibi. Dort dusme
  senaryosu (feed'de / shadow ortasinda / raporda / mark'ta) origin'de AYIRT
  EDILEMEZ. `report_gate.release` arizada claim'i SILDIGI icin ariza geride iz
  de birakmaz. 2026-09-08'de canlida oldu: watchdog/content_sanity taze,
  portfolio_F/report_runs bayat, tek etiket (rontgen 12.0).

UC PARCA (rontgen kapanis olcutu "run trace + commit manifest; partial
authoritative degil"):
  1. bu modul: docs/state/run_trace.json — begin/phase/end, atomik yazim
  2. workflow state commit: mesaj bu dosyadan status+phase okur
  3. health-logic.js: cekirdek metrik; status != OK -> kirmizi, iz yok -> "n"

FAIL-SAFE YONU (koddan once yazildi):
  - iz yazimi ARIZA URETMEZ: phase() icinde ne olursa olsun daemon dusmez;
    iz karar degil, kayittir. Ama sessiz de degil: yazamazsa stderr'e yazar.
  - partial commit ENGELLENMEZ: kanit korunur, ETIKETLENIR. "commit etme"
    secenegi izi de kaybettirirdi.
  - end() cagrilmadan kosum biterse dosyada status="RUNNING" kalir — bu da
    bir hukumdur: "kosum sonlanamadi" (SIGKILL, timeout, runner olumu).
  - damgalar UTC ve 'Z' tasir (D6; health-logic timestampMs ofsetsiz damgayi
    +03:00 sayar -> 3 saatlik sahte yas).

KALIP: stop_observer.write_payload ile ayni (tmp -> replace). Ikinci bir
atomik-yazici DOGMASIN diye buradaki `_atomic_write` kucuk ve ayni sekilde.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE_OUT = REPO_ROOT / "docs" / "state" / "run_trace.json"
SCHEMA_VERSION = 1


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write(payload, path=None):
    out = Path(path or TRACE_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    return out


def read(path=None):
    """Izi okur; yoksa/bozuksa None. Tuketiciler (workflow, panel, selftest) icin."""
    p = Path(path or TRACE_OUT)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Gecerli ama sozluk olmayan JSON ("x", 1, []) da BOZUK sayilir: fuzz
    # (2026-09-11, 300 deneme) 37 kez summary_line'i `.get` ile dusurdu; CLI
    # _guvenli sarmalinda degil -> commit mesaji [TRACE_CLI_ERR] olurdu.
    return d if isinstance(d, dict) else None


def _head_sha():
    """Fiilen kosan kodun SHA'si: `git rev-parse HEAD`. GITHUB_SHA tetik SHA'sidir;
    iki workflow da kosumdan once `git pull --rebase` yapiyor -> kosan kod HEAD'dir,
    tetik degil (ground-truth: proxy sessizce yanlislanir). git yoksa env, o da
    yoksa None; kaynak ayrica yazilir ki okuyucu hangisini gordugunu bilsin."""
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=str(REPO_ROOT), timeout=10)
        s = (r.stdout or "").strip()
        if r.returncode == 0 and len(s) >= 12:
            return s[:12], "git"
    except Exception:
        pass
    env = (os.environ.get("GITHUB_SHA") or "")[:12]
    return (env or None), ("env" if env else None)


def _guvenli(fn):
    """Iz yazimi asla cagirani dusurmez; hata stderr'e gider (sessiz degil)."""
    def sarma(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as exc:
            print(f"[run_trace] iz yazilamadi ({fn.__name__}): {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return None
    sarma.__name__ = fn.__name__
    return sarma


@_guvenli
def begin(slot, run_id=None, sha=None, workflow=None, path=None):
    """Kosum basinda. Onceki iz UZERINE yazilir: iz 'son kosum'u anlatir."""
    if sha:
        sha, sha_source = str(sha)[:12], "arg"
    else:
        sha, sha_source = _head_sha()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "slot": slot,
        "run_id": run_id or os.environ.get("GITHUB_RUN_ID"),
        "sha": sha,
        "sha_source": sha_source,   # git = fiili HEAD | env = GITHUB_SHA (tetik) | arg
        "workflow": workflow or os.environ.get("GITHUB_WORKFLOW"),
        "started_at": _utc(),
        "updated_at": _utc(),
        "status": "RUNNING",
        "phase": "begin",
        "phases": ["begin"],
        "ended_at": None,
        "error": None,
        "note": ("P0.5 kosum izi. status RUNNING kalmissa kosum SONLANAMADI "
                 "(timeout/runner olumu). FAILED ise `phase` dusulen adimdir."),
    }
    return _atomic_write(payload, path)


@_guvenli
def phase(name, path=None):
    """Bir kilometre tasi gecildi. begin() yoksa sessizce olusturur (iz karar degil)."""
    cur = read(path) or {"schema_version": SCHEMA_VERSION, "status": "RUNNING",
                         "phases": [], "started_at": _utc(), "slot": None}
    cur["phase"] = name
    cur.setdefault("phases", []).append(name)
    cur["updated_at"] = _utc()
    return _atomic_write(cur, path)


@_guvenli
def end(status, error=None, path=None):
    """Kosum sonu. status: OK | FAILED | NO_TRACE(iz hic baslamamissa)."""
    cur = read(path)
    if cur is None:
        cur = {"schema_version": SCHEMA_VERSION, "slot": None, "phases": [],
               "started_at": None, "phase": None}
        status = "NO_TRACE" if status == "OK" else status
    cur["status"] = status
    cur["ended_at"] = _utc()
    cur["updated_at"] = cur["ended_at"]
    cur["error"] = (f"{type(error).__name__}: {str(error)[:300]}"
                    if isinstance(error, BaseException) else (str(error)[:300] if error else None))
    return _atomic_write(cur, path)


def summary_line(path=None, run_id=None):
    """Commit mesaji icin tek satir:
    [OK] | [FAILED@shadow:A] | [RUNNING@feed] | [NO_TRACE] | [NO_RUN].

    run_id verilirse izin run_id'si onunla eslesmeli; eslesmiyorsa [NO_RUN]:
    bu workflow kosumunda uretici hic baslamadi (precise_runner erken cikti:
    "zaten gonderilmis" / "cok uzak" / "ayrilmis"). precise.yml commit adimi
    `always()` oldugu icin aksi halde ONCEKI kosumun [OK]'i bu kosumun
    mesajina basilirdi (gunde 4-6 kosumun cogu erken-cikis).
    """
    cur = read(path)
    if cur is None:
        return "[NO_TRACE]"
    if run_id is not None and str(cur.get("run_id") or "") != str(run_id):
        return "[NO_RUN]"
    st = cur.get("status") or "?"
    ph = cur.get("phase") or "?"
    if st in ("OK", "NO_TRACE"):
        return f"[{st}]"
    return f"[{st}@{ph}]"


if __name__ == "__main__":
    # workflow'dan: python -m bist_alpha.run_trace summary
    # GITHUB_RUN_ID varsa iz o kosuma ait olmali (yoksa [NO_RUN]); yerelde filtre yok.
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        print(summary_line(run_id=os.environ.get("GITHUB_RUN_ID")))
    else:
        print(json.dumps(read(), ensure_ascii=False, indent=2))
