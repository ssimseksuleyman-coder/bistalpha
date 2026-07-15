# Değişiklik Yönetimi

Bu sistemde değişiklik yönetiminin ana ilkesi: üretim motoru korunur, ölçüm
katmanları ayrılır, terfi kanıta bağlanır.

## Değişiklik Sınıfları

| Sınıf | Örnek | Risk | Kural |
|---|---|---|---|
| Üretim motoru | F seçimi, stop, rebalance | Yüksek | Sadece açık karar ve testle |
| Shadow hesap | O, G1, yeni hesap | Orta | Production yerine geçmez |
| Defter / ölçüm | fırsat, katalizör, akış, kalite | Düşük-Orta | F'e emir üretmez |
| Panel / rapor | dashboard, health, Telegram metni | Orta | Tek kaynak state olmalı |
| Operasyon | workflow, fallback, bakım, audit | Orta | Küçük commit, geri dönüş planı |
| Dokümantasyon | runbook, politika | Düşük | Kodla aynı niyeti taşımalı |

## Commit Öncesi Kontrol

```powershell
git diff --check
python -m py_compile scripts\system_control_audit.py
python scripts\system_control_audit.py --write docs\state\system_control_audit.json
```

Üretim motoruna dokunan değişikliklerde ek olarak:

```powershell
python selftest.py
python run_backtest.py
```

## Commit Kapsamı

Her commit tek amaç taşımalıdır:

- kod değişikliği,
- state güncellemesi,
- dokümantasyon,
- veya bakım aracı.

Bunlar zorunlu olmadıkça karıştırılmaz. Özellikle strateji değişikliği ile
bağımlılık güncellemesi aynı commit'e konmaz.

## Terfi Kapısı

Yeni fikir önce defter veya shadow olur. Production'a yaklaşması için:

1. Olgun forward pencere üretir.
2. Veri kalitesi geçer.
3. Operasyon kapısı yeşil veya kabul edilebilir sarıdır.
4. Risk / drawdown kapıları ihlal edilmez.
5. F'e göre katkısı net ve tekrarlanabilir görünür.

## Geri Alma

Sorun çıktığında sırayla:

1. Son commit kapsamı okunur.
2. State mi kod mu ayrılır.
3. Kod sorunuysa küçük düzeltme commit'i yapılır.
4. State sorunuysa state yeniden üretilir.
5. Zorunlu olmadıkça force-push yapılmaz.

## Yasaklar

- Ölçüm defteri production state'i bozmaz.
- Panelde görünen her metrik tek kaynaktan gelmelidir.
- Public çıktıya lisanslı veya özel türev veri konmaz.
- Shadow sonuçları terfi kapısı olmadan işlem motoru sayılmaz.
