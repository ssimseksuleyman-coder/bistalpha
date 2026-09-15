"""IBS TEPKI RADARI — EKSIK OLAN KIYAS (2026-09-12).

`ibs_reversal_ledger.py` (2026-07-06) ileri getiriyi MUTLAK olcuyor: 10g +2.09%,
isabet %58. Bogada evren zaten yukseliyorsa bu kenar DEGIL. Firsat defterinin kendi
kurali da ayni seyi soyluyor: review_policy.absolute_return_gate_allowed = False.

Bu script ayni olaylar icin AYNI GUN evren ortalamasini hesaplar ve farki (alpha)
verir. F motoruna, portfoylere, panele DOKUNMAZ; yalniz reports/ altina yazar.

YONTEM
  - olaylar: reports/ibs_reversal_backtest.json (yeniden uretilmez, oldugu gibi okunur)
  - evren: ayni tarihte fiyati olan tum hisseler (backtest'in kendi evreni degil —
    onu uretmek feed'in dinamik evrenini gerektirir; burada FIYATI OLAN evreni
    kullaniyorum; fark ACIKCA raporlanir, vekil oldugu yazilir)
  - fwd_Ng = (P[t+N] / P[t] - 1) * 100, olayla BIREBIR ayni formul
  - alpha = olay_fwd - ayni_gun_evren_ortalamasi_fwd
  - ayrica: her olay gunu icin evren medyani (aykiri-dayanikli ikinci olcum)
"""
import io
import json
import os
import statistics
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from bist_alpha import datafeed  # noqa: E402

IN = os.path.join(REPO, "reports", "ibs_reversal_backtest.json")
OUT = os.path.join(REPO, "reports", "ibs_benchmark_2026-09-12.json")
HORIZONS = (1, 3, 5, 10)


def ufuk_alpha(olaylar, k, idx, ev_ort, ev_med, ev_n, n_hisse, n_olay):
    """Bir ufuk icin alpha ozeti. HER ZAMAN dict (C1 incelemesi #6): eslesen olay yoksa n=0 ile YAZILIR,
    atlanmaz. evren_n (o gun fiyati olan hisse sayisi: min/medyan/max) YAZILIR. t notu VERIDEN turetilir."""
    alp_ort, alp_med, olay_v, ev_v, n_v = [], [], [], [], []
    for e in olaylar:
        v = e.get(k)
        i = idx.get(str(e["signal_date"])[:10])
        if v is None or i is None:
            continue
        eo = ev_ort.iloc[i]
        em = ev_med.iloc[i]
        if pd.isna(eo):
            continue
        olay_v.append(v); ev_v.append(float(eo)); n_v.append(int(ev_n.iloc[i]))
        alp_ort.append(v - float(eo))
        if not pd.isna(em):
            alp_med.append(v - float(em))
    n = len(alp_ort)
    t_notu = f"olaylar bagimsiz DEGIL ({n_hisse} hissede {n_olay} olay, ayni gun kumelenme) -> t ABARTILI"
    if n == 0:
        return {"n": 0, "olay_ort": None, "evren_ort": None, "alpha_ort": None, "alpha_medyan": None,
                "alpha_pozitif_pct": None, "alpha_vs_evren_medyan_ort": None, "t_stat_naif": None,
                "evren_n": None, "t_notu": t_notu}
    sd = statistics.pstdev(alp_ort) or 1e-9
    t = (sum(alp_ort) / n) / (sd / (n ** 0.5))
    return {
        "n": n,
        "olay_ort": round(sum(olay_v) / n, 3),
        "evren_ort": round(sum(ev_v) / n, 3),
        "alpha_ort": round(sum(alp_ort) / n, 3),
        "alpha_medyan": round(statistics.median(alp_ort), 3),
        "alpha_pozitif_pct": round(100 * sum(1 for x in alp_ort if x > 0) / n, 1),
        "alpha_vs_evren_medyan_ort": round(sum(alp_med) / len(alp_med), 3) if alp_med else None,
        "t_stat_naif": round(t, 2),
        "evren_n": {"min": min(n_v), "medyan": int(statistics.median(n_v)), "max": max(n_v)},
        "t_notu": t_notu,
    }


def main():
    os.chdir(REPO)
    rapor = json.load(io.open(IN, encoding="utf-8"))
    olaylar = rapor["events"]
    print(f"olay: {len(olaylar)} | tekil hisse: {len(set(e['ticker'] for e in olaylar))} | "
          f"tarih {rapor['date_range']['first_signal']} .. {rapor['date_range']['last_signal']}")

    feed = datafeed.get_feed("file")
    data = feed.get_latest()
    prices = data["prices"].sort_index()
    print(f"feed: {prices.shape[0]} gun x {prices.shape[1]} hisse | "
          f"{prices.index[0].date()} .. {prices.index[-1].date()}")

    # Evren ileri getirisi: her gun, fiyati olan tum hisseler icin fwd_N
    idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(prices.index)}
    evren_ort, evren_med, evren_n = {}, {}, {}
    for N in HORIZONS:
        fwd = (prices.shift(-N) / prices - 1.0) * 100.0
        evren_ort[N] = fwd.mean(axis=1)
        evren_med[N] = fwd.median(axis=1)
        evren_n[N] = fwd.notna().sum(axis=1)

    sonuc = {"kaynak": os.path.relpath(IN, REPO).replace(os.sep, "/"),   # F1: repo-goreli, kisisel yol YOK
             "yontem": "olay fwd - ayni gun evren ortalamasi (fiyati olan tum hisseler)",
             "uyari": "evren VEKIL: backtest'in dinamik evreni degil, fiyati olan tum hisseler",
             "n_olay": len(olaylar), "n_hisse": len(set(e["ticker"] for e in olaylar)), "horizons": {}}
    for N in HORIZONS:
        k = f"fwd_{N}d_pct"
        sonuc["horizons"][k] = ufuk_alpha(olaylar, k, idx, evren_ort[N], evren_med[N], evren_n[N],
                                          n_hisse=sonuc["n_hisse"], n_olay=len(olaylar))
        h = sonuc["horizons"][k]
        if h["n"] == 0:
            print(f"  {k}: n=0 OLCULDU-BOS (eslesen olay yok)")
        else:
            print(f"  {k}: n={h['n']} | olay {h['olay_ort']:+.2f}% | evren {h['evren_ort']:+.2f}% | "
                  f"ALPHA {h['alpha_ort']:+.2f}% (medyan {h['alpha_medyan']:+.2f}%, pozitif %{h['alpha_pozitif_pct']}) | "
                  f"t~{h['t_stat_naif']} | evren_n {h['evren_n']}")

    # Rejim ayrimi: yil bazli (kaba ama ayri pencere)
    sonuc["yil_bazli"] = {}
    for N in (5, 10):
        k = f"fwd_{N}d_pct"
        per = {}
        for e in olaylar:
            v = e.get(k); i = idx.get(str(e["signal_date"])[:10])
            if v is None or i is None:
                continue
            eo = evren_ort[N].iloc[i]
            if pd.isna(eo):
                continue
            yil = str(e["signal_date"])[:4]
            per.setdefault(yil, []).append(v - float(eo))
        sonuc["yil_bazli"][k] = {y: {"n": len(a), "alpha_ort": round(sum(a) / len(a), 3),
                                     "alpha_pozitif_pct": round(100 * sum(1 for x in a if x > 0) / len(a), 1)}
                                 for y, a in sorted(per.items())}
        print(f"  {k} yil bazli: " + " | ".join(
            f"{y} n={d['n']} alpha {d['alpha_ort']:+.2f}%" for y, d in sorted(sonuc['yil_bazli'][k].items())))

    io.open(OUT, "w", encoding="utf-8").write(json.dumps(sonuc, ensure_ascii=False, indent=2))
    print("yazildi:", OUT)


if __name__ == "__main__":
    main()
