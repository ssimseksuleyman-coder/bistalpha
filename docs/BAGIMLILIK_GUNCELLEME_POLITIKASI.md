# Bağımlılık Güncelleme Politikası

Amaç: üçüncü parti kütüphane değişikliklerinin canlı F motorunu bozmasını
engellemek. Kural basit: bağımlılık güncellemesi strateji kararı değildir;
operasyonel değişikliktir ve önce gölgede ölçülür.

## Temel Kurallar

1. Canlı F motoru çalışırken toplu ve kör paket güncellemesi yapılmaz.
2. Her güncelleme küçük grup halinde yapılır: veri çekme, raporlama, panel,
   bildirim gibi etkilediği alan belirtilir.
3. Güncelleme sonrası `selftest.py` ve `system_control_audit.py` çalışır.
4. Veri kaynağı kütüphaneleri için ayrıca canlı veri kapsamı kontrol edilir.
5. Başarılı sürüm gözlendikten sonra bilinen-iyi sürümler pinlenir.

## Önerilen Akış

```powershell
python -m pip install --upgrade pip
python -m pip install --upgrade <paket>
python selftest.py
python scripts\system_control_audit.py --write docs\state\system_control_audit.json
```

Sonra:

- Dashboard veri kapsamı kontrol edilir.
- Telegram / panel değer tutarlılığı kontrol edilir.
- F, O, G1 hesapları beklenen rolde kalıyor mu bakılır.
- Sadece bu kontroller temizse commit edilir.

## Pinleme Disiplini

`requirements.txt` içinde gevşek aralıklar (`>=`) geliştirme hızını artırır ama
canlı tekrarlanabilirliği zayıflatır. Canlıda önerilen durum:

- kritik paketlerde bilinen-iyi sürümü pinle,
- yeni sürümü önce shadow / audit ile ölç,
- sorun varsa önceki pin'e dön.

## Pin Hiyerarşisi

Tüm paketler eşit kritik değildir. Öncelik sırası:

| Paket | Rol | Kritik |
|---|---|---|
| `pandas` | veri çerçevesi, sinyal ve backtest akışı | Kırmızı |
| `numpy` | backtest matematiği | Kırmızı |
| `openpyxl` | `pandas.read_excel` altında FileFeed/Excel girdisi | Kırmızı |
| `yfinance` | canlı Yahoo veri kaynağı | Sarı |
| `requests`, `borsapy` | canlı/fallback veri yolları | Sarı |
| `pdfplumber` | broker/PDF parse hattı | Geçici |

`openpyxl` özellikle sessiz kritiktir: F'in backtest tabanı Excel FileFeed'den
geldiği için Excel parse davranışı değişirse F'in girdisi de değişebilir.

`yfinance` exact pinlenir, ama Yahoo API değiştikçe kontrollü yükseltme
gerektirebilir. Bu yüzden canlı veri kapsamı ve fallback zinciri her yükseltmede
kontrol edilir.

`pdfplumber` yalnızca PDF parse ihtiyacı sürdüğü sürece tutulur. Broker/PDF hattı
kapanırsa ölü bağımlılık olarak kaldırılır.

## F Çapa Testi

Pin değişikliği "kuruldu" diye tamam sayılmaz. Anlamlı regression kapısı:

```powershell
python run_backtest.py --mode F
```

Beklenen canlı/gömülü çapa: `Getiri : %301.07`, `Max DD : %-5.54`.
Bu değer korunuyorsa pinlenen sürümler F'in ölçüldüğü ortamı sabitlemiştir.
Fark varsa bağımlılık veya veri girdisi değişmiş demektir; commit edilmez.

## Geri Dönüş

Bir güncelleme sonrası veri kapsamı düşer, panel yüklenmez veya rapor gecikirse:

1. Yeni paketi geri al.
2. Eski bilinen-iyi sürümü kur.
3. Audit çalıştır.
4. Değişikliği küçük commit ile belgeleyerek kapat.

## Yasaklar

- Canlı workflow içinde otomatik `pip install --upgrade` yok.
- Git URL, yerel dosya yolu veya değişken kaynaklı paket yok.
- Bağımlılık güncellemesiyle strateji değişikliği aynı commit'e konmaz.
