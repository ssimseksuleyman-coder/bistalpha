"""Uretim feed'ini (borsapy) bir kez cek, local/'e onbellekle. Salt-okuma; F'e dokunmaz.

Amac: sinyal-kalitesi (Q1) ve exit-farkindalikli (Q2) olcumleri icin canli pencere
(2026-06..09) gunluk OHLC + XU100. Defterler seri tasimadigi icin gerekli.
Cikti: local/feed_onbellek_<tarih>.pkl  (prices/mins/maxs/opens/volumes + bist + meta)

DERS (2026-09-13): ilk surumde kayit EN SONDAYDI ve ondan onceki bir prob satiri
(Series uzerinde `or`) cokunce 31 dakikalik cekim kayboldu. Simdi: (1) KAYIT fetch'ten
hemen sonra, (2) fetch-sonrasi yol pahali islemden ONCE sahte veriyle kuru-kosulur.
"""
import datetime as dt
import io
import os
import pickle
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "local", f"feed_onbellek_{dt.date.today():%Y-%m-%d}.pkl")


def cek():
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    from bist_alpha import datafeed
    return datafeed.get_feed("borsapy").get_latest()


def kaydet(payload, out):
    """ATOMIK (C1 F6): ayni dizinde gecici dosyaya dump + fsync + os.replace. Dump hatasinda
    nihai dosya OLUSMAZ, gecici artik KALMAZ (yarim 20 MB pickle en yeni onbellek sanilmasin)."""
    import tempfile
    d = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".onbellek_", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(payload, fh)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, out)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return out


def cekim_damgasi(now=None):
    """Cekim ani, EKSENLI: UTC 'Z' (inceleme #3: naive '2026-09-13T22:45:59' UTC mi TR mi belli degildi)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("cekim_damgasi naive datetime kabul etmez (eksen belirsiz)")
    return now.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def isle(data, sure, out=OUT):
    # 1) KAYIT ONCE (atomik)
    kaydet({"data": dict(data), "cekim_saati": cekim_damgasi(),
            "sure_s": round(sure)}, out)
    print(f"KAYDEDILDI: {out} ({os.path.getsize(out) // 1024} KB) | cekim {sure:.0f}s")
    print("data anahtarlari:", sorted(k for k in data.keys() if not str(k).startswith("_")))
    p = data["prices"]
    print(f"prices: {p.shape[0]} gun x {p.shape[1]} hisse | {p.index[0].date()} .. {p.index[-1].date()}")
    for k in ("mins", "maxs", "opens", "volumes"):
        v = data.get(k)
        print(f"  {k}: {'YOK' if v is None else v.shape}")
    b = data.get("bist")
    print(f"  endeks 'bist': {'YOK' if b is None else (type(b).__name__, getattr(b, 'shape', None))}"
          f" | _bist_ok={data.get('_bist_ok')}")
    print("  source:", data.get("source"), "| pool:", data.get("source_pool_count"))

    # 2) CA probu: tek-gun oran >1.5 ya da <0.67 = duzeltilMEmis seri
    print("\nCA PROBU (ham mi, duzeltilmis mi):")
    for tic in ("KTLEV", "AKFIS", "CVKMD", "PASEU", "TMPOL"):
        if tic not in p.columns:
            print(f"  {tic}: seride YOK")
            continue
        s = p[tic].dropna()
        r = (s / s.shift(1)).dropna()
        kotu = r[(r > 1.5) | (r < 0.67)]
        print(f"  {tic}: {len(s)} gun | tek-gun sicrama: "
              + (", ".join(f"{d.date()} x{v:.2f}" for d, v in kotu.items()) if len(kotu) else "YOK -> duzeltilmis gorunuyor"))
    print("\ntamam:", out)


if __name__ == "__main__":
    t0 = time.time()
    veri = cek()
    isle(veri, time.time() - t0)
