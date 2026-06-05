# BIST Alpha v1.2 + OMEGA — Kurulabilir Sistem

Momentum tabanlı BIST hisse seçim ve backtest sistemi. Doğrudan bilgisayara
kurulup çalıştırılabilir Python paketi.

> **UYARI:** Tüm sonuçlar tek rejim (2024-2026 boğa) verisinde. Gerçek ayı
> piyasası test edilmedi. Mütevazı başla, sektör cap=2 koru. Yatırım tavsiyesi değildir.

---

## 1. KURULUM

### Gereksinimler
- Python 3.10+ (3.12 önerilir)
- pip

### Adımlar
```bash
# 1. Bu klasörü bilgisayarına kopyala/aç
cd bist_alpha_system

# 2. Bağımlılıkları kur
pip install -r requirements.txt
#   (gerekirse: pip install -r requirements.txt --break-system-packages)

# 3. Veri dosyanı yerleştir
#    data/Tarihsel_Fiyat_Bilgileri.xlsx  (Sayfa1 sheet'i, 14 kolon)
```

### Klasör yapısı
```
bist_alpha_system/
├── bist_alpha/
│   ├── __init__.py
│   ├── config.py        # TÜM parametreler (düzenlemek için burası)
│   ├── data.py          # Excel yükleme
│   ├── signals.py       # akıllı para sinyalleri (CPR/Acc/Wick)
│   ├── strategy.py      # skorlama + seçim + koşullu vize
│   ├── backtest.py      # backtest motoru + metrikler
│   └── sectors.py       # hisse->sektör eşlemesi (128 hisse)
├── run_backtest.py      # ana çalıştırma scripti
├── requirements.txt
├── README.md
└── data/
    └── Tarihsel_Fiyat_Bilgileri.xlsx   # senin verin (buraya koy)
```

---

## 2. ÇALIŞTIRMA

```bash
# Varsayılan mod (config.MODE = "F") ile backtest
python run_backtest.py

# Belirli mod
python run_backtest.py --mode A    # baseline (equal weight)
python run_backtest.py --mode B    # SM-weighted lot (birincil aday)
python run_backtest.py --mode F    # B + koşullu vize (üst-opsiyon)

# Üç modu karşılaştır
python run_backtest.py --compare

# Slippage cezası ekle (canlı gerçekçilik)
python run_backtest.py --mode F --slippage 0.004    # %0.40/yön

# Son rebalance pick'lerini göster (sinyallerle)
python run_backtest.py --picks --mode F
```

### Beklenen çıktı (referans — tek rejim veri)
```
Mode   Getiri    MaxDD  Sharpe  Calmar  Stop
A      %289.4   %-6.61   ...    43.78
B      %268.8   %-8.14   ...    33.03
F      %301.1   %-5.54   ...    54.32
```

---

## 3. MODLAR

| Mod | Açıklama | Statü |
|-----|----------|-------|
| A | Baseline: eşit ağırlık, cap=2 | Control |
| B | A + SM-weighted lot çarpanları | Birincil aday (geniş tabanlı +%14) |
| F | B + 3. hisseye GÜÇLÜ BİRİKİM vizesi | Üst-opsiyon (ODINE-tipi fırsata bağlı) |

---

## 4. PARAMETRE DÜZENLEME

Tüm parametreler `bist_alpha/config.py` içinde:
- `TOP_N`, `REBAL_GUN`, `MOM_GUN` — çekirdek
- `SEKTOR_CAP = 2` — **DEĞİŞTİRME** (overfitting koruması)
- `DUAL_THRESHOLD = 25` — giriş eşiği
- `LOT_MULTIPLIERS` — Variant B çarpanları
- `SLIPPAGE_PER_SIDE` — operasyonel ceza
- `MODE` — varsayılan strateji

---

## 5. CANLI / SHADOW KULLANIM

Shadow mode için 3 paralel hesap (A/B/F) çalıştır:
- Operasyonel slippage: `--slippage 0.004` (%0.40/yön)
- Execution: rebalans günü kapanış seansı, kapanışa yakın (AOF değil)
- Sığ hisse limiti: pozisyon = günlük hacmin %5-10'u
- Go-live kriteri: challenger getiri VE Calmar'da A'yı geçmeli, DD %2'den
  fazla kötüleşmemeli, canlı sonuç in-sample yönü doğrulamalı

**Asıl sınav:** İlk -%10 BIST düşüşünde B ve F davranışı.

---

## 6. KANITLANMIŞ / REDDEDİLEN

**Kanıtlanmış:** Alpha gerçek (bootstrap %99.6 BIST'i yener), edge güçleniyor,
slippage-dayanıklı (%1.5 round-trip'e kadar), düşük korelasyon (efektif N ~5.3),
parametre-robust.

**Reddedilen:** Winner DNA scoring (split-sample fail), DNA çift-filtre (gereksiz),
rebal=25 (kötü), cap=3 blanket (overfit), ATR×4-5 (DD 2x), hacim/likidite filtre.

**Bilinmeyen:** Gerçek ayı piyasası, survivorship (dışarıdan), SM sinyal semantiği.

---

## 7. METODOLOJİK ALTIN KURALLAR

1. Tek değişken değiştir (kitchen-sink kombinasyon yapma)
2. Güzel hikaye + parlak full-sample ≠ edge. Split-sample/canlı kanıt iste.
3. Risk kontrolünü kaldırmak backtest'i şişirir, gerçek riski artırır.
4. Her parametre yerini YENİ bilgiyle hak etmeli (parsimoni).
5. Sektör cap=2'yi koru (ayı test edilene kadar).

İmza: Claude (OMEGA araştırma laboratuvarı) — 2026-05-19
