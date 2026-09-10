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
import math
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


DATA_FEED_RUN_STATE = (
    Path(__file__).resolve().parents[1] / "docs" / "state" / "data_feed_run.json"
)
PRODUCER_TIMEZONE = "Europe/Istanbul"

FETCH_ERROR = "FETCH_ERROR"
EMPTY_PRICES = "EMPTY_PRICES"
INSUFFICIENT_POOL_COVERAGE = "INSUFFICIENT_POOL_COVERAGE"
MISSING_BIST_REFERENCE = "MISSING_BIST_REFERENCE"
CALENDAR_UNAVAILABLE = "CALENDAR_UNAVAILABLE"
STALE_LAST_DATA = "STALE_LAST_DATA"
SPARSE_MARKET_DAY = "SPARSE_MARKET_DAY"
FILE_FALLBACK_DISABLED = "FILE_FALLBACK_DISABLED"


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
        "schema_version": 2,
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


def _summarize_attempt_for_dashboard(attempt):
    """Keep the full day-by-day trace in the manifest, not the dashboard."""
    summary = dict(attempt)
    checked_days = summary.pop("checked_market_days", [])
    summary["checked_market_day_count"] = len(checked_days)
    summary["latest_checked_market_day"] = checked_days[-1] if checked_days else None
    return summary


def _tag_source(data, source, primary, attempts):
    """Dashboard/health icin kaynagin nasil secildigini gorunur kil."""
    data["_source_base"] = source
    data["_source_primary"] = primary
    data["_source_attempts"] = [
        _summarize_attempt_for_dashboard(attempt)
        for attempt in attempts[-5:]
    ]
    if source != primary:
        data["_source_fallback_from"] = primary
        if source == "file":
            data["_source"] = f"file_fallback_from_{primary}"
        else:
            data["_source"] = f"{source}_fallback_from_{primary}"
    else:
        data["_source"] = source
    return data


def _producer_now(now=None):
    timezone_local = ZoneInfo(PRODUCER_TIMEZONE)
    if now is None:
        return datetime.now(timezone_local)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone_local)
    return now.astimezone(timezone_local)


def _calendar_gate_context(now, calendar_path=None):
    from . import market_calendar

    local_now = _producer_now(now)
    calendar = market_calendar.load_calendar(
        calendar_path,
        year=local_now.year,
    )
    renewal = market_calendar.renewal_status(
        local_now,
        next_calendar_available=False,
        calendar=calendar,
    )
    if renewal.get("reject_code"):
        raise market_calendar.CalendarUnavailableError(
            f"Takvim kapsam disi: {local_now.date().isoformat()}"
        )
    expected_last = market_calendar.expected_last_closed_session(
        local_now,
        calendar,
    )
    expected_sessions = market_calendar.sessions_between(
        calendar["_valid_from"],
        expected_last,
        calendar,
    )
    return {
        "now": local_now,
        "calendar": calendar,
        "calendar_status": renewal.get("status"),
        "calendar_days_remaining": renewal.get("days_remaining"),
        "expected_last_closed_session": expected_last,
        "expected_sessions": expected_sessions,
    }


def _candidate_gate_assessment(data, context):
    """Build the one structured measurement used for both record and decision."""
    from . import datafeed, market_calendar

    assessment = _feed_attempt_metrics(data)
    assessment.update({
        "calendar_status": context["calendar_status"],
        "calendar_days_remaining": context["calendar_days_remaining"],
        "expected_last_closed_session": (
            context["expected_last_closed_session"].isoformat()
        ),
        "freshness_status": None,
        "bar_completeness": "unknown",
        "checked_market_days": [],
        "sparse_market_days": [],
        "reject_code": None,
        "reject_codes": [],
    })
    prices = data.get("prices") if isinstance(data, dict) else None
    violations = []
    if prices is None or getattr(prices, "empty", True):
        violations.append(EMPTY_PRICES)
        assessment["reject_code"] = violations[0]
        assessment["reject_codes"] = violations
        return assessment

    returned_symbols = int(prices.shape[1])
    expected_pool = data.get("_source_pool_count")
    minimum_ratio = 1.0 - datafeed.SPARSE_DAY_NAN_THRESHOLD
    try:
        expected_pool = int(expected_pool)
    except (TypeError, ValueError):
        expected_pool = 0
    minimum_symbols = math.ceil(expected_pool * minimum_ratio) if expected_pool else None
    assessment.update({
        "returned_symbols": returned_symbols,
        "expected_pool": expected_pool or None,
        "minimum_required_symbols": minimum_symbols,
        "pool_coverage_pct": (
            round(returned_symbols / float(expected_pool) * 100, 2)
            if expected_pool else None
        ),
    })
    if not expected_pool or returned_symbols < minimum_symbols:
        violations.append(INSUFFICIENT_POOL_COVERAGE)

    bist = data.get("bist")
    if (data.get("_bist_ok") is not True
            or bist is None or getattr(bist, "empty", True)):
        violations.append(MISSING_BIST_REFERENCE)

    try:
        freshness = market_calendar.assess_freshness(
            assessment.get("last_data_date"),
            context["now"],
            context["calendar"],
        )
        assessment.update(freshness)
        if freshness.get("reject_code"):
            violations.append(freshness["reject_code"])
    except (TypeError, ValueError):
        assessment["freshness_status"] = "STALE"
        violations.append(STALE_LAST_DATA)

    coverage = datafeed.market_day_coverage(
        data,
        expected_sessions=context["expected_sessions"],
        expected_last_closed_session=context["expected_last_closed_session"],
    )
    sparse_days = [
        row for row in coverage
        if (row["present"] / float(row["total"])) < minimum_ratio
    ]
    assessment["checked_market_days"] = coverage
    assessment["sparse_market_days"] = sparse_days
    if sparse_days:
        violations.append(SPARSE_MARKET_DAY)

    assessment["reject_codes"] = list(dict.fromkeys(violations))
    assessment["reject_code"] = (
        assessment["reject_codes"][0] if assessment["reject_codes"] else None
    )
    return assessment


def _gate_rejection_message(assessment):
    code = assessment.get("reject_code")
    if code == EMPTY_PRICES:
        return "Fiyat tablosu yok veya bos"
    if code == INSUFFICIENT_POOL_COVERAGE:
        return (
            "Kaynak havuzu kapsami yetersiz: "
            f"{assessment.get('returned_symbols')}/{assessment.get('expected_pool')} "
            f"(minimum {assessment.get('minimum_required_symbols')})"
        )
    if code == MISSING_BIST_REFERENCE:
        return "BIST referans serisi yok veya olculemedi"
    if code == STALE_LAST_DATA:
        return (
            f"Son veri bayat: {assessment.get('last_data_date')} < "
            f"{assessment.get('expected_last_closed_session')}"
        )
    if code == SPARSE_MARKET_DAY:
        sample = assessment.get("sparse_market_days", [])[-3:]
        return "BIST islem gununde hisse kapsami yetersiz: " + ", ".join(
            f"{item['date']} %{item['coverage_pct']} "
            f"({item['present']}/{item['total']})"
            for item in sample
        )
    return f"Veri gate reddi: {code}"


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


def safe_feed(*, now=None, calendar_path=None):
    """
    Select the first source that passes the independent calendar/data gate.

    Default chain with DATA_SOURCE=yahoo:
      yahoo -> borsapy -> file

    File fallback is diagnostic-only unless ALLOW_FILE_FALLBACK is explicitly
    enabled. Production workflows keep it disabled.
    """
    from . import config, datafeed

    source = getattr(config, "DATA_SOURCE", "file")
    allow_file_fallback = getattr(config, "ALLOW_FILE_FALLBACK", False)
    attempts = []
    last_error = None

    try:
        context = _calendar_gate_context(now, calendar_path=calendar_path)
    except Exception as exc:
        attempt = {
            "source": source,
            "status": "failed",
            "reject_code": CALENDAR_UNAVAILABLE,
            "reject_codes": [CALENDAR_UNAVAILABLE],
            "error": str(exc)[:300],
            "error_type": type(exc).__name__,
            "started_at": _utc_timestamp(),
            "finished_at": _utc_timestamp(),
            "duration_s": 0.0,
        }
        attempts.append(attempt)
        _persist_data_feed_run(source, "failed", attempts, error=exc)
        raise RuntimeError(
            f"Bagimsiz XIST takvimi kullanilamiyor: {exc}"
        ) from exc

    for candidate in _fallback_sources(source, config):
        started_at = _utc_timestamp()
        started_clock = time.monotonic()
        if candidate == "file" and candidate != source and not allow_file_fallback:
            finished_at = _utc_timestamp()
            attempts.append({
                "source": candidate,
                "status": "skipped",
                "reason": "ALLOW_FILE_FALLBACK=0",
                "reject_code": FILE_FALLBACK_DISABLED,
                "reject_codes": [FILE_FALLBACK_DISABLED],
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_s": round(time.monotonic() - started_clock, 3),
            })
            _persist_data_feed_run(source, "running", attempts)
            continue
        data = None
        try:
            feed = datafeed.get_feed(candidate)
            data = with_retry(feed.get_latest, retries=3, delay=10,
                              label=f"{candidate} veri cekme")
        except Exception as e:
            last_error = e
            attempt = {
                "source": candidate,
                "status": "failed",
                "reject_code": FETCH_ERROR,
                "reject_codes": [FETCH_ERROR],
                "error": str(e)[:300],
                "error_type": type(e).__name__,
                "started_at": started_at,
                "finished_at": _utc_timestamp(),
                "duration_s": round(time.monotonic() - started_clock, 3),
            }
            attempt.update(_feed_attempt_metrics(data))
            attempts.append(attempt)
            _persist_data_feed_run(source, "running", attempts, error=e)
            print(f"[selfheal] {candidate} veri kaynagi basarisiz: {e}")
            continue

        assessment = _candidate_gate_assessment(data, context)
        attempt = {
            "source": candidate,
            "status": "failed" if assessment.get("reject_code") else "ok",
            "started_at": started_at,
            "finished_at": _utc_timestamp(),
            "duration_s": round(time.monotonic() - started_clock, 3),
        }
        attempt.update(assessment)
        if assessment.get("reject_code"):
            reason = _gate_rejection_message(assessment)
            last_error = ValueError(reason)
            attempt["error"] = reason[:300]
            attempt["error_type"] = "DataGateRejected"
            attempts.append(attempt)
            _persist_data_feed_run(source, "running", attempts, error=last_error)
            print(f"[selfheal] {candidate} veri kaynagi reddedildi: {reason}")
            continue

        if candidate != source:
            print(f"[selfheal] {source} reddedildi -> {candidate} yedegi kullaniliyor")
        attempts.append(attempt)
        _persist_data_feed_run(
            source, "ok", attempts, selected_source=candidate)
        return _tag_source(data, candidate, source, attempts)

    _persist_data_feed_run(source, "failed", attempts, error=last_error)
    raise RuntimeError(f"{source} ve yedek veri kaynaklari alinamadi: {attempts}") from last_error
