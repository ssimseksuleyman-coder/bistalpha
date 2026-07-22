# MASAÜSTÜNE KURULUM — Adım Adım (Windows / Surface Pro)

## ÖNCE: Python kurulu mu?
Başlat menüsüne `python` yaz. Çıkmıyorsa:
1. https://www.python.org/downloads/ adresine git
2. "Download Python 3.12" butonuna tıkla
3. Kurulumda **"Add Python to PATH"** kutusunu MUTLAKA işaretle
4. "Install Now" → bitene kadar bekle

Python varsa direkt aşağı geç.

---

## KURULUM (2 dakika)

### Adım 1 — Zip'i Masaüstüne Aç
1. `BIST_ALPHA_SYSTEM_kurulabilir.zip` dosyasını Masaüstüne taşı
2. Üzerine **sağ tıkla → "Tümünü çıkar..."**
3. Çıkış konumu olarak Masaüstünü göster
4. Çıkarınca `bist_alpha_system` adında klasör oluşur — **adını `BISTALPA` olarak değiştir** (sağ tık → Yeniden Adlandır)

Şimdi masaüstünde `BISTALPA` klasörü var.

### Adım 2 — Çift Tıkla
1. BISTALPA klasörünü aç
2. **`kurulum.bat`** dosyasına çift tıkla
3. Komut penceresi açılır, otomatik:
   - Python kontrolü
   - Kütüphaneleri kurar (pandas, yfinance, borsapy, ...)
   - Selftest çalıştırır (11 bölüm)
   - "KURULUM TAMAM" der

### Adım 3 — Çalışıyor mu kontrol et
Hâlâ aynı pencerede şunu yaz, Enter:
```
python run_backtest.py --compare
```
Şunu görmelisin:
```
Mode      Getiri    MaxDD  Sharpe Calmar_y  Stop
A      %  289.4 % -6.61   7.70   44.42    55
B      %  268.8 % -8.14   6.95   33.51    55
F      %  301.1 % -5.54   7.34   55.12    56
```
`Calmar_y` yıllık getiri / maxDD karar metriğidir; eski toplam getiri / maxDD
formülü artık kodda `calmar_total` adıyla açıkça ayrılmıştır.
Bu çıktıyı görüyorsan **sistem çalışıyor.**

---

## ŞİMDİ NE YAPABİLİRSİN

### Komut Satırından (BISTALPA klasöründe komut istemi aç)
| Komut | Ne yapar |
|-------|----------|
| `python run_backtest.py --compare` | A/B/F karşılaştırması |
| `python analyze_stock.py ASELS` | Hisse analizi (destek/direnç + yan kaynak bayrakları) |
| `python daemon.py --once kapanis` | Tek döngü — TOP 10 üretir |
| `python shadow.py --status` | A/B/F shadow portföy durumu |
| `python selftest.py` | Öz-denetim (her şey yolunda mı?) |

### Yerel Web Dashboard (en güzeli)
1. Önce `python daemon.py --once test` çalıştır (dashboard JSON üretsin)
2. **`dashboard_ac.bat`** çift tıkla
3. Tarayıcı otomatik açılır: http://localhost:8000/
4. TOP 10, akıllı para bayrakları, hesaplar — hepsi orada
5. Kapatmak için komut penceresinde Ctrl+C

---

## 7/24 ÇALIŞMA (bilgisayar kapalıyken)

Yerel kurulum sadece bilgisayar açıkken çalışır. Surface'in kapalıyken sistem
yine de çalışsın istiyorsan **bir kez** GitHub'a yükle:

`deploy\UCRETSIZ_7_24_KURULUM.md` dosyasını aç ve adımları izle (3 dakika,
ücretsiz). Bir kez kurulduktan sonra Surface kapalı olsa bile sabah/öğle/akşam
otomatik rapor üretip Telegram/Email gönderir.

---

## SORUN ÇIKARSA

### "python tanınmıyor"
Python'u PATH'e eklemeden kurmuşsun. Python'u kaldır, tekrar kur, **"Add Python
to PATH" kutusunu işaretle.**

### "Selftest başarısız"
1. Komut penceresinde `python selftest.py` çalıştır
2. Hangi bölüm ⚠ veya ✗ ise göster — düzeltme genelde tek satır

### "Kütüphane kurulamadı"
1. İnternet bağlantını kontrol et
2. Kurumsal proxy varsa: `python -m pip install -r requirements.txt --proxy http://proxy:port`

### "Veri bulunamadı"
Zip içindeki `data\` klasörü çıkmamış olabilir. Zip'i yeniden çıkar.

---

**Tek tıkla kurulum — gerisi `kurulum.bat`'a kalıyor.**
