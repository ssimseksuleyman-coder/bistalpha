# Değişiklik Yönetimi

Bu sistemde değişiklik yönetiminin ana ilkesi: üretim motoru korunur, ölçüm
katmanları ayrılır, terfi kanıta bağlanır.

## Değişiklik Sınıfları

| Sınıf | Örnek | Risk | Kural |
|---|---|---|---|
| Üretim motoru | F seçimi, stop, rebalance | Yüksek | Sadece açık karar ve testle |
| Shadow hesap | O, G1, yeni hesap | Orta | Production yerine geçmez |
| Defter / ölçüm | fırsat, katalizör, akış, kalite | Düşük-Orta | F'e emir üretmez |
| Panel / rapor | dashboard, health, Telegram metni | Orta | Tek kaynak state olmalı |
| Operasyon | workflow, fallback, bakım, audit | Orta | Küçük commit, geri dönüş planı |
| Dokümantasyon | runbook, politika | Düşük | Kodla aynı niyeti taşımalı |

## Doğrulama Yasası — ground-truth'a bak, ara-göstergeye değil

**Her doğrulama ground-truth'a bakmalıdır. Ara-gösterge kanıt değildir.**

| Ara-gösterge (kanıt DEĞİL) | Ground-truth (kanıt) |
|---|---|
| `exit` kodu, `$?`, "komut başarılı döndü" | İşin fiilen bıraktığı iz: dosya, kayıt, uzak SHA |
| CI job `conclusion` (`success`/`cancelled`) | Yayınlanan çıktının içeriği |
| Dashboard/rapor özet alanı (`rebalance: true`) | Ham state (`portfolio_F.json` history olayları) |
| `status`/`ok` bayrağı | Bayrağı üreten hesabın girdisi |
| Tarih alanı (`date`, gün çözünürlüğü) | Saat-hassas damga (`timestamp`) |
| "Testler geçti" | Testin o kod yolunu gerçekten çalıştırdığı (mutasyon: bozunca kızarıyor mu) |
| Yerel saat (`datetime.now()`) | Damganın yazıldığı eksen (UTC) |

**Neden yasa:** ara-gösterge, gerçeğin *proxy*'sidir; gerçek değişince proxy sessizce yanlışlanır ve **yanlış-güven** üretir. Bu, sessiz-bug'ın doğuş koşuludur — ve tespit edilemez, çünkü gösterge "iyi" demeye devam eder.

**2026-07-17/18 oturumunda aynı sınıf altı kez tekrarladı:**
1. **Rebalance-bug** — `REBAL_GUN=30` "işlem günü" sanıldı, fiilen "bar-index % 30" idi; dashboard özeti `rebalance: false` diyordu, gerçeği `portfolio_F.json` history'sindeki **sıfır rebalance olayı** söyledi. Canlı F 6 hafta hiç çalışmadı.
2. **TZ** — `datetime.now()` (yerel) ile UTC damgalar karşılaştırıldı; yaş +3h şişti. Ground-truth = damganın yazıldığı eksen.
3. **`$?`** — tarayıcı v1 doğrulamasında geçersiz exit-kodu testi.
4. **Push** — `push exit=0` yazdı ama push reddedilmişti (`$?` boru hattındaki `tail`'i okuyordu); gerçeği `origin/main`'in **fiili SHA'sı** söyledi.
5. **`market_data`** — `date` (gün, 00:00 sayılıyor) okundu, `timestamp` (18:40:40) mevcuttu; sahte "3 slot kaçtı" alarmı üretti.
6. **CI `cancelled`** — `conclusion` alanı "kırık" gibi okundu; gerçeği **yayınlanan sayfanın içeriği** söyledi (eşzamanlılık supersede'i, kırılma değil).

**Uygulama kuralları:**
- Bir şeyi "çalışıyor/düzeldi" demeden önce, işin **bıraktığı izi** oku — çalıştığını iddia eden alanı değil.
- Bir denetim yazarken sor: *bu kontrol neye bakıyor — gerçeğe mi, gerçeğin özetine mi?*
- Zamanlanmış her davranış için "son ne zaman çalıştı / gecikti mi" **ham kayıttan** doğrulanır.
- Detektör kurarken test çift yönlüdür: bozunca kırmızı **ve** sağlamken yeşil.

## Zaman Damgası Disiplini

Yukarıdaki yasanın *"yerel saat vs damganın yazıldığı eksen"* satırının **alan haritası**.
Bu sistemde damgalar **iki farklı eksende** yazılıyor ve çoğu **ofset taşımıyor** — yani
damga, bakan kişiye kendi eksenini söylemiyor.

| Alan | Eksen | Ofset | Not |
|---|---|---|---|
| `report_runs.sent_at` | TR | **VAR** (`+03:00`) | Tek açık alan. Ofseti silme, olduğu gibi parse et. |
| `dashboard.timestamp` | TR yerel | yok | |
| `content_sanity.updated_at` | UTC | yok | Kapının okuduğu alan. |
| `liveness.updated_at` | UTC | yok | |
| `watchdog.updated_at` | UTC | yok | |

Aynı koşum bu yüzden iki farklı saat gösterir. 2026-08-28 günici koşumu `dashboard`'a
`14:30:43` (TR), `content_sanity`'ye `11:30:52` (UTC) yazdı — **3 saat fark, tek koşum**.

**Kurallar**

- Her `timestamp` alanı **kendi eksen etiketiyle** parse edilir.
- Ofset **silinerek** veya string **kesilerek** (`[:19]`) yaş hesabı yapılmaz.
- **Negatif yaş görülürse önce denetim aracının hatası varsayılır**, verinin değil.
- Kapılar **UTC** okur (`shadow.py` → `run_utc_date`). TR günü dönmüşken UTC dönmemiş
  olabilir; **00:00–03:00 TR** penceresinde kapı **bir önceki günü** ölçer.

**Yaşanmış (2026-08-28):** sekiz maddelik read-only denetimde `dashboard.timestamp` UTC
sanıldı ve `-2.2h` **negatif yaş** üretildi. İmkânsız bir sayı olduğu için yakalandı; daha
küçük bir sapma sessizce geçerdi. Aynı gün `#0w`'nin (`Z` eksikliği) ve kapı tarih tuzağının
üçüncü örneği — sınıf: **eksen/ofset belirsizliği**.

## Commit Öncesi Kontrol

```powershell
git diff --check
python -m py_compile scripts\system_control_audit.py
python scripts\system_control_audit.py --write docs\state\system_control_audit.json
```

Üretim motoruna dokunan değişikliklerde ek olarak:

```powershell
python selftest.py
python run_backtest.py
```

## Commit Kapsamı

Her commit tek amaç taşımalıdır:

- kod değişikliği,
- state güncellemesi,
- dokümantasyon,
- veya bakım aracı.

Bunlar zorunlu olmadıkça karıştırılmaz. Özellikle strateji değişikliği ile
bağımlılık güncellemesi aynı commit'e konmaz.

## Terfi Kapısı

Yeni fikir önce defter veya shadow olur. Production'a yaklaşması için:

1. Olgun forward pencere üretir.
2. Veri kalitesi geçer.
3. Operasyon kapısı yeşil veya kabul edilebilir sarıdır.
4. Risk / drawdown kapıları ihlal edilmez.
5. F'e göre katkısı net ve tekrarlanabilir görünür.

## Geri Alma

Sorun çıktığında sırayla:

1. Son commit kapsamı okunur.
2. State mi kod mu ayrılır.
3. Kod sorunuysa küçük düzeltme commit'i yapılır.
4. State sorunuysa state yeniden üretilir.
5. Zorunlu olmadıkça force-push yapılmaz.

## Yasaklar

- Ölçüm defteri production state'i bozmaz.
- Panelde görünen her metrik tek kaynaktan gelmelidir.
- Public çıktıya lisanslı veya özel türev veri konmaz.
- Shadow sonuçları terfi kapısı olmadan işlem motoru sayılmaz.
