"""BAR DURUMU — taban/tavan kilidi icin TEK OTORITE (2026-09-21).

Canli kanit 2026-09-16..21: OZATD/TRHOL/ALKLC/DSTKF/SELEC gunlerce taban kilidindeyken panel ve
Telegram "AL" yazdi. Kok: signals.compute_signals kilitli barda (high==low) CPR'yi 0.5 ile
dolduruyor, kilitli gunde hacim ~0 oldugundan acc_ratio patliyor -> "Birikim" -> reporter "AL".
F motoruna (secim/stop/agirlik) DOKUNULMAZ; bu modul yalniz DURUMU olcer, tuketiciler (rapor
etiketi, radar/omega listeleri, ileride secim erteleme) buradan okur. Ikinci bir tanim YAZILMAZ.

Tanimlar (kapanis-kapanis, floor_lock_accounting ile ayni esik):
  taban gunu : gunluk getiri <= FLOOR_PCT (-9.5)       tavan gunu : >= CEIL_PCT (+9.5)
  kilitli bar: taban/tavan gunu VE gun araligi 0 (high == low; gun boyu kilit, eslesme yok)
  son        : SON barin durumu ('taban' | 'tavan' | None)   ardisik: sondan geriye ayni durumun gun sayisi
Tarih indekste yoksa OLCULEMEDI (sonraki bara kaydirma YOK — taban_readiness'taki delik dersi).
"""
from __future__ import annotations

import pandas as pd

FLOOR_PCT = -9.5
CEIL_PCT = 9.5
PENCERE = 5


def _bos(olculemedi=True):
    return {"son": None, "ardisik": 0, "taban_gun": 0, "tavan_gun": 0, "kilitli_bar": 0, "olculemedi": olculemedi}


def gun_durumu(data, ticker, date=None, n=PENCERE):
    """Son n bar icin taban/tavan/kilit sayimi ve SON barin durumu. Saf; IO yok."""
    prices = data["prices"]
    if ticker not in prices.columns:
        return _bos()
    if date is None:
        date = prices.index[-1]
    date = pd.Timestamp(date)
    if date not in prices.index:
        return _bos()
    i = int(prices.index.get_loc(date))
    if i < 1:
        return _bos()
    lo = max(0, i - n)
    seri = prices[ticker].iloc[lo:i + 1]
    ret = seri.pct_change() * 100
    mins = data.get("mins"); maxs = data.get("maxs")
    if mins is not None and maxs is not None and ticker in mins.columns and ticker in maxs.columns:
        rng = (maxs[ticker].iloc[lo:i + 1] - mins[ticker].iloc[lo:i + 1])
    else:
        rng = pd.Series([float("nan")] * len(seri), index=seri.index)
    taban = (ret <= FLOOR_PCT).fillna(False)
    tavan = (ret >= CEIL_PCT).fillna(False)
    kilit = ((rng == 0) & (taban | tavan)).fillna(False)
    if pd.isna(ret.iloc[-1]):
        return _bos()
    son = "taban" if bool(taban.iloc[-1]) else ("tavan" if bool(tavan.iloc[-1]) else None)
    ardisik = 0
    if son:
        # ardisik gun sayisi PENCEREYLE SINIRLI DEGIL (SELEC 6 gun): tam seride geriye yuru
        tam = prices[ticker].iloc[:i + 1].pct_change() * 100
        mask = (tam <= FLOOR_PCT) if son == "taban" else (tam >= CEIL_PCT)
        for v in reversed(mask.fillna(False).values):
            if v:
                ardisik += 1
            else:
                break
    return {"son": son, "ardisik": int(ardisik), "taban_gun": int(taban.sum()), "tavan_gun": int(tavan.sum()),
            "kilitli_bar": int(kilit.sum()), "olculemedi": False}


def etiket(durum):
    """Rapor/panel etiketi; kilit yoksa None (mevcut sinyal etiketi kullanilir)."""
    if not durum or not durum.get("son"):
        return None
    ad = "TABAN KILIDI" if durum["son"] == "taban" else "TAVAN KILIDI"
    return f"{ad} ({durum['ardisik']} g)"
