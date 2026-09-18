"""BAR ARSIVI — sistemin cektigi gunluk barlari SAKLA (2026-09-18).

OLCUM: daemon gunde 3x (acilis/gunici/kapanis) ~625 hisse x ~750 bar cekiyordu ve hicbirini
kalici bir yere yazmiyordu (runner gecici; tek kalici fiyat dosyasi donmus backtest Excel'i,
2026-04-28'de biter). Bedeli olculdu: yfinance'in 2026-09-17 deligi (IEYHO/SELEC) kendi
verimizden doldurulamadi -> taban-kilit hesabi eksik kaldi. Her canli gun geri gelmez.

TASARIM (kucuk, salt-ekleme, F'e dokunmaz):
  * data/bars/YYYY-MM.csv — kolonlar sabit (COLUMNS), UTF-8, LF. Hisseler + XU100 (close-only).
  * Her kosumda feed'in SON `KUYRUK_GUN` satiri islenir; (tarih, hisse) icin son yazilan degerle
    AYNI ise yazilmaz (idempotent), FARKLI ise yeni satir EKLENIR — ustune yazilmaz: gunici kismi
    bar + kapanis nihai bar, ya da ertesi gun gorunen gec revizyon ayri satirlardir; `run_label`
    ve `fetched_at` hangi gorusun ne zaman alindigini soyler. Tuketici: son_barlar() = son gorus.
  * NaN kapanis = bar yok -> satir yazilmaz.
  * Kaynak `file` (donmus Excel'e dusus) ise ARSIVLENMEZ; durum dosyasi nedenini yazar.
  * docs/state/bar_archive.json: kosum sayaclari (liveness uyesi DEGIL; ileride olabilir).
  * Cagiran: daemon feed fazindan sonra, selfheal.guarded icinde (arsiv hatasi raporu dusurmez,
    ama loglanir). Workflow state-commit adimi data/bars/ dizinini ekler.
  * data/bars/.gitkeep TAKIPLI: `git add -f data/bars/` dizin bossa/yoksa pathspec hatasiyla state
    adimini dusururdu (daemon kosmayan always() adimi); .gitkeep dizini her zaman var eder.
Boyut (CIKARIM): ~626 satir/gun nihai + gunici kismi -> ~60-90 KB/gun, ~2 MB/ay.
"""
from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone

COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "source", "run_label", "fetched_at"]
KUYRUK_GUN = 5          # feed'in son kac gunu islenir (gec gelen bar / revizyon yakalansin)
XU100 = "XU100"
ARSIVLENMEZ_KAYNAK = ("file",)
WRITER = "bist_alpha.bar_archive.append_bars"


def _num(v, nd=4):
    """float -> sabit basamakli metin; NaN/None -> ''."""
    try:
        if v is None:
            return ""
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if math.isnan(f) or math.isinf(f):
        return ""
    return f"{round(f, nd):.{nd}f}".rstrip("0").rstrip(".") if nd else str(int(round(f)))


def _cell(frame, d, t):
    try:
        return frame.loc[d, t]
    except Exception:
        return None


def _dosya(root, ay):
    return os.path.join(root, "data", "bars", f"{ay}.csv")


def _son_degerler(path):
    """Dosyadaki (tarih, hisse) -> son satirin (open, high, low, close, volume) metinleri."""
    son = {}
    if not os.path.exists(path):
        return son
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            son[(r["date"], r["ticker"])] = (r["open"], r["high"], r["low"], r["close"], r["volume"])
    return son


def son_barlar(path):
    """Tuketici: (tarih, hisse) -> SON gorus satiri (dict). Gunici kismi bar kapanisla, eski
    gorus revizyonla ezilir (dosyada ikisi de durur)."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            out[(r["date"], r["ticker"])] = r
    return out


def _satirlar(data, run_label, fetched_at):
    """Feed sozlugunden aday satirlar (son KUYRUK_GUN gun)."""
    prices = data["prices"]
    opens, mins, maxs, vols = (data.get(k) for k in ("opens", "mins", "maxs", "volumes"))
    bist = data.get("bist")
    # provenance: TAM kaynak dizgesi (orn. 'borsapy_fallback_from_yahoo' = birincil dustu), taban degil
    source = str(data.get("_source") or data.get("_source_base") or "")
    tarihler = list(prices.index[-KUYRUK_GUN:])
    for d in tarihler:
        ds = d.strftime("%Y-%m-%d")
        for t in prices.columns:
            c = _num(_cell(prices, d, t))
            if c == "":
                continue                                    # NaN kapanis = bar yok
            yield {"date": ds, "ticker": str(t),
                   "open": _num(_cell(opens, d, t)) if opens is not None else "",
                   "high": _num(_cell(maxs, d, t)) if maxs is not None else "",
                   "low": _num(_cell(mins, d, t)) if mins is not None else "",
                   "close": c,
                   "volume": _num(_cell(vols, d, t), nd=0) if vols is not None else "",
                   "source": source, "run_label": run_label, "fetched_at": fetched_at}
        if bist is not None:
            try:
                bc = _num(bist.loc[d])
            except Exception:
                bc = ""
            if bc != "":
                yield {"date": ds, "ticker": XU100, "open": "", "high": "", "low": "", "close": bc, "volume": "",
                       "source": source, "run_label": run_label, "fetched_at": fetched_at}


def _durum_yaz(root, durum):
    p = os.path.join(root, "docs", "state", "bar_archive.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(durum, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def append_bars(data, run_label, root, now=None):
    """Feed'in son gunlerini arsive ekle. Donus: durum sozlugu (docs/state/bar_archive.json ile ayni)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("append_bars: naive datetime kabul etmez (eksen belirsiz)")
    fetched_at = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    source = str(data.get("_source_base") or data.get("_source") or "")
    durum = {"writer": WRITER, "generated_at": fetched_at, "run_label": run_label,
             "source": str(data.get("_source") or source),
             "rows_seen": 0, "rows_added": 0, "dates": [], "files": [], "skipped_reason": None}
    if source in ARSIVLENMEZ_KAYNAK or str(data.get("_source", "")).startswith("file"):
        durum["skipped_reason"] = f"kaynak '{data.get('_source') or source}' donmus dosya: arsivlenmez"
        _durum_yaz(root, durum)
        return durum

    aday = list(_satirlar(data, run_label, fetched_at))
    durum["rows_seen"] = len(aday)
    durum["dates"] = sorted({r["date"] for r in aday})
    buffers = {}                                            # ay -> (path, son_degerler, yeni satirlar)
    for r in aday:
        ay = r["date"][:7]
        if ay not in buffers:
            p = _dosya(root, ay)
            buffers[ay] = [p, _son_degerler(p), []]
        p, son, yeni = buffers[ay]
        deger = (r["open"], r["high"], r["low"], r["close"], r["volume"])
        if son.get((r["date"], r["ticker"])) == deger:
            continue                                        # ayni gorus: idempotent
        son[(r["date"], r["ticker"])] = deger
        yeni.append(r)
    for ay, (p, _son, yeni) in sorted(buffers.items()):
        if not yeni:
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        yeni_dosya = not os.path.exists(p) or os.path.getsize(p) == 0
        with open(p, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
            if yeni_dosya:
                w.writeheader()
            w.writerows(yeni)
        durum["rows_added"] += len(yeni)
        durum["files"].append(os.path.relpath(p, root).replace(os.sep, "/"))
    _durum_yaz(root, durum)
    return durum
