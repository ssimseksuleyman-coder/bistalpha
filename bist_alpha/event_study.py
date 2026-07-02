"""
event_study.py — Katalizor olcum motoru (market-model event study).

Bir katalizor (bedelsiz, endeks-girisi, bilanco surprizi, geri-alim...) etrafinda
anormal getiri (AR) ve kumulatif anormal getiri (CAR) olcer, istatistiksel
anlamlilik (t-stat) verir, KABUL/RET hukmu doner. Sisteme fiyat-disi bilgi katmak
icin olc-sonra-terfi motoru.

BAGIMLILIK YOK (numpy/pandas). Katalizor tarihleri disaridan gelir (catalyst_feed).
Motor tarih kaynagindan bagimsizdir; sentetik olaylarla kendi kendine dogrulanabilir.

Market-model:
  Tahmin penceresi [-est_start, -est_gap]: r_stock = alpha + beta * r_index  (regresyon)
  Olay penceresi [-k, +k]: beklenen = alpha + beta*r_index; AR = gercek - beklenen
  CAR = olay penceresindeki AR toplami
  Toplulastirma: ortalama CAR, t-stat = mean/(std/sqrt(N)); |t|>2 anlamli
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change()


def market_model(stock_ret: pd.Series, index_ret: pd.Series):
    """Tahmin penceresi getirilerinden alpha, beta (OLS)."""
    df = pd.concat([stock_ret, index_ret], axis=1).dropna()
    if len(df) < 20:
        return None, None
    x = df.iloc[:, 1].values
    y = df.iloc[:, 0].values
    vx = x.var()
    if vx == 0:
        return None, None
    beta = np.cov(x, y)[0, 1] / vx
    alpha = y.mean() - beta * x.mean()
    return float(alpha), float(beta)


def resolve_event_index(prices_index, event_date, event_time=None,
                        after_hours_cutoff="18:00", react_shift=None):
    """Katalizor tarihini t=0 (piyasa tepki gununun) KONUM INDEKSINE cevirir.
    KONVANSIYON: piyasa, haberin bilinebildigi ILK islem gunu tepki verir.
      - Seans-ici (trading gunu, saat < kapanis): t0 = o gun
      - Seans-sonrasi (trading gunu, saat >= kapanis): t0 = SONRAKI islem gunu (+1)
      - Hafta sonu/tatil: t0 = sonraki islem gunu (searchsorted zaten verir)
    KAP bildirimlerinin cogu seans-sonrasi -> saat yoksa react_shift=1 onerilir.
    Doner: konum indeksi (int) veya None (aralik disi)."""
    import pandas as _pd
    ts = _pd.Timestamp(event_date).normalize()
    base = int(prices_index.searchsorted(ts, side="left"))
    if base >= len(prices_index):
        return None
    is_trading_day = prices_index[base].normalize() == ts
    if react_shift is not None:
        pos = base + int(react_shift)
    elif event_time is not None and is_trading_day and str(event_time) >= after_hours_cutoff:
        pos = base + 1          # seans-sonrasi: ertesi islem gunu
    else:
        pos = base
    if pos < 0 or pos >= len(prices_index):
        return None
    return pos


def abnormal_returns(prices, index, ticker, event_idx,
                     est_start=250, est_gap=20, k=10):
    """Tek olay icin AR serisi ve CAR. event_idx = olay gununun konum indeksi.
    Tahmin: [event-est_start, event-est_gap]; Olay: [event-k, event+k]."""
    if ticker not in prices.columns:
        return None
    sr = prices[ticker].pct_change()
    # HIZALAMA (regresyon degil, OLAY-PENCERESI icin sart): asagidaki dongu
    # ir.iloc[t] ile sr.iloc[t]'yi POZISYONEL eslesir; event_idx prices.index'te
    # bir pozisyon oldugu icin bu ancak ir ile sr AYNI indekste ise ayni tarihe
    # denk gelir. index (or. data['bist'] 500g) prices'tan (508g) kisaysa
    # ir.iloc[t] SINIR DISI -> IndexError (gercek veriyle uretildi). Reindex ile
    # endeksi prices.index'e hizalayip bunu iceride kapatiyoruz.
    ir = index.reindex(prices.index).pct_change()
    a0, a1 = event_idx - est_start, event_idx - est_gap
    if a0 < 1 or event_idx + k >= len(prices):
        return None
    alpha, beta = market_model(sr.iloc[a0:a1], ir.iloc[a0:a1])
    if alpha is None:
        return None
    ar = []
    for t in range(event_idx - k, event_idx + k + 1):
        expected = alpha + beta * ir.iloc[t]
        actual = sr.iloc[t]
        if pd.isna(actual) or pd.isna(expected):
            ar.append(np.nan)
        else:
            ar.append(actual - expected)
    ar = np.array(ar, dtype=float)
    car = np.nansum(ar)
    return {"ar": ar, "car": float(car), "beta": beta,
            "car_pre": float(np.nansum(ar[:k])),      # olaydan ONCE (sizinti/onculuk)
            "car_post": float(np.nansum(ar[k + 1:])), # olaydan SONRA (tepki)
            "ar_event_day": float(ar[k]) if not np.isnan(ar[k]) else 0.0}


def event_study(events, prices, index, est_start=250, est_gap=20, k=10, react_shift=None):
    """events: [(ticker, date), ...] veya [(ticker, date, time), ...] veya (ticker, idx).
    react_shift: seans-sonrasi feed'ler icin +1 (KAP onerisi). date+time varsa otomatik.
    -> toplulastirilmis CAR + t-stat + hukum."""
    cars, car_pre, car_post, ev_day, betas = [], [], [], [], []
    used = 0
    for ev in events:
        tic, ed = ev[0], ev[1]
        etime = ev[2] if len(ev) > 2 else None
        if isinstance(ed, (int, np.integer)):
            eidx = int(ed)
        else:
            eidx = resolve_event_index(prices.index, ed, event_time=etime, react_shift=react_shift)
        if eidx is None:
            continue
        res = abnormal_returns(prices, index, tic, int(eidx), est_start, est_gap, k)
        if res is None:
            continue
        cars.append(res["car"]); car_pre.append(res["car_pre"])
        car_post.append(res["car_post"]); ev_day.append(res["ar_event_day"])
        betas.append(res["beta"]); used += 1
    if used < 3:
        return {"n": used, "verdict": "YETERSIZ_ORNEK (min 3)"}
    cars = np.array(cars)
    mean_car = cars.mean()
    t = mean_car / (cars.std(ddof=1) / np.sqrt(used)) if cars.std(ddof=1) > 0 else 0.0
    return {
        "n": used,
        "mean_car_pct": round(mean_car * 100, 3),
        "mean_car_pre_pct": round(np.mean(car_pre) * 100, 3),   # olay oncesi (sizinti sinyali)
        "mean_car_post_pct": round(np.mean(car_post) * 100, 3), # olay sonrasi (islem edilebilir)
        "mean_event_day_pct": round(np.mean(ev_day) * 100, 3),
        "t_stat": round(float(t), 2),
        "significant": bool(abs(t) > 2.0),
        "mean_beta": round(float(np.mean(betas)), 2),
        "verdict": ("ANLAMLI KATALIZOR (|t|>2)" if abs(t) > 2.0 else "ANLAMSIZ (gurultuden ayrilamiyor)"),
    }


def tradeable_edge(study: dict) -> dict:
    """Katalizor islem edilebilir mi: olay-SONRASI CAR anlamli+pozitif mi?
    Olay-oncesi CAR buyukse bilgi zaten fiyatta (gec kalinmis); sonrasi onemli."""
    if study.get("n", 0) < 3 or not study.get("significant"):
        return {"tradeable": False, "reason": study.get("verdict", "yetersiz")}
    post = study.get("mean_car_post_pct", 0)
    pre = study.get("mean_car_pre_pct", 0)
    return {
        "tradeable": bool(post > 0.5),   # olay sonrasi >%0.5 anormal getiri
        "post_car_pct": post,
        "pre_car_pct": pre,
        "note": ("olay sonrasi islem edilebilir tepki var" if post > 0.5
                 else "bilgi olaydan once fiyatlanmis (gec) — islem edilemez"),
    }
