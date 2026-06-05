# BIST ALPHA v1.2 + OMEGA — OTONOM PRODUCTION KILAVUZU

6 eksiği kapatan otomasyon katmanı. Sistem artık araştırma backtest'i değil,
kendi kendine çalışan servis.

> **DÜRÜST ÇERÇEVE:** Otomasyon iskeleti + tüm mantık ÇALIŞIYOR. Dış bağlantılar
> (canlı BIST verisi, Deniz kaynağı, SMTP/Telegram kimlikleri) senin gireceğin
> config değerleridir. Kod hazır — sen "fişe takarsın".

---

## 6 EKSİK → ÇÖZÜM

| # | Eksik | Çözüm modülü | Durum |
|---|-------|--------------|-------|
| 1 | Dinamik hisse listesi | `datafeed.py` (dynamic_universe) | ✅ çalışıyor |
| 2 | Otomatik sinyal (e-posta/Telegram) | `reporter.py` + `notifier.py` | ✅ kod hazır, kimlik gir |
| 3 | 09:45/14:30/18:30 raporlama | `scheduler.py` + `daemon.py` | ✅ çalışıyor |
| 4 | On-demand rapor + hisse analiz | `analyze_stock.py` | ✅ çalışıyor |
| 5 | Deniz bülten oto-çekme | `deniz_fetcher.py` | ✅ klasör modu çalışıyor |
| 6 | Otomatik bakım | `maintenance.py` | ✅ çalışıyor |

---

## KURULUM (otomasyon)

```bash
cd bist_alpha_system
pip install -r requirements.txt    # requests eklendi (Telegram için)

# Veriyi koy
#   data/Tarihsel_Fiyat_Bilgileri.xlsx
# Deniz bültenlerini düşür
#   deniz_inbox/  (klasöre xlsx bültenleri at — oto-çekilir)
```

### config.py — kimlik bilgilerini aç (yorumları kaldır)
```python
# E-posta
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "seninmail@gmail.com"
SMTP_PASS = "uygulama_sifresi"        # Gmail: uygulama şifresi
MAIL_TO   = "alici@mail.com"

# Telegram (@BotFather'dan token, kendi chat_id'in)
TELEGRAM_TOKEN   = "123456:ABC..."
TELEGRAM_CHAT_ID = "987654321"
```

---

## ÇALIŞTIRMA

### Sürekli servis (kendi döngüsü)
```bash
python daemon.py        # 09:45/14:30/18:30 bekler, otomatik rapor+bildirim
```

### Cron ile (önerilen — daha sağlam)
```cron
45 9  * * 1-5  cd /yol/bist_alpha_system && python daemon.py --once acilis
30 14 * * 1-5  cd /yol/bist_alpha_system && python daemon.py --once gunici
30 18 * * 1-5  cd /yol/bist_alpha_system && python daemon.py --once kapanis
```

### On-demand (istediğin zaman)
```bash
python analyze_stock.py TERA ASELS KTLEV   # hisse analizi
python analyze_stock.py --report           # anlık tam rapor
python analyze_stock.py TERA --json        # JSON çıktı
```

---

## SİNYAL MANTIĞI (rapor aksiyonları)

| Aksiyon | Anlam | Koşul |
|---------|-------|-------|
| 🟢 AL | Yeni/güçlü pozisyon | Pick + GÜÇLÜ BİRİKİM/Birikim |
| 🟡 BEKLE | Tut, izle | Pick ama Nötr/zayıf sinyal |
| 🔴 SAT | Çık | Stop tetiklendi |
| ⭐ FIRSAT | İzleme listesi | Pick değil ama GÜÇLÜ BİRİKİM + yüksek momentum |

🎫 = koşullu vize (3. sektör hissesi, GÜÇLÜ BİRİKİM)

---

## CANLI VERİ / DENİZ BAĞLAMA (dış bağlantılar)

### Canlı BIST verisi (eksik #1 tam otomasyon)
`datafeed.py` → `APIFeed.get_latest()` içini doldur:
- config'e `DATA_SOURCE = "api"`, `BIST_API_URL`, `BIST_API_KEY`
- API response'unu pivot formatına çevir (prices/mins/maxs/aofs/volumes/mcaps/bist)

### Deniz e-posta otomasyonu (eksik #5 tam otomasyon)
İki seçenek:
1. **Klasör modu (en kolay, çalışıyor):** Deniz e-postalarının ekini bir
   klasöre senkronla (ör. Gmail filtresi + Drive). `DENIZ_FOLDER` o klasör.
2. **IMAP modu:** `deniz_fetcher.py` → `EmailFetcher.fetch_latest()` doldur,
   config'e `IMAP_HOST/USER/PASS/DENIZ_SENDER`, `DENIZ_SOURCE = "email"`.

---

## OTOMATİK BAKIM (eksik #6)

`maintenance.py` her döngüde:
- Veri güncelliği (son tarih çok eski mi?)
- NaN patlaması (eksik veri)
- Donmuş fiyat (tatil/durdurma)
- Snapshot/log rotasyonu (eski dosyaları temizler)

Sorun bulursa otomatik bildirim atar.

---

## MİMARİ NOTU — DENİZ YAN KAYNAK

Deniz bülteni sektör teknik puanı (0-100) verir. Sistem bunu SADECE overlay
olarak kullanır (rapordaki [normal]/[zayıf]/[güçlü] etiketi). Deniz ASLA hisse
seçmez, skoru override etmez — analizde kanıtlandı: Deniz'i takip etmek %50
alpha kaybettirir.

İmza: Claude (OMEGA) — 2026-05-19

---
---

# GÜNCELLEME (v2) — OMEGA Denetimi Sonrası Tamamlanan Eksikler

OMEGA arşivi denetlendi. Eklenen 6 parça:

## YENİ MODÜLLER
| Modül | İşlev | Durum |
|-------|-------|-------|
| `portfolio.py` | Pozisyon state KALICILIĞI (A/B/F kalıcı portföy, SAT sinyali, give-back) | ✅ kritik eksik kapandı |
| `levels.py` | Destek/direnç (pivot bazlı) — hisse analizine eklendi | ✅ |
| `shadow.py` | A/B/F paralel shadow runner (kalıcı portföylerle) | ✅ |

## YENİ OPSİYONEL FİLTRELER (config — VARSAYILAN KAPALI)
Day 30 forensik bulguları. F config'te test edildi:

| Flag | Bulgu | Test sonucu | Varsayılan |
|------|-------|-------------|-----------|
| `LATE_ENTRY_FILTER` | Son 5g >%20 yükseleni atla | Bizim veride ZARARLI (-30pp getiri) | KAPALI |
| `SIDEWAYS_SCALING` | Yatay piyasada pozisyon yarıya | DD yarıya iner, getiri düşer (risk tercihi) | KAPALI |

**Açmadan önce:** Tek tek shadow'da 30 gün test et (Day 30 dokümanı disiplini). Birlikte açma.

## GÖMÜLÜ VERİ (turnkey)
- `data/Tarihsel_Fiyat_Bilgileri.xlsx` — ana fiyat verisi (artık pakette)
- `deniz_inbox/` — 5 Deniz bülteni gömülü (29_04, 30_04, 04_05, 05_05, 14_05)

Paket artık kutudan çıkar çıkmaz çalışır — veri koymaya gerek yok.

## SHADOW MODE ÇALIŞTIRMA
```bash
python shadow.py            # bugünün shadow adımı (A/B/F kalıcı portföy)
python shadow.py --status   # 3 hesabın güncel durumu + pozisyonlar + stop
```
Her gün cron ile çağır; portföyler kalıcı, SAT sinyalleri gerçek çalışır.

## DAY 30 DOKÜMANI NOTU
3 forensik bulgu (geç giriş, sideways, sektör pattern) KOD olarak eklendi ama
KAPALI. Day 30'da (2026-06-13) K0 sonucuna bak, EN FAYDALI görünen BİR tanesini
seç, shadow'da test et. Bulgu 1'i bizim veri reddetti; Bulgu 2 risk tercihi.

---
---

# GÜNCELLEME (v3) — Otomatik Bakım & Öz-İyileştirme

## EKLENEN 3 YETENEK
| İstek | Modül | Davranış |
|-------|-------|----------|
| Sistem hatalarını kendi kendine düzeltme | `selfheal.py` | retry + veri yedeğe düşme + bozuk state onarımı + hata yakala/bildir/çökme |
| Model parametrelerini otomatik optimize | `optimizer.py` | DİSİPLİNLİ: walk-forward, SADECE öneri, config'i değiştirmez |
| Eski log/geçici dosya temizliği | `maintenance.clean_temp()` | __pycache__, *.pyc, *.tmp, bozuk yedekler |

## SELF-HEAL (selfheal.py)
- `safe_feed()`: Yahoo/API çökerse otomatik gömülü Excel'e düşer (servis durmaz)
- `with_retry()`: geçici hataları 3 kez dener
- `validate_and_repair_state()`: bozuk portföy JSON'unu yedekler + sıfırlar
- `guarded()`: daemon görevlerini sarar — tek hata tüm servisi düşürmez
daemon her döngüde bunları kullanır.

## OPTİMİZER — DİSİPLİNLİ (optimizer.py)
```bash
python daemon.py --optimize    # öneri üret (config DEĞİŞMEZ)
```
⚠️ Naif optimizasyon = overfitting (cap=3/rebal=25/DNA dersi). Bu optimizer:
walk-forward yapar, OOS'ta doğrulamayan değişikliği önermez, config'i asla
otomatik değiştirmez. Çıktı: optimizer_suggestions.json. İnsan onayı + shadow şart.

## BAKIM — genişletildi
`maintenance.run_maintenance()` artık: veri sağlık + snapshot rotasyonu +
log rotasyonu + temp/cache temizliği. daemon her döngüde çağırır.
