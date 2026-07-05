# BIST Alpha — Yeni Bilgisayar / Yeni Kullanıcı Kurulumu

Bu belge, sistemi **sıfır bir Windows makinesine veya yeni bir kullanıcıya** kurmak içindir.
Güncel kod GitHub'da da var: `ssimseksuleyman-coder/bistalpha` (git clone ile de kurulabilir).

> **F DOKUNULMAZ:** `MODE="F"` üretim motoru near-optimal; parametreler (`bist_alpha/config.py`) ölçülerek sabitlendi. Değiştirmeden çalıştır.

---

## 1) Önkoşullar

- **Python 3.10+** (GitHub Actions 3.12 kullanır; 3.10/3.11/3.12 çalışır) — https://python.org (kurulumda "Add to PATH" işaretle)
- İnternet (canlı veri: yfinance)
- (Opsiyonel) Git — GitHub'dan clone / 7-24 deploy için
- (Opsiyonel) Katalizör KAP-scraper için Playwright + Chromium

---

## 2) Kurulum (adım adım)

```powershell
# 1. Paketi bir klasöre aç (ör. C:\BISTALPA\bist_alpha_system) ve içine gir
cd C:\BISTALPA\bist_alpha_system

# 2. Sanal ortam oluştur + aktifle
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # PowerShell
# (cmd ise: .venv\Scripts\activate.bat)

# 3. Bağımlılıkları kur
pip install -r requirements.txt

# 4. (SADECE katalizör pipeline istiyorsan) Playwright + Chromium
pip install playwright
playwright install chromium
```

> `.venv/` pakete DAHİL DEĞİL (makineye özel) — her makinede yeniden kurulur.

---

## 3) Yapılandırma — gizli anahtarlar ORTAM DEĞİŞKENİNDEN (kodda saklanmaz)

Kodda hiçbir secret yok; `config.py` hepsini `os.environ`'dan okur. İhtiyaç duyulanları set et:

| Değişken | Ne için | Zorunlu mu |
|---|---|---|
| `DATA_SOURCE` | `yahoo` (varsayılan, ücretsiz) \| `borsapy` \| `file` | Hayır (yahoo default) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram bildirimi | Bildirim istiyorsan |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` | E-posta bildirimi | İstersen (Telegram yeterli) |
| `SMTP_PORT` | Varsayılan 587 | Hayır |

PowerShell'de geçici set (tek oturum):
```powershell
$env:DATA_SOURCE = "yahoo"
$env:TELEGRAM_TOKEN = "..."
$env:TELEGRAM_CHAT_ID = "..."
```
Kalıcı set: Windows → "Ortam Değişkenlerini Düzenle" → Kullanıcı değişkenleri.

---

## 4) Çalıştırma

```powershell
# Sistem sağlık testi (önce bunu koş)
python selftest.py

# Backtest (Excel verisi ile, offline çalışır)
python run_backtest.py

# Canlı bir döngü (shadow + rapor + bildirim) — tek sefer
python daemon.py --once acilis
#   etiketler: acilis | gunici | kapanis
```

- **Dashboard:** `docs/state/dashboard.json` üretilir; `docs/index.html` onu okur (GitHub Pages ile yayınlanır).
- **Portföyler:** `portfolios/portfolio_*.json` (A/B/F/O/G1 kağıt-hesapları) kalıcıdır, her koşuda güncellenir.

---

## 5) 7-24 Otonom Deploy (GitHub Actions — bilgisayar KAPALI iken bulutta çalışır)

1. Kendi GitHub reposuna push et (repo **public** olursa Actions dakikası sınırsız).
2. Repo → **Settings → Secrets and variables → Actions** → aynı secret'ları ekle:
   `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, (istersen) `SMTP_HOST/USER/PASS`, `MAIL_TO`.
3. `.github/workflows/` altındaki workflow'lar push'ta otomatik aktif olur:
   - `bist-alpha.yml` — ana canlı döngü (retry-pencereli cron + push)
   - `precise.yml` — tam-zamanlı raporlama (cron gecikmesini yener)
   - `catalyst.yml` — günlük KAP katalizör toplayıcı (Playwright)
4. **GitHub Pages** aç (Settings → Pages → `docs/` klasörü) → dashboard yayınlanır.

Bot state'i kendisi commit eder; **kod değişikliğini elle push edersin.**

---

## 6) Temiz başlangıç istersen (opsiyonel)

Paket, mevcut kağıt-hesap geçmişini içerir (süreklilik için). Sıfırdan başlamak istersen:
```powershell
Remove-Item portfolios\portfolio_*.json
Remove-Item docs\state\*.json
```
Bir sonraki koşuda temiz üretilir (portföyler 1.0'dan başlar).

---

## 7) Depo yapısı (özet)

- `bist_alpha/` — çekirdek paket (strategy, backtest, portfolio, signals, datafeed, config…)
- `daemon.py` / `shadow.py` — canlı orkestrasyon + shadow hesaplar
- `run_backtest.py` / `selftest.py` — backtest + sağlık testi
- `data/Tarihsel_Fiyat_Bilgileri.xlsx` — FileFeed/backtest için tarihsel veri
- `portfolios/` — A/B/F/O/G1 kağıt-hesap state'i
- `docs/` — dashboard (GitHub Pages)
- `.github/workflows/` — 7-24 otomasyon

Sorun olursa: `python selftest.py` çıktısı ilk teşhis noktasıdır.
