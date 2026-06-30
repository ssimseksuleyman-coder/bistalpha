"""
YAN KAYNAK OVERLAY — OMEGA istihbaratının TAMAMI tek modülde.

MİMARİ: Hepsi OVERLAY (etiket/bayrak). Hiçbiri hisse SEÇMEZ, skoru override
etmez. Momentum seçimi yapar; bunlar sadece "dikkat/teyit" bayrağı ekler.

Kapsanan OMEGA kaynakları (data/omega/ altında):
  - deniz_puanlari.json           : 100 hisse Deniz teknik skoru (günlük bülten)
  - foreign_flow.json             : yabancı giriş/çıkış (10g + günlük)
  - volume_hunter.json            : hacim patlaması/kuruması/tarihsel min uyarı
  - earnings_actuals_1Q26.json    : bilanço sürpriz + upgrade sinyalleri
  - macro_factors.json            : FX pozisyonu + ihracat payı (TL şoku riski)
  - seasonal_may_patterns.json    : Mayıs sezonsal kazananlar
  - sector_timeseries_v4_complete : sektör pattern (pump-dump, defensif)
  - support_resistance.json       : Deniz pivot destek/direnç (canlı pivot'tan iyi)
"""
import os
import json
import threading
from datetime import date as date_type, datetime
from . import config

_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "omega")
_cache = {}
_cache_lock = threading.Lock()


def _load(name):
    with _cache_lock:
        if name not in _cache:
            path = os.path.join(_DIR, f"{name}.json")
            try:
                with open(path, encoding="utf-8") as f:
                    _cache[name] = json.load(f)
            except Exception:
                _cache[name] = {}
        return _cache[name]


def _date_from_meta(meta):
    raw = (meta or {}).get("extracted") or (meta or {}).get("date")
    if not raw:
        src = (meta or {}).get("source", "")
        import re
        m = re.search(r"(\d{2})[./_-](\d{2})[./_-](\d{4})", src)
        raw = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _as_date(value):
    if value is None:
        return date_type.today()
    if hasattr(value, "date"):
        return value.date()
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def deniz_source_status(as_of=None, max_age_days=None):
    d = _load("deniz_puanlari")
    meta = d.get("_meta", {}) if isinstance(d, dict) else {}
    src_date = _date_from_meta(meta)
    if max_age_days is None:
        max_age_days = getattr(config, "DENIZ_MAX_AGE_DAYS", 3)
    if not src_date:
        return {"available": bool(d), "date": None, "age_days": None,
                "fresh": False, "status": "unknown"}
    ref = _as_date(as_of)
    age = max(0, (ref - src_date).days)
    return {"available": True, "date": src_date.isoformat(), "age_days": age,
            "fresh": age <= max_age_days, "status": "fresh" if age <= max_age_days else "stale",
            "source": meta.get("source")}


# ---- Deniz hisse teknik skoru ----
def deniz_stock_score(ticker, as_of=None, allow_stale=False):
    d = _load("deniz_puanlari")
    if not allow_stale and as_of is not None:
        if not deniz_source_status(as_of).get("fresh"):
            return None
    v = d.get(ticker)
    return float(v) if isinstance(v, (int, float)) else None


# ---- Yabancı akış ----
def foreign_flow(ticker):
    d = _load("foreign_flow")
    for item in d.get("consistent_inflow_10d", []):
        if item.get("ticker") == ticker:
            return "10g_yabancı_giriş"
    for item in d.get("consistent_outflow_10d", []):
        if item.get("ticker") == ticker:
            return "10g_yabancı_çıkış"
    for item in d.get("today_largest_increase_pct", []):
        if item.get("ticker") == ticker:
            return "bugün_yabancı_giriş"
    for item in d.get("today_largest_decrease_pct", []):
        if item.get("ticker") == ticker:
            return "bugün_yabancı_çıkış"
    return None


# ---- Hacim avcıları ----
def volume_signal(ticker):
    d = _load("volume_hunter")
    for item in d.get("near_2026_min_volume_DANGER", []):
        if item.get("ticker") == ticker:
            return "tarihsel_min_DİKKAT"
    for item in d.get("yuksek_burst_top5", []):
        if item.get("ticker") == ticker:
            return "hacim_patlaması"
    for item in d.get("drought_top5", []):
        if item.get("ticker") == ticker:
            return "hacim_kuruması"
    return None


# ---- Bilanço sürprizi ----
def earnings_signal(ticker):
    d = _load("earnings_actuals_1Q26")
    for c in d.get("companies", []):
        if c.get("ticker") == ticker:
            return {"result": c.get("result"), "surprise_pct": c.get("surprise_pct"),
                    "recommendation": c.get("recommendation")}
    return None


# ---- FX riski (TL şokunda) ----
def fx_risk(ticker):
    d = _load("macro_factors")
    for item in d.get("fx_positions_mio_USD_or_EUR", []):
        if item.get("ticker") == ticker:
            net = item.get("net_fx_position_mio")
            if net is not None and net < 0:
                return f"negatif_FX_pozisyon ({net:.0f}mn)"  # TL düşerse zarar
            return "pozitif_FX_pozisyon"
    return None


# ---- Sezonsal (Mayıs) ----
def seasonal_may(ticker):
    d = _load("seasonal_may_patterns")
    for item in d.get("may_top10_10year_avg", []):
        if item.get("ticker") == ticker:
            return f"Mayıs_kazananı (%{item.get('may_avg_pct')})"
    return None


# ---- Sektör pattern (Bulgu 3 verisi) ----
def sector_pattern_note(sector_code):
    d = _load("sector_timeseries_v4_complete")
    stats = d.get("_full_period_stats", {})
    for item in stats.get("best_performers_by_score_change", []):
        if item.get("code") == sector_code and item.get("vol_high"):
            return "pump_dump_riski"
    return None


# ---- Deniz destek/direnç (pivot'tan iyi, gerçek seviye) ----
def deniz_levels(ticker):
    d = _load("support_resistance")
    st = d.get("stocks", {})
    lv = st.get(ticker)
    if not lv:
        return None
    return {"destek": [lv.get("d1"), lv.get("d2"), lv.get("d3")],
            "direnc": [lv.get("r1"), lv.get("r2"), lv.get("r3")],
            "5g_ho": lv.get("5g_ho")}


# ---- Hepsini birleştir: bir hisse için tüm yan-kaynak bayrakları ----
def annotate_ticker(ticker, sector=None, as_of=None, allow_stale_deniz=False):
    flags = {}
    ds = deniz_stock_score(ticker, as_of=as_of, allow_stale=allow_stale_deniz)
    if ds is not None:
        flags["deniz_skor"] = ds
    for fn, key in [(foreign_flow, "yabancı"), (volume_signal, "hacim"),
                    (seasonal_may, "sezonsal")]:
        v = fn(ticker)
        if v:
            flags[key] = v
    es = earnings_signal(ticker)
    if es and es.get("result"):
        flags["bilanço"] = es["result"]
    fx = fx_risk(ticker)
    if fx and "negatif" in fx:
        flags["fx_risk"] = fx
    if sector:
        sp = sector_pattern_note(sector)
        if sp:
            flags["sektör_uyarı"] = sp
    return flags
