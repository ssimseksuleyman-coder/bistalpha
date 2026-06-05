# BISTALPA Canli / 7-24 Durum

Tamamlananlar:
- Varsayilan `DATA_SOURCE` artik `yahoo`; yerel daemon/shadow canli veri dener.
- Yahoo canli veri bossa sistem anlasilir hata verir; `selfheal.safe_feed()` gomulu Excel yedegine duser.
- `canli_veri_kontrol.bat` eklendi: canli veri cekimini test eder.
- `canli_calistir.bat` eklendi: tek canli dongu calistirir ve dashboard JSON gunceller.
- `github_724_kontrol.bat` eklendi: 7/24 GitHub Actions hazirligini denetler.
- `selftest.py` artik GitHub remote yoksa 7/24 icin uyarir.

Kalan kullaniciya bagli adimlar:
- GitHub remote/repo yoksa bilgisayar kapaliyken 7/24 aktif olmaz.
- GitHub Actions secrets uzaktan okunamaz; repo ayarlarina SMTP/Telegram/IMAP secrets eklenmeli.
- Bu bilgisayarda `git` komutu PATH'te yoksa push icin Git kurulumu veya GitHub web upload gerekir.
