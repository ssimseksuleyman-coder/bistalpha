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
from datetime import datetime, timezone
from pathlib import Path


DATA_FEED_RUN_STATE = (
    Path(__file__).resolve().parents[1] / "docs" / "state" / "data_feed_run.json"
)


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _feed_attempt_metrics(data):
    """Return JSON-safe facts already available from a feed response."""
    if not isinstance(data, dict):
        return {}
    prices = data.get("prices")
    if prices is None:
        return {}
    metrics = {
        "returned_symbols": int(prices.shape[1]),
        "expected_pool": data.get("_source_pool_count"),
    }
    try:
        last = prices.index[-1]
        metrics["last_data_date"] = (
            str(last.date()) if hasattr(last, "date") else str(last)[:10]
        )
    except Exception:
        metrics["last_data_date"] = None
    return metrics


def _write_data_feed_run(primary_source, status, attempts,
                         selected_source=None, error=None):
    """Persist the latest feed decision even when no dashboard can be built."""
    payload = {
        "schema_version": 1,
        "generated_at": _utc_timestamp(),
        "status": status,
        "primary_source": primary_source,
        "selected_source": selected_source,
        "attempt_count": len(attempts),
        "source_attempts": attempts,
    }
    if error:
        payload["error"] = str(error)[:500]
    path = Path(DATA_FEED_RUN_STATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return payload


def _persist_data_feed_run(primary_source, status, attempts,
                           selected_source=None, error=None):
    """Keep observability failure separate from the feed selection decision."""
    try:
        return _write_data_feed_run(
            primary_source,
            status,
            attempts,
            selected_source=selected_source,
            error=error,
        )
    except Exception as exc:
        print(f"[selfheal] data feed run manifesti yazilamadi: {exc}")
        return None


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
        started_at = _utc_timestamp()
        started_clock = time.monotonic()
        if candidate == "file" and candidate != source and not allow_file_fallback:
            finished_at = _utc_timestamp()
            attempts.append({
                "source": candidate,
                "status": "skipped",
                "reason": "ALLOW_FILE_FALLBACK=0",
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_s": round(time.monotonic() - started_clock, 3),
            })
            _persist_data_feed_run(source, "running", attempts)
            continue
        data = None
        sparse_days = []
        try:
            feed = datafeed.get_feed(candidate)
            data = with_retry(feed.get_latest, retries=3, delay=10,
                              label=f"{candidate} veri cekme")
            if data["prices"].shape[1] < 50 or data["prices"].empty:
                raise ValueError("Veri yetersiz/bos")
            sparse_days = datafeed.sparse_market_days(data)
            if sparse_days:
                sample = sparse_days[-3:]
                raise ValueError(
                    "XU100 islem gununde hisse kapsami yetersiz: "
                    + ", ".join(
                        f"{item['date']} %{item['coverage_pct']} "
                        f"({item['present']}/{item['total']})"
                        for item in sample
                    )
                )
            if candidate != source:
                print(f"[selfheal] {source} coktu -> {candidate} yedegi kullaniliyor")
            attempt = {
                "source": candidate,
                "status": "ok",
                "started_at": started_at,
                "finished_at": _utc_timestamp(),
                "duration_s": round(time.monotonic() - started_clock, 3),
            }
            attempt.update(_feed_attempt_metrics(data))
            attempts.append(attempt)
            _persist_data_feed_run(
                source, "ok", attempts, selected_source=candidate)
            return _tag_source(data, candidate, source, attempts)
        except Exception as e:
            last_error = e
            attempt = {
                "source": candidate,
                "status": "failed",
                "error": str(e)[:300],
                "error_type": type(e).__name__,
                "started_at": started_at,
                "finished_at": _utc_timestamp(),
                "duration_s": round(time.monotonic() - started_clock, 3),
            }
            attempt.update(_feed_attempt_metrics(data))
            if sparse_days:
                attempt["sparse_market_days"] = sparse_days[-3:]
            attempts.append(attempt)
            _persist_data_feed_run(source, "running", attempts, error=e)
            print(f"[selfheal] {candidate} veri kaynagi basarisiz: {e}")

    _persist_data_feed_run(source, "failed", attempts, error=last_error)
    raise RuntimeError(f"{source} ve yedek veri kaynaklari alinamadi: {attempts}") from last_error
