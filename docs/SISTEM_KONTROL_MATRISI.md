# BIST Alpha Sistem Kontrol Matrisi

Bu matrisin amacı F motorunu bozmadan sistemi denetlemektir. Kontrollerin
mantığı: önce gözlem, sonra ölçüm, sonra sınırlı düzeltme, en son terfi.

Otomatik kontrol:

```powershell
python scripts\system_control_audit.py --write docs\state\system_control_audit.json
```

Kırmızı sonuç canlı motorun güvenini düşürür. Sarı sonuç doğrudan hata değildir;
bakım veya sadeleştirme gerektiren alanı işaret eder.

## Kontrol Katmanları

| Katman | Amaç | Kırmızı Ne Demek? | Sarı Ne Demek? | Doğru Aksiyon |
|---|---|---|---|---|
| Duplicate / redundant dosya | Aynı işi yapan dosya ve deney kalıntılarını bulmak | Aynı çıktı iki kaynaktan üretiliyor | Fazla root script veya aynı isimli dosya var | Aktifi koru, deneyi `local/` altına al veya birleştir |
| Yanıltıcı bilgi / gürültü | Eski, lisanslı veya yanlış isimlerin panelde görünmesini engellemek | Public docs/state kirli | Etiket veya panel açıklaması belirsiz | Public artefaktı sanitize et, cloud run ile yeniden üret |
| Birleştirme / sadeleştirme | Her defterin tek rolü olmasını sağlamak | Bir defter F state'i bozabiliyor | Fazla deneysel dosya birikmiş | Defterleri ölçümde tut, production'a karıştırma |
| Operasyon / kod kalitesi | Kodun derlenmesi, daemon izolasyonu, workflow sağlığı | Syntax hatası veya daemon kırılganlığı | Ledger hook inceleme ister | Önce izolasyon, sonra dashboard bağlama |
| Veri bütünlüğü | JSON parse, dashboard schema, fiyat kapsamı | State bozuk veya zorunlu alan yok | Kapsam eşiğe yakın | Veri kaynağı ve fallback zincirini kontrol et |
| Uygulama adımları | Kurulum, cron, manuel tetik ve state commit yolu | Workflow eksik | Fallback veya runbook eksik | Workflow'u küçük patch ile tamamla |
| Stratejik karar | F üretim, O/G1 shadow, defterler ölçüm | Shadow production gibi davranıyor | Rol panelde görünmüyor | Terfi kapısı olmadan production'a alma |
| Risk / execution | Stop, değerleme, operasyon kapısı | Stop/değerleme primitive yok | Operasyon kapısı sarı/kırmızı | Sinyali değil operasyonu düzelt |
| Modülerizasyon | Paket ve script ayrımı | Import/compile kırılıyor | Düşük referanslı modül var | Yetim modülü belgeleyerek tut veya arşivle |
| Performans / ölçekleme | Büyük tarama, network fallback, state büyümesi | Workflow ölçeklenemiyor | Root script ve state büyüyor | Cap, rotasyon, batch ve fallback uygula |
| İzleme / geri bildirim | Health, Telegram, report_runs, ledger sonuçları | Panel mesajla çelişiyor | Metrik eksik | Tek kaynak dashboard/state; Telegram ondan üretir |
| Bağlanmamış süreç | Çalışmayan veya bağlanmayan modülleri bulmak | Kritik modül hiç çağrılmıyor | Deneysel modül düşük referanslı | Ölçüm defteri ise belge, değilse kaldır |
| Güvenlik / yasal uyum | Secret ve lisanslı/türev veri sızıntısı | Token veya broker-türev public | Ignore politikası eksik | Secret rotate, history purge gerekirse planlı yap |
| Gizlilik / veri minimizasyonu | PII, kişisel yol, raw state ve gereksiz detay sızıntısını engellemek | Token/e-posta/kişisel yol public | Privacy policy veya state minimizasyon uyarısı | Ham veri local, public sadece özet/agrega |
| Bağımlılık güncelleme | Üçüncü parti paket değişikliklerinin F'i bozmasını engellemek | Değişken dış kaynak veya manifest eksik | Sürümler gevşek aralıkta | Önce shadow/test, sonra bilinen-iyi pin |
| Değişiklik yönetimi | Commit kapsamı, geri alma ve terfi disiplinini korumak | Workflow force-push veya state yolu belirsiz | Politika veya kapsam uyarısı | Küçük commit, audit, rollback notu |
| Dokümantasyon | Kurulum, veri kaynağı, defter ve karar mantığı | Runbook yok | Doküman koddan geride | Değişiklikle birlikte kısa karar notu ekle |
| Kullanıcı / arayüz | Dashboard ve sağlık paneli okunabilirliği | Panel yüklenmiyor | Kart adı/etiketi yanıltıcı | Kartı gerçek veri kaynağına göre adlandır |
| Yedek / felaket / canlı geçiş | State kalıcılığı ve geri dönüş | Portföy state yok | Backup prosedürü belirsiz | Commit edilen state + lokal yedek + force-push disiplini |
| Uç durum / stres | Taban, re-entry, bozuk veri, Yahoo kesintisi | Stres aracı yok | Araç var ama rapora bağlı değil | Ayrı defterde ölç, F'e bağlama |
| Kendi bakımını yapma | Sistem kendi sağlığını ölçebiliyor mu | Selftest/audit yok | Audit var ama koşulmuyor | Büyük değişiklik öncesi/sonrası audit çalıştır |

## Terfi Disiplini

1. F production motoru korunur.
2. Yeni fikir önce defter veya shadow hesap olur.
3. Defter kendi katkısını 5g / 21g / 63g gibi olgun pencerelerde ölçer.
4. Dashboard sadece ölçümü gösterir; işlem kararı F tarafında kalır.
5. Canlıya terfi için veri kalitesi, operasyon kapısı ve risk kapıları yeşil olmalıdır.

## Audit Sonucu Nasıl Okunur

- `green`: kırmızı yok, sarı yok. Sistem bakım açısından temiz.
- `yellow`: kırmızı yok ama bakım borcu var. Canlı sinyal kullanılabilir, fakat terfi yapılmaz.
- `red`: güven kırıcı hata var. Önce operasyon veya veri düzeltilir.

Audit JSON dosyası:

```text
docs/state/system_control_audit.json
```

Bu dosya panelde ayrı bir bakım kartına bağlanabilir. Production sinyal kaynağı
değildir; ölçüm aparatıdır.
