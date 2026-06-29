"""BIST hisse evreni.

Normal akışta BIST sembol havuzu canlı/harici kaynaktan oluşturulur. Ağ veya
kaynak geçici bozulursa sistem durmasın diye aşağıdaki liste yedek olarak kalır.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path

FALLBACK_BIST_TICKERS = [
    'AAGYO', 'ACSEL', 'ADEL', 'ADESE', 'ADGYO', 'AEFES', 'AFYON', 'AGESA',
    'AGHOL', 'AGROT', 'AGYO', 'AHGAZ', 'AHSGY', 'AKBNK', 'AKCNS', 'AKENR',
    'AKFGY', 'AKFIS', 'AKFYE', 'AKGRT', 'AKMGY', 'AKSA', 'AKSEN', 'ALARK',
    'ALBRK', 'ALCAR', 'ALCTL', 'ALFAS', 'ALGYO', 'ALKA', 'ALKIM', 'ALKLC',
    'ALTNY', 'ALVES', 'ANEL', 'ANGEN', 'ANHYT', 'ANSGR', 'ARASE', 'ARCLK',
    'ARDYZ', 'ARENA', 'ARMGD', 'ARSAN', 'ARTMS', 'ARZUM', 'ASELS', 'ASGYO',
    'ASTOR', 'ASUZU', 'ATAGY', 'ATAKP', 'ATATP', 'ATATR', 'ATEKS', 'ATLAS',
    'ATSYH', 'AVGYO', 'AVHOL', 'AVPGY', 'AYCES', 'AYDEM', 'AYEN', 'AYGAZ',
    'AZTEK', 'BAGFS', 'BALSU', 'BANVT', 'BASGZ', 'BAYRK', 'BEYAZ', 'BIMAS',
    'BIOEN', 'BIZIM', 'BMSCH', 'BNTAS', 'BOBET', 'BORLS', 'BORSK', 'BOSSA',
    'BRISA', 'BRKVY', 'BRSAN', 'BRYAT', 'BSOKE', 'BTCIM', 'BUCIM', 'BURCE',
    'BVSAN', 'CANTE', 'CCOLA', 'CEMAS', 'CEMTS', 'CGCAM', 'CIMSA', 'CLEBI',
    'CMBTN', 'CONSE', 'CRDFA', 'CRFSA', 'CVKMD', 'CWEN', 'DARDL', 'DENGE',
    'DEVA', 'DGGYO', 'DOAS', 'DOFRB', 'DOGUB', 'DOHOL', 'DOKTA', 'DSTKF',
    'DYOBY', 'EBEBEK', 'ECILC', 'ECZYT', 'EGEEN', 'EGGUB', 'EGPRO', 'EGSER',
    'EKGYO', 'EMNIS', 'ENERY', 'ENJSA', 'ENKAI', 'ERCB', 'EREGL', 'ESCAR',
    'EUPWR', 'FROTO', 'FZLGY', 'GARAN', 'GEDIK', 'GENIL', 'GEREL', 'GIPTA',
    'GLRMK', 'GUBRF', 'HALKB', 'HEDEF', 'HEKTS', 'HTTBT', 'HURGZ', 'ICBTC',
    'IEYHO', 'IHAAS', 'INDES', 'INFO', 'ISCTR', 'ISDMR', 'IZENR', 'KAREL',
    'KARSN', 'KAYSE', 'KBORU', 'KCHOL', 'KLGYO', 'KLKIM', 'KLMSN', 'KLSER',
    'KONTR', 'KONYA', 'KOTON', 'KRDMA', 'KRDMB', 'KRDMD', 'KTLEV', 'KTSKR',
    'KUTPO', 'KUYAS', 'LILAK', 'MAGEN', 'MANAS', 'MAVI', 'MGROS', 'MIATK',
    'MOBTL', 'MPARK', 'MTRKS', 'NETAS', 'NETCD', 'NTGAZ', 'OBAMS', 'ODAS',
    'ODINE', 'OTKAR', 'OYAKC', 'OZKGY', 'PAHOL', 'PAPIL', 'PATEK', 'PEKGY',
    'PENGD', 'PENTA', 'PETKM', 'PGSUS', 'POLHO', 'QNBTR', 'RAYSG', 'REEDER',
    'RYSAS', 'SAHOL', 'SARKY', 'SASA', 'SAYAS', 'SDTTR', 'SELEC', 'SISE',
    'SMRTG', 'SOKM', 'TABGD', 'TATGD', 'TAVHL', 'TBORG', 'TCELL', 'TEHOL',
    'TERA', 'THYAO', 'TKFEN', 'TKNSA', 'TKSB', 'TMSN', 'TOASO', 'TRALT',
    'TRGYO', 'TRILC', 'TTKOM', 'TTRAK', 'TUPRS', 'TURSG', 'ULKER', 'VAKBN',
    'VAKKO', 'VBTYZ', 'VESBE', 'VESTL', 'YEOTK', 'YKBNK', 'ZOREN', 'ZRGYO',
]

_LAST_META = {
    "method": "fallback_static",
    "count": len(FALLBACK_BIST_TICKERS),
    "fallback": True,
}


def _env(key, default=None):
    return os.environ.get(key, default)


def _cache_path():
    return Path(_env(
        "BIST_SYMBOLS_CACHE_PATH",
        os.path.join(tempfile.gettempdir(), "bistalpha_bist_symbols.json"),
    ))


def _cache_hours():
    try:
        return float(_env("BIST_SYMBOLS_CACHE_HOURS", "12"))
    except ValueError:
        return 12.0


def _normalize(symbol):
    symbol = str(symbol or "").upper().strip()
    symbol = symbol.split(":")[-1].split(".")[0]
    symbol = re.sub(r"[^A-Z0-9]", "", symbol)
    if not symbol or symbol.startswith(("XU", "XK", "XT", "XY")):
        return None
    return symbol if 3 <= len(symbol) <= 8 else None


def _dedupe(symbols):
    out = []
    seen = set()
    for raw in symbols:
        symbol = _normalize(raw)
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return sorted(out)


def _read_cache():
    path = _cache_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - float(payload.get("created_at", 0))
        if age > _cache_hours() * 3600:
            return None
        symbols = _dedupe(payload.get("symbols", []))
        if len(symbols) >= 100:
            return symbols, payload.get("method", "cache")
    except Exception:
        return None
    return None


def _write_cache(symbols, method):
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "created_at": time.time(),
            "method": method,
            "symbols": symbols,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fetch_tradingview_symbols():
    import requests

    url = "https://scanner.tradingview.com/turkey/scan"
    payload = {
        "columns": ["name", "exchange", "type", "subtype", "typespecs"],
        "filter": [
            {"left": "exchange", "operation": "equal", "right": "BIST"},
            {"left": "type", "operation": "equal", "right": "stock"},
        ],
        "options": {"lang": "tr"},
        "range": [0, 900],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "symbols": {"query": {"types": []}, "tickers": []},
    }
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json().get("data", [])
    symbols = []
    for item in data:
        row = item.get("d") or []
        name = row[0] if row else item.get("s")
        symbols.append(name)
    symbols = _dedupe(symbols)
    if len(symbols) < 100:
        raise ValueError(f"TradingView BIST sembol havuzu zayif: {len(symbols)}")
    return symbols


def _load_external_symbols():
    source = _env("BIST_SYMBOLS_SOURCE", "auto").lower()
    if source in ("fallback", "static", "file"):
        raise RuntimeError("BIST_SYMBOLS_SOURCE fallback olarak ayarli")

    cached = _read_cache()
    if cached:
        symbols, method = cached
        return symbols, f"{method}_cache"

    if source not in ("auto", "tradingview"):
        raise RuntimeError(f"Bilinmeyen BIST_SYMBOLS_SOURCE: {source}")

    symbols = _fetch_tradingview_symbols()
    _write_cache(symbols, "tradingview_bist_scanner")
    return symbols, "tradingview_bist_scanner"


def all_bist_tickers():
    """BIST tum hisse kaynak havuzunu dondurur; canli kaynak yoksa yedek liste."""
    global _LAST_META
    try:
        symbols, method = _load_external_symbols()
        _LAST_META = {"method": method, "count": len(symbols), "fallback": False}
        return symbols
    except Exception as exc:
        symbols = _dedupe(FALLBACK_BIST_TICKERS)
        _LAST_META = {
            "method": "fallback_static",
            "count": len(symbols),
            "fallback": True,
            "error": str(exc),
        }
        return symbols


def universe_meta():
    return dict(_LAST_META)


BIST_TICKERS = FALLBACK_BIST_TICKERS

SYMBOL_DISPLAY_ALIASES = {
    # TradingView/BIST havuzu bazi yeni/ozel sembolleri kisaltarak dondurebiliyor.
    "ALTIN": "ALTINS1",
    "DMLKT": "DMLKTG",
}

YAHOO_SYMBOL_ALIASES = {
    # Sadece Yahoo'da gercekten veri donduren farkli semboller buraya eklenir.
}


def yahoo_symbols(tickers=None):
    """Yahoo Finance sembolleri (BIST = .IS suffix)."""
    return [YAHOO_SYMBOL_ALIASES.get(t, t + ".IS") for t in (tickers or all_bist_tickers())]


def display_symbol(symbol):
    """Kullaniciya gosterilecek nihai BIST sembol adi."""
    return SYMBOL_DISPLAY_ALIASES.get(symbol, symbol)
