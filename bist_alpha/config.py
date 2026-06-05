"""
BIST Alpha v1.2 — Konfigürasyon
Tüm sistem parametreleri tek yerde. Değiştirmek için burayı düzenle.
"""

# ---- Çekirdek v1.2 parametreleri ----
TOP_N = 10              # Tutulacak hisse sayısı
REBAL_GUN = 30          # Rebalance periyodu (işlem günü)
MOM_GUN = 252           # Momentum penceresi (1 yıl)
RS_GUN_30 = 30          # Orta vade relative strength
RS_GUN_5 = 5            # Kısa vade relative strength
DUAL_THRESHOLD = 25     # M252 > %25 giriş eşiği
SEKTOR_CAP = 2          # Sektör başına max hisse (KORU — değiştirme)
UNIVERSE_SIZE = 100     # En büyük N market cap = evren

# ---- Skor ağırlıkları ----
W_M252 = 0.5
W_RS30 = 0.3
W_RS5 = 0.2

# ---- Stop parametreleri ----
ABS_STOP_PCT = 0.15     # Mutlak %15 stop
# Trailing (kazanca göre daralan):
TRAIL_TIGHT = 0.05      # gain >= %30 ise
TRAIL_MID = 0.10        # gain >= %15 ise
TRAIL_WIDE = 0.15       # diğer

# ---- İşlem maliyetleri ----
COMMISSION = 0.004      # round-trip komisyon (%0.4)
SLIPPAGE_PER_SIDE = 0.0040  # her alım/satımda ek kayma (%0.40) — canlı/shadow için

# ---- Strateji modu ----
# "A" = baseline (equal weight)
# "B" = SM-weighted lot (birincil aday)
# "F" = B + koşullu vize (BİRİNCİL — doğru sektör eşlemesinde A/B'yi geçer)
MODE = "F"

# ---- SM sinyal eşikleri ----
CPR_GUCLU = 0.60        # GÜÇLÜ BİRİKİM için CPR alt sınırı
ACC_MIN = 2.0           # Acc Ratio alt sınırı (sweet spot)
ACC_MAX = 5.0           # Acc Ratio ÜST sınırı (blow-off koruması — TEHOL dersi)
WICK_MAX = 0.40         # Üst fitil üst sınırı
CPR_BIRIKIM = 0.50      # Birikim için CPR
ACC_BIRIKIM = 1.2       # Birikim için Acc
CPR_DAGITIM = 0.40      # Dağıtım için CPR üst sınırı
ACC_DAGITIM = 0.8       # Dağıtım için Acc alt sınırı
WICK_DAGITIM = 0.45     # Üst fitil dağıtım eşiği

# ---- Lot çarpanları (Variant B) ----
LOT_MULTIPLIERS = {
    "GÜÇLÜ_BİRİKİM": 1.5,
    "Birikim": 1.0,
    "Nötr": 0.6,
    "Üst_fitil_dağıtım": 0.6,
    "DAĞITIM": 1.0,        # ELEME YOK — 1.0 = tam ağırlık. DAĞITIM paradoksu:
                           # %75 win verdi; M252 filtresi kötüleri zaten ayıkladı.
                           # Elemek %234 alpha kaybettirir, o yüzden tutuluyor.
    "veri_yok": 1.0,
}

# ---- Veri dosyası ----
DATA_PATH = "data/Tarihsel_Fiyat_Bilgileri.xlsx"
SHEET_NAME = "Sayfa1"


# ============================================================================
# OTOMASYON KATMANI AYARLARI (6 eksik için — kullanıcı doldurur)
# ============================================================================
import os as _os  # ortam değişkeni okuma (deploy için güvenli)

def _env(key, default=None):
    """Önce ortam değişkeni (deploy/secret), yoksa default."""
    return _os.environ.get(key, default)

# ---- Veri kaynağı (eksik #1) ----
DATA_SOURCE = _env("DATA_SOURCE", "yahoo")   # "file" | "yahoo" | "borsapy" (TradingView) | "api"
BIST_API_URL = _env("BIST_API_URL")           # APIFeed için
BIST_API_KEY = _env("BIST_API_KEY")
TV_USERNAME = _env("TV_USERNAME")    # borsapy/TradingView opsiyonel auth
TV_PASSWORD = _env("TV_PASSWORD")

# ---- Bildirim: E-posta (eksik #2) — ENV'den okunur (kodda saklama) ----
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASS = _env("SMTP_PASS")
MAIL_TO   = _env("MAIL_TO")

# ---- Bildirim: Telegram (eksik #2) ----
TELEGRAM_TOKEN   = _env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

# ---- Deniz bülten kaynağı (eksik #5) ----
DENIZ_SOURCE = _env("DENIZ_SOURCE", "folder")  # "folder" | "email"
DENIZ_FOLDER = _env("DENIZ_FOLDER", "deniz_inbox")
IMAP_HOST = _env("IMAP_HOST")
IMAP_USER = _env("IMAP_USER")
IMAP_PASS = _env("IMAP_PASS")
DENIZ_SENDER = _env("DENIZ_SENDER")

# ---- Bakım (eksik #6) ----
SNAPSHOT_KEEP_DAYS = 90
LOG_KEEP_DAYS = 30


# ============================================================================
# FORENSİK FİLTRELER (Day 30 bulguları — HEPSİ VARSAYILAN KAPALI)
# Tek tek shadow'da test edilmeden AÇMA. Test sonuçları:
#   Bulgu1 (late entry): bizim veride ZARARLI (-30pp getiri) — açma
#   Bulgu2 (sideways):   risk azaltma (DD yarıya, getiri düşer) — tercihe bağlı
# ============================================================================
LATE_ENTRY_FILTER = False       # son 5g >%X yükseleni atla
LATE_ENTRY_THRESHOLD = 20.0
SIDEWAYS_SCALING = False        # yatay piyasada pozisyon küçült
SIDEWAYS_THRESHOLD = 1.0        # XU100 son 5g |değişim| < bu -> sideways
SIDEWAYS_SCALE = 0.5            # sideways'te pozisyon çarpanı
SECTOR_PUMP_VETO = False        # Bulgu3: son 3 gün üst üste >%3 ise atla (bizim veride -19pp, KAPALI)

# ---- Portföy state ----
STATE_DIR = "portfolios"        # A/B/F kalıcı portföy dosyaları

