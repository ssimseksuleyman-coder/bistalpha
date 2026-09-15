"""Q1 — SINYAL KALITESI: listede gorunmek ILERI getiriyi ongoruyor mu?  (2026-09-13; C1 denetimi 2026-09-15)

Kurgu (dis elestiri, ACIK_ISLER "GERI CEKILDI"):
  * soru AYRI: burada yalniz ongoru; exit GEREKMEZ
  * sabit ufuk, event-time: +5 / +21 / +63 islem gunu; ufuktan genc sinyal SAYILMAZ (sag-sansur)
  * GIRIS = sinyal + ENTRY_LAG gun kapanisi (varsayilan 1: look-ahead yok)
  * ENDEKS-USTU: excess = hisse_getiri - XU100_getiri, ayni pencere
  * CA: tek-gun oran BIST limiti disinda (>1.5 / <0.67) -> CA gunu, getirisi 0'lanir; ISARETLENIR, ELENMEZ
  * dagilim: ceyrekler; isabet = excess > 0
  * kisit: tek rejim, korele varliklar, etkin n << n

DENETIM KILITLERI (C1):
  F2  'Ortak' = iki katmandaki EN ERKEN tarih (ortak_ilk)
  F4  sifir gozlemli ufuk da sayaclariyla YAZILIR (ufuk_ozeti her zaman dict dondurur)
  PROV cikti kaynak damgasi tasir: input_origin_sha (defterlerin okundugu SHA), tool_head_sha,
       tool_sha256 + tool_dirty, cache adi + SHA-256, generated_at (UTC Z), params;
       herhangi biri OLCULEMEZSE (git hatasi) RAISE — fail-open None YOK (inceleme #2)
  ic bosluk: pencere d0..d1 icinde tek NaN -> veri_eksik (yatay-fiyat tasima YOK)
  CA isareti: yalniz CA tarihi (d0, d1] icindeyse (hisse-geneli degil)
  import yan etkisi YOK (chdir main icinde)

Kaynaklar: local/feed_onbellek_<tarih>.pkl (borsapy uretim feed'i) + origin defterleri. Salt-okuma
(repo dosyasina yazmaz; ciktilar local/ altina).
"""
import glob
import hashlib
import io
import json
import os
import pickle
import subprocess
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HORIZONS = (5, 21, 63)
CA_UST, CA_ALT = 1.5, 0.67          # BIST gunluk limit +-10% -> bunun disi CA
ENTRY_LAG = int(os.environ.get("Q1_ENTRY_LAG", "1"))


def show(path, ref="origin/main"):
    raw = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=ROOT)
    if raw.returncode != 0:
        raise RuntimeError(f"git show {ref}:{path} rc={raw.returncode}: {raw.stderr.strip()[:160]}")
    return json.loads(raw.stdout)


def ilk_sinyaller(perf, layer):
    first = OrderedDict(); cnt = defaultdict(int)
    for sn in sorted(perf["snapshots"], key=lambda s: s["date"]):
        for e in sn.get("events") or []:
            if e.get("layer") == layer:
                cnt[e["ticker"]] += 1
                first.setdefault(e["ticker"], e["entry_date"])
    return [(t, d, cnt[t]) for t, d in first.items()]


def ilk_items(d):
    first = OrderedDict(); cnt = defaultdict(int)
    for sn in sorted(d["snapshots"], key=lambda s: s["date"]):
        for it in sn.get("items") or []:
            cnt[it["ticker"]] += 1
            first.setdefault(it["ticker"], it.get("entry_date") or sn["date"])
    return [(t, dd, cnt[t]) for t, dd in first.items()]


def ortak_ilk(T, Q):
    """Iki katmanda da gorulen hisseler; tarih = IKI KATMANDAKI EN ERKEN (F2: Q, T'yi ezmesin)."""
    tT = {t: (d, c) for t, d, c in T}; tQ = {t: (d, c) for t, d, c in Q}
    out = [(t, min(tT[t][0], tQ[t][0]), tT[t][1] + tQ[t][1]) for t in tT if t in tQ]
    return sorted(out, key=lambda x: x[1])


def ca_duzelt(prices):
    """Tek-gun oran limit disi -> CA gunu; o gunun getirisi 0 (CA gununden itibaren 1/r_ca ile
    olceklenir). NaN KORUNUR (C1 incelemesi #4): bosluk 'yatay fiyat' olarak tasinmaz; bosluklu
    pencere ufuk_ozeti'nde veri_eksik sayilir. Donus: (adj_prices, {ticker:[tarih,...]})"""
    r = prices / prices.shift(1)
    ca = ((r > CA_UST) | (r < CA_ALT)).fillna(False)
    faktor = (1.0 / r.where(ca, 1.0)).cumprod()          # CA olmayan gun 1.0; NaN oran CA sayilmaz
    adj = prices * faktor                                 # prices NaN ise adj NaN kalir
    isaret = {t: [d.strftime("%Y-%m-%d") for d in ca.index[ca[t]]] for t in prices.columns if ca[t].any()}
    return adj, isaret


def ceyrek(v):
    q = np.percentile(v, [25, 50, 75])
    return {"q1": round(float(q[0]), 2), "medyan": round(float(q[1]), 2), "q3": round(float(q[2]), 2),
            "ort": round(float(np.mean(v)), 2), "min": round(float(min(v)), 2), "max": round(float(max(v)), 2)}


def ufuk_ozeti(sig, h, adj, prices, bist, ca_isaret=None, entry_lag=None):
    """Bir liste x bir ufuk. HER ZAMAN dict dondurur (F4): n=0 ise excess=None, sayaclar dolu.
    sig: [(hisse, sinyal_tarihi_str, listeleme_sayisi)]. Donus: (ozet_dict, satir_listesi)."""
    lag = ENTRY_LAG if entry_lag is None else entry_lag
    ca_isaret = ca_isaret or {}
    pos = {d: i for i, d in enumerate(prices.index)}
    bpos = {d: i for i, d in enumerate(bist.index)}
    ex, ham, endeks, kayit = [], [], [], []
    eslesmeyen = sansur = veri_eksik = 0
    son_gun = prices.index[-1]
    for t, d, cnt in sig:
        dd = pd.Timestamp(d)
        if dd > son_gun:                                   # SAG SANSUR EN ONCE (inceleme #3/#4): seriden genc
            sansur += 1                                    # sinyal, hisse cache'te OLSUN OLMASIN 'sansurlu'
            continue                                       # (hisse uyeligi ancak degerlendirilebilir tarihte anlamli)
        if t not in adj.columns or dd not in pos:          # seri icinde ama hisse/bar yok = gercek eslesmezlik
            eslesmeyen += 1
            continue
        i = pos[dd] + lag
        if i + h >= len(prices.index):
            sansur += 1
            continue
        pencere = adj[t].iloc[i:i + h + 1]                # d0..d1 dahil; IC BOSLUK da veri_eksik (C1 #4)
        p0, p1 = pencere.iloc[0], pencere.iloc[-1]
        d0, d1 = prices.index[i], prices.index[i + h]
        if pencere.isna().any() or p0 <= 0 or d0 not in bpos or d1 not in bpos:
            veri_eksik += 1
            continue
        ca_pencerede = any(d0 < pd.Timestamp(x) <= d1 for x in ca_isaret.get(t, ()))   # CA yalniz (d0,d1] icinde
        b0, b1 = bist.iloc[bpos[d0]], bist.iloc[bpos[d1]]
        rs = (p1 / p0 - 1) * 100; rb = (b1 / b0 - 1) * 100
        ex.append(rs - rb); ham.append(rs); endeks.append(rb)
        kayit.append({"hisse": t, "sinyal": d, "listeleme": cnt, "ham": round(rs, 2), "xu100": round(rb, 2),
                      "excess": round(rs - rb, 2), "ca": ca_pencerede})
    ozet = {"n": len(ex), "toplam_sinyal": len(sig), "sansurlu": sansur, "eslesmeyen": eslesmeyen, "veri_eksik": veri_eksik,
            "excess": ceyrek(ex) if ex else None,
            "isabet_pct": round(100 * sum(1 for v in ex if v > 0) / len(ex), 1) if ex else None,
            "ham_medyan": round(float(np.median(ham)), 2) if ham else None,
            "xu100_medyan": round(float(np.median(endeks)), 2) if endeks else None,
            "ca_isaretli": sum(1 for k in kayit if k["ca"])}
    assert ozet["n"] + sansur + eslesmeyen + veri_eksik == len(sig), "sayim uzlasmadi (sessiz dusme)"
    return ozet, kayit


def _git_q1(*a):
    """FAIL-CLOSED (C1 incelemesi #3): git hatasi -> RAISE; None ile devam YOK."""
    r = subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)} rc={r.returncode}: {r.stderr.strip()[:160]} -> provenance OLCULEMEDI, islem durdu")
    return r.stdout


def _sha256(path):
    hsh = hashlib.sha256()
    with open(path, "rb") as fh:
        for blok in iter(lambda: fh.read(1 << 20), b""):
            hsh.update(blok)
    return hsh.hexdigest()


def provenance(cache_path, params, tool_path=None):
    """Kaynak damgasi (hepsi olculur, olculemeyen RAISE):
      input_origin_sha  = defterlerin okundugu origin/main commit'i (tam SHA; show() ayni SHA'yi kullanir)
      tool_head_sha     = aracin kostugu yerel HEAD;  tool_dirty = arac dosyasi HEAD'den farkli/izlenmiyor
      tool_sha256       = arac dosyasinin icerigi (dirty olsa da hangi kodun kostugu belli)
      cache_name/sha256 = onbellek; generated_at (UTC Z); params"""
    tool_path = tool_path or os.path.abspath(__file__)
    rel = os.path.relpath(tool_path, ROOT).replace(os.sep, "/")
    return {"input_origin_sha": _git_q1("rev-parse", "origin/main").strip(),
            "tool_head_sha": _git_q1("rev-parse", "HEAD").strip(),
            "tool_path": rel,
            "tool_sha256": _sha256(tool_path),
            "tool_dirty": bool(_git_q1("status", "--porcelain", "--", rel).strip()),
            "cache_name": os.path.basename(cache_path), "cache_sha256": _sha256(cache_path),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "params": dict(params)}


def main():
    os.chdir(ROOT)
    pk = sorted(glob.glob(os.path.join(ROOT, "local", "feed_onbellek_*.pkl")))
    if not pk:
        sys.exit("onbellek yok: once scripts/feed_onbellek_cek.py")
    cache = pickle.load(io.open(pk[-1], "rb")); data = cache["data"]
    prices = data["prices"].sort_index(); bist = data["bist"].sort_index()
    prov = provenance(pk[-1], {"ENTRY_LAG": ENTRY_LAG, "HORIZONS": list(HORIZONS), "CA_UST": CA_UST, "CA_ALT": CA_ALT})
    print(f"ENTRY_LAG={ENTRY_LAG} | onbellek {prov['cache_name']} sha256={prov['cache_sha256'][:12]} | "
          f"girdi origin {prov['input_origin_sha'][:12]} | arac HEAD {prov['tool_head_sha'][:12]} "
          f"dirty={prov['tool_dirty']} sha256={prov['tool_sha256'][:12]} | "
          f"prices {prices.shape} {prices.index[0].date()}..{prices.index[-1].date()} | bist {len(bist)}")
    adj, ca_isaret = ca_duzelt(prices)
    print(f"CA duzeltmesi: {len(ca_isaret)} hissede tek-gun limit-disi sicrama (>{CA_UST} / <{CA_ALT}) 0'landi")

    ref = prov["input_origin_sha"]                       # damgalanan SHA ile OKUNAN SHA ayni
    perf = show("docs/state/performance_ledger.json", ref)
    miss = show("docs/state/missed_opportunities.json", ref)
    opp = show("docs/state/opportunity_ledger.json", ref)
    T = ilk_sinyaller(perf, "transformation"); Q = ilk_sinyaller(perf, "quiet_accumulation")
    FT = ilk_sinyaller(perf, "F_top10"); M = ilk_items(miss); F = ilk_items(opp)
    listeler = [("Donusum Radari", T), ("Sessiz Birikim", Q), ("Kacirilanlar", M), ("Firsat", F),
                ("Ortak (Sessiz+Radar)", ortak_ilk(T, Q)), ("F top10 (secim)", FT)]

    sonuc = {"provenance": prov, "son_fiyat_gunu": str(prices.index[-1].date()), "horizons": list(HORIZONS),
             "ca_isaretli_hisse": ca_isaret, "listeler": {}}
    satirlar = []
    for ad, sig in listeler:
        L = {"n_sinyal": len(sig), "ufuk": {}}
        for h in HORIZONS:
            ozet, kayit = ufuk_ozeti(sig, h, adj, prices, bist, ca_isaret)
            L["ufuk"][h] = ozet                      # F4: n=0 olsa da yazilir
            satirlar += [{"liste": ad, "ufuk": h, **k} for k in kayit]
        sonuc["listeler"][ad] = L

    print(f"\n{'liste':22s} ufuk   n  sansur(esl,eksik) | excess q1 / MEDYAN / q3 | ort | isabet | ham med | XU100 med | CA")
    for ad, L in sonuc["listeler"].items():
        for h, u in L["ufuk"].items():
            e = u["excess"]
            if e is None:
                print(f"{ad:22s} +{h:<3d} {u['n']:>4d} {u['sansurlu']:>5d}({u['eslesmeyen']:>2d},{u['veri_eksik']:>2d}) | OLCULDU-BOS (sifir gozlem)")
            else:
                print(f"{ad:22s} +{h:<3d} {u['n']:>4d} {u['sansurlu']:>5d}({u['eslesmeyen']:>2d},{u['veri_eksik']:>2d}) | {e['q1']:>+6.1f} / {e['medyan']:>+6.1f} / {e['q3']:>+6.1f} | {e['ort']:>+6.1f} | %{u['isabet_pct']:<5.1f} | {u['ham_medyan']:>+6.1f} | {u['xu100_medyan']:>+6.1f} | {u['ca_isaretli']}")
    out_j = os.path.join(ROOT, "local", f"Q1_sinyal_kalitesi_lag{ENTRY_LAG}.json")
    out_c = os.path.join(ROOT, "local", f"Q1_sinyal_kalitesi_lag{ENTRY_LAG}.csv")
    io.open(out_j, "w", encoding="utf-8").write(json.dumps(sonuc, ensure_ascii=False, indent=1))
    pd.DataFrame(satirlar).to_csv(out_c, sep=";", index=False, encoding="utf-8-sig")
    print("\nKISIT: tek rejim (boga), korele varliklar, ortusen pencereler -> etkin n << n; anlamlilik iddiasi YOK.")
    print("yazildi:", out_j, "|", out_c)


if __name__ == "__main__":
    main()
