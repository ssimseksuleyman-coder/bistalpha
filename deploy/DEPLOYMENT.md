# 7/24 ÇALIŞMA — DAĞITIM (DEPLOYMENT) KILAVUZU

## ÖNCE DÜRÜST GERÇEK

Kendi bilgisayarında `daemon.py` veya cron çalıştırırsan, sistem **sadece
bilgisayar AÇIKKEN** çalışır. Bilgisayar kapalı/uykudaysa:
- daemon süreci ölür
- cron tetiklenmez
- 09:45/14:30/18:30 raporları GELMEZ

**Gerçek 7/24 için sistem "her zaman açık" bir yerde çalışmalı.** 3 seçenek:

---

## SEÇENEK 1 — GITHUB ACTIONS (ÜCRETSİZ, SUNUCU YOK) ⭐ en kolay

Bilgisayarın kapalı olsa bile GitHub'ın bulutunda çalışır. Sunucu yönetmezsin.

**Kurulum:**
1. Kodu bir GitHub repo'ya koy (private olabilir)
2. `deploy/github-actions-cron.yml` → `.github/workflows/bist-alpha.yml` yap
3. Repo Settings → Secrets and variables → Actions → şunları ekle:
   `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
4. Push et → otomatik 09:45/14:30/18:30 (TR) çalışır

**Artı:** Ücretsiz, sunucu yok, bakım yok.
**Eksi:** cron yoğunlukta birkaç dk gecikebilir (tam saat garanti değil).
Veri için: repo'ya commit et VEYA `DATA_SOURCE=api` ile canlı çek.

---

## SEÇENEK 2 — VPS + SYSTEMD (en güvenilir, ~5$/ay)

DigitalOcean / Hetzner / AWS Lightsail gibi küçük bir Linux sunucu.
Tam saat hassasiyeti, kesintisiz.

**Kurulum:**
```bash
# Sunucuda:
sudo timedatectl set-timezone Europe/Istanbul
sudo useradd -r -s /bin/false bistalpha
sudo cp -r bist_alpha_system /opt/
sudo pip3 install -r /opt/bist_alpha_system/requirements.txt

# Kimlik bilgilerini /etc/systemd/system/bist-alpha.service içine
# Environment= satırları olarak ekle (SMTP_USER vb.) veya EnvironmentFile kullan

sudo cp /opt/bist_alpha_system/deploy/bist-alpha.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bist-alpha   # açılışta otomatik
sudo systemctl start bist-alpha
journalctl -u bist-alpha -f        # canlı log
```

**Artı:** Tam güvenilir, tam saat, otomatik yeniden başlar, reboot'a dayanır.
**Eksi:** Aylık küçük ücret, sunucu kurulumu.

---

## SEÇENEK 3 — DOCKER (her yerde, esnek)

Cloud, Raspberry Pi (evde sürekli açık), veya herhangi Docker host.

```bash
docker build -t bist-alpha -f deploy/Dockerfile .
docker run -d --name bist-alpha --restart unless-stopped \
    -e TZ=Europe/Istanbul \
    -e SMTP_HOST=smtp.gmail.com -e SMTP_USER=... -e SMTP_PASS=... -e MAIL_TO=... \
    -e TELEGRAM_TOKEN=... -e TELEGRAM_CHAT_ID=... \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/deniz_inbox:/app/deniz_inbox \
    -v $(pwd)/portfolios:/app/portfolios \
    bist-alpha
```

`--restart unless-stopped`: çökerse/host reboot olursa otomatik açılır.

**Raspberry Pi notu:** Evde sürekli açık bir Pi (~5W) en ucuz 7/24 çözümdür.

---

## KARŞILAŞTIRMA

| Seçenek | Maliyet | Saat hassasiyeti | Sunucu bakımı | Kimin için |
|---------|---------|------------------|---------------|-----------|
| GitHub Actions | Ücretsiz | ±birkaç dk | Yok | En kolay başlangıç ⭐ |
| VPS + systemd | ~5$/ay | Tam | Az | En güvenilir |
| Docker (Pi) | Donanım | Tam | Az | Evde 7/24, tek seferlik maliyet |

---

## KİMLİK BİLGİLERİ — ARTIK ENV'DEN OKUNUR (güvenli)

`config.py` kimlik bilgilerini ortam değişkeninden okur — koda yazmazsın:
- GitHub Actions: Secrets
- systemd: `Environment=` satırları
- Docker: `-e` parametreleri

Hiçbir şifre kaynak kodda durmaz.

---

## ÖNERİ

1. **Başlangıç:** GitHub Actions (ücretsiz, hızlı kurulum, dene-gör)
2. **Ciddi/canlı:** VPS + systemd (tam güvenilirlik, tam saat)
3. **Evde donanımın varsa:** Raspberry Pi + Docker

Hepsinde: veri kaynağını (canlı BIST API veya commit'lenen Excel) ve Deniz
kaynağını (e-posta/klasör senkronu) bağlamayı unutma.

İmza: Claude (OMEGA) — 2026-05-20
