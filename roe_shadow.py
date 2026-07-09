"""
roe_shadow.py — IZOLE ROE-SAPMA olcum-araci (G3). OLCUM-ARACI, canli-hesap DEGIL.

F'e / portfoylere / dashboard.json'a / shadow.py'ye SIFIR dokunus. Sadece portfolio_F.json'i
OKUR + yfinance. backtest.run(F) DEGISMEZ (regresyon-none, taban-guard gibi).

AMAC: F'in momentum-pick'lerine ROE-filtresi (yuksek-ROE alt-kume) uygulamanin CANLI forward
katkisini olcmek. G3 = F'i AYNALAMAZ (yoksa sinyal olculmez) -> ROE-filtreli SAPMA. G3-vs-F
forward-getiri farki = ROE-filtre'nin katkisi. Yon OLCUMDEN turetildi (ROE +0.16 = yuksek-iyi,
ZAYIF-sinyal, n=67; G3 forward gozlem biriktirerek firm-up eder — simdiden hukum YOK).

LOOK-AHEAD-SIZ (kaynak-PIT'liginden degil, FORWARD-INSADAN): forward-only, backfill YOK. Her
rebalansta O AN yfinance-guncel-ROE'yle karar + DONDUR (frozen). Gecmis kararlar current-ROE ile
yeniden hesaplanmaz. Deniz-PIT'e gerek yok (Deniz zaten teknik, ROE vermez); kaynak yfinance-guncel.

KONSANTRASYON-KORUMASI: medyan-split AMA MIN_G3_PICKS taban -> G3 asiri-konsantre olup "edge"i
ROE yerine konsantrasyondan almasin (RSI-confound dersi). n_f vs n_g3 ledger'da (izlenir).

Kullanim: python roe_shadow.py   (her paper-rebalans sonrasi; forward-getiri olgunlasinca dolar)
"""
import json, os, warnings; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd, numpy as np

REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "roe_shadow_ledger.json")
MIN_G3_PICKS = 5        # az-pick taban (konsantrasyon-confound korumasi)
HORIZON_DAYS = 21       # forward-getiri ufku (~1 rebalans)


def _load(p, default):
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: return default
    return default


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def f_current_picks():
    """F'in guncel portfoyu (canli holdings). OKUR, dokunmaz."""
    s = json.load(open(os.path.join(REPO, "portfolios", "portfolio_F.json"), encoding="utf-8"))
    picks = list(s.get("positions", {}).keys())
    dt = s.get("history", [])[-1]["date"] if s.get("history") else None
    return picks, dt


def frozen_roe(tickers):
    """O ANKI yfinance-guncel ROE (frozen — karar-aninda dondurulur, sonra re-fetch yok)."""
    roe = {}
    for t in tickers:
        try: roe[t] = yf.Ticker(t + ".IS").info.get("returnOnEquity")
        except Exception: roe[t] = None
    return roe


def roe_filter(picks, roe):
    """Medyan-split + az-pick taban. Doner: (g3_picks, not)."""
    valid = {t: r for t, r in roe.items() if r is not None}
    if len(valid) < 2:
        return list(picks), "roe-yok -> filtre-yok (F ile ozdes, sinyal-yok kayit)"
    med = float(np.median(list(valid.values())))
    kept = [t for t in picks if valid.get(t, med - 1e9) >= med]   # yuksek-ROE yari
    note = "medyan-split (ROE>=%.3f)" % med
    if len(kept) < MIN_G3_PICKS and len(valid) >= 1:              # AZ-PICK KORUMASI
        kept = [t for t, _ in sorted(valid.items(), key=lambda x: -x[1])[:MIN_G3_PICKS]]
        note = "az-pick-floor: en yuksek-ROE %d (medyan-split %d biraktirdi)" % (MIN_G3_PICKS, sum(1 for t in picks if valid.get(t, med-1e9) >= med))
    return kept, note


def record(ledger):
    """Guncel rebalans kararini DONDUR (look-ahead-siz: sadece bugunku ROE)."""
    picks, dt = f_current_picks()
    if not picks or dt is None:
        return ledger, "F pozisyon/tarih yok"
    if any(e.get("date") == dt for e in ledger):
        return ledger, "zaten-kayitli (%s)" % dt
    roe = frozen_roe(picks)
    g3, note = roe_filter(picks, roe)
    rec = dict(date=dt, f_picks=picks,
               roe={t: (round(r, 4) if r is not None else None) for t, r in roe.items()},
               g3_picks=g3, n_f=len(picks), n_g3=len(g3), filter_note=note, fwd=None)
    ledger.append(rec)
    return ledger, rec


def evaluate(ledger):
    """Olgunlasan kararlar icin forward-getiri (F-all vs G3, esit-agirlik). Frozen kararlar."""
    for rec in ledger:
        if rec.get("fwd") is not None:
            continue
        d0 = pd.Timestamp(rec["date"])
        if (pd.Timestamp.now() - d0).days < HORIZON_DAYS:
            continue   # olgunlasmamis -> bekle (look-ahead-siz)
        tics = sorted(set(rec["f_picks"] + rec["g3_picks"]))
        try:
            raw = yf.download([t + ".IS" for t in tics],
                              start=(d0 - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
                              end=(d0 + pd.Timedelta(days=HORIZON_DAYS + 7)).strftime("%Y-%m-%d"),
                              interval="1d", auto_adjust=True, progress=False, group_by="column")
            cl = raw["Close"].copy(); cl.columns = [c.replace(".IS", "") for c in cl.columns]
        except Exception:
            continue

        def basket_ret(names):
            rs = []
            for t in names:
                if t in cl.columns:
                    s = cl[t].dropna()
                    if len(s) >= 2:
                        r = (s.iloc[min(HORIZON_DAYS, len(s) - 1)] / s.iloc[0] - 1) * 100
                        if abs(r) <= 60:  # >±%60 = corp-action artefakti, atla (taban-guard dersi)
                            rs.append(r)
            return float(np.mean(rs)) if rs else None

        f_ret = basket_ret(rec["f_picks"]); g3_ret = basket_ret(rec["g3_picks"])
        if f_ret is not None and g3_ret is not None:
            rec["fwd"] = dict(f_ret=round(f_ret, 2), g3_ret=round(g3_ret, 2),
                              edge=round(g3_ret - f_ret, 2))
    return ledger


if __name__ == "__main__":
    ledger = _load(LEDGER, [])
    ledger, rec = record(ledger)
    ledger = evaluate(ledger)
    ledger.sort(key=lambda e: e.get("date") or "")
    _save(LEDGER, ledger)

    print("=" * 62)
    print("ROE-SAPMA OLCUM DEFTERI (G3, izole; F'e/canliya DOKUNMAZ)")
    print("=" * 62)
    if isinstance(rec, dict):
        print("YENI KARAR (frozen): %s" % rec["date"])
        print("  F pick (%d): %s" % (rec["n_f"], rec["f_picks"]))
        print("  ROE (guncel, frozen): %s" % {t: rec["roe"][t] for t in rec["f_picks"]})
        print("  G3 pick (%d, ROE-filtreli): %s" % (rec["n_g3"], rec["g3_picks"]))
        print("  filtre: %s" % rec["filter_note"])
    else:
        print("Kayit: %s" % rec)
    matured = [e for e in ledger if e.get("fwd")]
    print("\nOLGUNLASAN KARARLAR (G3-vs-F forward, %dg):" % HORIZON_DAYS)
    if matured:
        edges = [e["fwd"]["edge"] for e in matured]
        for e in matured:
            print("  %s: F %+.2f%% | G3 %+.2f%% | edge %+.2fpp (n_g3=%d/%d)"
                  % (e["date"], e["fwd"]["f_ret"], e["fwd"]["g3_ret"], e["fwd"]["edge"], e["n_g3"], e["n_f"]))
        print("  -> ROE-filtre ort edge: %+.2fpp (n=%d karar). %s"
              % (np.mean(edges), len(edges),
                 "cok az gozlem, hukum YOK" if len(edges) < 5 else "biriktikce firm-up"))
    else:
        print("  (henuz olgunlasan karar yok — forward-getiri %dg sonra dolar; look-ahead-siz)" % HORIZON_DAYS)
    print("\nDefter: %s (izole, daemon-commit yolunda DEGIL)" % os.path.relpath(LEDGER, REPO))
    print("Not: ROE zayif-sinyal (+0.16, n=67); G3 firm-up icin biriktirir, simdiden hukum yok.")
