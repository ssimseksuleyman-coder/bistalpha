# Gizlilik Canli Gecis Karari

Karar tarihi: 2026-07

## Karar

C stratejisi kapandi: sistem public GitHub Pages yerine private repo + Cloudflare
Pages + Cloudflare Access mimarisine gecirilecek.

Bu karar purge yerine ana gizlilik yolu olarak kabul edildi. Purge yalnizca hukuki
veya zorunlu bir gerekce dogarsa yeniden degerlendirilir. Eski public donem
kopyalari, cache, fork veya arsivler icin tam silme garantisi yoktur.

## Katmanlar

1. Sanitize: birinci katman. Public/private fark etmeden korunur.
2. Private repo: kod, commit gecmisi, Actions loglari ve state commit akisinin
   genel gorunurlugunu kapatir.
3. Cloudflare Pages: `docs/` klasorunu yayinlar. `docs/` silinmez.
4. Cloudflare Access: dashboard ve dogrudan JSON URL'lerini kimlik dogrulama
   arkasina alir.
5. Deploy testi: private sonrasi Cloudflare deploy yetkisinin bozulmadigini
   dogrular.

## Uygulama Sirasi

1. Sanitize kontrolleri korunur; hicbir hassas alan geri acilmaz.
2. Cloudflare Pages repo `main` ve output `docs` ile kurulur.
3. Ilk deploydan hemen sonra Cloudflare Access eklenir; deploy ile Access
   arasinda manuel test yapilmaz.
4. Access hem `*.pages.dev` hem varsa custom domain hostunu kapsar.
5. Test edilir:
   - Ana sayfa login istiyor mu?
   - `state/dashboard.json` dogrudan URL ile login istiyor mu?
   - Health ve diger state JSON dosyalari login istiyor mu?
6. GitHub Pages ayari kapatilir; `docs/` klasoru kalir.
7. Repo private yapilmadan once GitHub `Insights -> Forks` kontrol edilir.
   Fork varsa private gecis ve eski public veri riski yeniden degerlendirilir.
8. Repo private yapilir.
9. Private sonrasi yeni bir Cloudflare deploy tetiklenir ve dashboard donmuyor mu
   kontrol edilir.

## Kabul Kriterleri

- Sanitizer aktif ve audit temiz.
- Cloudflare Access ana HTML ve dogrudan JSON dosyalarini koruyor.
- `*.pages.dev` acikta kalmiyor.
- Custom domain varsa o da Access kapsaminda.
- GitHub Pages eski public yayin kaynagi olarak kapali.
- Private repo sonrasi Cloudflare deploy alabiliyor.
- Telegram, dashboard ve portfolio state ayni kaynak state ile tutarli.

## Otomatik Erisim Kontrolu

Cloudflare Access kurulduktan sonra anonim istemciyle kontrol:

```powershell
python scripts\cloudflare_access_check.py `
  --base https://<cloudflare-pages-host>/ `
  --retired https://ssimseksuleyman-coder.github.io/bistalpha/
```

Custom domain de varsa ikinci `--base` olarak eklenir. Script su yollarin login
arkasinda kalip kalmadigini kontrol eder:

- `/`
- `/state/dashboard.json`
- `/state/system_control_audit.json`
- `/health.html`

`FAIL` sonucu varsa repo private yapilmaz; once Access route/policy duzeltilir.

## Uygulama Runbook'u

Ekranda adim adim kurulum icin:

```text
docs/CLOUDFLARE_ACCESS_KURULUM.md
```

## Degismez Kural

Access ikinci katmandir. Sanitize birinci katman olarak kalir. Access var diye
ham Deniz, broker, secret, local path, email, token veya lisansli/turev veri
dashboard/state dosyalarina yazilmaz.
