# Cloudflare Pages + Access Kurulum Runbook

Amac: BIST Alpha dashboard ve state JSON dosyalarini public GitHub Pages yerine
Cloudflare Access arkasinda yayinlamak.

Bu runbook F motoruna, stratejiye, portfoy state'e veya sanitizer'a dokunmaz.

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
uzundur ama sanitizer birinci katman olarak riski azaltir. Hassas veri sızıntısı
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

Basari kriteri:

- Incognito tarayicida ana sayfa ve `docs/state/*.json` URL'leri Access login
  ekranina duser.
- `python scripts\cloudflare_access_check.py ...` sonucu `RESULT: OK` olur.
- `curl -I` veya benzeri anonim HTTP kontrolde 200 ile dashboard/JSON icerigi
  donmez; Access redirect, 401 veya 403 kabul edilebilir.
- Arama motoru kontrolunde `site:bistalpha.pages.dev` sonucu beklenmez. Sonuc
  varsa URL incelenir; dashboard veya JSON icerigi gorunuyorsa Access tekrar
  duzeltilir.

## 6. GitHub Pages Kapatma

Cloudflare Access testleri gecince GitHub Pages kapatilabilir:

```text
GitHub repo -> Settings -> Pages -> Source: None / Disable
```

`docs/` klasoru silinmez.

Sadece `docs/` icinden dosya silmek gecmis commit'leri temizlemez. Hukuki veya
zorunlu sızıntı gerekcesi varsa history temizligi ayri karar olarak ele alinir;
normal geciste purge ana yol degildir.

Eski URL artik dashboard gostermemeli:

```text
https://ssimseksuleyman-coder.github.io/bistalpha/
```

Not: GitHub Pages kapatildiktan sonra eski `github.io` URL'i DNS/cache/CDN
nedeniyle bir sure daha cevap verebilir. Bu, ayar basarisiz demek zorunda
degildir; fakat dashboard veya JSON icerigi 24 saatten uzun gorunurse yeniden
kontrol edilir.

## 7. Fork Kontrolu

Repo private yapilmadan once:

```text
GitHub repo -> Insights -> Forks
```

Opsiyonel API kontrolu:

```text
GET https://api.github.com/repos/ssimseksuleyman-coder/bistalpha/forks
```

Response bos liste ise fork envanteri temiz kabul edilir. Bu envanter private
gecisten once alinmalidir; private sonrasi public fork gorunurlugu ve API
davranisi degisebilir.

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

## 9. Private Sonrasi Deploy Testi

Private gecisten sonra Cloudflare'in GitHub yetkisi sessizce bozulabilir. Bunu
mutlaka test et:

1. Kucuk bir dokuman commit'i push edilir veya Cloudflare'dan redeploy tetiklenir.
2. Cloudflare Pages yeni deployment aliyor mu kontrol edilir.
3. Dashboard timestamp donuk kalmiyor mu kontrol edilir.
4. `scripts\cloudflare_access_check.py` tekrar kosulur.

Build fail olursa GitHub App yetkisini kontrol et:

```text
GitHub -> Settings -> Applications -> Cloudflare Pages -> Repository access
Cloudflare -> Workers & Pages -> bistalpha -> Settings -> Builds & deployments
```

Cloudflare Pages private repo'ya erisemiyorsa yeniden yetkilendirme yapilir.

## Kabul Durumu

Tamam sayilmasi icin:

- Cloudflare Pages deploy aliyor.
- Ana sayfa login istiyor.
- Direkt JSON URL'leri login istiyor.
- `*.pages.dev` acikta degil.
- Custom domain varsa o da Access arkasinda.
- GitHub Pages eski yayin kaynagi kapali.
- Private repo sonrasi Cloudflare deploy aliyor.
- Sanitizer aktif kaldi.
