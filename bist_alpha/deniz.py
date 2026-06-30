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


def _extract_date_from_filename(filename):
    m = re.search(r'(\d{2})[_.\-\s](\d{2})[_.\-\s](\d{4})', filename)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "unknown"


def _parse_bulletin_xlsx(path, date):
    """xlsx formatı: Sheet9'dan sektör puanları."""
    sector_scores = {}
    try:
        df9 = pd.read_excel(path, sheet_name='Sheet9', header=None, engine="openpyxl")
        for i in range(2, len(df9)):
            code = df9.iloc[i, 1]
            if pd.isna(code) or not isinstance(code, str):
                continue
            code = code.strip()
            if not (3 <= len(code) <= 6):
                continue
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
    return sector_scores


def _parse_bulletin_pdf(path):
    """
    PDF formatı: Sayfa 9 (puanlama) veya Sayfa 10 (5 günlük karşılaştırma) dan sektör puanları.

    Sayfa 10 daha temiz metin üretir; her satırın son sayısı en güncel günün skoru.
    Sayfa 9 birincil hedef: "X[KOD] ... NN" deseni.
    """
    try:
        import pdfplumber
    except ImportError:
        print("[deniz] pdfplumber kurulu değil — 'pip install pdfplumber'")
        return {}

    sector_scores = {}
    try:
        with pdfplumber.open(path) as pdf:
            # Önce sayfa 10 (index 9) — 5 günlük karşılaştırma, son sütun = en güncel
            if len(pdf.pages) >= 10:
                txt = pdf.pages[9].extract_text() or ""
                # Satır deseni: XKOD Bıst İsim N1 N2 N3 N4 N5 XKOD Bıst İsim P1% P2%...
                # Satır ikinci kez XKOD ile tekrarlanır; ilk yarıdaki son integer = en güncel gün.
                for line in txt.splitlines():
                    cm = re.match(r'^(X[A-Z0-9]{2,5})\s+', line.strip())
                    if not cm:
                        continue
                    code = cm.group(1)
                    # İlk yarı: ikinci 'X[KOD]' tekrarına kadar
                    second = line.find(code, len(code) + 1)
                    first_half = line[:second] if second > 0 else line
                    integers = re.findall(r'\b(\d+)\b', first_half)
                    if len(integers) >= 5:
                        score = int(integers[-1])  # son sayı = en güncel gün
                        if 0 <= score <= 100:
                            sector_scores[code] = float(score)

            # Sayfa 9 (index 8) — puanlama listesi; sayfa 10 boşsa buraya bak
            if not sector_scores and len(pdf.pages) >= 9:
                txt = pdf.pages[8].extract_text() or ""
                for line in txt.splitlines():
                    # "XKOD BIst ... NN" — satır sonundaki sayı = 100 puan skoru
                    m = re.match(r'^(X[A-Z0-9]{2,5})\s+.+?\s+(\d{1,3})\s*$', line.strip())
                    if m:
                        code = m.group(1)
                        score = int(m.group(2))
                        if 0 <= score <= 100:
                            sector_scores[code] = float(score)
    except Exception as e:
        print(f"[deniz] PDF parse hatası: {e}")

    return sector_scores


def parse_bulletin(path):
    """
    Deniz Teknik Takip Bülteni okur (xlsx veya pdf).
    Returns: dict {
        'date': 'YYYY-MM-DD' (dosya adından),
        'sector_scores': {sektor_kodu: 0-100 puan},
        'market_score': XU100 puanı (0-100),
    }
    """
    date = _extract_date_from_filename(os.path.basename(path))
    ext = os.path.splitext(path)[1].lower()

    if ext == '.pdf':
        sector_scores = _parse_bulletin_pdf(path)
    else:
        sector_scores = _parse_bulletin_xlsx(path, date)

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
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bulletin, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
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


def bulletin_status(bulletin, as_of=None, max_age_days=None):
    """Dashboard ve bildirim için bülten tazeliğini açıkça raporla."""
    if max_age_days is None:
        try:
            max_age_days = int(os.environ.get("DENIZ_MAX_AGE_DAYS", "3"))
        except Exception:
            max_age_days = 3
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
