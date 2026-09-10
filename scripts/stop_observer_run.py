"""P0.6/madde-7 kosucusu — bagimsiz stop gozlemi.

`selfheal.safe_feed` KULLANILMAZ ve bu BILINCLIDIR (bkz bist_alpha/stop_observer.py
docstring): veri kapisinin reddi SUREKLILIK hakkindadir, ANLIK FIYAT gecerliligi
hakkinda degil. Stop yalnizca guncel fiyat ister. Kapiya baglanirsa senaryo-3
("ana yol hatasinda stop yine calisir") sessizce olur.

Cikis kodu HER ZAMAN 0 degildir: fiyat hic alinamazsa 1 doner ki adim
kirmizi gorunsun (`continue-on-error` YOK — hata gizlenmemeli).
"""

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bist_alpha import stop_observer  # noqa: E402

HESAPLAR = ["F", "A", "B", "O", "G1"]


def _held(state):
    return sorted((state or {}).get("positions") or {})


def _select_symbol_frame(raw, aliases):
    columns = getattr(raw, "columns", None)
    if columns is None or getattr(columns, "nlevels", 1) <= 1:
        return raw
    for level in range(columns.nlevels):
        labels = set(columns.get_level_values(level))
        for alias in aliases:
            if alias in labels:
                try:
                    return raw.xs(alias, axis=1, level=level, drop_level=True)
                except (KeyError, IndexError, ValueError):
                    pass
    return raw


def _bar_date(index_value):
    """Barin GUN damgasi. tz-aware indeks 09-08 vakasinda maintenance'i kirmisti;
    burada yalniz YYYY-AA-GG metnine indirilir, karsilastirmaya sokulmaz."""
    try:
        return str(index_value)[:10]
    except Exception:
        return None


def _last_close(raw, aliases):
    """Tek semboldeki duz tabloyu ve cok-sembollu MultiIndex'i ayni okur.

    Doner: (fiyat, bar_tarihi). Tarih BILEREK fiyatla birlikte tasinir:
    5 gunluk pencerenin SON GECERLI bari alinir, o bar bugunun olmayabilir
    (islem durdurma, tatil, kaynak gecikmesi). Tarih tasinmazsa panel BAYAT
    fiyat uzerinden kendinden emin bir YESIL gosterir — yanlis-guven.
    """
    frame = _select_symbol_frame(raw, aliases)
    close = None
    for name in ("Close", "close"):
        try:
            close = frame[name]
            break
        except (KeyError, TypeError, IndexError):
            pass
    if close is None:
        return None, None
    if getattr(close, "ndim", 1) > 1:
        close = close.iloc[:, 0]
    try:
        values = close.dropna()
        if len(values) == 0:
            return None, None
        value = float(values.iloc[-1])
        if not math.isfinite(value):
            return None, None
        return value, _bar_date(values.index[-1])
    except (TypeError, ValueError, OverflowError, IndexError):
        return None, None


def _borsapy_prices(tickers):
    import borsapy
    raw = borsapy.download(list(tickers), period="5d", interval="1d", group_by="ticker")
    out, tarih = {}, {}
    for t in tickers:
        value, gun = _last_close(raw, (t,))
        if value is not None:
            out[t] = value
            tarih[t] = gun
    return out, tarih


def _yahoo_prices(tickers):
    import yfinance as yf
    d = yf.download([f"{t}.IS" for t in tickers], period="5d", interval="1d",
                    auto_adjust=False, progress=False, group_by="ticker", threads=True)
    out, tarih = {}, {}
    for t in tickers:
        value, gun = _last_close(d, (f"{t}.IS", t))
        if value is not None:
            out[t] = value
            tarih[t] = gun
    return out, tarih


def fetch_prices(tickers):
    """Iki bagimsiz kaynak. Oncelik borsapy (kabul edilen kaynak), yedek yahoo.

    Ikisi de varsa BIRINCIL kullanilir ve ikisi de kayda gecer. Uyusmazlik
    POLITIKASI KASTEN YOK: fark artefaktta gorunur, karar veriye bakilarak
    sonra verilir. Uydurma esik konmaz.

    Doner: (fiyatlar, kaynaklar, fark, tarihler). `tarihler` SECILEN fiyatin
    bar gunudur; bayatlik OLCULUR ama burada HUKME cevrilmez (esik uydurulmaz).
    """
    sonuc, kaynaklar, tarihler = {}, [], {}
    birincil, yedek = {}, {}
    b_tarih, y_tarih = {}, {}
    for ad, fn, hedef in (("borsapy", _borsapy_prices, "birincil"),
                          ("yahoo", _yahoo_prices, "yedek")):
        try:
            veri, gunler = fn(tickers)
            if hedef == "birincil":
                birincil.update(veri)
                b_tarih.update(gunler)
            else:
                yedek.update(veri)
                y_tarih.update(gunler)
            kaynaklar.append({"source": ad, "status": "ok", "returned": len(veri),
                              "bar_dates": dict(sorted(gunler.items()))})
        except Exception as e:
            kaynaklar.append({"source": ad, "status": "failed",
                              "error": f"{type(e).__name__}: {str(e)[:120]}"})
    for t in tickers:
        if t in birincil:
            sonuc[t] = birincil[t]
            tarihler[t] = b_tarih.get(t)
        elif t in yedek:
            sonuc[t] = yedek[t]
            tarihler[t] = y_tarih.get(t)
    # Bar gunleri de kayda gecer: iki kaynak AYNI fiyati verip FARKLI gunden
    # veriyor olabilir (biri bayat). Yalniz `diff_pct` bakan biri bunu "uyum"
    # sanardi; tarihler yan yana durunca sanmaz.
    fark = {
        t: {"borsapy": birincil[t], "yahoo": yedek[t],
            "diff_pct": round((yedek[t] / birincil[t] - 1) * 100, 4),
            "bar_dates": {"borsapy": b_tarih.get(t), "yahoo": y_tarih.get(t)}}
        for t in tickers if t in birincil and t in yedek and birincil[t]
    }
    return sonuc, kaynaklar, fark, tarihler


def main():
    durumlar, hesap_durumlari = stop_observer.load_states(
        HESAPLAR, state_dir=ROOT / "portfolios"
    )
    for acc, status in hesap_durumlari.items():
        if status.get("status") != "loaded":
            print(
                f"[stop-observer] {acc} state {status.get('status')}: "
                f"{status.get('error', status.get('path'))}"
            )

    hesap_satirlari = {acc: [] for acc in HESAPLAR}
    unavailable = [
        acc for acc, status in hesap_durumlari.items()
        if status.get("status") != "loaded"
    ]

    # BOS SONUC AYRIMI: "acik pozisyon yok" ile "state hic okunamadi" AYNI SEY DEGIL.
    # Ikisi de bos ticker listesi verir; ilki normal, ikincisi ariza.
    if not durumlar:
        print("[stop-observer] HICBIR hesap state'i okunamadi — gozlem YAPILAMADI")
        payload = stop_observer.build_payload(
            hesap_satirlari,
            [{"source": "portfolio_state", "status": "failed",
              "error": "hicbir hesap yuklenemedi"}],
            run_label=os.environ.get("STOP_OBS_LABEL"),
            account_status=hesap_durumlari,
        )
        stop_observer.write_payload(payload)
        _emit(False, payload)
        return 1

    tickers = sorted({t for st in durumlar.values() for t in _held(st)})
    print(f"[stop-observer] pozisyon tasiyan sembol: {len(tickers)} {tickers}")
    if not tickers:
        payload = stop_observer.build_payload(
            hesap_satirlari, [], run_label=os.environ.get("STOP_OBS_LABEL"),
            account_status=hesap_durumlari,
        )
        stop_observer.write_payload(payload)
        print("[stop-observer] acik pozisyon yok — gozlem bos")
        _emit(False, payload)
        # KISMI hesap eksikligi ARIZA DEGIL: iz + kapi tasir, exit 0.
        # (exit 1 verirse job duser -> P0.3 -> Telegram; karar (3) ile celisir.)
        return 0

    fiyatlar, kaynaklar, fark, tarihler = fetch_prices(tickers)
    if fark:
        print(f"[stop-observer] kaynak farki: {json.dumps(fark, ensure_ascii=False)}")
    if not fiyatlar:
        print("[stop-observer] HICBIR kaynaktan fiyat alinamadi")
    _gunler = sorted({g for g in tarihler.values() if g})
    if _gunler:
        print(f"[stop-observer] fiyat bar gunu: {_gunler[0]}"
              + (f" .. {_gunler[-1]}" if _gunler[0] != _gunler[-1] else ""))

    hesap_satirlari = {
        acc: stop_observer.evaluate_stops(durumlar[acc], fiyatlar, price_dates=tarihler)
        for acc in durumlar
    }
    payload = stop_observer.build_payload(hesap_satirlari, kaynaklar,
                                          run_label=os.environ.get("STOP_OBS_LABEL"),
                                          account_status=hesap_durumlari,
                                          cross_check=fark)
    yol = stop_observer.write_payload(payload)
    print(f"[stop-observer] iz yazildi: {yol}")

    for acc, satirlar in hesap_satirlari.items():
        for r in satirlar:
            if r["status"] != "priced":
                print(f"[stop-observer] {acc} {r['ticker']}: {r['status']} "
                      f"(stop={r['stop_level']}) — OLCULEMEDI, temiz DEGIL")
            elif r["breached"]:
                print(f"[stop-observer] {acc} {r['ticker']}: STOP ALTINDA "
                      f"fiyat={r['price']} < stop={r['stop_level']}")

    _emit(payload["breach"], payload)
    # CIKIS KODU = "gozlem YAPILABILDI mi", "eksiksiz miydi" DEGIL.
    # Eksiklik kapiyla tasinir (payload['gate']), cikis koduyla degil.
    return 0 if fiyatlar else 1


def _emit(breached, payload):
    out = os.environ.get("GITHUB_OUTPUT")
    ozet = (f"breached={str(bool(breached)).lower()} "
            f"positions={payload['position_count']} unpriced={payload['unpriced_count']} "
            f"gate={(payload.get('gate') or {}).get('verdict', 'RED')}")
    print(f"[stop-observer] {ozet}")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"breached={str(bool(breached)).lower()}\n")
            fh.write(f"unpriced={payload['unpriced_count']}\n")
            fh.write(f"positions={payload['position_count']}\n")
            fh.write(f"state_unavailable={payload.get('unavailable_account_count', 0)}\n")
            fh.write(f"gate={(payload.get('gate') or {}).get('verdict', 'RED')}\n")


if __name__ == "__main__":
    sys.exit(main())
