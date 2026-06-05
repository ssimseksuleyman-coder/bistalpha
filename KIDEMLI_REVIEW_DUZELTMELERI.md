# KIDEMLİ REVIEW — 5 Tespit ve Düzeltmeleri
**Tarih:** 2026-05-21

Kıdemli mühendis incelemesinde bulunan 5 gerçek sorun ve kod düzeltmeleri.

## TESPİT 1 — Veri Sağlayıcı Min/Max Anomali İğneleri
**Sorun:** yfinance vb. tek hatalı tick ile High/Low'u bozar. CPR/wick sinyalleri
Min/Max'a bağlı → bozuk iğne = çöp sinyal.
**Düzeltme:** `signals.sanitize_ohlc()` — günlük aralık (max/min-1) > %25 ise
anomali kabul edip kapanışa göre makul sınıra çeker (BIST ±%10-20 limit bilgisi).
compute_signals otomatik çağırır. Test: enjekte edilen 3x spike yakalandı.

## TESPİT 2 — Kapanış/TWAP Penceresinde Likidite Sıkışması
**Sorun:** Kapanışta yürütüm önerdik ama kapanış seansı likiditesi gün-içinden az;
sığ hisselerde sıkışma (kademe çizme).
**Düzeltme:** `levels.close_window_liquidity_ok()` — kapanış penceresi ~%15 günlük
hacim, pozisyon bunun %10'unu aşarsa uyarır. Hisse analizine bağlandı.
NOT: Hacim kolonu birimi kesin değil — eşikleri (close_fraction, max_participation)
canlıda kalibre et.

## TESPİT 3 — SQLite WAL vs GitHub Actions Kalıcılık Çatışması
**Sorun:** SQLite WAL kullanılsaydı, -wal/-shm sidecar dosyaları + ephemeral runner
+ git-commit kalıcılığı çatışırdı.
**Çözüm (kasıtlı tasarım):** SQLite KULLANMIYORUZ. Portföy state = JSON. Üstelik
artık ATOMİK yazım (geçici dosya → os.replace + fsync). Runner görev ortasında
ölse bile dosya ya eski ya yeni — asla yarım/bozuk. Git-dostu + güvenli.

## TESPİT 4 — selftest.py Statik Tarih/Değer Sapması
**Sorun:** selftest A/B/F getirilerini sabit aralıkta (150-185 vb.) kontrol ediyordu;
bu sadece gömülü 2024-2026 verisi için geçerli. Canlı/yahoo veride yanlış FAIL.
**Düzeltme:** Sabit aralık SADECE DATA_SOURCE=file iken denetlenir. Canlı veride
yalnızca "makul aralık (-50..+500)" kontrolü. Tarih bağımlı sabit varsayım kaldırıldı.

## TESPİT 5 — selftest.py Truncated/Eksik Kontroller
**Sorun:** Docstring "CLI'lar çalışıyor mu" diyordu ama CLI hiç çalıştırılmıyordu;
bölüm numaraları kaymıştı.
**Düzeltme:** Bölüm 10 eklendi — run_backtest/analyze_stock/daemon CLI'ları
subprocess ile GERÇEKTEN çalıştırılıp çıkış kodu denetlenir. Docstring 10 kontrole
hizalandı.

## SONUÇ
5 tespit de kapatıldı. `python selftest.py` artık 10 bölüm denetler ve hepsi geçer.
