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

## Gizlilik Karari

2026-07 karari: public GitHub Pages ana canli yayin yolu olmaktan cikarilir.
Yeni hedef private repo + Cloudflare Pages + Cloudflare Access mimarisidir.

- Sanitizer birinci katman olarak kalir.
- Cloudflare Access ikinci katmandir; HTML ve dogrudan JSON URL'lerini korur.
- Repo private yapilmadan once fork kontrolu gerekir.
- Private sonrasi Cloudflare deploy yetkisi tekrar test edilir.
- Purge yalnizca hukuki veya zorunlu gerekce dogarsa yeniden degerlendirilir.

Detayli runbook:

```text
docs/GIZLILIK_CANLI_GECIS_KARARI.md
```

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

## Sağlık Artefaktlarını Okuma

`liveness.json` tek başına nihai hüküm değildir. Alt dosyaların **toplu tarama
fotoğrafıdır** ve fotoğraf çekildikten sonra alt dosyalar güncellenmiş olabilir.

| Dosya | Ne söyler |
|---|---|
| `dashboard.json` | Son sinyal/veri state'i |
| `watchdog.json` | Bekçinin son gerçek durumu (`sonuc`, `verdict` değil) |
| `content_sanity.json` | Anlamlılık kontrolünün son gerçek durumu |
| `liveness.json` | Yukarıdakilerin son toplu fotoğrafı; bayat olabilir |

Okuma sırası: önce `liveness.updated_at` yaşı, sonra alt dosyaların damgaları.

| liveness satırı | Gerçek alt dosya | Yorum | Aksiyon |
|---|---|---|---|
| RED (`A/BAYAT`) | `watchdog` güncel ve `SESSIZ` | liveness eski fotoğraf | Yeniden tara; müdahale değil |
| RED (`A/BAYAT`) | `watchdog` güncel ve `ALARM` | Gerçek alarm | Üretim hattını incele |
| RED (`A/YOK` · `A/BOZUK`) | `watchdog` yok veya bozuk | Gerçek alarm | Tarayıcı zincirini incele |
| RED (`B*/*`) | İçerik kontrolü bozuk gördü | Gerçek alarm veya ayrı inceleme | Liveness içeriğini denetle |
| GREEN | `watchdog` güncel ve `SESSIZ` | Sağlıklı | Aksiyon yok |

Alt dosyalar `liveness.updated_at`'ten daha yeniyse panel bunu ayrı göstermelidir:
güncel alt hüküm ile eski toplu hüküm aynı ekranda farklı yaşlardadır.

`liveness = RED` + alt dosyalar güncel ve temiz ise hüküm **"sistem kırmızı" değil,
"toplu sağlık taraması bayat"** demektir. İkisi farklı aksiyon gerektirir.

Ölçülmüş maliyet (2026-08-28/29): bayat bir RED, tarayıcı günde bir koştuğu ve cron
saatlerce gecikebildiği için yaklaşık **24 saat** panelde kalabilir.

## content_sanity Alarm Dili

`select_valid_count / price_count` oranının dağılımı ölçüldü (kaynak: `content_sanity.json`
git tarihçesi, 27 gün, 2026-07-24 .. 2026-08-31). Dağılım iki parçalıdır; arada örnek yoktur.

| Sınıf | Ölçülen oran | Anlamı |
|---|---|---|
| Normal | 0.93 – 0.95 | Skor evreni sağlam |
| Geçici içgün çöküş | Gün içinde bazı koşumlar < 0.02, bazıları normal | Bar geçici bozuldu, gün içinde toparlandı |
| Gün boyu çöküş | Günün çoğu koşumu < 0.02 | Yapısal; o gün seçim çöplerle karar verirdi |

Frekans: herhangi bir çöküş görülen gün 4/27, gün boyu çökük kalan gün 2/27.

Eşik `0.5`'tir ve hassas bir ayar değildir: normal küme ile çöküş kümesi arasında
`0.02 – 0.93` boşluğu vardır ve bu aralıkta **hiç örnek gözlenmemiştir**. Bu nedenle
ara (amber) bant şu an tanımlanmaz; veri onu desteklemez.

Bu bir uyarı eşiğidir, karar eşiği değildir. `content_sanity` Top10 veya Fırsat
yayınını bastırmaz; yalnız `shadow.py` veri kapısı üzerinden rebalans kararını erteler.

Bu dağılımı izleyecek denetim `missed_opportunities.json`'a değil `content_sanity.json`
tarihçesine bakmalı ve **gün başına** toplulaştırmalıdır; aynı günün birden çok koşumu
bağımsız gözlem değildir.
