"""Defterler icin ORTAK olcum yardimcilari — evren sepeti + kume-dayanikli SE.

NEDEN BU DOSYA VAR (`#0r`, 2026-08-14):
`flow`/`catalyst`/`quality` defterlerinin HICBIRINDE evren-sepeti fonksiyonu YOKTU
(olculdu: `sepet-izi 0`). Alternatif ortak modul DEGIL, **~50 satir yeni tekrar**
olurdu (`_basket_return` 30 + kume-SE 20). Karsilastirma "yeni dosya vs hicbir sey"
degil, **"yeni dosya vs tekrar"**dir.
*Simetrik karsi-ornek (`#0p` Adim-2): orada var-olan blok tekillesecekti ve olculdu
-> +6 satir kazanc, 9 parametreli dolaylandirma, 69 satirlik gercek tekrar yerinde
kaliyordu => modul ACILMADI, is iptal. Kural: var-olan VARSA acma, var-olan YOKSA
ve alternatif tekrarsa AC.*

ICERIK:
  basket_return / basket_return_series  <- `macro_surprise_ledger`den TASINDI
                                           (tek kaynak; macro da buradan alir)
  cluster_stats                         <- YENI, `#0r` cekirdegi

⚠️ F-DATAPATH DISI: bu modulu yalniz defterler kullanir. `strategy/backtest/
config/portfolio/signals` hicbirini import ETMEZ ve etmemeli.
"""

import math

import pandas as pd


def _round(value, digits=2):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        value = round(float(value), digits)
    except Exception:
        return None
    return 0.0 if value == 0 else value


def _price_at_pos(prices, ticker, pos):
    if pos is None or pos < 0 or pos >= len(prices.index) or ticker not in prices.columns:
        return None
    value = prices.iloc[pos][ticker]
    if pd.isna(value) or value <= 0:
        return None
    return float(value)


def basket_return(prices, tickers, entry_pos, window):
    """Esit-agirlik sepet getirisi: [entry_pos, entry_pos+window], yuzde."""
    if entry_pos is None or int(entry_pos) + window >= len(prices.index):
        return None
    returns = []
    for ticker in tickers:
        start = _price_at_pos(prices, ticker, int(entry_pos))
        end = _price_at_pos(prices, ticker, int(entry_pos) + window)
        if start and end:
            returns.append((end / start - 1) * 100)
    return _round(sum(returns) / len(returns)) if returns else None


def basket_return_series(prices, window):
    """`basket_return`in VEKTORLESTIRILMIS ayni-anlamli hali (tum pozisyonlar).

    Dongu hali ~39.7 sn / 485 pozisyon; vektor hali ~0.026 sn (~1500x).
    Esdegerlik TUM pozisyonlarda dogrulandi (5 nokta DEGIL) — bkz `#0p`.
    """
    if prices is None or getattr(prices, "empty", True):
        return None
    frame = prices[[c for c in prices.columns if c]]
    frame = frame.where(frame > 0)
    fwd = (frame.shift(-window) / frame - 1.0) * 100.0
    return fwd.mean(axis=1, skipna=True).map(lambda v: _round(v) if v == v else float("nan"))


def cluster_stats(pairs):
    """KUME-DAYANIKLI kenar + SE. `pairs` = [(kume_anahtari, deger), ...].

    NEDEN (`#0r`): defter kapilari `len(mature21) >= 20` ile **SATIR** sayiyor,
    **bagimsiz birim** saymiyor. Olculdu (catalyst): 18 olayin HEPSI `2026-07-06`
    tarihli — 18 bagimsiz olay degil, **tek gunde 18 hisse**. Ayni gunun hisseleri
    ortak piyasa hareketine maruz => etkin n(tarih) ~ 1. Naif SE (sqrt(p(1-p)/18))
    o veriye uygulanirsa **anlamsiz** bir guven uretir.

    YONTEM: her KUME (tarih) icin ortalama alinir -> 18 hisse TEK noktaya coker
    (kume-ici korelasyon boylece otomatik cozulur). Kenar = kume ortalamalarinin
    ortalamasi; SE = sd(kume_ort)/sqrt(K).
      K < 2  -> kumeler-arasi varyans TANIMSIZ -> se=None ("hesaplanamadi")
    Bu, sabit bir esik (ör. "20 tarih") uydurmadan kendini duzenler: veri
    yetmiyorsa kapi ACILMAZ, cunku SE hesaplanamaz.

    AVG UZERINDEN, HIT UZERINDEN DEGIL: hit bir ORANDIR; kumeler farkli boyutta
    olunca kumeler-arasi varyans gercek etkiden cok **kume boyutu heterojenligini**
    olcer ve K kucukken dayaniksizdir. (`#0p` makroda hit dogruydu, cunku orada
    her tarihte TEK olay vardi — kume sorunu yoktu.)

    ⚠️ BILINEN SINIR — K=2 ZAYIF: iki kumeden hesaplanan sd son derece
    guvenilmezdir (df=1). Kapi `K >= 2`de aciliyor, yani K=2 GECIYOR ve bu
    K=1'den yalnizca biraz iyidir. Daha yuksek bir minimum koymak ya da t-carpani
    kullanmak UYDURMA BIR SABIT (esik ya da guven duzeyi) gerektirirdi — `#0p`de
    tam bu yuzden mutlak esikten vazgecmistik. Secim: sabit uydurma, ama `k`yi
    YAYINLA (`n_unique_dates_21d`, `cluster_21d.k`) ki okuyan zayifligi gorsun.
    Kume sayisi arttikca guclenmesi beklenir; K=2'lik bir "izleme_degeri_var"
    TEK BASINA hukum sayilmamalidir.

    Doner: {"k": K, "n": toplam, "edge": kume-ort-ort, "se": SE|None,
            "edge_in_se": edge/se|None, "largest_cluster": en buyuk kume boyu}
    """
    gecerli = [(str(k), float(v)) for k, v in (pairs or [])
               if k is not None and v is not None]
    if not gecerli:
        return {"k": 0, "n": 0, "edge": None, "se": None,
                "edge_in_se": None, "largest_cluster": 0}

    kume = {}
    for k, v in gecerli:
        kume.setdefault(k, []).append(v)
    kume_ort = [sum(vs) / len(vs) for vs in kume.values()]
    K = len(kume_ort)
    edge = sum(kume_ort) / K

    se = None
    if K >= 2:
        var = sum((x - edge) ** 2 for x in kume_ort) / (K - 1)
        se = math.sqrt(var / K)

    return {
        "k": K,
        "n": len(gecerli),
        "edge": _round(edge),
        "se": _round(se) if se is not None else None,
        "edge_in_se": (_round(edge / se) if se not in (None, 0) else None),
        "largest_cluster": max(len(vs) for vs in kume.values()),
    }


def gate_verdict(cs, min_clusters=2):
    """`cluster_stats` ciktisindan kapi hukmu.

    izleme_degeri_var : kenar SE'yi ASIYOR (edge > se)
    kenarda_tut       : olculdu ama kenar SE'yi asmiyor
    hesaplanamadi     : K < min_clusters -> kumeler-arasi varyans yok
    """
    if not cs or cs.get("k", 0) < min_clusters or cs.get("se") is None:
        return "hesaplanamadi"
    return "izleme_degeri_var" if (cs["edge"] or 0) > cs["se"] else "kenarda_tut"
