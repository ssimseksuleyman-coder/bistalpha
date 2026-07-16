# Cloudflare Pages + Access Kurulum Runbook

Amac: BIST Alpha dashboard ve state JSON dosyalarini public GitHub Pages yerine
Cloudflare Access arkasinda yayinlamak.

Bu runbook F motoruna, stratejiye, portfoy state'e veya sanitizer'a dokunmaz.

## Degismez Kurallar

- `docs/` klasoru silinmez; Cloudflare Pages buradan yayin yapar.
- Sanitizer gevsetilmez. Access ikinci katmandir.
- Access testi tamamlanmadan repo private yapilmaz.
- Private yapmadan once GitHub `Insights -> Forks` kontrol edilir.
- Cloudflare deploy testi gecmeden GitHub Pages kapatilmis sayilmaz.

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

## 6. GitHub Pages Kapatma

Cloudflare Access testleri gecince GitHub Pages kapatilabilir:

```text
GitHub repo -> Settings -> Pages -> Disable / None
```

`docs/` klasoru silinmez.

Eski URL artik dashboard gostermemeli:

```text
https://ssimseksuleyman-coder.github.io/bistalpha/
```

## 7. Fork Kontrolu

Repo private yapilmadan once:

```text
GitHub repo -> Insights -> Forks
```

Fork varsa dur. Private gecis ve eski public veri riski yeniden degerlendirilir.

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
