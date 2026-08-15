"""Flow and buyback ledger.

Measurement layer only. It records share buybacks, foreign-flow observations,
and takas/custody observations, then follows forward returns. It never opens
trades and never changes the F production motor.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (5, 21, 63)
MAX_EVENTS = 700


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "flow_ledger.json"


def _kap_events_path() -> Path:
    return _repo_root() / "docs" / "state" / "catalysts.json"


def _local_flow_dir() -> Path:
    override = os.environ.get("FLOW_LEDGER_DIR")
    return Path(override) if override else _repo_root() / "local" / "flow_inputs"


HEADER_ALIASES = {
    "date": {"date", "tarih", "event_date", "islem_tarihi", "bildirim_tarihi"},
    "ticker": {"ticker", "kod", "hisse", "sembol", "pay_kodu", "symbol"},
    "type": {"type", "tur", "kategori", "event_type"},
    "signal": {"signal", "sinyal", "etiket", "yon", "direction"},
    "source": {"source", "kaynak"},
    "source_tier": {"source_tier", "kaynak_tipi"},
    "source_url": {"source_url", "url", "kap_url", "link"},
    "foreign_net_value": {"foreign_net_value", "yabanci_net_tutar", "yabanci_net_tl"},
    "foreign_net_lot": {"foreign_net_lot", "yabanci_net_lot", "yabanci_net_adet"},
    "foreign_ownership_pct": {"foreign_ownership_pct", "yabanci_payi", "yabanci_orani"},
    "takas_change_pct": {"takas_change_pct", "takas_degisim", "saklama_degisim"},
    "custody_concentration_pct": {
        "custody_concentration_pct", "takas_yogunlasma", "saklama_yogunlasma",
    },
    "buyback_lot": {"buyback_lot", "geri_alim_lot", "geri_alim_adet"},
    "buyback_value": {"buyback_value", "geri_alim_tutar", "geri_alim_tl"},
    "buyback_price": {"buyback_price", "geri_alim_fiyat", "ortalama_fiyat"},
    "note": {"note", "not", "aciklama", "title", "baslik"},
}

ALIASES_BY_HEADER = {
    alias: canonical
    for canonical, aliases in HEADER_ALIASES.items()
    for alias in aliases
}

NUMERIC_FIELDS = {
    "foreign_net_value", "foreign_net_lot", "foreign_ownership_pct",
    "takas_change_pct", "custody_concentration_pct", "buyback_lot",
    "buyback_value", "buyback_price",
}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _date_text(value):
    return str(value.date()) if hasattr(value, "date") else str(value)


def _round(value, digits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        value = round(float(value), digits)
    except Exception:
        return None
    return 0.0 if value == 0 else value


def _slug(value) -> str:
    text = str(value or "").strip()
    text = text.translate(str.maketrans({
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    }))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return text


def _coerce_number(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "nan", "None"}:
        return None
    text = text.replace("%", "").replace("x", "").replace("X", "").strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def _normalize_row(row: dict) -> dict:
    out = {}
    for raw_key, value in (row or {}).items():
        key = ALIASES_BY_HEADER.get(_slug(raw_key), _slug(raw_key))
        if key in NUMERIC_FIELDS:
            out[key] = _coerce_number(value)
        elif key == "date" and hasattr(value, "date"):
            out[key] = _date_text(value)
        elif key == "ticker":
            out[key] = _norm_ticker(value)
        else:
            out[key] = value
    return out


def _norm_ticker(ticker):
    return str(ticker or "").split(".")[0].upper().strip()


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(_repo_root()).as_posix()
    except Exception:
        return str(path)


def _local_paths():
    directory = _local_flow_dir()
    if not directory.exists():
        return []
    paths = []
    for pattern in ("*.json", "*.csv", "*.xlsx", "*.xls"):
        paths.extend(sorted(directory.glob(pattern)))
    return paths


def _read_local_file(path: Path):
    meta = {
        "source": "local flow extract",
        "source_ref": "private_local",
        "source_type": path.suffix.lower().lstrip(".") or "unknown",
    }
    rows = []
    try:
        if path.suffix.lower() == ".json":
            payload = _load_json(path, {})
            if isinstance(payload, list):
                rows = payload
            elif isinstance(payload, dict):
                meta.update(payload.get("_meta", {}) or {})
                rows = payload.get("events") or payload.get("rows") or []
        elif path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(path, encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="cp1254")
            rows = df.to_dict(orient="records")
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
            rows = df.to_dict(orient="records")
    except Exception as e:
        return {"_meta": {**meta, "error": str(e)}, "events": []}
    return {"_meta": meta, "events": [_normalize_row(r) for r in rows if isinstance(r, dict)]}


def _price_at_pos(prices, ticker, pos):
    if pos is None or pos < 0 or pos >= len(prices.index) or ticker not in prices.columns:
        return None
    value = prices.iloc[pos][ticker]
    if pd.isna(value) or value <= 0:
        return None
    return float(value)


def _first_price_on_or_after(prices, ticker, date_s):
    if prices is None or prices.empty or ticker not in prices.columns or not date_s:
        return None, None, None
    target = pd.Timestamp(date_s)
    pos = int(prices.index.searchsorted(target, side="left"))
    while pos < len(prices.index):
        value = _price_at_pos(prices, ticker, pos)
        if value is not None:
            return value, _date_text(prices.index[pos]), pos
        pos += 1
    return None, None, None


def _position_of_date(prices, date_s):
    """Tarihin fiyat matrisindeki konumu; PENCERE DISINDA -> None (KIRPMAZ).

    #0u (2026-08-14): `catalyst_ledger`den KOPYALANDI (uc kopya oldu -> `#0t`ye
    birlestirme adayi olarak yazildi).
    NEDEN `_first_price_on_or_after` DEGIL: o, ticker'in fiyati YOKSA ileri kayar.
    `entry_pos`i ondan turetmek, `#0u`in duzelttigi kaymayi `entry_pos`a TASIRDI
    (07-31 bari o ticker icin bossa yine 08-03'e atlardi). Burada aranan SAF
    tarih->konum; fiyatin dolu olup olmadigi ayri sorudur.

    #0q (2026-08-13): eski surum iki yonde de SESSIZCE KIRPIYORDU — pencere
    ONCESI icin `searchsorted` 0 doner ve 0 gecerli sayilirdi, pencere SONRASI
    icin `len-1` dondurulurdu. Kirpma, olculEMEYEN bir olaya pencere ucundaki
    BASKA bir gunun getirisini atfeder.
      Ayni kusur makroda OLCULDU: 259 olayin 235'i entry_pos=0'a kirpilip AYNI
      "-1.5%" 21g getirisini tasidi ve `hit_21d_pct 5.8` SAHTE ISTATISTIGI
      public panele cikti (bkz `#0p`).
    """
    if prices is None or prices.empty or not date_s:
        return None
    target = pd.Timestamp(date_s)
    if target < prices.index[0]:
        return None
    pos = int(prices.index.searchsorted(target, side="left"))
    if pos >= len(prices.index):
        return None
    return pos


# #0u — CIPALI ALANLAR: olayin TARIHSEL OLGUSU, feed sonradan degisse de sabit.
# Merge'de mevcut deger EZILMEZ. (`entry_pos` BU LISTEDE YOK: o kayan pencereye
# gore TUREV, her kosumda `entry_date`ten yeniden hesaplanir -- `#0q`.)
CIPALI_ALANLAR = ("entry_date", "entry_price")


def _event_key(event):
    return "|".join([
        str(event.get("source_id") or ""),
        str(event.get("type") or ""),
        str(event.get("event_date") or ""),
        str(event.get("ticker") or ""),
    ])


def _kap_buyback_events(prices):
    payload = _load_json(_kap_events_path(), {})
    rows = payload.get("events", []) if isinstance(payload, dict) else []
    events = []
    for row in rows:
        typ = _slug(row.get("type") or "")
        title = str(row.get("title") or "")
        title_l = title.lower()
        title_slug = _slug(title)
        is_buyback = typ == "geri_alim" or any(k in title_l for k in (
            "geri alim", "geri alım", "pay geri", "kendi pay",
            "payların geri", "paylarin geri",
        )) or any(k in title_slug for k in (
            "geri_alim", "pay_geri", "kendi_pay", "paylarin_geri",
        ))
        if not is_buyback:
            continue
        ticker = _norm_ticker(row.get("ticker"))
        event_date = row.get("date") or row.get("event_date")
        if not ticker or not event_date:
            continue
        entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, event_date)
        events.append({
            "source_id": "kap_buyback",
            "source": "KAP resmi geri alim bildirimi",
            "source_tier": "primary",
            "source_score": 3,
            "type": "geri_alim",
            "signal": "official_buyback",
            "event_date": str(event_date),
            "ticker": ticker,
            "entry_date": entry_date,
            "entry_price": _round(entry),
            "entry_pos": entry_pos,
            "opens_trade": False,
            "kap_confirmed": True,
            "note": title,
            "source_url": row.get("url"),
        })
    return events


def _local_flow_events(prices):
    out = []
    for payload in [_read_local_file(p) for p in _local_paths()]:
        meta = payload.get("_meta", {})
        for row in payload.get("events", []):
            ticker = _norm_ticker(row.get("ticker"))
            event_date = row.get("date") or row.get("event_date")
            if not ticker or not event_date:
                continue
            typ = _slug(row.get("type") or "flow")
            if typ in {"yabanci", "foreign", "foreignflow"}:
                typ = "foreign_flow"
            elif typ in {"takas", "saklama", "custody"}:
                typ = "takas"
            entry, entry_date, entry_pos = _first_price_on_or_after(prices, ticker, event_date)
            source_tier = row.get("source_tier") or meta.get("source_tier") or "local_private"
            source_score = 2 if source_tier in {"licensed", "broker", "local_private"} else 1
            out.append({
                "source_id": row.get("source_id") or f"{typ}:private_local",
                "source": row.get("source") or meta.get("source") or "private local flow extract",
                "source_ref": meta.get("source_ref", "private_local"),
                "source_tier": source_tier,
                "source_score": source_score,
                "type": typ,
                "signal": row.get("signal") or row.get("direction") or row.get("sinyal"),
                "event_date": str(event_date),
                "ticker": ticker,
                "entry_date": entry_date,
                "entry_price": _round(entry),
                "entry_pos": entry_pos,
                "opens_trade": False,
                "kap_confirmed": bool(row.get("kap_confirmed", False)),
                "foreign_net_value": _round(row.get("foreign_net_value"), 1),
                "foreign_net_lot": _round(row.get("foreign_net_lot"), 1),
                "foreign_ownership_pct": _round(row.get("foreign_ownership_pct"), 2),
                "takas_change_pct": _round(row.get("takas_change_pct"), 2),
                "custody_concentration_pct": _round(row.get("custody_concentration_pct"), 2),
                "buyback_lot": _round(row.get("buyback_lot"), 1),
                "buyback_value": _round(row.get("buyback_value"), 1),
                "buyback_price": _round(row.get("buyback_price"), 2),
                "note": row.get("note"),
                "source_url": row.get("source_url") or row.get("url"),
                "public_detail_policy": "aggregate_metrics_only; raw takas holder details stay local",
            })
    return out


def _refresh_event(event, prices, as_of_pos):
    ticker = event.get("ticker")
    entry = event.get("entry_price")
    if entry is None and event.get("event_date"):
        # ILK hesap: giris henuz yok -> event_date'ten TURET ve CIPALA.
        entry, entry_date, _pos0 = _first_price_on_or_after(prices, ticker, event.get("event_date"))
        event["entry_price"] = _round(entry)
        event["entry_date"] = entry_date
    # #0u/#0q: `entry_pos` TUREV -> HER KOSUMDA cipali `entry_date`ten hesaplanir.
    # Onbelleklenirse pencere kaydikca bayatlar (`#0q`); `_first_price_on_or_after`
    # ile turetilirse fiyati bos gunlerde ILERI KAYAR ve `#0u`in duzelttigi kayma
    # geri gelir. Bu yuzden SAF tarih->konum (`_position_of_date`).
    entry_pos = _position_of_date(prices, event.get("entry_date"))
    event["entry_pos"] = entry_pos
    current = _price_at_pos(prices, ticker, as_of_pos)
    event["current_price"] = _round(current)
    if entry is None or entry_pos is None or current is None:
        event["status"] = "missing_price"
        event["current_return_pct"] = None
        return event
    age = max(0, int(as_of_pos - int(entry_pos)))
    event["age_trading_days"] = age
    event["current_return_pct"] = _round((current / float(entry) - 1) * 100)
    for window in WINDOWS:
        key = f"return_{window}d_pct"
        if int(entry_pos) + window <= as_of_pos:
            px = _price_at_pos(prices, ticker, int(entry_pos) + window)
            event[key] = _round((px / float(entry) - 1) * 100) if px else None
        else:
            event[key] = None
    mature = [w for w in WINDOWS if event.get(f"return_{w}d_pct") is not None]
    event["status"] = f"mature_{max(mature)}d" if mature else "open"
    return event


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _hit(values):
    values = [float(v) for v in values if v is not None]
    return sum(1 for v in values if v > 0) / len(values) * 100 if values else None


def _summary(events, as_of):
    ret21 = [e.get("return_21d_pct") for e in events]
    ret63 = [e.get("return_63d_pct") for e in events]
    by_type = {}
    for event in events:
        typ = event.get("type") or "unknown"
        row = by_type.setdefault(typ, {"type": typ, "n": 0, "ret21": [], "wins21": 0, "mature_21d": 0})
        row["n"] += 1
        if event.get("return_21d_pct") is not None:
            row["mature_21d"] += 1
            row["ret21"].append(event["return_21d_pct"])
            row["wins21"] += 1 if float(event["return_21d_pct"]) > 0 else 0
    type_rows = []
    for row in by_type.values():
        n21 = row["mature_21d"]
        type_rows.append({
            "type": row["type"],
            "n": row["n"],
            "mature_21d": n21,
            "avg_21d_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(row["wins21"] / n21 * 100, 1) if n21 else None,
        })
    mature21 = [e for e in events if e.get("return_21d_pct") is not None]
    decision = "olcum_devam"
    if not events:
        decision = "akis_ve_geri_alim_verisi_bekliyor"
    elif len(mature21) >= 20:
        avg21 = _avg(ret21)
        hit21 = _hit(ret21)
        decision = "izleme_degeri_var" if avg21 is not None and avg21 > 0 and (hit21 or 0) >= 50 else "kenarda_tut"
    local_files = _local_paths()
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "tracked_events": len(events),
        "opens_trade": False,
        "matured_5d": len([e for e in events if e.get("return_5d_pct") is not None]),
        "matured_21d": len(mature21),
        "matured_63d": len([e for e in events if e.get("return_63d_pct") is not None]),
        "avg_21d_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(_hit(ret21), 1),
        "avg_63d_return_pct": _round(_avg(ret63)),
        "hit_63d_pct": _round(_hit(ret63), 1),
        "kap_buyback_events": len([e for e in events if e.get("type") == "geri_alim"]),
        "foreign_flow_events": len([e for e in events if e.get("type") == "foreign_flow"]),
        "takas_events": len([e for e in events if e.get("type") == "takas"]),
        "local_input_files": len(local_files),
        "local_input_source": "private_local",
        "decision": decision,
        "readiness": {
            "status": "active" if events else "empty",
            "data_status": "kap_buyback_scanner_active_no_event_yet" if not events else "measuring",
            "message": (
                "KAP geri alim taramasi aktif; yabanci/takas icin local-private akis dosyasi bekleniyor. "
                "Ham takas ve lisansli akis detaylari public repo'ya yazilmaz."
            ),
            "next_step": "KAP geri alim olayi geldikce otomatik olculur; yabanci/takas icin private input alani kullan.",
            "known_contract": "docs/AKIS_GERI_ALIM_DEFTERI.md",
            "opens_trade": False,
            "promotion_gate": "closed_until_20_mature_21d_events",
        },
        "latest_candidates": sorted(events, key=lambda e: e.get("event_date") or "", reverse=True)[:10],
        "by_type": sorted(type_rows, key=lambda x: x["type"]),
        "note": (
            "Akis ve geri alim defteri olcer; KAP geri alim resmi, yabanci/takas local-private "
            "kaynakla izlenir. F motoruna emir uretmez."
        ),
        "public_detail_policy": "raw takas holder details and licensed flow extracts stay private-only",
    }


def update(report, data, path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    ledger_path = Path(path) if path else _ledger_path()
    existing = _load_json(ledger_path, {"events": []}).get("events", [])
    merged = {_event_key(e): e for e in existing}
    for event in _kap_buyback_events(prices) + _local_flow_events(prices):
        old = merged.get(_event_key(event), {})
        # #0u: CIPALI alanlar EZILMEZ. `_kap_buyback_events`/`_local_flow_events`
        # olayi HER KOSUMDA sifirdan kuruyor ve taze `entry_date`/`entry_price`
        # uretiyor; eski `old.update(...)` bunlari mevcut degerlerin USTUNE
        # yaziyordu -> defterin gecmisi feed'le birlikte kayiyordu.
        #   OLCULDU (2026-08-14): 3/22 olay kaydi. AKSGY/BALAT/EKIM 07-31 ->
        #   08-03; sebep 07-31 barinin feed'de sonradan %98.7 NaN'a dusmesi
        #   (defter yazildiginda fiyat VARDI). entry_price 9.3 -> 9.6 vb.
        # Ayni fikir bu dosyada zaten vardi (`quality`de `kap_confirmed` sticky);
        # `#0u` onu KALICI-ALAN kavramina genellestiriyor.
        old.update({k: v for k, v in event.items()
                    if (v is not None or k not in old)
                    and not (k in CIPALI_ALANLAR and old.get(k) is not None)})
        merged[_event_key(event)] = old
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    events = [_refresh_event(event, prices, as_of_pos) for event in events]
    events.sort(key=lambda e: (e.get("event_date") or "", e.get("type") or "", e.get("ticker") or ""))
    payload = {
        "summary": _summary(events, as_of),
        "events": events,
    }
    _save_json(ledger_path, payload)
    return payload["summary"]
