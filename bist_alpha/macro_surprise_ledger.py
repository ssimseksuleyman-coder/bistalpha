"""Macro surprise ledger.

Measurement layer only. It follows manually or programmatically recorded macro
surprise events against broad BIST and F Top10 forward returns. It does not
open trades or modify the F production motor.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


WINDOWS = (1, 5, 21, 63)
MAX_EVENTS = 500


EVENT_TYPES = {
    "US_CPI": "external",
    "FED": "external",
    "NFP": "external",
    "DXY": "external",
    "US10Y": "external",
    "BRENT": "external",
    "TR_CPI": "turkey",
    "TCMB_RATE": "turkey",
    "PMI": "turkey",
    "INDUSTRIAL_PRODUCTION": "turkey",
    "RESERVES": "turkey",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ledger_path() -> Path:
    return _repo_root() / "docs" / "state" / "macro_surprise_ledger.json"


def _sources_path() -> Path:
    return _repo_root() / "docs" / "state" / "macro_surprise_sources.json"


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


def _date_text(value):
    return str(value.date()) if hasattr(value, "date") else str(value)


def _norm_ticker(ticker):
    return str(ticker or "").split(".")[0].upper().strip()


def _price_at_pos(prices, ticker, pos):
    if pos is None or pos < 0 or pos >= len(prices.index) or ticker not in prices.columns:
        return None
    value = prices.iloc[pos][ticker]
    if pd.isna(value) or value <= 0:
        return None
    return float(value)


def _before_window(prices, date_s):
    """Olay tarihi fiyat penceresinin BASLANGICINDAN once mi?"""
    if prices is None or prices.empty or not date_s:
        return False
    try:
        return pd.Timestamp(date_s) < prices.index[0]
    except Exception:
        return False


def _first_pos_on_or_after(prices, date_s):
    """Olayin giris pozisyonu; OLCULEMEZSE (None, None).

    BUG (2026-08-07, makro backfill'i acikca gosterdi): `searchsorted` pencere
    ONCESI bir tarih icin 0 doner, ve 0 < len oldugu icin eski surum onu GECERLI
    sayardi -> 2005 tarihli bir olay, 2024'teki pencere BASLANGICINA kirpilir ve
    o gunun ileri-getirisi o olaya atfedilirdi. Sonuc: 259 olayin 235'i AYNI
    entry_pos=0'i ve AYNI "-1.5%" 21g getirisini tasidi; `hit_21d_pct` 5.8
    gibi bir SAHTE ISTATISTIK panelde yayinlandi.
    Pencere SONRASI zaten dogru ele aliniyordu (pos >= len -> None); eksik olan
    ONCESIYDI. Sinif: "olcemedigini olctum sanmak" — sinyal yoklugu != sorun
    yoklugu'nun hesaplama tarafi.
    """
    if prices is None or prices.empty or not date_s:
        return None, None
    if _before_window(prices, date_s):
        return None, None
    pos = int(prices.index.searchsorted(pd.Timestamp(date_s), side="left"))
    if pos >= len(prices.index):
        return None, None
    return pos, _date_text(prices.index[pos])


def _basket_return(prices, tickers, entry_pos, window):
    if entry_pos is None or int(entry_pos) + window >= len(prices.index):
        return None
    returns = []
    for ticker in tickers:
        start = _price_at_pos(prices, ticker, int(entry_pos))
        end = _price_at_pos(prices, ticker, int(entry_pos) + window)
        if start and end:
            returns.append((end / start - 1) * 100)
    return _round(sum(returns) / len(returns)) if returns else None


def _event_key(event):
    return "|".join([
        str(event.get("id") or event.get("source_id") or ""),
        str(event.get("date") or ""),
        str(event.get("type") or ""),
    ])


def _sources():
    payload = _load_json(_sources_path(), {"sources": []})
    return payload.get("sources", []) if isinstance(payload, dict) else []


def _source_events(sources):
    events = []
    for source in sources:
        if source.get("disabled"):
            continue
        event_type = str(source.get("type") or "").upper()
        event_date = source.get("date")
        if not event_type or not event_date:
            continue
        group = EVENT_TYPES.get(event_type, source.get("group") or "unknown")
        actual = source.get("actual")
        expected = source.get("expected")
        surprise = source.get("surprise")
        if surprise is None and actual is not None and expected not in (None, 0):
            try:
                surprise = float(actual) - float(expected)
            except Exception:
                surprise = None
        events.append({
            "key": _event_key(source),
            "id": source.get("id") or _event_key(source),
            "date": str(event_date),
            "type": event_type,
            "group": group,
            "source": source.get("source"),
            "source_url": source.get("source_url"),
            "actual": actual,
            "expected": expected,
            "surprise": _round(surprise, 4),
            "unit": source.get("unit"),
            "direction": source.get("direction", "unknown"),
            "note": source.get("note"),
            "opens_trade": False,
        })
    return events


def _refresh_event(event, report, prices, as_of_pos):
    # PENCERE ONCESI OLAY -> OLCULEMEZ. Bu kontrol CACHE'TEN ONCE gelir:
    # `entry_pos` olayda onbelleklendigi icin (asagi) yalniz fonksiyonu duzeltmek
    # ESKI KIRPILMIS kayitlari IYILESTIRMEZ. Burasi onlari da temizler (idempotent).
    if _before_window(prices, event.get("date")):
        event["entry_pos"] = None
        event["entry_date"] = None
        event["age_trading_days"] = None
        for w in WINDOWS:
            event[f"market_return_{w}d_pct"] = None
            event[f"f_top10_return_{w}d_pct"] = None
        event["status"] = "veri_penceresi_oncesi"
        return event
    # #0q (2026-08-13): `entry_pos` KALICI VERI DEGIL — kayan 2 yillik pencereye
    # gore TUREVDIR. Onbelleklenirse pencere her ilerledikce eski bari gosterir
    # ve olcum SESSIZCE yanlis tarihten baslar.
    #   OLCULDU: 24/24 olayin entry_pos'u 5 bar kayikti (kayitli 2024-09-03 ->
    #   fiilen 2024-09-10 olculuyordu) ve 23 olgun olayin 23'unun getirisi bir
    #   gecede degisti (2025-10-03: 3.00 -> -0.28, ISARET degisimi).
    # KALICI olan `date`; entry_pos/entry_date HER KOSUMDA ondan turetilir
    # (idempotent, pencere kaymasina bagisik).
    # NOT: pencere-oncesi korumasi (yukarida) BU SATIRLARDAN ONCE calisir, ve
    # `_first_pos_on_or_after` kirpma-karsiti (2026-08-07 duzeltmesi) -> pencere
    # disi olay 0'a KIRPILMAZ, None doner.
    entry_pos, entry_date = _first_pos_on_or_after(prices, event.get("date"))
    event["entry_pos"] = entry_pos
    event["entry_date"] = entry_date
    if entry_pos is None:
        event["status"] = "future_or_missing_price"
        return event
    age = max(0, int(as_of_pos - int(entry_pos)))
    event["age_trading_days"] = age
    all_tickers = [c for c in prices.columns if c]
    # ⚠️ #0p — LOOK-AHEAD UYARISI (2026-08-12). Alan DEGISTIRILMEDI, ama
    # SONUCU HUKME ESAS ALINAMAZ. `f_tickers` BUGUNUN top10'u; `entry_pos`
    # ise gecmis bir tarih (2024-09-03 gibi). Yani olculen sey:
    # "F'in BUGUN sectigi hisseler, IKI YIL ONCEKI tarihten 21 gunde ne getirdi".
    # Bugunun top10'u zaten 252-gun momentumu yuksek OLDUGU ICIN orada
    # -> gecmise uygulamak pozitif sonucu GARANTILER.
    # OLCULDU: f_top10 - market = avg +15.79 / hit %95.7 (n=23) = artefakt imzasi.
    # Karsilastirmasi: market = avg +2.61 / hit %65.2.
    # Duzeltmesi ayri is: olay anindaki top10 gerekir (`f_top10_at_entry`
    # alani `catalyst_ledger`de VAR, burada YOK). Silmiyoruz cunku o gun
    # geldiginde tarihsel kayit lazim; ama kapi bu alani KULLANMAZ.
    f_tickers = [_norm_ticker(r.get("ticker")) for r in (report or {}).get("top10", [])]
    f_tickers = [t for t in f_tickers if t in prices.columns]
    for window in WINDOWS:
        event[f"market_return_{window}d_pct"] = _basket_return(prices, all_tickers, entry_pos, window)
        event[f"f_top10_return_{window}d_pct"] = _basket_return(prices, f_tickers, entry_pos, window)
    mature = [w for w in WINDOWS if event.get(f"market_return_{w}d_pct") is not None]
    event["status"] = f"mature_{max(mature)}d" if mature else "open"
    return event


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _hit(values):
    values = [float(v) for v in values if v is not None]
    return sum(1 for v in values if v > 0) / len(values) * 100 if values else None


# =====================================================================
# #0p — KOSULSUZ TABAN CIZGISI (2026-08-12)
# =====================================================================
BASELINE_MIN_N = 60             # taban icin gereken en az gozlem
MIN_MATURE_FOR_DECISION = 20    # eskiden satir-ici sabit "20"


def _basket_return_series(prices, window):
    """`_basket_return`in VEKTORLESTIRILMIS ayni-anlamli hali.

    NEDEN: taban ~485 baslangic noktasi ister. `_basket_return` dongusu
    olculdu -> **39.7 sn** (her pozisyonda ticker basina `prices.iloc[pos]`
    bir Series yaratiyor). Gunde 3 kosan daemon icin kabul edilemez.
    Vektorlestirilmis hali **0.026 sn** (~1500x).

    ESDEGERLIK, DAVRANIS DAVRANISA:
      `_price_at_pos` NaN ve `value <= 0` -> None    =>  `.where(frame > 0)`
      `_basket_return` `if start and end`            =>  oran NaN ise disarida
      `entry_pos + window >= len(index)` -> None     =>  `shift(-window)` NaN
      ortalama sonra `_round`                        =>  ayni `_round`
    Tum pozisyonlarda dogrulandi (5 nokta DEGIL) — bkz ACIK_ISLER #0p.
    """
    if prices is None or getattr(prices, "empty", True):
        return None
    frame = prices[[c for c in prices.columns if c]]
    frame = frame.where(frame > 0)
    fwd = (frame.shift(-window) / frame - 1.0) * 100.0
    return fwd.mean(axis=1, skipna=True).map(lambda v: _round(v) if v == v else float("nan"))


def _baseline_stats(prices, window, lo_pos, hi_pos):
    """KOSULSUZ TABAN — "kosullu vs kosulsuz" karsilastirmasinin paydasi.

    Olay gunlerinin getirisi, AYNI ARALIKTAKI TUM GUNLERIN getirisiyle
    karsilastirilir. Ayni hesap (`_basket_return_series` = `_basket_return`in
    dogrulanmis vektor hali), ayni fiyat matrisi, ayni pencere, ayni evren;
    degisen TEK sey baslangic tarihleri kumesi:

        kosullu  = yalniz olay tarihleri          (n ~ 23)
        kosulsuz = araliktaki her islem gunu      (n ~ 485)

    NEDEN MUTLAK ESIK DEGIL: `avg>0 / hit>=50` evren yonunu olcume SIZDIRIR.
    Yukselen bir piyasada rastgele 23 tarih bu esigi %91.03 geciyor
    (bootstrap 20 000 tekrar; bkz ACIK_ISLER #0p) -> kapi ayirt etmiyor.

    CALISMA ANINDA hesaplanir, SABIT GOMULMEZ: taban rejime baglidir
    (2024-08..2026-08 icin avg +2.51 / hit %63.7; baska donemde baska deger).

    NOT: olay gunleri tabandan CIKARILMAZ (23/485 = %4.7). Dahil etmek
    muhafazakar yondedir: olaylar iyiyse tabani hafifce YUKARI ceker,
    yani kapiyi zorlastirir.
    """
    if prices is None or lo_pos is None or hi_pos is None:
        return None
    series = _basket_return_series(prices, window)
    if series is None:
        return None
    window_vals = series.iloc[int(lo_pos):int(hi_pos) + 1]
    values = [float(v) for v in window_vals if v == v]   # NaN ele
    if len(values) < BASELINE_MIN_N:
        return None
    return {
        "n": len(values),
        "avg": _round(_avg(values)),
        "hit": _round(_hit(values), 1),
        "window": window,
        "from": _date_text(prices.index[int(lo_pos)]),
        "to": _date_text(prices.index[int(hi_pos)]),
    }


def _hit_se(n, baseline_hit_pct):
    """Hit oraninin standart hatasi (yuzde puani) — SIFIR HIPOTEZI altinda.

    ⚠️ VARYANS TABANDAN ALINIR, ORNEKLEMDEN DEGIL. Sinadigimiz hipotez
    "olay gunleri taban dagilimindan geliyor" -> H0'in varyansi p0(1-p0)/n,
    p0 = TABAN hit orani.

    NEDEN ONEMLI (cift-yonlu testte YAKALANDI, 2026-08-12): ornekleme
    dayali SE, hit %0 veya %100'de p(1-p)=0 -> **SE=0** verir ve kapi tam
    kacinmak istedigimiz ciplak `>`a GERI DUSER. Ilk surumde sagliklı-yon
    testi (en iyi 23 gun, hit %100) GREEN verdi ama YANLIS SEBEPLE: guvenlik
    payi anlamli oldugu icin degil, pay YOK OLDUGU icin. Taban orani ~%64-67
    oldugundan p0(1-p0) asla cokmez.
    """
    if not n or int(n) <= 0 or baseline_hit_pct is None:
        return None
    p0 = float(baseline_hit_pct) / 100.0
    if p0 <= 0.0 or p0 >= 1.0:
        return None
    return _round((p0 * (1 - p0) / int(n)) ** 0.5 * 100, 1)


def _summary(events, as_of, sources, prices=None):
    ret21 = [e.get("market_return_21d_pct") for e in events]
    ret63 = [e.get("market_return_63d_pct") for e in events]
    by_group = {}
    for event in events:
        group = event.get("group") or "unknown"
        row = by_group.setdefault(group, {"group": group, "n": 0, "ret21": []})
        row["n"] += 1
        row["ret21"].append(event.get("market_return_21d_pct"))
    group_rows = []
    for row in by_group.values():
        group_rows.append({
            "group": row["group"],
            "n": row["n"],
            "avg_21d_market_return_pct": _round(_avg(row["ret21"])),
            "hit_21d_pct": _round(_hit(row["ret21"]), 1),
        })
    decision = "olay_bekliyor" if not events else "olcum_devam"
    baseline21 = None
    edge21 = None
    mature21 = [r for r in ret21 if r is not None]
    if len(mature21) >= MIN_MATURE_FOR_DECISION and _avg(ret21) is not None:
        # Taban ARALIGI olaylarin kendi araligi olmali (elma-elma).
        poss = [int(e["entry_pos"]) for e in events
                if e.get("market_return_21d_pct") is not None
                and e.get("entry_pos") is not None]
        baseline21 = _baseline_stats(prices, 21, min(poss), max(poss)) if poss else None
        if baseline21 is None:
            # Taban yoksa HUKUM DE YOK. Eski davranisa (mutlak esik) DUSULMEZ.
            decision = "taban_hesaplanamadi"
        else:
            avg_edge = _round(_avg(ret21) - baseline21["avg"])
            hit_edge = _round((_hit(ret21) or 0) - baseline21["hit"], 1)
            # SE TABANDAN (H0), orneklemden DEGIL — bkz `_hit_se` docstring.
            hit_se = _hit_se(len(mature21), baseline21["hit"])
            edge21 = {
                "avg_pp": avg_edge,
                "hit_pp": hit_edge,
                "hit_se_pp": hit_se,
                "hit_se_basis": "baseline_h0",
                "hit_edge_in_se": (_round(hit_edge / hit_se, 2)
                                   if hit_se is not None and hit_se > 0 else None),
            }
            # KAPI: tabanin USTUNDE olmak YETMEZ — bir standart hata KADAR ustunde olmali.
            # Ciplak `>` ile rastgele orneklerin ~%50'si gecer (simetri) -> yine ayirt etmez.
            # Olcum: mevcut veride hit farki +1.5pp, SE 10.0pp -> 0.15 SE -> kenarda_tut.
            decision = ("izleme_degeri_var"
                        if avg_edge > 0 and hit_se is not None and hit_edge > hit_se
                        else "kenarda_tut")
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "tracked_events": len(events),
        "source_count": len([s for s in sources if not s.get("disabled")]),
        "opens_trade": False,
        "matured_21d": len([e for e in events if e.get("market_return_21d_pct") is not None]),
        "matured_63d": len([e for e in events if e.get("market_return_63d_pct") is not None]),
        "avg_21d_market_return_pct": _round(_avg(ret21)),
        "hit_21d_pct": _round(_hit(ret21), 1),
        "avg_63d_market_return_pct": _round(_avg(ret63)),
        "hit_63d_pct": _round(_hit(ret63), 1),
        # #0p — HUKMU DENETLENEBILIR YAPAN IKI ALAN. Kararin dayanagi
        # panelde/JSON'da GORUNUR olmali, yoksa okuyan yine cikarim uydurur.
        "baseline_21d": baseline21,
        "edge_vs_baseline_21d": edge21,
        "decision": decision,
        "readiness": {
            "status": "active" if events else "empty",
            "data_status": "macro_event_source_waiting" if not events else "measuring",
            # 2026-08-13: `message`/`next_step` KOSULSUZ sabit metindi -> kart
            # kendisiyle CELISIYORDU: ayni kutuda hem "measuring" hem "kaynak
            # gelmeden hukum yok", ve 08-06'da yuklenen 259 kaynagi "ekle" diye
            # oneriyordu. Artik `status`/`data_status` gibi VERIDEN turetiliyor.
            "message": (
                "Makro defter hazir; kaynak/event gelmeden surpiz alpha hukmu yok. "
                "Consensus yoksa olay sadece takvim/reaksiyon olcumu sayilir."
                if not events else
                f"{len(events)} olay izleniyor. Hukum KOSULSUZ TABANA gore veriliyor "
                "(ayni fiyat matrisinde tum baslangic noktalari); mutlak esik KULLANILMAZ."
            ),
            "next_step": (
                "docs/state/macro_surprise_sources.json icine resmi kaynakli olay ekle."
                if not events else
                "Olgunlasma bekleniyor; kenar 1-SE'yi asana kadar hukum yok."
            ),
            "opens_trade": False,
            "promotion_gate": "closed_until_mature_multi_regime_sample",
        },
        # #0p — alan saklanmaya devam ediyor; uyari ONUNLA BIRLIKTE tasinir.
        "f_top10_return_warning": (
            "LOOK-AHEAD: f_top10_return_* alanlari BUGUNUN top10'unu GECMIS "
            "tarihlere uygular -> yapisal olarak pozitif (olculdu: asiri getiri "
            "avg +15.79 / hit %95.7). HUKME ESAS ALINMAZ; kapi bu alani kullanmaz."
        ),
        "by_group": sorted(group_rows, key=lambda x: x["group"]),
        "latest_events": sorted(events, key=lambda e: e.get("date") or "", reverse=True)[:10],
        "event_types": EVENT_TYPES,
        "note": "Macro Surprise defteri olcer; fiyat sinyalinden bagimsizdir ve F motoruna emir uretmez.",
    }


def update(report, data, path=None, sources_path=None, max_events=MAX_EVENTS):
    prices = data.get("prices") if data else None
    if prices is None or prices.empty:
        return {"error": "price data missing"}
    sources = _sources() if sources_path is None else _load_json(Path(sources_path), {"sources": []}).get("sources", [])
    ledger_path = Path(path) if path else _ledger_path()
    existing = _load_json(ledger_path, {"events": []}).get("events", [])
    merged = {_event_key(e): e for e in existing}
    for event in _source_events(sources):
        old = merged.get(_event_key(event), {})
        old.update({k: v for k, v in event.items() if v is not None or k not in old})
        merged[_event_key(event)] = old
    events = list(merged.values())[-max_events:]
    as_of_pos = len(prices.index) - 1
    as_of = _date_text(prices.index[as_of_pos])
    events = [_refresh_event(event, report, prices, as_of_pos) for event in events]
    events.sort(key=lambda e: (e.get("date") or "", e.get("type") or ""))
    payload = {
        "summary": _summary(events, as_of, sources, prices=prices),
        "events": events,
    }
    _save_json(ledger_path, payload)
    return payload["summary"]
