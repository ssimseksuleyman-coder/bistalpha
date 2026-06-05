# SEKTÖR EŞLEME DÜZELTMESİ — Bir Sonucu Çürüten Bulgu
**Tarih:** 2026-05-21 | Tetikleyen: kıdemli review (sektör/universe tutarsızlığı)

## SORUN
sectors.py 128 hisse eşliyordu; universe 240. Top-100 momentum evreninin **38'i
eşlenmemişti** → hepsi varsayılan "XU100"a düşüyordu → cap=2 için yanlış rekabet
(38 hisseden en fazla 2'si tutulabiliyordu — yapay aşırı kısıtlama).

## DÜZELTME
37 hisse gerçek sektörlerine eşlendi (XGMYO, XELKT, XUSIN, XGIDA, XUHIZ, XBANK,
XUTEK, XHOLD vb.). Sadece DOFRB belirsiz kaldı (XU100 default). Kapsam: 165 hisse.

## ETKİ — KRİTİK
| Config | ESKİ (yanlış) | YENİ (doğru) | DD | Calmar |
|--------|--------------|--------------|-----|--------|
| A | %168 | %289 | -6.6 | 43.8 |
| B | %187 | %269 | -8.1 | 33.0 |
| F | %198 | %301 | -5.5 | 54.3 |

Split-sample OOS: A %99, B %107, F %106.

## ÇÜRÜTÜLEN SONUÇ
**"B (SM lot) güvenli birincil iyileştirme"** — YANLIŞMIŞ.
- Eski (yanlış eşleme): B>A → B önerildi
- Doğru eşleme: B<A (%269<%289, Calmar 33<44). İlk yarıda B %78 vs A %96.
- SM-lot avantajı, 38 hissenin yanlış XU100 yığılmasının ARTEFAKTIYDI.

## AYAKTA KALAN
**F (koşullu vize)** hâlâ en iyi: A'yı getiri/DD/Calmar'da geçiyor, her iki yarıda
da sağlam. Koşullu vize gerçek değer katıyor.

## REVİZE TAVSİYE
- ESKİ: A control / B birincil / F üst-opsiyon
- YENİ: **A control / F birincil aday** (B artık önerilmiyor — A'yı geçemiyor)
- Shadow setup: A vs F (B'yi düşür veya sadece referans tut)

## İKİ UYARI
1. Mutlak sayılar şişti (168→289): doğru sektör = daha çok yüksek-momentum hisse
   tutulabiliyor. Meşru (gerçek cap=2 korunuyor) AMA tek rejim, ayı test edilmedi.
2. Bu, veri kalitesinin (sektör eşlemesi) yanlış sonuç üretebildiğinin kanıtı.
   Her sonuç, altındaki veri varsayımları kadar sağlam.

## DERS
selftest artık sektör kapsamını da denetlemeli (eklendi). Eşleme eksikliği gibi
yapısal hatalar sessizce yanlış sonuç üretir.
