"""
firsat_ledger.py — IZOLE FIRSAT-DEFTERI. OLCUM/OGRENME araci, islem-acmaz.

DISIPLIN: "Firsat listesi OGRETIR; F motoru ISLEM ACAR." Bu defter F'in evren/sektor-cap
ELEME-mantiginin ne zaman alfa-biraktigini olcer (chase-sinyali DEGIL). F/daemon'a SIFIR dokunus:
dashboard.json'un URETTIGI firsatlar'i OKUR + yfinance. backtest.run(F) DEGISMEZ (yaprak-modul).

HINDSIGHT-KORUMASI (⭐FIRSAT-dersinin-tersine-kaymamak icin; kullanici-tasarimi):
  (1) SIMETRIK raporlama — her zaman DAGILIM (X%-cokta / Y%-kostu / MEDYAN), ASLA "en-iyi-FIRSAT"
      listesi (kazanan-secmek = hindsight-bias). Dagilim-gosterir, cherry-pick-etmez.
  (2) HUKUM-ESIGI onden-sabit (REVIEW_MED_21D + MIN_N_JUDGMENT) — birkac-guclu-FIRSAT (bogada-her-zaman-olur)
      hindsight-tetiklemesin. Esik-altinda hukum-YOK ("F-eleme-dogru-kalibre").
  (3) F-DOKUNULMAZ: defter F'e ASLA auto-feed-olmaz. En fazla olculu-gozden-gecirme ISARETI acar; o
      review KENDISI uc-kapidan (offset+confound+ayi) gecer. Diagnostik, chase-DEGIL.

LOOK-AHEAD-SIZ (forward-insa): her firsat ILK-gorunumde 8-alan FROZEN; 5g/21g forward olgunlasinca
dolar; F-top10-graduation sonraki kosularda guncellenir. Gecmis kararlar yeniden-hesaplanmaz.

8 ALAN: (1) giris-tarihi (2) giris-fiyati (3) 5g/21g getiri (4) F-top10'a-girdi-mi (graduation)
        (5) ust-fitil/hacim/kapanis-gucu (GUCLU_BIRIKIM 3-bileseni) (6) tepe-yakinligi (from_high)
        (7) katalizor-var-mi (catalyst_ledger cross-ref) (8) F-neden-almadi (evren/sektor-cap/outscored)

Kullanim: python firsat_ledger.py   (periyodik; dashboard-firsatlar dolunca birikir)
"""
import json, os, sys, warnings; warnings.filterwarnings('ignore')
import yfinance as yf, pandas as pd, numpy as np

REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "firsat_ledger.json")
DASH = os.path.join(REPO, "docs", "state", "dashboard.json")
CATALYST = os.path.join(REPO, "docs", "state", "catalyst_ledger.json")
WIN = (5, 21)            # forward-getiri pencereleri (islem-gunu)
SEKTOR_CAP = 2           # config.SEKTOR_CAP ile ayni ("KORU" sabiti; leaf-izolasyon icin hardcode)
MAX_AGE_FREEZE = 21      # bu-yastan eski firsat'i ILK-kez dondurme (backfill-yasagi = look-ahead)
# HINDSIGHT-KORUMASI: hukum-esigi ONDEN-SABIT (birkac-guclu-FIRSAT hindsight-tetiklemesin).
REVIEW_MED_21D = 15.0    # olgun-FIRSAT MEDYAN-21g > bu (VE n>=MIN) -> F-eleme OLCULU-gozden-gecirme ISARETI.
#   YARGI-CAGRISI (taban_readiness MAX_DRAG gibi): 15% konservatif (boga medyani sisirir; ideal F-relative).
MIN_N_JUDGMENT = 30      # hukum icin min olgun-gozlem (n<30 = "birkac-guclu-FIRSAT", hindsight, hukum-YOK).


def _load(p, default):
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: return default
    return default


def _save(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _dash():
    d = _load(DASH, {})
    firs = d.get("firsatlar") or (d.get("watchlists", {}) or {}).get("firsatlar") or []
    top10 = d.get("top10", [])
    date = d.get("date")
    return firs, top10, date


def _ohlcv(ticker):
    """1y OHLCV (frozen sinyaller + giris-fiyati icin). Doner df ya da None."""
    try:
        raw = yf.download(ticker + ".IS", period="1y", interval="1d",
                          auto_adjust=False, progress=False)
        if raw is None or raw.empty:
            return None
        return raw
    except Exception:
        return None


def _signals_from_ohlcv(df):
    """GUCLU_BIRIKIM 3-bileseni + tepe-yakinlik (signals.py formulleri, tek-hisse)."""
    try:
        c = df["Close"].dropna(); h = df["High"].reindex(c.index); l = df["Low"].reindex(c.index)
        v = df["Volume"].reindex(c.index)
        rng = (h - l).where((h - l) > 0, np.nan)
        cpr = ((c - l) / rng).rolling(10).mean().iloc[-1]                        # kapanis-gucu (aralikta-konum)
        ret = c.pct_change()
        upv = v.where(ret > 0, 0).rolling(20).sum().iloc[-1]
        dnv = v.where(ret < 0, 0).rolling(20).sum().iloc[-1]
        acc = float(upv / (dnv + 1e-9))                                          # hacim (up/down devir)
        aof = (h + l + c) / 3
        upper_body = np.maximum(aof.values, c.values)
        uw = pd.Series((h.values - upper_body) / rng.values, index=c.index).rolling(5).mean().iloc[-1]  # ust-fitil
        fh = float(c.iloc[-1] / c.tail(252).max() - 1) * 100                     # tepe-yakinligi (%)
        f = lambda x: round(float(x), 3) if x is not None and not pd.isna(x) else None
        return dict(cpr=f(cpr), acc=f(acc), upper_wick=f(uw), from_high_pct=round(fh, 1),
                    entry_price=round(float(c.iloc[-1]), 2))
    except Exception:
        return dict(cpr=None, acc=None, upper_wick=None, from_high_pct=None, entry_price=None)


def _catalyst_flag(ticker):
    """catalyst_ledger'da bu ticker icin olay var mi (fiyat-disi-eksen cross-ref)."""
    cl = _load(CATALYST, {})
    events = cl.get("events", []) if isinstance(cl, dict) else []
    hit = [e for e in events if str(e.get("ticker", "")).upper() == ticker.upper()]
    return dict(has=bool(hit), types=sorted({e.get("type") for e in hit})[:3]) if hit else dict(has=False, types=[])


def _approx_score(item):
    """dashboard firsatlar/top10 item'inin skor-vekili (m21~RS30 yaklasik). Siralama icin."""
    return 0.5 * (item.get("m252") or 0) + 0.3 * (item.get("m21") or 0) + 0.2 * (item.get("m5") or 0)


def _exclusion_reason(item, top10):
    """F NEDEN ALMADI — dashboard-top10'dan decompose (kismi; tam-evren universe-list ister)."""
    sec = item.get("sector")
    sec_ct = sum(1 for r in top10 if r.get("sector") == sec)
    if sec_ct >= SEKTOR_CAP:
        return "sektor-cap-dolu (%s: %d/%d)" % (sec, sec_ct, SEKTOR_CAP)
    fs = _approx_score(item)
    tops = [_approx_score(r) for r in top10]
    if tops and fs >= min(tops):
        return "evren-disi (skor-yeterli ama universe-filtreledi; ~kesin degil)"
    return "outscored (skor top10-cutoff-alti, sira>10)"


def freeze(item, top10, date):
    t = str(item.get("ticker"))
    oh = _ohlcv(t)
    sig = _signals_from_ohlcv(oh) if oh is not None else dict(cpr=None, acc=None, upper_wick=None, from_high_pct=None, entry_price=None)
    return dict(
        date=date, ticker=t, sector=item.get("sector"),
        entry_price=sig["entry_price"],
        m252=item.get("m252"), m21=item.get("m21"), m5=item.get("m5"),
        signals=dict(cpr=sig["cpr"], acc_ratio=sig["acc"], upper_wick=sig["upper_wick"]),   # (5)
        from_high_pct=sig["from_high_pct"],                                                  # (6)
        catalyst=_catalyst_flag(t),                                                          # (7)
        exclusion_reason=_exclusion_reason(item, top10),                                     # (8)
        fwd_5d=None, fwd_21d=None,                                                           # (3)
        graduated_to_top10=None,                                                            # (4)
    )


def record(ledger):
    firs, top10, date = _dash()
    if not date:
        return ledger, [], "dashboard tarih yok"
    have = {(e["ticker"], e["date"]) for e in ledger}
    # ayni-ticker onceden-kayitliysa (herhangi tarih) yeniden-dondurme (ilk-gorunum sabit)
    seen_ticker = {e["ticker"] for e in ledger}
    caught = []
    for it in firs:
        t = str(it.get("ticker"))
        if t in seen_ticker or (t, date) in have:
            continue
        caught.append(freeze(it, top10, date))
    ledger.extend(caught)
    return ledger, caught, ("firsatlar bos (dashboard henuz firsatlar-oncesi state)" if not firs else "%d yeni" % len(caught))


def evaluate(ledger):
    firs, top10, _ = _dash()
    cur_top = {str(r.get("ticker")) for r in top10}
    for rec in ledger:
        # (4) graduation: sonradan F-top10'a girdi mi
        if rec.get("graduated_to_top10") is None and rec["ticker"] in cur_top:
            rec["graduated_to_top10"] = _dash()[2]
        # (3) forward 5g/21g (olgunlasinca)
        if rec.get("fwd_21d") is not None or rec.get("entry_price") is None:
            continue
        d0 = pd.Timestamp(rec["date"]); age = (pd.Timestamp.now() - d0).days
        if age < WIN[0]:
            continue
        oh = _ohlcv(rec["ticker"])
        if oh is None: continue
        c = oh["Close"].dropna()
        pos = c.index.searchsorted(d0)
        if pos >= len(c): continue
        base = rec["entry_price"]
        for w, key in [(WIN[0], "fwd_5d"), (WIN[1], "fwd_21d")]:
            if age >= w and rec.get(key) is None and pos + w < len(c):
                r = (c.iloc[pos + w] / base - 1) * 100
                if abs(r) <= 80:   # corp-action artefakt-guard (roe_shadow dersi)
                    rec[key] = round(float(r), 2)
    return ledger


def _health(caught):
    ec = len(caught)
    pwr = "NA" if ec == 0 else sum(1 for r in caught if r["entry_price"] is not None)
    catn = sum(1 for r in caught if r["catalyst"]["has"])
    return "HEALTH: firsat_caught=%d with_price=%s with_catalyst=%d" % (ec, pwr, catn)


if __name__ == "__main__":
    ledger = _load(LEDGER, [])
    ledger, caught, note = record(ledger)
    ledger = evaluate(ledger)
    ledger.sort(key=lambda e: (e.get("date") or "", e.get("ticker") or ""))
    _save(LEDGER, ledger)

    print("=" * 66)
    print("FIRSAT DEFTERI (izole ogrenme-araci; F islem-acmaz, dokunmaz)")
    print("=" * 66)
    print("Kayit: %s" % note)
    for r in caught:
        print("  %s %-7s [%s] fiyat=%s | neden-almadi: %s | katalizor:%s"
              % (r["date"], r["ticker"], r["sector"], r["entry_price"],
                 r["exclusion_reason"], "VAR" if r["catalyst"]["has"] else "yok"))
    mat = [e for e in ledger if e.get("fwd_21d") is not None]
    grad = [e for e in ledger if e.get("graduated_to_top10")]
    print("\nDEFTER: %d firsat | olgun(21g): %d | F-top10'a-girdi: %d" % (len(ledger), len(mat), len(grad)))
    if mat:
        from collections import Counter
        r21 = sorted(e["fwd_21d"] for e in mat); n = len(r21)
        crashed = sum(1 for r in r21 if r < -5); ran = sum(1 for r in r21 if r > 5)
        flat = n - crashed - ran; med = float(np.median(r21))
        # (1) SIMETRIK DAGILIM — kazanan-SECMEZ (en-iyi-FIRSAT listesi YOK = hindsight-korumasi)
        print("  DAGILIM (21g, SIMETRIK): %d cokta(<-5%%) | %d duz | %d kostu(>+5%%) | MEDYAN %+.1f%%  (n=%d)"
              % (crashed, flat, ran, med, n))
        print("  F-neden-almadi kirilimi (olgun): %s" % dict(Counter(e["exclusion_reason"].split(" (")[0] for e in mat)))
        # (2) HUKUM-ESIGI ONDEN-SABIT — hindsight-tetiklemez
        if n >= MIN_N_JUDGMENT and med > REVIEW_MED_21D:
            print("  >> ESIK-ASILDI (medyan %+.1f > %+.1f, n=%d>=%d): F-eleme OLCULU-gozden-gecirme ISARETI"
                  " — defter TETIKLEMEZ; review KENDISI offset+confound+ayi UC-KAPIDAN gecer." % (med, REVIEW_MED_21D, n, MIN_N_JUDGMENT))
        else:
            print("  >> Esik-altinda (medyan %+.1f <= %+.1f ya da n<%d): F-eleme DOGRU-kalibre, HUKUM-YOK." % (med, REVIEW_MED_21D, MIN_N_JUDGMENT))
    print("\n" + _health(caught))
    print("Defter: %s (izole, daemon-commit yolunda DEGIL)" % os.path.relpath(LEDGER, REPO))
    print("Not: SIMETRIK-dagilim (kazanan-secmez) + onden-esik + F-DOKUNULMAZ. chase-DEGIL, eleme-diagnostigi. Prior: FIRSAT bull-artefakt.")
