# Cloudflare Pages + Access Kurulum Runbook

Amac: BIST Alpha dashboard ve state JSON dosyalarini public GitHub Pages yerine
Cloudflare Access arkasinda yayinlamak.

Bu runbook F motoruna, stratejiye, portfoy state'e veya sanitizer'a dokunmaz.
Bu belge 30 gunluk strateji/modul-ekleme yasagi kapsaminda bir al-sat katmani
degildir; erisim ve gizlilik altyapisi kararidir.

## Baglam

- Cloudflare Pages henuz kurulmamissa bu dosya kurulum sirasidir; mevcut canli
  yayin GitHub Pages olabilir.
- Yayinlanan kaynak `docs/` klasorudur. Dashboard HTML ve `docs/state/*.json`
  dosyalari bu klasorden servis edilir.
- Hedeflenen risk public web, arama motoru, dogrudan JSON URL erisimi ve repo
  gecmisi/log gorunurlugudur.
- Access burada Cloudflare Zero Trust Access anlamina gelir; email OTP veya
  benzeri kimlik kapisi kullanilir.
- `docs/` klasoru silinmez. Cloudflare Pages'in yayin kaynagi olarak kalir.
- Bu runbook `docs/` icinde oldugu icin Access/private gecis tamamlanana kadar
  kendisi de public kabul edilir. Secret, token, e-posta veya hassas state detayi
  icermez; gecis tamamlaninca bu belge de Access/private arkasina girer.

## Degismez Kurallar

- `docs/` klasoru silinmez; Cloudflare Pages buradan yayin yapar.
- Sanitizer gevsetilmez. Access ikinci katmandir.
- Private yapmadan once GitHub `Insights -> Forks` kontrol edilir.
- Cloudflare deploy testi gecmeden GitHub Pages kapatilmis sayilmaz.

## Gecis Modu Secimi

Karar heuristigi:

```text
Suphe varsa Acil Gizlilik Modu secilir.
```

Normal mod, dashboard'un kesintisiz kalmasini onceler:

1. Cloudflare Pages kur.
2. Hemen Access ekle.
3. Access ve direkt JSON testlerini gec.
4. GitHub Pages'i kapat.
5. Fork kontrolu yap.
6. Repo private yap.
7. Private sonrasi Cloudflare deploy testini gec.

Acil gizlilik modu, public erisimi en hizli kesmeyi onceler:

1. Fork kontrolu yap.
2. Repo private yap.
3. Cloudflare Pages + Access'i kur.
4. Access ve direkt JSON testlerini gec.
5. GitHub Pages durumunu kontrol et.
6. Private sonrasi Cloudflare deploy testini gec.

Acil modda dashboard kisa sure kaybolabilir. Normal modda public pencere daha
uzundur ama sanitizer birinci katman olarak riski azaltir. Hassas veri sizintisi
suphesi varsa acil mod secilir.

Bu gecis Katman 8 isleriyle paralel ilerleyebilir, fakat gizlilik supheliyse
once bu gecis tamamlanir. Gizlilik kirmizi iken yeni veri/strateji katmani
terfi ettirilmez.

## 1. Cloudflare Pages Projesi

Cloudflare dashboard:

```text
Workers & Pages -> Create application -> Pages -> Connect to Git
```

Ayarlar:

```text
Repository: ssimseksuleyman-coder/bistalpha
Production branch: main
Build command: bos
Build output directory: docs
Root directory: /
```

Deploy baslatilir. Olusacak URL genelde su formatta olur:

```text
https://bistalpha.pages.dev/
```

Bu adimdan sonra public test yapma; hemen Access ekle.

## 2. Cloudflare Access

Ilk Access ayari:

```text
Workers & Pages -> bistalpha -> Settings -> General -> Enable access policy
```

Policy:

```text
Action: Allow
Include: Emails
Email: kendi e-posta adresin
Login method: One-time PIN / email OTP
```

## 3. Pages.dev Host Kontrolu

Cloudflare'da production ve preview hostlari ayri davranabilir. Bu yuzden Access
kapsami iki hostu da kapatmalidir:

```text
bistalpha.pages.dev
*.bistalpha.pages.dev
```

Kontrol:

```text
Zero Trust -> Access controls -> Applications -> bistalpha
```

Gerekirse application hostname ayarinda wildcard ve production host ayrimi
duzeltilir.

## 4. Custom Domain Varsa

Custom domain kullanilacaksa once Pages'e domain ekle:

```text
Workers & Pages -> bistalpha -> Custom domains -> Set up a domain
```

Sonra Access icin ayri self-hosted application ekle:

```text
Zero Trust -> Access controls -> Applications -> Create application
Self-hosted and private
```

Hostname ornegi:

```text
dashboard.senin-domainin.com
```

Policy yine:

```text
Allow -> Emails -> kendi e-posta adresin
```

## 5. Anonim Erisim Testi

Gizli/incognito pencerede su URL'ler login istemeli:

```text
https://bistalpha.pages.dev/
https://bistalpha.pages.dev/state/dashboard.json
https://bistalpha.pages.dev/state/system_control_audit.json
https://bistalpha.pages.dev/health.html
```

Ardindan repo icinden script kos:

```powershell
python scripts\cloudflare_access_check.py `
  --base https://bistalpha.pages.dev/ `
  --retired https://ssimseksuleyman-coder.github.io/bistalpha/
```

Custom domain varsa:

```powershell
python scripts\cloudflare_access_check.py `
  --base https://bistalpha.pages.dev/ `
  --base https://dashboard.senin-domainin.com/ `
  --retired https://ssimseksuleyman-coder.github.io/bistalpha/
```

`FAIL` varsa repo private yapilmaz. Once Access route/policy duzeltilir.

Script spec'i:

- Protected URL icin `OK`: `401`, `403`, veya Cloudflare Access login
  hedefine giden `3xx` redirect.
- Protected URL icin `OK`: response body/Location icinde
  `cloudflareaccess.com`, `/cdn-cgi/access`, `cf-access` veya benzeri Access
  isareti.
- Protected URL icin `FAIL`: `200` ile dashboard HTML veya JSON state icerigi.
- Protected URL icin `FAIL`: `5xx`; altyapi hatasi Access kaniti sayilmaz.
- Anonymous testte `CF_Authorization` cookie beklenmez; bu cookie login
  sonrasina aittir.
- `--github-pages-api` icin `404` beklenir; `200` aktif GitHub Pages config'i
  demektir.
- `--forks-api` paginated taranir; bos liste beklenir.

Makine-dogrulanabilir komut:

```powershell
python scripts\cloudflare_access_check.py `
  --base https://bistalpha.pages.dev/ `
  --retired https://ssimseksuleyman-coder.github.io/bistalpha/ `
  --github-pages-api https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/pages `
  --forks-api https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/forks?per_page=100 `
  --sanitize-state docs/state/dashboard.json `
  --mode normal `
  --write-gate local/security_gate.json
```

Private sonrasi Cloudflare deploy testi de gectiyse `--cloudflare-deploy-ok`
eklenir. Bu komut `local/security_gate.json` uretir. `privacy_ok=true` ve
`live_fresh_ok=true` olmadan yeni katman terfisi yapilmaz. `local/` git disidir;
Access kurulmadan once gate durumu public yayinlanmaz.

Koruma ve tazelik ayri kapilardir:

- `privacy_ok`: Access/private/sanitize/fork/deploy koruma sorusudur.
- `live_fresh_ok`: Access arkasinda gorulen JSON'un yeni state ile eslestigi
  tazelik sorusudur.
- `live_fresh_ok=null` bilinmiyor demektir; yesil sayilmaz ve terfi/pilot
  icin yeterli degildir.
- Paper donemde tazelik manuel login + timestamp/hash kontroluyle
  `--live-fresh-ok` olarak isaretlenebilir.
- Pilot/gercek-para oncesi tazelik kontrolu Cloudflare Access Service Token ile
  otomatiklestirilmelidir. Token `local/` veya secret ortaminda kalir, repo'ya
  girmez.

Basari kriteri:

- Incognito tarayicida ana sayfa ve `docs/state/*.json` URL'leri Access login
  ekranina duser.
- `python scripts\cloudflare_access_check.py ...` sonucu `RESULT: OK` olur.
- `curl.exe -I` veya benzeri anonim HTTP kontrolde 200 ile dashboard/JSON icerigi
  donmez; Access redirect, 401 veya 403 kabul edilebilir. 500 kabul edilmez.
- Arama motoru kontrolunde `site:bistalpha.pages.dev` sonucu beklenmez. Sonuc
  varsa URL incelenir; dashboard veya JSON icerigi gorunuyorsa Access tekrar
  duzeltilir.
- Arama motoru sonucu cache kaynakli kalirsa Google Search Console URL Removal
  Tool ile kaldirma talebi degerlendirilir.

Ornek anonim HTTP kontrol:

```powershell
curl.exe -I https://bistalpha.pages.dev/state/dashboard.json
```

Beklenen: `302`/`303` ile Access login redirect'i veya `401`/`403`. `200` ile
JSON gelirse koruma hatali, `5xx` gelirse altyapi hatasi vardir.

## 6. GitHub Pages Kapatma

Cloudflare Access testleri gecince GitHub Pages kapatilabilir:

```text
GitHub repo -> Settings -> Pages -> Source: None / Disable
```

`docs/` klasoru silinmez.

Sadece `docs/` icinden dosya silmek gecmis commit'leri temizlemez. Hukuki veya
zorunlu sizinti gerekcesi varsa history temizligi ayri karar olarak ele alinir;
normal geciste purge ana yol degildir.

Eski URL artik dashboard gostermemeli:

```text
https://ssimseksuleyman-coder.github.io/bistalpha/
```

Not: GitHub Pages kapatildiktan sonra eski `github.io` URL'i DNS/cache/CDN
nedeniyle bir sure daha cevap verebilir. Bu, ayar basarisiz demek zorunda
degildir; fakat dashboard veya JSON icerigi 24 saatten uzun gorunurse yeniden
kontrol edilir.

API dogrulamasi:

```text
GET https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/pages
```

Beklenen: GitHub Pages kapaliysa `404` veya yetki/visibility kaynakli erisim yok.
`200` ile aktif Pages konfigi donerse eski yayin kaynagi hala aciktir.

## 7. Fork Kontrolu

Repo private yapilmadan once:

```text
GitHub repo -> Insights -> Forks
```

Opsiyonel API kontrolu:

```text
GET https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/forks?per_page=100
```

Response bos liste ise fork envanteri temiz kabul edilir. `Link` header'inda
`rel="next"` varsa sonraki sayfalar da cekilir. Bu envanter private gecisten
once alinmalidir; private sonrasi public fork gorunurlugu ve API davranisi
degisebilir.

Fork varsa dur. Private gecis ve eski public veri riski yeniden degerlendirilir.
Fork sahibi kendi fork'unu private yapmadikca o kopya disarida kalabilir.
Gerekirse GitHub destek/DMCA/takedown sureci ayri hukuki karar olarak ele
alinir.

## 8. Repo Private

Fork yoksa:

```text
GitHub repo -> Settings -> General -> Danger Zone -> Change visibility
```

Repo private yapilir.

Not: Repo private olduktan sonra disaridan bagimsiz `raw.githubusercontent.com`
ve GitHub Pages kontrolleri yapilamaz. Bundan sonra dogrulama, senin paylastigin
komut ciktilari, ekran goruntuleri veya Access arkasindan alinan dosya ozetleri
uzerinden ilerler. Bu gizlilik icin kabul edilen operasyonel bedeldir.

## 9. Private Sonrasi Deploy Testi

Private gecisten sonra Cloudflare'in GitHub yetkisi sessizce bozulabilir. Bunu
mutlaka test et:

1. Kucuk bir dokuman commit'i push edilir veya Cloudflare'dan redeploy tetiklenir.
2. 5 dakika icinde Cloudflare Pages build log gorunuyor mu kontrol edilir.
3. Dashboard timestamp donuk kalmiyor mu kontrol edilir.
4. `scripts\cloudflare_access_check.py` tekrar kosulur.

Build fail olursa GitHub App yetkisini kontrol et:

```text
GitHub -> Settings -> Applications -> Cloudflare Pages -> Repository access
Cloudflare -> Workers & Pages -> bistalpha -> Settings -> Builds & deployments
```

Cloudflare Pages private repo'ya erisemiyorsa yeniden yetkilendirme yapilir.

## 9b. Tutarlilik ve Canary

Dashboard gorunuyor diye sistem canli sayilmaz; eski deployment da gorunebilir.
Canli kabul icin:

- Trivial commit push edilir.
- 5 dakika icinde Cloudflare build log'u gorunur.
- Dashboard timestamp yeni deployment sonrasina ilerler.
- Telegram mesaji ve dashboard ayni `generated_at` veya ayni state commit'inden
  uretilmis olur.
- `docs/state/dashboard.json` hash'i, Cloudflare arkasinda login sonrasi gorulen
  JSON ile eslesir.

Gundelik canary:

```powershell
python scripts\cloudflare_access_check.py `
  --base https://bistalpha.pages.dev/ `
  --retired https://ssimseksuleyman-coder.github.io/bistalpha/ `
  --github-pages-api https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/pages `
  --forks-api https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/forks?per_page=100 `
  --sanitize-state docs/state/dashboard.json `
  --write-gate local/security_gate.json
```

Canary `red` ise yeni veri/strateji katmani terfi ettirilmez. Canary `yellow`
ise eksik manuel kontroller tamamlanmadan terfi yoktur.

Anonim canary Access sonrasi icerigi okuyamaz; sadece korumayi dogrular.
Bu yuzden tazelik ayri kontrol edilir. Login sonrasi `docs/state/dashboard.json`
hash'i ve dashboard timestamp'i canli gorunen JSON ile eslesirse ayni komuta
`--live-fresh-ok` eklenebilir. Bu bayrak unutulursa `live_fresh_ok=null` kalir
ve sistem tazeligi bilinmiyor kabul eder.

## 10. Security Gate State

Gizlilik kirmizi/sari/yesil karari manuel hafizada kalmaz. Katman 8 ve yeni
veri/strateji terfileri su state'i okuyabilmelidir:

```json
{
  "privacy_ok": false,
  "live_fresh_ok": null,
  "promotion_ok": false,
  "level": "red",
  "privacy_level": "red",
  "mode": "normal",
  "last_check": "2026-07-16T00:00:00+03:00",
  "checks": {
    "access_html_ok": false,
    "access_json_ok": false,
    "pages_dev_ok": false,
    "github_pages_retired": false,
    "fork_inventory_ok": false,
    "cloudflare_deploy_ok": false,
    "sanitize_ok": true,
    "live_fresh_ok": null
  },
  "missing_freshness_checks": ["live_fresh_ok"],
  "decision": "no_new_layer_promotion",
  "note": "Gizlilik kirmizi iken yeni katman terfi ettirilmez.",
  "freshness_note": "live_fresh_ok null ise tazelik bilinmiyor kabul edilir; yesil sayilmaz."
}
```

Hedef dosya:

```text
local/security_gate.json
```

`privacy_ok=false` veya `level=red` ise yeni defter, Katman 8, shadow veya veri
kaynagi production'a terfi etmez. F motoru mevcut haliyle korunur.

`level=yellow` de terfi icin yeterli degildir; sadece acil kirmizi riskin
kalktigini, fakat fork/deploy/sanitize gibi manuel kapilarin tamamlanmadigini
gosterir.

`live_fresh_ok=true` degilse terfi/pilot gecisi yapilmaz. `null`, kontrol
edilmedi anlamina gelir; basarili veya taze kabul edilmez. Bu durum F motorunu
durdurmaz, sadece yeni katman terfisini ve pilot gecisini kilitler.

## Kabul Durumu

Tamam sayilmasi icin:

- `scripts/cloudflare_access_check.py --base ... --write-gate ...` sonucu
  `RESULT: OK`, `security_gate.privacy_ok=true` ve
  `security_gate.live_fresh_ok=true`.
- Ana sayfa ve direkt JSON URL'leri anonim erisimde 302/401/403 veya Access
  login isareti donduruyor; 200 ile dashboard/JSON donmuyor.
- `*.pages.dev` ve varsa custom domain ayni testi geciyor.
- `GET /repos/ssimseksuleyman-coder/bistalpha/pages` aktif Pages config'i
  dondurmuyor.
- Fork envanteri `?per_page=100` ve pagination kontroluyle temiz veya risk
  kabul karari yazili.
- Private repo sonrasi trivial commit 5 dakika icinde Cloudflare build log'u
  uretiyor.
- Telegram/dashboard/state ayni state commit'i veya ayni `generated_at` ile
  tutarli.
- Sanitizer aktif ve audit temiz.
- Pilot/gercek-para oncesi `live_fresh_ok` manuel beyanla degil, Cloudflare
  Access Service Token ile otomatik dogrulanir.
