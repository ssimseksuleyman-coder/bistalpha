# Acik Isler

Bu dosya F motorunu degistirmez. Amac, operasyonel karar ve bekleyen isleri
repo icinde izlenebilir tutmaktir.

## P0 - Gizlilik Canli Gecis

Durum: plan ve kontrol araci hazir; Cloudflare Pages + Access kurulum penceresi
bekleniyor.

Kaynak runbook:

```text
docs/CLOUDFLARE_ACCESS_KURULUM.md
```

Karar:

- Suphe varsa Acil Gizlilik Modu.
- Gizlilik kirmizi iken yeni veri/strateji katmani terfi ettirilmez.
- `docs/state/security_gate.json` ile privacy gate kaydi tutulur.

Tamamlanma kriterleri:

- Cloudflare Pages deploy aliyor.
- Cloudflare Access ana sayfa ve direkt JSON URL'lerini koruyor.
- `*.pages.dev` acikta degil.
- GitHub Pages eski yayin kaynagi kapali.
- Fork envanteri temiz veya risk kabul karari yazili.
- Repo private.
- Private sonrasi Cloudflare deploy testi basarili.
- `scripts/cloudflare_access_check.py` sonucu `RESULT: OK`.

## P1 - Katman 8 / Yeni Veri Katmanlari

Durum: gizlilik kapisi yesil olmadan terfi yok.

Not: Defterler, shadow hesaplar ve yeni kaynaklar olcumde kalabilir; production
terfi karari icin once `security_gate.privacy_ok=true` gerekir.
