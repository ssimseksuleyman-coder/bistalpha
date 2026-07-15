# ÜCRETSİZ 7/24 KURULUM — Bilgisayar Kapalıyken Çalışır

Surface Pro 5 (veya herhangi bilgisayar) KAPALI olsa bile sistem çalışır.
**Sıfır maliyet:** GitHub Actions (ücretsiz bulut) + yfinance (ücretsiz canlı veri).

---

## MİMARİ — Nasıl Çalışır

```
GitHub bulutu (ücretsiz, hep açık)
   │  cron: 09:45 / 14:30 / 18:30 (TR)
   ▼
1. yfinance ile CANLI BIST verisi çek (ücretsiz, key yok)
2. Deniz bültenini Gmail'den çek (IMAP, ücretsiz)
3. Sinyal üret (top10 + al/sat/bekle/fırsat)
4. E-posta + Telegram gönder
5. Portföy state'i repo'ya commit et (kalıcı)
   │
   ▼
Senin telefonun/mailin (bilgisayar kapalı olabilir)
```

---

## ADIM ADIM KURULUM (15 dakika)

### 1. GitHub repo oluştur
- github.com → New repository → **Private** seç
- Bu paketi (bist_alpha_system) repo'ya yükle

### 2. Workflow dosyasını yerleştir
```
deploy/github-actions-cron.yml  →  .github/workflows/bist-alpha.yml
```

### 3. Gmail uygulama şifresi al (e-posta + Deniz için)
- Google Hesap → Güvenlik → 2 Adımlı Doğrulama (aç)
- Uygulama Şifreleri → yeni şifre oluştur (16 hane)

### 4. Telegram bot oluştur
- Telegram'da @BotFather → /newbot → token al
- @userinfobot → kendi chat_id'ini öğren

### 5. Deniz e-postalarını Gmail'e yönlendir
- Deniz bülten e-postalarını alan adrese Gmail filtresi kur
- (veya Deniz'e Gmail adresini abone yap)

### 6. GitHub Secrets ekle
Repo → Settings → Secrets and variables → Actions → New secret:

| Secret | Değer |
|--------|-------|
| SMTP_HOST | smtp.gmail.com |
| SMTP_USER | ornek@example.com |
| SMTP_PASS | (uygulama şifresi) |
| MAIL_TO | alici@example.com |
| TELEGRAM_TOKEN | (BotFather token) |
| TELEGRAM_CHAT_ID | (chat id) |
| IMAP_HOST | imap.gmail.com |
| IMAP_USER | ornek@example.com |
| IMAP_PASS | (uygulama şifresi) |
| DENIZ_SENDER | (Deniz e-posta adresi) |

### 7. Push et — BİTTİ
Otomatik 09:45/14:30/18:30'da çalışır. Bilgisayarın kapalı olabilir.
Test için: repo → Actions → "BIST Alpha 7/24 Canli" → Run workflow

---

## VERİ KAYNAKLARI — TAM LİSTE

| Kaynak | Yöntem | Ücret | Key? |
|--------|--------|-------|------|
| BIST fiyat (canlı) | yfinance (Yahoo `.IS`) | Ücretsiz | Yok ✓ |
| BIST fiyat (yedek) | Gömülü Excel (502 gün) | — | — |
| Deniz bülten | Gmail IMAP | Ücretsiz | App şifresi |
| XU100 endeks | yfinance (XU100.IS) | Ücretsiz | Yok ✓ |

**yfinance notu:** OHLCV verir. Min=Low, Max=High, AOF≈(H+L+C)/3 (yakınsama).
Akıllı para sinyalleri bu yakınsamayla çalışır — gömülü Excel'deki gerçek AOF'tan
ufak farklı olabilir. Canlıda doğruluğu birkaç hissede teyit et.

---

## KÜTÜPHANELER — TAM LİSTE (requirements.txt)
```
pandas      — veri işleme
numpy       — sayısal
openpyxl    — Excel okuma (gömülü veri + Deniz)
requests    — Telegram bildirim
yfinance    — ÜCRETSİZ canlı BIST verisi
```
Hepsi pip'te ücretsiz. GitHub Actions otomatik kurar.

---

## MALİYET TABLOSU

| Kalem | Maliyet |
|-------|---------|
| GitHub Actions (private repo, ayda ~2000 dk ücretsiz) | 0 TL |
| yfinance canlı veri | 0 TL |
| Gmail IMAP | 0 TL |
| Telegram bot | 0 TL |
| **TOPLAM** | **0 TL / ay** |

GitHub Actions ücretsiz kotası: private repo ayda 2000 dakika. Bu sistem günde
3 çalışma × ~2 dk = ayda ~120 dk. Kotanın çok altında. **Tamamen ücretsiz.**

---

## SINIRLAR (dürüst)

1. **GitHub cron ±birkaç dk gecikebilir** (yoğunlukta). Saniye hassasiyeti
   gerekirse VPS+systemd (deploy/bist-alpha.service) — ama o ücretli (~5$/ay).
2. **yfinance veri kalitesi** Yahoo'ya bağlı; nadiren gecikme/eksik olabilir.
   Gömülü Excel yedek olarak durur.
3. **Deniz IMAP** Gmail'e e-posta gelmesine bağlı; filtre doğru kurulmalı.

Bu sınırlar ücretsiz mimarinin doğal sonucu. Tam profesyonel SLA istersen
ücretli veri + VPS gerekir; ama ücretsiz kurulum gerçek ve çalışır.

İmza: Claude (OMEGA) — 2026-05-21

---

## VERİ KAYNAĞI SEÇENEKLERİ (3 alternatif)

DATA_SOURCE ile seçilir. safe_feed() hepsinde gömülü Excel'e yedek düşer.

| DATA_SOURCE | Kaynak | Ücret | Kapsam | Risk |
|-------------|--------|-------|--------|------|
| `yahoo` | Yahoo Finance (yfinance) | Ücretsiz | İyi | Rate-limit/ban (paylaşımlı IP) |
| `borsapy` | TradingView (borsapy) | Ücretsiz* | BIST'te daha iyi (yerli) | Resmi değil, ToS riski, kırılgan |
| `file` | Gömülü Excel (yedek) | — | 502 gün sabit | Canlı değil |

\* borsapy bazı özellikler için TradingView auth ister (TV_USERNAME/TV_PASSWORD).
Gecikmeli (15dk) veri genelde authsuz; canlı için abonelik gerekebilir.

### borsapy (TradingView) hakkında dürüst notlar
- **WebSocket vs cron:** borsapy.TradingViewStream (canlı WebSocket) KALICI süreç
  içindir (VPS/systemd daemon). GitHub Actions'ın kısa cron'u için
  borsapy.download() SNAPSHOT kullanılır — adapter bunu yapar.
- **Kırılganlık:** Resmi olmayan kütüphane; TradingView arayüzü değişirse kırılabilir.
  safe_feed otomatik gömülü Excel'e düşer, sistem durmaz.
- **ToS:** TradingView kullanım şartları programatik erişimi kısıtlayabilir; kendi
  sorumluluğunda kullan.

### Hangisini seç?
- **Başlangıç/ücretsiz:** yahoo (en basit)
- **BIST kapsamı önemliyse:** borsapy (TradingView, daha iyi yerli kapsam)
- İkisi de safe_feed ile gömülü Excel'e yedeklenir — canlı kaynak çökse bile rapor üretilir.
