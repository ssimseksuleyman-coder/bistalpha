# Acik Isler

Bu dosya F motorunu degistirmez. Amac, operasyonel karar ve bekleyen isleri
repo icinde izlenebilir tutmaktir.

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

Durum: gizlilik kapisi yesil olmadan terfi yok.

Not: Defterler, shadow hesaplar ve yeni kaynaklar olcumde kalabilir; production
terfi karari icin once `security_gate.privacy_ok=true` ve
`security_gate.live_fresh_ok=true` gerekir. `live_fresh_ok=null` bilinmeyen/bayat
kabul edilir.
