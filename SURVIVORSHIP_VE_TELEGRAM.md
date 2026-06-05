# SURVIVORSHIP DÜZELTMESİ + TELEGRAM VERİ YÜKLEME

## 1. SURVIVORSHIP BIAS

### Mevcut maruziyet (ölçüldü)
- 242 hisseden 228'i tam geçmiş, 11'i sonradan listelenme
- Veride 0 delisting görünüyor — AMA bu yanıltıcı: veri 2026'da derlendi, yani
  2024-2026 arası delist olanlar **hiç yok** (hayatta kalanlar bias'ı).

### Çözüm altyapısı: nokta-zamanlı endeks üyeliği
`universe_history.py` — her tarihte endekste olan hisseleri bilir.
- Kaynak: KAP + BIST endeks duyuruları → `data/hisse_endeks_katilim_ds.csv`
- CSV formatı: `tarih,endeks,hisse,durum` (durum 1=üye)
- CSV varsa: backtest evreni nokta-zamanlı üyelikle sınırlanır (look-ahead ve
  survivorship azalır), `dynamic_universe` otomatik kullanır
- CSV yoksa: mcap top-100 (mevcut) + selftest uyarısı

### CSV'yi nasıl üretirsin
1. KAP endeks değişiklik duyuruları (BIST100/BIST30 giriş-çıkış)
2. BIST resmi endeks kompozisyon arşivi
3. Her değişikliği `tarih,endeks,hisse,durum` satırına çevir
4. data/ altına koy (veya Telegram'la gönder — aşağıya bak)

### DÜRÜST SINIR
Üyelik CSV'si look-ahead'i çözer AMA delist hisselerin FİYAT geçmişi yoksa onları
"tutmuş" gibi simüle edemeyiz. Tam düzeltme için hem üyelik HEM delist hisse
fiyatı gerekir. Bu modül altyapıyı kurar + eksiği `survivorship_report()` ile ölçer.
Yani: %289 gibi sayılar survivorship'ten bir miktar şişkin olabilir — CSV eklenince
gerçek rakam ortaya çıkar.

## 2. TELEGRAM İLE MANUEL VERİ YÜKLEME

`telegram_ingest.py` — bot'a gönderilen dosyaları indirir, doğru klasöre koyar.

| Gönderilen dosya | Gittiği yer |
|------------------|-------------|
| *Teknik_Takip*.xlsx | deniz_inbox/ (Deniz bülteni) |
| *endeks_katilim*.csv | data/hisse_endeks_katilim_ds.csv (survivorship) |
| Tarihsel*/fiyat*.xlsx | data/ (fiyat güncelleme) |
| diğer | data/uploads/ |

### Nasıl çalışır
- daemon her döngüde `telegram_ingest.fetch_uploads()` çağırır (cron-dostu, getUpdates)
- Bot'a dosya at → indirilir → "✅ Alındı" mesajı gelir
- Güvenlik: sadece TELEGRAM_CHAT_ID'den gelen dosyalar kabul edilir
- Offset takibi (data/.tg_offset) → aynı dosya tekrar inmez
- Mevcut bildirim TELEGRAM_TOKEN'ı ile aynı (ek kurulum yok)

### Kullanım
Telefonundan Telegram'da bota Deniz bültenini veya endeks CSV'sini gönder →
sistem bir sonraki çalışmada otomatik alır. Bilgisayar açık olması gerekmez
(GitHub Actions çalışınca çeker).

İmza: Claude — 2026-05-21
