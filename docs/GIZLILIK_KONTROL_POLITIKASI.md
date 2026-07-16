# Gizlilik Kontrol Politikası

Amaç: public repo, GitHub Pages, Telegram çıktısı ve state dosyalarında kişisel
bilgi, secret, lisanslı/türev veri veya gereksiz ham veri sızıntısını önlemek.

## Public Olabilir

- Sanitized dashboard metrikleri
- Toplu/özet performans defterleri
- Resmi kaynaklardan türetilmiş, ham içerik taşımayan agregalar
- Kod, test, politika ve runbook dosyaları

## Public Olmamalı

- Telegram bot token, chat id, API key, SMTP/IMAP bilgileri
- Kişisel e-posta adresleri
- Yerel makine kullanıcı klasörü yolları
- Ham PDF, Excel, e-posta eki, mesaj gövdesi
- Lisanslı aracı kurum bülteni veya ondan türetilmiş satır-detay veri
- Özel portföy notları, manuel karar notları, kişisel hazırlık dosyaları

## State Dosyası Kuralı

`docs/state/` public sayılır. Buraya sadece:

- özet metrik,
- karar etiketi,
- sayım,
- yaş / tazelik,
- kaynak türü,
- sanitize edilmiş liste

yazılır. Ham dosya adı, e-posta, attachment, PDF yolu, token, kişisel yol veya
satır-detay broker içeriği yazılmaz.

## Secret Yönetimi

Secret'lar sadece GitHub Actions Secrets veya yerel `.env` içinde tutulur.
Repo içinde gerçek değer yazılmaz. Bir secret yanlışlıkla paylaşılırsa:

1. Hemen ilgili serviste rotate edilir.
2. Repo içinde geçtiyse history temizliği değerlendirilir.
3. Audit yeniden çalıştırılır.
4. Olay küçük bir bakım notuyla kapatılır.

## Otomatik Kontrol

```powershell
python scripts\system_control_audit.py --write docs\state\system_control_audit.json
```

Audit şu sınıfları kontrol eder:

- token benzeri literal,
- e-posta literal,
- kişisel absolute path,
- public state içinde hassas alan,
- lisanslı/private path ignore politikası.

## Canli Yayin Karari

2026-07 karari: public GitHub Pages ana yayin yolu olmaktan cikarilir. Canli
dashboard icin private repo + Cloudflare Pages + Cloudflare Access kullanilir.
Detayli sira ve kabul kriterleri:

```text
docs/GIZLILIK_CANLI_GECIS_KARARI.md
```

Bu karar sanitizer'i gevsetmez. Access ikinci katmandir; ham veya lisansli/turev
veri state dosyalarina yazilmaz.

## Prensip

Ölçüm için gereken minimum veri public olur. Ham veri local kalır. F motoru
gizli veya lisanslı dış kaynağa bağımlı hale getirilmez.
