# WEB DASHBOARD KURULUMU — Ücretsiz, 7/24, Bilgisayar Kapalı

## NEDEN BU YAKLAŞIM
Always-on web server gerekmez. Mimari:
1. GitHub Actions (cron) çalışınca **`docs/state/dashboard.json`** üretir + commit eder
2. **GitHub Pages** `docs/` klasörünü statik site olarak sunar (ücretsiz, 7/24)
3. Telefondan/tabletten **https://<kullanıcı>.github.io/<repo>/** ziyaret et — JSON'u alıp gösterir
4. Bilgisayarın kapalı olsa bile çalışır — Pages GitHub'da barınır, JSON da Actions'tan gelir

## KURULUM (3 dakika, ÜCRETSİZ)

### 1. GitHub Pages'i aç
- Repo → **Settings** → **Pages**
- "Build and deployment" → Source: **Deploy from a branch**
- Branch: `main` / Folder: **`/docs`**
- Save → birkaç dakika sonra siten yayında

### 2. Adresi öğren
- Pages ayarlarında URL gösterilir: `https://<kullanıcı>.github.io/<repo>/`
- Telefonun ana ekranına ekle (PWA gibi) — hızlı erişim

### 3. Bekle (veya elle tetikle)
- İlk Actions çalıştırmasında `docs/state/dashboard.json` üretilir + commit edilir
- Pages otomatik güncellenir, dashboard veriyi gösterir
- Elle test: repo → Actions → "Run workflow"

## DASHBOARD NE GÖSTERİR
- **Genel:** mod (A/B/F), Deniz rejim skoru, A/B/F pozisyon sayısı
- **TOP 10 öneri:** sıralama, hisse, sektör, M252, AL/SAT/BEKLE/FIRSAT, akıllı para sinyali
- **Yan kaynak bayrakları:** Deniz hisse skoru, yabancı akış, hacim uyarısı, FX-risk, bilanço, sezonsal
- **Vize işareti** (F modu koşullu vize)
- **3 Shadow hesap:** A/B/F için tutulan pozisyonlar (giriş + zirve)

## GÜVENLİK NOTU
Dashboard JSON repo'ya commit edilir — repo **private** olsa bile **Pages site PUBLIC** olur.
Hassas veri (gerçek pozisyon büyüklükleri, kimlik) dashboard'a sızmaz; sadece ticker
ve görece sayılar görünür. Yine de paylaşmak istemiyorsan:
- Pages'i kapalı tut, sadece local'de `python -m http.server -d docs 8000` ile bak
- 2026-07 karari: private repo + Cloudflare Pages + Cloudflare Access kullan.
  Access ana sayfayi ve `docs/state/dashboard.json` dogrudan URL'sini korumali.
  Kurulum sirasi icin `docs/GIZLILIK_CANLI_GECIS_KARARI.md` dosyasina bak.

Not: Cloudflare Access ikinci katmandir. Sanitizer kaldirilmaz; ham Deniz,
broker, secret, local path veya lisansli/turev veri state dosyalarina yazilmaz.

## MOBİL UYUM
Tek-dosya HTML, vanilla JS, framework yok. Mobile-first responsive tasarım, dark/light
otomatik adapte olmaz (sade beyaz). Telefonda hızlı yükler (~5KB HTML + ~3KB JSON).

İmza: Claude — 2026-05-21
