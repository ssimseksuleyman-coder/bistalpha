# Akis ve Geri Alim Defteri

Bu katman takas bilgileri, yabanci giris/cikis ve pay geri alim olaylarini
olcer. Islem motoru degildir; F motoruna emir uretmez.

## Kaynak Sirasi

1. **KAP geri alim bildirimleri**: resmi ve public kullanima uygundur.
2. **Resmi/kurumsal yabanci akim verileri**: piyasa-genel rejim filtresi olarak
   olculur; hisse secmez.
3. **Hisse bazli yabanci/takas verisi**: cogunlukla lisansli veri olabilir.
   Sadece local-private dosya olarak okunur; ham saklama/takas detaylari public
   repo'ya yazilmaz.

## Local Girdi

Klasor: `local/flow_inputs/`

Desteklenen dosyalar: JSON, CSV, XLSX, XLS.

Ornek JSON:

```json
{
  "_meta": {
    "source": "licensed local takas export",
    "source_tier": "local_private",
    "extracted_at": "2026-07-13T18:30:00"
  },
  "events": [
    {
      "date": "2026-07-13",
      "ticker": "ASELS",
      "type": "foreign_flow",
      "signal": "10g_yabanci_giris",
      "foreign_net_value": 125000000,
      "foreign_ownership_pct": 38.4
    },
    {
      "date": "2026-07-13",
      "ticker": "KCHOL",
      "type": "takas",
      "signal": "kurumsal_takas_artisi",
      "takas_change_pct": 1.8,
      "custody_concentration_pct": 42.0
    }
  ]
}
```

CSV/XLSX basliklari otomatik eslenir:

- `ticker`, `kod`, `hisse`, `sembol`
- `date`, `tarih`, `islem_tarihi`, `bildirim_tarihi`
- `type`, `tur`, `kategori`
- `signal`, `sinyal`, `yon`
- `foreign_net_value`, `yabanci_net_tutar`, `yabanci_net_tl`
- `foreign_net_lot`, `yabanci_net_lot`
- `foreign_ownership_pct`, `yabanci_payi`, `yabanci_orani`
- `takas_change_pct`, `takas_degisim`, `saklama_degisim`
- `custody_concentration_pct`, `takas_yogunlasma`

## Olcum

Her olay icin defter sunlari tutar:

- olay tarihi
- giris tarihi ve fiyati
- mevcut getiri
- 5g / 21g / 63g getiri
- olay tipi: `geri_alim`, `foreign_flow`, `takas`
- kaynak tipi ve puani

## Disiplin

- KAP geri alim: resmi katalizor, ama tek basina islem actirmaz.
- Yabanci akim: hisse secici degil; rejim ve teyit etiketi olarak olculur.
- Takas: lisansli/ham detay local kalir; public panel sadece toplu metrik gosterir.
- En az 20 adet 21g olgun olay olmadan karar verilmez.
- 21g ortalama getiri pozitif ve isabet orani >= %50 degilse terfi yoktur.
- Terfi olsa bile F motoru otomatik degismez; once shadow hipotezi acilir.
