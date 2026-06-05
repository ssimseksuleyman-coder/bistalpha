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
    m = re.search(r'(\d{2})_(\d{2})_(\d{4})', os.path.basename(path))
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
