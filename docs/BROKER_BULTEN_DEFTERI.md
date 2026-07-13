# Broker Bulten Defteri

Bu katman Tera, ICBC, Bizim Menkul, Deniz ve benzeri araci kurum bultenlerini
olcer. Islem motoru degildir; F motoruna emir uretmez.

## Disiplin

- Ham bulten PDF/metin/hedef fiyat/not public repo'ya girmez.
- Local girdi klasoru: `local/broker_bulletins/`
- Private detay defteri: `local/broker_bulletin_ledger_private.json`
- Public ozet: `docs/state/broker_bulletin_ledger.json`
- Public ozette tekil broker cagrisi, hedef fiyat, not ve ham metin yoktur.
- KAP/sirket/BIST resmi teyidi olmadan hicbir broker sinyali terfi etmez.

## Local Girdi Semasi

`local/broker_bulletins/tera_20260713.json` gibi bir dosya:

```json
{
  "events": [
    {
      "source_id": "tera",
      "date": "2026-07-13",
      "type": "suggestion_list",
      "ticker": "ASELS",
      "action": "AL",
      "reason_type": "model_portfoy",
      "target_price": 0,
      "official_confirmed": false,
      "kap_confirmed": false,
      "note": "Local-only not. Public dashboard'a cikmaz."
    }
  ]
}
```

Alanlar:

- `source_id`: `tera`, `icbc`, `bizim`, `deniz` veya yeni kaynak.
- `date`: bulten/olay tarihi.
- `type`: `suggestion_list`, `market_outlook`, `company_report`, `model_portfolio`, `target_revision`.
- `ticker`: BIST kodu.
- `action`: `AL`, `TUT`, `SAT`, `EKLE`, `CIKAR`, `IZLE`.
- `reason_type`: `bilanco`, `degerleme`, `temettu`, `makro`, `sektor`, `sirket_haberi`, `teknik`.
- `target_price`, `previous_target_price`, `upside_pct`, `note`: private/local kalir.
- `official_confirmed` / `kap_confirmed`: resmi dogrulama bayragi.

## Olcumler

Her olay icin private defterde tutulur:

- giris tarihi ve fiyati
- 1g / 5g / 21g / 63g getiri
- mevcut getiri
- F Top10 / F pozisyon kesisimi
- kaynak skoru
- resmi teyit bayragi

Public panelde yalniz kaynak/type bazli toplu sonuc gosterilir:

- olay sayisi
- 5g / 21g / 63g olgun olay
- ortalama getiri
- isabet orani
- karar

## Kaynak Puani

- KAP / BIST / SPK / sirket resmi: `3`
- Broker / data vendor: `2`
- X / sosyal yorum: `1`
- Duyum / hedef tek basina: `0`

Broker puani `2` oldugu icin, iyi performans gosterirse bile resmi teyit aranmadan
F motoruna aktarilmaz.

## Terfi Kapisi

Bir kaynak veya bulten tipi sadece su sartlarla "izleme degeri var" seviyesine gelir:

- 21 gun olgun olay sayisi en az `20`
- 21g ortalama getiri pozitif
- 21g isabet orani en az `%50`
- KAP/sirket/BIST resmi teyit sureci bagli

Bu kosullar saglansa bile F motoru otomatik degismez; sadece insan onayli yeni
shadow hipotezi acilir.
