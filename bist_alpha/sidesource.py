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

_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "omega")
_cache = {}


def _load(name):
    if name in _cache:
        return _cache[name]
    path = os.path.join(_DIR, f"{name}.json")
    try:
        with open(path, encoding="utf-8") as f:
            _cache[name] = json.load(f)
    except Exception:
        _cache[name] = {}
    return _cache[name]


# ---- Deniz hisse teknik skoru ----
def deniz_stock_score(ticker):
    d = _load("deniz_puanlari")
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
def annotate_ticker(ticker, sector=None):
    flags = {}
    ds = deniz_stock_score(ticker)
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
