"""
ÖZ-İYİLEŞTİRME (self-healing) — sistem hatalarını kendi kendine toparlama.

İlke: "sessizce mantık değiştirme" DEĞİL. Gerçek self-healing =
  - Geçici hataları yeniden dene (retry)
  - Birincil veri kaynağı çökerse yedeğe düş (Yahoo → gömülü Excel)
  - Bozuk state'i tespit et + onar/sıfırla
  - İstisnayı yakala, logla, bildir, ÇÖKME (daemon ayakta kalsın)
"""
import time
import os
import json
import traceback
from datetime import datetime


def with_retry(fn, retries=3, delay=5, label="işlem"):
    """Geçici hatalarda yeniden dener (network, veri çekme vb.)."""
    last = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[selfheal] {label} denemesi {i+1}/{retries} basarisiz: {e}")
            if i < retries - 1:
                time.sleep(delay)
    raise last


def _fallback_sources(primary, config):
    """Primary + fallback zincirini yinelenmeyen kaynak listesine cevir."""
    raw_chain = getattr(config, "DATA_FALLBACK_CHAIN", "borsapy,file") or ""
    chain = [x.strip() for x in str(raw_chain).split(",") if x.strip()]
    sources = []
    for source in [primary] + chain:
        if source not in sources:
            sources.append(source)
    return sources


def _tag_source(data, source, primary, attempts):
    """Dashboard/health icin kaynagin nasil secildigini gorunur kil."""
    data["_source_base"] = source
    data["_source_primary"] = primary
    data["_source_attempts"] = attempts[-5:]
    if source != primary:
        data["_source_fallback_from"] = primary
        if source == "file":
            data["_source"] = f"file_fallback_from_{primary}"
        else:
            data["_source"] = f"{source}_fallback_from_{primary}"
    else:
        data["_source"] = source
    return data


def validate_and_repair_state(account, state_dir="portfolios"):
    """
    Portföy JSON'unu doğrula. Bozuksa yedekle + sıfırla (veri kaybı önlenir).
    """
    path = os.path.join(state_dir, f"portfolio_{account}.json")
    if not os.path.exists(path):
        return True  # yok = temiz başlangıç
    try:
        with open(path) as f:
            state = json.load(f)
        # Zorunlu alanlar
        if not ("account" in state and "cash" in state and "positions" in state):
            raise ValueError("Eksik zorunlu alanlar: account/cash/positions")
        if not isinstance(state["positions"], dict):
            raise ValueError("positions dict değil")
        for tic, pos in state["positions"].items():
            if not all(k in pos for k in ("entry", "peak", "shares")):
                raise ValueError(f"{tic}: eksik pos alanı (entry/peak/shares)")
        return True
    except Exception as e:
        print(f"[selfheal] {account} portföyü bozuk ({e}) → yedeklenip sıfırlanıyor")
        bak = path + f".bozuk_{datetime.now():%Y%m%d_%H%M%S}.bak"
        try:
            os.rename(path, bak)
        except OSError:
            pass
        return False


def _write_error_log(label, tb):
    """Tam traceback'i logs/ altına yazar (1500 karakter kısıtı yok)."""
    try:
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:30]
        path = os.path.join(log_dir, f"error_{ts}_{safe_label}.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {label}\n\n{tb}")
    except Exception:
        pass


def guarded(fn, notify_fn=None, label="döngü"):
    """
    Bir görevi koru: hata olursa yakala, logla, bildir, ÇÖKME.
    daemon görevlerini buna sarar — tek hata tüm servisi düşürmez.
    """
    try:
        return fn()
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[selfheal] {label} HATA (yakalandı, servis ayakta):\n{tb}")
        _write_error_log(label, tb)
        if notify_fn:
            try:
                notify_fn(f"⚠️ BIST Alpha — {label} hatası",
                          f"{e}\n\n{tb[:1500]}")
            except Exception:
                pass
        return None


def safe_feed():
    """
    Fetch primary data; if it fails, try live-ish fallback before file fallback.

    Default chain with DATA_SOURCE=yahoo:
      yahoo -> borsapy -> file

    File fallback is still gated by ALLOW_FILE_FALLBACK.
    """
    from . import config, datafeed

    source = getattr(config, "DATA_SOURCE", "file")
    allow_file_fallback = getattr(config, "ALLOW_FILE_FALLBACK", False)
    attempts = []
    last_error = None

    for candidate in _fallback_sources(source, config):
        if candidate == "file" and candidate != source and not allow_file_fallback:
            attempts.append({
                "source": candidate,
                "status": "skipped",
                "reason": "ALLOW_FILE_FALLBACK=0",
            })
            continue
        try:
            feed = datafeed.get_feed(candidate)
            data = with_retry(feed.get_latest, retries=3, delay=10,
                              label=f"{candidate} veri cekme")
            if data["prices"].shape[1] < 50 or data["prices"].empty:
                raise ValueError("Veri yetersiz/bos")
            if candidate != source:
                print(f"[selfheal] {source} coktu -> {candidate} yedegi kullaniliyor")
            attempts.append({"source": candidate, "status": "ok"})
            return _tag_source(data, candidate, source, attempts)
        except Exception as e:
            last_error = e
            attempts.append({
                "source": candidate,
                "status": "failed",
                "error": str(e)[:300],
            })
            print(f"[selfheal] {candidate} veri kaynagi basarisiz: {e}")

    raise RuntimeError(f"{source} ve yedek veri kaynaklari alinamadi: {attempts}") from last_error
