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
