"""
Deniz Yatırım Günlük Bülten entegrasyonu — YAN KAYNAK.

MİMARİ KARAR (analizle kanıtlandı):
  Deniz KARAR KAYNAĞI DEĞİL. v1.2 ile %16 örtüşür; Deniz'i takip etmek ~%50
  alpha kaybettirir. Bülten SADECE şunlar için kullanılır:
    1. Sektör rejimi teyidi (momentum pick'i teknik olarak zayıf sektörden mi?)
    2. Market rejimi (XU100 teknik puanı — BIST<MA200 kill switch'i tamamlar)
    3. Event/uyarı bayrağı

  Deniz ASLA hisse seçmez, skoru override etmez. Sadece güven/bayrak overlay'i.

Bülten formatı (BIST Teknik Takip Bülteni .xlsx):
  Sheet9 = sektör puanlama (Endeks Kodu, ..., 100 Puan = 0-100 teknik skor)
  Sheet2 = hareketli ortalama sinyalleri (E/H)
"""
import pandas as pd
import re
import os
import json
import glob
from datetime import date as date_type, datetime


def parse_bulletin(path):
    """
    Deniz Teknik Takip Bülteni xlsx'i okur.
    Returns: dict {
        'date': 'YYYY-MM-DD' (dosya adından),
        'sector_scores': {sektor_kodu: 0-100 puan},
        'market_score': XU100 puanı (0-100),
    }
    """
    # Tarih (dosya adından, ör ..._14_05_2026_...)
    m = re.search(r'(\d{2})[_.\-\s](\d{2})[_.\-\s](\d{4})', os.path.basename(path))
    date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "unknown"

    sector_scores = {}
    try:
        df9 = pd.read_excel(path, sheet_name='Sheet9', header=None, engine="openpyxl")
        # Satır 1 başlık; satır 2+ veri. Kolon 0=kod, son sayısal kolon=100 puan
        for i in range(2, len(df9)):
            code = df9.iloc[i, 1]
            if pd.isna(code) or not isinstance(code, str):
                continue
            code = code.strip()
            if not (3 <= len(code) <= 6):
                continue
            # "100 Puan" kolonu — kolon 4 (Endeks, İsim, Puan, Toplam, 100Puan)
            score = None
            for c in [5, 4, 3]:
                if c < df9.shape[1] and pd.notna(df9.iloc[i, c]):
                    try:
                        score = float(df9.iloc[i, c])
                        break
                    except (ValueError, TypeError):
                        continue
            if score is not None:
                sector_scores[code] = round(score, 1)
    except Exception as e:
        print(f"[deniz] Sheet9 okunamadı: {e}")

    market_score = sector_scores.get('XU100')

    return {
        'date': date,
        'sector_scores': sector_scores,
        'market_score': market_score,
    }


def save_snapshot(bulletin, out_dir="deniz_snapshots"):
    """Bülteni günlük snapshot JSON olarak saklar (geçmiş hafıza)."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"deniz_{bulletin['date'].replace('-','_')}.json")
    with open(path, "w") as f:
        json.dump(bulletin, f, ensure_ascii=False, indent=2)
    return path


# ---- YAN KAYNAK KULLANIM FONKSİYONLARI ----

def load_latest_snapshot(snapshot_dir="deniz_snapshots"):
    """En son kaydedilmis Deniz snapshot'ini yukle; yoksa None."""
    files = glob.glob(os.path.join(snapshot_dir, "deniz_*.json"))
    if not files:
        return None

    def sort_key(path):
        base = os.path.basename(path)
        m = re.search(r"deniz_(\d{4})_(\d{2})_(\d{2})", base)
        return m.groups() if m else ("0", "0", "0")

    latest = sorted(files, key=sort_key)[-1]
    try:
        with open(latest, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("source_file", os.path.basename(latest))
        data["loaded_from_snapshot"] = True
        return data
    except Exception as e:
        print(f"[deniz] Son snapshot okunamadi: {e}")
        return None


def bulletin_status(bulletin, as_of=None, max_age_days=4):
    """Dashboard ve bildirim için bülten tazeliğini açıkça raporla."""
    if not bulletin:
        return {
            "available": False,
            "date": None,
            "age_days": None,
            "fresh": False,
            "status": "missing",
            "market_score": None,
        }
    raw_date = bulletin.get("date")
    try:
        bulletin_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        if as_of is None:
            reference = date_type.today()
        elif hasattr(as_of, "date"):
            reference = as_of.date()
        else:
            reference = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
        age_days = max(0, (reference - bulletin_date).days)
    except Exception:
        age_days = None
    fresh = age_days is not None and age_days <= max_age_days
    return {
        "available": True,
        "date": raw_date,
        "age_days": age_days,
        "fresh": fresh,
        "status": "fresh" if fresh else "stale",
        "market_score": bulletin.get("market_score"),
        "sector_count": len(bulletin.get("sector_scores", {})),
        "source_file": bulletin.get("source_file"),
        "fetched_at": bulletin.get("fetched_at"),
        "loaded_from_snapshot": bulletin.get("loaded_from_snapshot", False),
    }


def sector_regime_flag(bulletin, sector_code, weak_threshold=40):
    """
    Bir sektörün teknik rejimi zayıf mı? (Deniz puanına göre)
    Returns: 'zayıf' | 'normal' | 'güçlü' | 'bilinmiyor'
    KULLANIM: pick'i VETO ETMEZ — sadece güven bayrağı.
    """
    score = bulletin['sector_scores'].get(sector_code)
    if score is None:
        return 'bilinmiyor'
    if score < weak_threshold:
        return 'zayıf'
    if score >= 70:
        return 'güçlü'
    return 'normal'


def market_regime_ok(bulletin, min_score=40):
    """
    Market (XU100) teknik olarak yeterince güçlü mü?
    BIST<MA200 kill switch'i TAMAMLAR (override etmez).
    """
    ms = bulletin.get('market_score')
    if ms is None:
        return True  # veri yoksa engelleme
    return ms >= min_score


def annotate_picks(bulletin, picks, get_sector_fn):
    """
    Pick listesine Deniz sektör rejim bayrağı ekler (bilgi amaçlı).
    Returns: [{'ticker':.., 'sector':.., 'deniz_regime':..}]
    Pick'leri DEĞİŞTİRMEZ — sadece etiketler.
    """
    out = []
    for t in picks:
        sec = get_sector_fn(t)
        out.append({
            'ticker': t,
            'sector': sec,
            'deniz_regime': sector_regime_flag(bulletin, sec),
        })
    return out
