"""
Akıllı para sinyalleri modülü.
Min/Max/AOF/Hacim ile birikim/dağıtım sinyalleri hesaplar. OHLC gerekmez.

UYARI: Min/Max/AOF kolon semantiğini canlıdan önce 2-3 hissede manuel doğrula.
"""
import pandas as pd
import numpy as np
from . import config


def sanitize_ohlc(data, max_daily_range=0.25, verbose=False):
    """
    TESPİT 1 — Min/Max anomali iğnelerini temizle.
    Veri sağlayıcılar (yfinance vb.) tek bir hatalı tick ile High/Low'u bozabilir.
    CPR/wick sinyalleri Min/Max'a bağlı — bozuk iğne = çöp sinyal.

    BIST fiyat limitleri (~±%10-20) bilgisiyle: bir günde (max/min - 1) > %25 ise
    neredeyse kesin anomali (hatalı tick veya bölünmemiş split). Bu günlerde
    Min/Max kapanışa göre makul sınırlara çekilir (winsorize).

    Returns: temizlenmiş data kopyası + temizlenen hücre sayısı.
    """
    prices = data['prices']
    mins = data['mins'].copy()
    maxs = data['maxs'].copy()
    aofs = data['aofs'].copy()

    # Anormal aralık maskesi: (max-min)/close > eşik
    rng = (maxs - mins)
    rel = rng.div(prices.where(prices > 0))
    bad = (rel > max_daily_range) & prices.notna() & mins.notna() & maxs.notna()
    n_bad = int(bad.sum().sum())

    if n_bad > 0:
        # Bozuk günlerde: max ve min'i kapanış ± yarım-eşik ile sınırla
        ceil_ = prices * (1 + max_daily_range / 2)
        floor_ = prices * (1 - max_daily_range / 2)
        maxs = maxs.where(~bad, np.minimum(maxs, ceil_))
        mins = mins.where(~bad, np.maximum(mins, floor_))
        # AOF da bozuksa kapanışa çek
        aof_bad = (aofs > ceil_) | (aofs < floor_)
        aofs = aofs.where(~(bad & aof_bad), prices)
        if verbose:
            print(f"[signals] {n_bad} Min/Max anomali iğnesi temizlendi")

    clean = dict(data)
    clean['mins'] = mins
    clean['maxs'] = maxs
    clean['aofs'] = aofs
    clean['_anomalies_clipped'] = n_bad
    return clean


def compute_signals(data, sanitize=True):
    """
    Pivot tablolardan SM sinyal serileri üretir.

    Returns: dict with cpr_10, acc_ratio, upper_wick (gün x hisse DataFrame)
    """
    if sanitize:
        data = sanitize_ohlc(data)
    prices = data['prices']
    mins = data['mins']
    maxs = data['maxs']
    aofs = data['aofs']
    volumes = data['volumes']

    day_range = maxs - mins

    # 1) CPR — Close Position in Range (10g ortalaması)
    cpr_raw = np.where(day_range > 0, (prices - mins) / day_range, 0.5)
    cpr_df = pd.DataFrame(cpr_raw, index=prices.index, columns=prices.columns)
    cpr_10 = cpr_df.rolling(10).mean()

    # 2) Acc Ratio — yukarı/aşağı gün hacim oranı (20g)
    returns = prices.pct_change(fill_method=None)
    up_vol_20 = volumes.where(returns > 0, 0).rolling(20).sum()
    down_vol_20 = volumes.where(returns < 0, 0).rolling(20).sum()
    acc_ratio = up_vol_20 / (down_vol_20 + 1e-9)

    # 3) Upper Wick — üst fitil oranı (5g ortalaması)
    upper_body = pd.DataFrame(np.maximum(aofs.values, prices.values),
                              index=prices.index, columns=prices.columns)
    upper_wick = ((maxs - upper_body) / day_range.where(day_range > 0, 1)).rolling(5).mean()

    return {'cpr_10': cpr_10, 'acc_ratio': acc_ratio, 'upper_wick': upper_wick}


def classify(cpr, acc, uw):
    """Tek bir hisse-gün için sinyal sınıfı döner."""
    if pd.isna(cpr):
        return "veri_yok"
    # GÜÇLÜ BİRİKİM — Acc ÜST SINIRI 5 (blow-off koruması)
    if cpr >= config.CPR_GUCLU and config.ACC_MIN <= acc <= config.ACC_MAX and uw < config.WICK_MAX:
        return "GÜÇLÜ_BİRİKİM"
    if cpr >= config.CPR_BIRIKIM and acc >= config.ACC_BIRIKIM:
        return "Birikim"
    if cpr < config.CPR_DAGITIM or acc < config.ACC_DAGITIM:
        return "DAĞITIM"
    if uw >= config.WICK_DAGITIM:
        return "Üst_fitil_dağıtım"
    return "Nötr"


def signal_for(signals, date, ticker):
    """Verilen tarih+hisse için sinyal sınıfını döner."""
    cpr_10 = signals['cpr_10']
    acc_ratio = signals['acc_ratio']
    upper_wick = signals['upper_wick']
    if date not in cpr_10.index or ticker not in cpr_10.columns:
        return "veri_yok"
    cpr = cpr_10.loc[date, ticker] if pd.notna(cpr_10.loc[date, ticker]) else 0.5
    acc = acc_ratio.loc[date, ticker] if date in acc_ratio.index and pd.notna(acc_ratio.loc[date, ticker]) else 1.0
    uw = upper_wick.loc[date, ticker] if date in upper_wick.index and pd.notna(upper_wick.loc[date, ticker]) else 0.3
    return classify(cpr, acc, uw)


def lot_multiplier(sig):
    """Sinyale göre pozisyon lot çarpanı (Variant B)."""
    return config.LOT_MULTIPLIERS.get(sig, 1.0)
