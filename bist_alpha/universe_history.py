"""
SURVIVORSHIP BIAS DÜZELTMESİ — Nokta-zamanlı endeks üyeliği.

SORUN: Evren 242 hisse, ama bu veri 2026'da derlendiği için "hayatta kalanlar".
2024'te BIST100'de olup delist olan/düşen hisseler veride YOK → zararları hiç
alınmıyor → backtest şişer.

ÇÖZÜM: Her tarihte hangi hisselerin endekste olduğunu bilmek (nokta-zamanlı).
Kaynak: KAP + BIST endeks duyuruları → hisse_endeks_katilim_ds.csv
Beklenen CSV formatı:
    tarih,endeks,hisse,durum
    2024-04-01,XU100,GARAN,1
    2024-04-01,XU100,ASELS,1
    ...
    (durum: 1=üye, 0=çıktı; veya giriş/çıkış tarihleri)

KULLANIM: CSV varsa backtest evreni nokta-zamanlı üyelikle sınırlanır (look-ahead
ve survivorship azalır). CSV yoksa mevcut davranış (mcap top-100) sürer + UYARI.

DÜRÜST SINIR: CSV üyeliği look-ahead'i çözer AMA delist hisselerin FİYAT verisi
yoksa onları "tutmuş" gibi simüle edemeyiz. Tam düzeltme için hem üyelik hem
delist hisse fiyat geçmişi gerekir. Bu modül altyapıyı kurar + eksiği ölçer.
"""
import os
import pandas as pd
from . import config

_CSV = os.path.join(os.path.dirname(__file__), "..", "data",
                    "hisse_endeks_katilim_ds.csv")
_cache = {"loaded": False, "df": None}


def available():
    """Nokta-zamanlı üyelik CSV'si var mı?"""
    return os.path.exists(_CSV)


def _load():
    if _cache["loaded"]:
        return _cache["df"]
    _cache["loaded"] = True
    if not available():
        _cache["df"] = None
        return None
    try:
        df = pd.read_csv(_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        if "tarih" in df.columns:
            df["tarih"] = pd.to_datetime(df["tarih"], errors="coerce")
        _cache["df"] = df
    except Exception as e:
        print(f"[universe_history] CSV okunamadı: {e}")
        _cache["df"] = None
    return _cache["df"]


def index_members(date, index="XU100"):
    """
    Verilen tarihte endekste olan hisseler (nokta-zamanlı).
    CSV yoksa None döner → çağıran mcap top-100'e düşer.
    """
    df = _load()
    if df is None:
        return None
    sub = df[df.get("endeks", "").astype(str).str.upper() == index.upper()] \
        if "endeks" in df.columns else df
    if "tarih" in sub.columns:
        sub = sub[sub["tarih"] <= pd.Timestamp(date)]
        # Her hisse için en son durum
        if "durum" in sub.columns and "hisse" in sub.columns:
            latest = sub.sort_values("tarih").groupby("hisse")["durum"].last()
            return set(latest[latest == 1].index.tolist())
    if "hisse" in sub.columns:
        return set(sub["hisse"].unique().tolist())
    return None


def survivorship_report(data):
    """
    Nokta-zamanlı üyeleri fiyat verisiyle karşılaştır: kaç üye eksik?
    Survivorship açığını sayısallaştırır.
    """
    df = _load()
    if df is None:
        return {"available": False,
                "note": "hisse_endeks_katilim_ds.csv yok — survivorship ölçülemiyor. "
                        "KAP/BIST endeks duyurularından üretip data/ altına koy."}
    prices = data['prices']
    have = set(prices.columns)
    # Tüm tarihlerdeki tüm üyeler
    all_members = set(df["hisse"].unique()) if "hisse" in df.columns else set()
    missing = all_members - have
    return {
        "available": True,
        "total_members_ever": len(all_members),
        "in_price_data": len(all_members & have),
        "missing_from_price_data": len(missing),
        "missing_examples": sorted(list(missing))[:20],
        "note": "missing = endekste olmuş ama fiyat verisi yok (delist?) → "
                "bunların zararı simüle edilemez (kalıntı survivorship).",
    }
