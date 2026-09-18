"""
taban_readiness.py - IZOLE gercek-para-hazirlik defteri. CANLI STATE'E DOKUNMAZ.

Ne yapar: canli F stop'larini taban-lock-farkinda duzeltir (floor_lock_accounting), taban-risk
metrikleri + OLCULEBILIR gecis-kriteri uretir, reports/taban_honest_ledger.json'a yazar
(dashboard.json'a DEGIL -> izole, risksiz). Sadece portfolio_F.json'i OKUR + fiyat kaynagi.
Amac: paper penceresinde iki soruyu SEZGIYLE degil KANITLA yanitlamak:
  1. "Kagit sayi ne kadar iyimserdi?" -> booked vs taban-honest (gap)
  2. "Gercek-paraya hazir miyiz?" -> birikimli, cok-pencere kriter (asagida)

GECIS KRITERI (onden sabit, sezgi degil):
  C1 Yeterli kanit : >=5 bagimsiz pencere (tek/uc pencere yetmez)
  C2 Kumulatif+drag: (a) KUMULATIF taban-honest low > 0 (bireysel dusus-penceresine izin;
                     "her pencere pozitif" momentum'u paper'da hapseder) + (b) pencere-basi
                     taban-drag <= 8pp (taban-lock SURPRIZINI yakalar, piyasa-dususunu degil)
  C3 Modellenmis kuyruk: max ardisik-kilit <= 5 gun (olctugumuz kuyrugun icinde, surpriz yok)
  C4 Karakterize   : taban_ratio pencereler-arasi tutarli (asiri spike raporlanir)
  HAZIR ancak C1 & C2 & C3 & C4. Aksi: "N pencere daha gerek".

2026-09-18 YENIDEN KURULUM (olcum: 09-01 penceresinde 10 stop'un 9'u taban gunu; kagit -15.5 /
taban-durust -35.9; arac 07-08'den beri kosmamisti):
  * PENCERE = REBALANS DONGUSU (initial_entry/rebalance sinirlari), "iki kosum arasi" DEGIL.
    Defter her seferinde portfoy gecmisinden YENIDEN kurulur (deterministik; eski 'kosum arasi'
    kayitlar yerine gecer). Stoplar tarihe gore atanir (gecmisin sirasi degil: 07-27/28 sira bozuk).
  * DELIK = veri_eksik: stop gunu fiyat serisinde YOKSA sonraki bara KAYDIRILMAZ (eski searchsorted
    IEYHO 09-17 -> 09-18: "-19%, kilit 0" uydurmasi); stop sayilir, etiketlenir, oran/drag disi.
    Stop sonrasi seride referans (XU100) gunu eksikse seri_delik=True: kilit/cikis "en az".
  * FIYAT KAYNAGI sirasi: --cache (borsapy onbellegi, delik yok) -> yfinance (delikli olabilir).
    Kayit 'price_source' tasir. data/bars arsivi (2026-09-18'den itibaren) birikince eklenir.
Kullanim:
  python taban_readiness.py [--cache local/feed_onbellek_YYYY-MM-DD.pkl] [--write]
  (--write yoksa KURU KOSUM: defter yazilmaz, yalniz basilir)
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import warnings

warnings.filterwarnings("ignore")
import pandas as pd  # noqa: E402

import floor_lock_accounting as FLA  # noqa: E402

REPO = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(REPO, "reports", "taban_honest_ledger.json")
MIN_READY_WINDOWS = 5
MIN_LOW_RETURN_PCT = 0.0        # C2a: KUMULATIF taban-honest low bu ustunde (pencere-basi DEGIL)
MAX_READY_LOCK_DAYS = 5
MAX_TABAN_RATIO_PCT = 60
MAX_TABAN_RATIO_RANGE_PCT = 50
MAX_WINDOW_DRAG_PCT = 8.0       # C2b: pencere-basi taban-drag (low) tavani. YARGI-CAGRISI:
#   drag ~1.5pp/taban-stop (olculen: TERA %17.5 ceza x %9 agirlik). 8pp ~= 5-6 taban-stop =
#   sepetin YARISI bir pencerede kilit = kriz-baslangici (2018/2020 deseni) = yakalanmasi
#   gereken kuyruk. Gozlem-ustu (olculen max 4.45pp, ~1.8x), felaket-alti (gercek kriz 12-30pp+).
#   PROVIZYONEL: 2 pencerede kalibre; C1=5'e ulasinca YENIDEN BAK (normal-rough 8'e yaklasirsa
#   cok-tutuk). C2b "tum pencereler <=tavan" -> bir asim kalici diskalifiye (KASITLI: gercek
#   krizde kilit surprizi yasandiysa o pencere hazirlik kanitindan duser).
CORP_ACTION_THRESH = -20.0     # gunluk < bu = BIST +-%10/20 limit-DISI = kesin bedelsiz/split
#   artefakti (ham veri, auto_adjust=False). Taban DEGIL -> ledger'da taban-sayimi+drag'den haric.
#   IZOLE: sadece bu tool; F'e/F-girdisine/backtest.py'ye dokunmaz (regresyon riski YOK).
WINDOW_EVENTS = ("initial_entry", "rebalance")
REF_TICKER = "XU100"


# ---------------------------------------------------------------- pencereler
def windows_from_history(hist):
    """Rebalans donguleri: [{start, end|None, start_total, end_total, stops:[...]}].
    Sinir = initial_entry/rebalance kayitlari; stoplar (start, end] araligina TARIHE gore atanir."""
    bounds = sorted((h for h in hist if h.get("event") in WINDOW_EVENTS), key=lambda h: h["date"])
    if not bounds:
        return []
    last_total = None
    for h in sorted(hist, key=lambda h: h["date"]):
        if h.get("total") is not None:
            last_total = h["total"]
    out = []
    for i, b in enumerate(bounds):
        start = b["date"]
        end = bounds[i + 1]["date"] if i + 1 < len(bounds) else None
        end_total = bounds[i + 1].get("total") if end else last_total
        stops = []
        for h in hist:
            d = h.get("date")
            if d is None or d <= start or (end and d > end):
                continue
            for tr in (h.get("trades") or []):
                if tr.get("type") == "SELL" and tr.get("reason") == "stop":
                    stops.append(dict(date=d, tic=tr["ticker"], price=tr.get("price"),
                                      shares=tr.get("shares"), total=h.get("total")))
        stops.sort(key=lambda s: (s["date"], s["tic"]))
        out.append(dict(start=start, end=end, start_total=b.get("total"), end_total=end_total, stops=stops))
    return out


# ---------------------------------------------------------------- fiyat kaynaklari
def cache_prices(cache, tickers, start, end, today=None):
    """borsapy onbellegi (feed_onbellek_*.pkl sozlugu) -> (close, low) cerceveleri, XU100 dahil.
    Onbellek [start, end] araligini KAPSAMIYORSA None (uydurma yok; cagiran yfinance'a duser).
    Ust sinir HAFTA SONU GUVENLI: son bar, min(end, bugun) - 4 gun'den yeni olmali (Cuma onbellegi
    Pazartesi gecerli; 'bugun-1' kurali hafta sonu None verirdi = bagimsiz okuma bulgusu)."""
    data = cache.get("data", cache)
    prices = data["prices"]
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.now().normalize()
    if prices.index.min() > s or prices.index.max() < min(e, today) - pd.Timedelta(days=4):
        return None
    cols = [t for t in tickers if t in prices.columns]
    close = prices.loc[s:e, cols].copy()
    mins = data.get("mins")
    low = mins.loc[s:e, cols].copy() if mins is not None else close.copy()
    bist = data.get("bist")
    if bist is not None:
        close[REF_TICKER] = bist.reindex(close.index)
        low[REF_TICKER] = bist.reindex(low.index)
    return close, low


def yfinance_prices(tickers, start, end):
    import yfinance as yf
    raw = yf.download([t + ".IS" for t in tickers] + ["XU100.IS"], start=start, end=end,
                      interval="1d", auto_adjust=False, progress=False, group_by="column")
    close = raw["Close"].copy(); low = raw["Low"].copy()
    close.columns = [c.replace(".IS", "") for c in close.columns]
    low.columns = [c.replace(".IS", "") for c in low.columns]
    return close, low


# ---------------------------------------------------------------- pencere analizi (saf)
def analyze_window(window, close, low):
    """Bir rebalans penceresi x fiyat cercevesi. Ag/IO yok. HER stop bir satir: veri_eksik olan
    sayilir ve etiketlenir, taban orani/drag'e girmez (kaydirma YOK)."""
    stops = window["stops"]
    st, et = window.get("start_total"), window.get("end_total")
    booked = (et / st - 1) * 100 if st and et else None      # olculemeyen getiri 0.0 DEGIL, None (uydurma yok)
    ref = close[REF_TICKER].dropna().index if REF_TICKER in close.columns else close.dropna(how="all").index
    details, drag_stops, locks = [], [], []
    corp_actions = veri_eksik = seri_delik = kilit_acik = 0
    for x in stops:
        t = x["tic"]; d = pd.Timestamp(x["date"])
        row = dict(date=x["date"], tic=t, daily_ret=None, taban=None, corp_action=False,
                   lock_days=None, real_exit_close=None, veri_eksik=False, seri_delik=False,
                   kilit_acik=False, kilit_tavan=False)
        ser = close[t].dropna() if t in close.columns else pd.Series(dtype=float)
        ser = ser[~ser.index.duplicated(keep="last")]        # cift bar -> get_loc dilim dondururdu
        if d not in ser.index or ser.index.get_loc(d) == 0:
            row["veri_eksik"] = True; veri_eksik += 1
            details.append(row); continue
        pos = int(ser.index.get_loc(d))
        lser = low[t].reindex(ser.index) if t in low.columns else ser
        rc = FLA.backtest_exit(ser, pos)
        rl = FLA.backtest_exit(ser, pos, use_low=True, lows_series=lser)
        dayret = float(round((ser.iloc[pos] / ser.iloc[pos - 1] - 1) * 100, 1))   # numpy -> python (JSON)
        is_corp = bool(dayret < CORP_ACTION_THRESH)                                # np.bool_ JSON'a yazilamaz
        # stop..cikis arasinda referansin gordugu bir gun bu seride yoksa kilit/cikis "en az"
        ex_idx = min(rc["exit_idx"], len(ser) - 1)
        ref_span = ref[(ref > ser.index[pos]) & (ref <= ser.index[ex_idx])]
        delik = any(r not in ser.index for r in ref_span)
        # kilit HALA ACIK: seri son barinda bitiyor ve o bar da taban -> cikis fiyati bilinmiyor, drag "en az"
        acik = bool(rc["was_locked"] and ex_idx == len(ser) - 1 and ex_idx >= 1
                    and FLA.is_floor_day(ser.iloc[ex_idx - 1], ser.iloc[ex_idx]))
        tavan = bool(rc["was_locked"] and rc["lock_days"] >= FLA.MAX_LOCK_DAYS)   # zorla cikis: gercek kilit daha uzun olabilir
        row.update(daily_ret=dayret, taban=bool(rc["was_locked"] and not is_corp), corp_action=is_corp,
                   lock_days=int(rc["lock_days"]), real_exit_close=float(rc["exit_price"]), seri_delik=bool(delik),
                   kilit_acik=acik, kilit_tavan=tavan)
        details.append(row)
        if delik:
            seri_delik += 1
        if acik:
            kilit_acik += 1
        if is_corp:
            corp_actions += 1
        elif rc["was_locked"]:
            locks.append(rc["lock_days"])
            w = (x["shares"] * ser.iloc[pos] / x["total"] * 100 if x.get("shares") and x.get("total") else 0)
            drag_stops.append(dict(weight=w, recorded_exit=x["price"],
                                   real_exit_close=float(rc["exit_price"]), real_exit_low=float(rl["exit_price"])))
    dg = FLA.portfolio_drag(drag_stops)
    n_olculen = len(details) - veri_eksik
    n_taban = len(locks)
    return dict(
        window_start_date=window["start"], window_end_date=window.get("end"),
        n_stops=n_olculen, n_taban_stops=n_taban, veri_eksik_stops=veri_eksik, seri_delik_stops=seri_delik,
        kilit_acik_stops=kilit_acik, corp_action_stops=corp_actions,
        taban_ratio=round(n_taban / (n_olculen - corp_actions) * 100) if (n_olculen - corp_actions) else 0,
        max_consecutive_lock=max(locks) if locks else 0,
        multi_day_locks=sum(1 for l in locks if l >= 2),
        booked_ret=None if booked is None else round(booked, 1),
        drag_close=float(dg["drag_close_pct"]), drag_low=float(dg["drag_low_pct"]),
        taban_honest_close=None if booked is None else round(booked - dg["drag_close_pct"], 1),
        taban_honest_low=None if booked is None else round(booked - dg["drag_low_pct"], 1),
        drag_en_az=bool(kilit_acik or seri_delik or any(d["kilit_tavan"] for d in details)),
        stops=details,
    )


def rebuild_ledger(hist, close, low, price_source="verilen", run_date=None):
    """Tum rebalans pencerelerini yeniden hesapla (deterministik). Eski defter kayitlari YERINE gecer."""
    out = []
    for w in windows_from_history(hist):
        rec = analyze_window(w, close, low)
        rec["price_source"] = price_source
        rec["run_date"] = run_date or str(pd.Timestamp.now().date())
        out.append(rec)
    out.sort(key=lambda r: r["window_start_date"])
    return out


# ---------------------------------------------------------------- defter + kriter
def save_ledger(ledger):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
        f.write("\n")


def assess(ledger):
    """OLCULEBILIR gecis-kriteri (sezgi degil). Doner: (hazir_mi, satirlar, hukum)."""
    n = len(ledger)
    c1 = n >= MIN_READY_WINDOWS
    cum_low = 1.0; olculemeyen = 0
    for w in ledger:
        v = w.get("taban_honest_low")
        if v is None:
            olculemeyen += 1; continue                       # getirisi olculemeyen pencere kanit degil
        cum_low *= (1 + v / 100.0)
    cum_low = (cum_low - 1) * 100
    c2a = (cum_low > MIN_LOW_RETURN_PCT) and n > 0 and olculemeyen == 0
    # C2b: drag ALT SINIR olan pencere (acik kilit / seri delik / 10g tavan) tavani gecmese de KANIT VEREMEZ:
    # gercek drag daha buyuk olabilir -> fail-closed (bagimsiz okuma 2026-09-18)
    alt_sinir = sum(1 for w in ledger if w.get("drag_en_az"))
    c2b = all(w.get("drag_low", 0) <= MAX_WINDOW_DRAG_PCT and not w.get("drag_en_az") for w in ledger) and n > 0
    c2 = c2a and c2b
    c3 = all(w.get("max_consecutive_lock", 0) <= MAX_READY_LOCK_DAYS for w in ledger) and n > 0
    ratios = [w.get("taban_ratio", 0) for w in ledger]
    ratio_range = (max(ratios) - min(ratios)) if ratios else 0
    c4 = (n > 0 and max(ratios) <= MAX_TABAN_RATIO_PCT and (n < 2 or ratio_range <= MAX_TABAN_RATIO_RANGE_PCT))
    lines = [
        f"  C1 Yeterli kanit (>={MIN_READY_WINDOWS} pencere): {'OK' if c1 else 'HAYIR'} ({n} pencere)",
        f"  C2 Kumulatif-poz + drag-sinir  : {'OK' if c2 else 'HAYIR'} "
        f"(a: kum-low {cum_low:+.1f}%>0={c2a}{' | olculemeyen pencere ' + str(olculemeyen) if olculemeyen else ''} | b: drag<={MAX_WINDOW_DRAG_PCT}pp={c2b}{' | drag alt-sinir (kanit veremez) ' + str(alt_sinir) if alt_sinir else ''})",
        f"  C3 Modellenmis kuyruk (<={MAX_READY_LOCK_DAYS} gun): {'OK' if c3 else 'HAYIR'}",
        f"  C4 Taban_ratio kontrolu        : {'OK' if c4 else 'HAYIR'} "
        f"{ratios} (max<={MAX_TABAN_RATIO_PCT}, aralik<={MAX_TABAN_RATIO_RANGE_PCT})",
    ]
    ready = c1 and c2 and c3 and c4
    verdict = ("HAZIR-ADAYI (kriter saglandi; yine de son karari sen ver)" if ready
               else f"HENUZ DEGIL - {max(0, MIN_READY_WINDOWS - n)} pencere daha + kriterler tutmali (kanit birikiyor)")
    return ready, lines, verdict


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pf", default=os.path.join(REPO, "portfolios", "portfolio_F.json"))
    ap.add_argument("--cache", default=None, help="borsapy onbellegi (local/feed_onbellek_*.pkl); yoksa yfinance")
    ap.add_argument("--write", action="store_true", help="defteri YAZ (varsayilan kuru kosum)")
    a = ap.parse_args(argv)
    hist = json.load(open(a.pf, encoding="utf-8")).get("history", [])
    wins = windows_from_history(hist)
    if not wins:
        print("pencere yok (initial_entry/rebalance kaydi bulunamadi)"); return 1
    tickers = sorted({s["tic"] for w in wins for s in w["stops"]})
    start = (pd.Timestamp(wins[0]["start"]) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    end = (pd.Timestamp.now().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    close = low = None; source = None
    if a.cache:
        cache = pickle.load(open(a.cache, "rb"))
        got = cache_prices(cache, tickers, start, end)
        if got is not None:
            close, low = got; source = f"cache:{os.path.basename(a.cache)}"
        else:
            print(f"onbellek {a.cache} araligi kapsamiyor ({start}..{end}) -> yfinance")
    if close is None:
        close, low = yfinance_prices(tickers, start, end); source = "yfinance"
    ledger = rebuild_ledger(hist, close, low, price_source=source)
    print("=" * 66)
    print("TABAN-DURUST GERCEK-PARA DEFTERI (izole; rebalans pencereleri; kaynak: " + source + ")")
    print("=" * 66)
    for rec in ledger:
        b = rec["booked_ret"]; kag = f"{b:+.1f}%" if b is not None else "OLCULEMEDI"
        td = (f"{rec['taban_honest_low']:+.1f}..{rec['taban_honest_close']:+.1f}%" if b is not None else "OLCULEMEDI")
        print(f"[{rec['window_start_date']} -> {rec['window_end_date'] or 'ACIK'}] stop {rec['n_stops']} "
              f"(taban {rec['n_taban_stops']} %{rec['taban_ratio']}, eksik {rec['veri_eksik_stops']}, delik {rec['seri_delik_stops']}, acik kilit {rec['kilit_acik_stops']}) "
              f"| kagit {kag} | taban-durust {td} (drag {rec['drag_low']}..{rec['drag_close']}pp{', EN AZ' if rec['drag_en_az'] else ''}) "
              f"| max kilit {rec['max_consecutive_lock']}g")
        for d in rec["stops"]:
            if d["veri_eksik"]:
                print(f"    {d['date']} {d['tic']:6s} VERI EKSIK (seride yok; kaydirilmadi)")
            else:
                print(f"    {d['date']} {d['tic']:6s} gun-ret {d['daily_ret']:+.1f}% "
                      f"{'TABAN kilit ' + str(d['lock_days']) + 'g' if d['taban'] else 'normal'}"
                      f"{' [seri delik: en az]' if d['seri_delik'] else ''}{' [KILIT ACIK: cikis bilinmiyor]' if d['kilit_acik'] else ''}"
                      f"{' [kilit tavani ' + str(FLA.MAX_LOCK_DAYS) + 'g: en az]' if d['kilit_tavan'] else ''}{' [CA?]' if d['corp_action'] else ''}")
    print(f"\nGECIS KRITERI ({len(ledger)} pencere):")
    ready, lines, verdict = assess(ledger)
    for l in lines:
        print(l)
    print(f"  -> {verdict}")
    if a.write:
        save_ledger(ledger)
        print(f"\nYAZILDI: {os.path.relpath(LEDGER, REPO)} ({len(ledger)} pencere, kaynak {source})")
    else:
        print(f"\nKURU KOSUM: defter yazilmadi (--write ile yazilir): {os.path.relpath(LEDGER, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
