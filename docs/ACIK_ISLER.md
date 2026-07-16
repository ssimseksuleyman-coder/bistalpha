# Acik Isler

Bu dosya F motorunu degistirmez. Amac, operasyonel karar ve bekleyen isleri
repo icinde izlenebilir tutmaktir.

## Trading / Gercek Para

## P0 - Gercek Para Kapisi (C1)

Durum: C1 2/5 pencere. Aylardir acik.

Bloker: pilot acilmadi; gercek fill yok; C1 dolmuyor. Paper sinyal ve shadow
hesaplar C1'i kapatmaz.

Kalan:

- 3 bagimsiz pilot-fill penceresi.
- Broker secimi: Midas veya Deniz. Komisyon varsayimlari kullanici tarafindan
  teyit edilir ve karar yazili hale getirilir.
- Pilot sermaye: 40k karari verildi. DSTKF tipi 2000+ TL pick'lerde 1-2 lot
  ile kaba slippage ve fill davranisi olculecek; bu sinir biliniyor.
- `--pf` hook: `taban_readiness` gercek hesap dosyasini okuyacak. Pilot
  baslayinca eklenir; F motorunu degistirmez.
- `privacy_ok=true` pilot on-kosuludur.
- `live_fresh_ok=true` pilot on-kosuludur ve pilot/gercek-para oncesi
  Cloudflare Access Service Token ile otomatik dogrulanmalidir.

Tamamlanma kriterleri:

- Broker secimi ve pilot hesap akisi yazili.
- Pilot sermaye transfer/limit karari tamam.
- `privacy_ok=true` ve otomatik `live_fresh_ok=true`.
- Toplam 5 C1 penceresi gercek fill verisiyle kayitli; su an 2/5.
- Taban/lock, slippage, fill, gecikme ve Telegram/dashboard tutarliligi C1
  defterine yaziliyor.

Not: Hicbir ek teknik mod veya defter bu kapiyi kapatmaz. Bu kapiyi yalnizca
gercek fill verisi kapatir.

## Infrastructure / Gizlilik

## P0 - Gizlilik Canli Gecis

Durum: plan ve kontrol araci hazir; Cloudflare Pages + Access kurulum penceresi
bekleniyor.

Kaynak runbook:

```text
docs/CLOUDFLARE_ACCESS_KURULUM.md
```

Karar:

- Suphe varsa Acil Gizlilik Modu.
- Aktif sanitize sizintisi yoksa varsayilan uygulama Normal Mod'dur.
- Gizlilik kirmizi iken yeni veri/strateji katmani terfi ettirilmez.
- `privacy_ok` ve `live_fresh_ok` ayri kapilardir; koruma yesil olsa bile
  tazelik bilinmiyorsa terfi/pilot gecisi yoktur.
- `live_fresh_ok=null` kontrol edilmedi anlamina gelir; basarili veya taze
  kabul edilmez.
- `local/security_gate.json` ile privacy gate kaydi tutulur.

Tamamlanma kriterleri:

- Cloudflare Pages deploy aliyor.
- Cloudflare Access ana sayfa ve direkt JSON URL'lerini koruyor.
- `*.pages.dev` acikta degil.
- GitHub Pages eski yayin kaynagi kapali.
- Fork envanteri temiz veya risk kabul karari yazili.
- Repo private.
- Private sonrasi Cloudflare deploy testi basarili.
- `scripts/cloudflare_access_check.py` sonucu `RESULT: OK`.
- `local/security_gate.json` icinde `privacy_ok=true`.
- Paper donemde tazelik manuel login + timestamp/hash kontroluyle
  `live_fresh_ok=true` yapilabilir.
- Pilot/gercek-para oncesi `live_fresh_ok=true` Cloudflare Access Service Token
  ile otomatik dogrulanir.

## Strategy / Veri Katmanlari

## P1 - Katman 8 / Yeni Veri Katmanlari

Durum: gizlilik ve tazelik kapilari yesil olmadan terfi yok.

Not: Defterler, shadow hesaplar ve yeni kaynaklar olcumde kalabilir; production
terfi karari icin once `security_gate.privacy_ok=true` ve
`security_gate.live_fresh_ok=true` gerekir. `live_fresh_ok=null` bilinmeyen/bayat
kabul edilir.

## P2 - KAP Finansal Tablo Parser Envanteri

Durum: Temel Kalite Defteri iskelet halinde; gercek KAP finansal tablo
otomasyonu yok. Deniz veya broker turevi statik veri public repo'ya girmez.

Amac:

- KAP finansal raporlarindan ROE, net kar buyumesi, ciro buyumesi, borcluluk,
  marj ve ozkaynak kalemlerini resmi kaynakla cikarmak.
- Temel Kalite Defteri'ni Deniz/broker turevi veri olmadan doldurmak.
- Stockeys/X gibi kaynaklari sadece aday kaynagi olarak tutmak; KAP dogrulamasi
  olmadan islem veya kalite puani uretmemek.

Kalan:

- KAP kaynak envanteri: PDF, Excel, XBRL veya API erisimi hangi sirayla
  kullanilacak yazilacak.
- Sirket-kalem esleme sozlugu: net kar, satis geliri, ozkaynak, toplam borc,
  nakit, FAVOK gibi kalemlerin rapor formatlarindaki adlari belirlenecek.
- Parser pilotu: once 5-10 likit sirket ve son 4 ceyrek uzerinde test.
- Dogrulama: KAP ciktisi en az iki kaynaktan veya manuel kontrolle eslesmeden
  defterde `trusted=true` olmayacak.
- Hata modu: parser bozuktur veya kalem bulunamamistir ise defter bos kalir;
  F raporu etkilenmez.

Tamamlanma kriterleri:

- En az 30 benzersiz sirket icin son rapor donemi metrikleri KAP kaynakli ve
  dogrulanmis.
- `quality_ledger` her metrik icin kaynak tarihini, rapor donemini ve
  guven/eksik alan durumunu yaziyor.
- Temel kalite puani sadece olcum ve izleme amaclidir; F motoruna otomatik
  terfi yoktur.
