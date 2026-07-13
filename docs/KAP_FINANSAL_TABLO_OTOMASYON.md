# KAP Finansal Tablo Otomasyonu

Bu katman temel kalite verisini olcer. Islem motoru degildir; F motoruna emir
uretmez.

## Veri Disiplini

- Birincil kaynak: KAP, sirket yatirimci iliskileri, BIST/SPK gibi resmi kaynaklar.
- Broker/X/Stockeys/Midas/Investing/Bigpara sadece aday veya alarm kaynagi olabilir.
- KAP/sirket resmi dogrulamasi olmadan temel kalite sinyali islem motoruna aktarilmaz.
- Ham finansal tablo extract'leri public repo'ya girmez.
- Local girdi klasoru: `local/kap_financials/`
- Eski tek dosya uyumlulugu: `local/kap_financial_actuals.json`
- Public defter: `docs/state/quality_ledger.json`

## Desteklenen Local Dosyalar

`local/kap_financials/` altinda JSON, CSV, XLSX veya XLS dosyasi okunur.

Ornek JSON:

```json
{
  "_meta": {
    "source": "KAP resmi finansal tablo extract",
    "extracted_at": "2026-07-13T18:00:00"
  },
  "companies": [
    {
      "ticker": "ASELS",
      "release_date": "2026-05-10",
      "period": "2026/03",
      "roe_pct": 32.4,
      "profit_yoy_pct": 68.1,
      "revenue_mio": 15234.0,
      "favok_mio": 4210.0,
      "net_debt_ebitda": 0.7,
      "surprise_pct": 12.5,
      "official_source_url": "https://www.kap.org.tr/..."
    }
  ]
}
```

CSV/XLSX dosyalarinda su basliklar otomatik eslenir:

- `ticker`, `kod`, `hisse`, `sembol`
- `release_date`, `tarih`, `bildirim_tarihi`, `kap_tarihi`
- `period`, `donem`
- `roe`, `roe_pct`, `ozkaynak_karliligi`
- `profit_yoy_pct`, `net_kar_yoy`, `kar_buyumesi`
- `profit_qoq_pct`, `net_kar_qoq`
- `revenue_mio`, `ciro`, `satis_geliri`, `hasila`
- `favok_mio`, `favok`, `ebitda`
- `net_debt_ebitda`, `net_borc_favok`
- `surprise_pct`, `beklenti_sapmasi`
- `official_source_url`, `kap_url`, `link`

## Olcumler

Her resmi finansal tablo olayi icin defter su alanlari tutar:

- aciklama tarihi
- giris tarihi ve giris fiyati
- 5g / 21g / 63g sonraki getiri
- ROE
- kar buyumesi
- ciro
- FAVOK
- net borc / FAVOK
- beklenti sapmasi
- eksik metrikler

## Kalite Bayraklari

- `roe_guclu`: ROE >= 20
- `kar_buyumesi`: kar buyumesi >= 20
- `beklenti_ustu`: beklenti sapmasi >= 5
- `hedef_yukari`: hedef fiyat degisimi >= 5

Bu bayraklar tek basina islem actirmaz. Olgun kohortlarda 5/21/63 gun sonucu
pozitif ve tutarliysa yeni shadow hipotezi acilabilir.

## Terfi Kapisi

Bir temel kalite filtresi ancak su sira ile ilerler:

1. Local resmi veri deftere girer.
2. 5/21/63 gun kohortlari olgunlasir.
3. En az 20 adet 21g olgun olay birikir.
4. Ortalama 21g getiri pozitif ve isabet orani en az %50 olur.
5. F motoruna dokunmadan yeni shadow hesap veya izleme karti acilir.
6. Canli ileri testte de calismazsa reddedilir; calisirsa terfi tartisilir.

## Lisans ve Gizlilik

Deniz/Tera/ICBC/Bizim gibi araci kurum bultenlerinden turetilmis tablo public
repo'ya konmaz. Resmi kurum ve sirketlerin kendi acikladigi veriler
yeniden-KAP/sirket kaynagindan dogrulanarak local extract olarak kullanilir.
