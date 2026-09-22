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
    ve `fetched_at` hangi gorusun ne zaman alindigini soyler. TEKILLIK (date, ticker, fetched_at).
    (date, ticker, run_label) tekil DEGILDIR — revizyonlar ayni etiketle birden cok satir uretir (relabel
    sonrasi 09-16 icin iki `backfill` satiri gibi); bunu varsayan okuyucu sessizce bozulur
    (pivot(index=[date,ticker], columns=run_label) hata verir; drop_duplicates(subset=[date,ticker,
    run_label]) varsayilan keep='first' ile siraya bagli olarak ESKI gorusu tutar, revizyonu sessizce atar).
    Canli gunde TIPIK 3 satir/hisse (slot basina bir: acilis kismi, gunici kismi, kapanis nihai); slotta
    verisi olmayan hisse eksik kalir (OLCULDU 09-21: acilis 627 / gunici 625 / kapanis 625 -> 2 hisse yalniz
    acilis). Revizyonlar ekler (09-21: 1877 satir/gun; tasarim bilincli, "boyut sapmasi" degil). Hicbir
    satir SILINMEZ (relabel dahil): iki satir iki ayri gorus.
  * SINIF SOZLESMESI — DORT DURUM, karsilastirma TR EKSENINDE (`cekim_tr_tarihi`; bar tarihi zaten TR):
      fetched_at gecersiz         -> ARIZI  (yazici: ArsivArizi, TUM batch reddedilir; okuyucu: sinif 'arizi')
      bar tarihi >  cekim TR gunu -> ARIZI  (gelecek bar uretilemez = veri hatasi; sessiz backfill YOK)
      bar tarihi <  cekim TR gunu -> backfill  (slot etiketi TASINMAZ)
      bar tarihi == cekim TR gunu -> slot / kapanis
    Gerekce: 09-21 07:36Z'de cekilen 09-15..18 NIHAI barlari "acilis-ani kismi bar" gibi etiketlenmisti (aktif
    yanlis anlam; 09-21 itibariyla 2583 satir, sonraki yazimlar sayiyi degistirir). TR ekseni: 21:00Z sonrasi elle
    dispatch (00:xx TR, 08-28'de yasandi) UTC'de ayni gun gorunur ama TR'de ERTESI gundur -> backfill (T15).
    "Esit degilse backfill" ILK SURUMUN HATASIYDI: gelecek bar ve gecersiz damga sessizce gecmis-gorus
    sayiliyordu (2026-09-22 disaridan okuma) -> T18.
  * MUHUR SAYACLARI — IKI AYRI KUME, birimleri KARISTIRILMAZ (durum dosyasi + append_bars donusu):
      kosum olayi: rejected_future_row_count, rejected_batch_row_count (SATIR) · invalid_fetched_at_event_count (OLAY)
      arsiv ici  : archive_future_row_count, archive_invalid_fetched_at_row_count (SATIR; `sinif_sayimi`)
    Canli muhur ONCE bu sayaclarin HEPSININ 0 oldugunu arar; degilse muhur GECERSIZ.
  * KANONIK BAR KURALI (tek okuyucu, kanonik_barlar()): (tarih, hisse) icin `kapanis` satiri varsa o;
    yoksa en son slot satiri (acilis/gunici, fetched_at'e gore); yoksa `backfill`; en son `arizi` (ARIZI satir
    gecerli satiri EZEMEZ ama GIZLENMEZ de, `sinif` alaninda gorunur). Eski yanlis etiketli satirlar SINIF
    SOZLESMESIYLE (bar_sinifi) dogru okunur -> dosya yeniden yazilmadan tutarli.
  * RELABEL KAPSAMI (`_relabel_kapsamda`, TEK OTORITE bar_sinifi): yalniz sinifi `backfill` olup etiketi henuz
    backfill OLMAYAN satir yeniden etiketlenir. ARIZI satir KAPSAM DISI — etiketini cevirmek arizayi normal
    gecmis-gorus gibi gosterir ve relabel olcumune katardi (2026-09-22 disaridan okuma, T18h).
  * PIT: sonradan gelen revizyon (backfill) kanonik kapanis barini DEGISTIRMEZ (revizyon dosyada durur,
    son_barlar() 'son gorus' olarak verir).
    Okuyucular kendi kuralini UYDURMAZ: tek bar isteyen kanonik_barlar(), son gorus isteyen son_barlar().
    Dogrudan okuma YASAK (selftest T16 tarar): gerekce yukaridaki tekillik — (date,ticker,run_label)'i anahtar
    sanan pandas okuyucusu hata vermeden yanlis sonuc uretir; iki okuyucu fonksiyon bu tuzagi kapsulleyen tek yer.
  * ATOMIK YAZIM (T17): CSV ve durum dosyasi ayni dizinde tmp + fsync + os.replace ile yazilir; kesinti ya da
    os.replace hatasi (OneDrive kilidi) hedefe DOKUNMAZ, temp silinir, hata cagirana gider. SINIR: atomiklik
    DOSYA BASINADIR, cok-dosyali transaction DEGIL — CSV yazilip durum JSON'u duserse eski durum korunur ve
    hata gorunur; yeniden kosum idempotent tamamlar (ayni icerik -> 0 satir, durum yeniden yazilir).
  * SEMA KARANTINASI (_satir_oku): eksik kolon (yarim satir) ya da fazla alan -> ArsivBozuk; append YAPILMAZ,
    dosya DEGISMEZ, sessiz kirpma YOK. Baslik dogrulamasi satir sayisindan bagimsizdir.
  * NaN kapanis = bar yok -> satir yazilmaz.
  * Kaynak `file` (donmus Excel'e dusus) ise ARSIVLENMEZ; durum dosyasi nedenini yazar.
  * docs/state/bar_archive.json: kosum sayaclari (liveness uyesi DEGIL; ileride olabilir).
  * Cagiran: daemon feed fazindan sonra, selfheal.guarded icinde (arsiv hatasi raporu dusurmez,
    ama loglanir). Workflow state-commit adimi data/bars/ dizinini ekler.
  * data/bars/.gitkeep TAKIPLI: `git add -f data/bars/` dizin bossa/yoksa pathspec hatasiyla state
    adimini dusururdu (daemon kosmayan always() adimi); .gitkeep dizini her zaman var eder.
Boyut (OLCULDU 2026-09-21, ilk canli gun): 1877 satir/gun (627 acilis + 625 gunici + 625 kapanis; kismi
barlar her kosumda degistigi icin 3 gorus/hisse/gun) ~150 KB/gun ~3 MB/ay. (Eski tahmin ~2 MB/ay yaniltiydi:
"degisen bar" kisiti canli gunde pratikte tam yazim demektir.)
"""
from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

COLUMNS = ["date", "ticker", "open", "high", "low", "close", "volume", "source", "run_label", "fetched_at"]
KUYRUK_GUN = 5          # feed'in son kac gunu islenir (gec gelen bar / revizyon yakalansin)
XU100 = "XU100"
ARSIVLENMEZ_KAYNAK = ("file",)
WRITER = "bist_alpha.bar_archive.append_bars"
BACKFILL = "backfill"                    # bar tarihi < cekim TR tarihi: slot etiketi tasinmaz
ARIZI = "arizi"                          # gecersiz fetched_at ya da GELECEK tarihli bar (sessiz backfill DEGIL)
TZ_TR = ZoneInfo("Europe/Istanbul")      # bar tarihi TR ekseninde; cekim tarihi de TR'ye cevrilip karsilastirilir


def cekim_tr_tarihi(fetched_at):
    """fetched_at (UTC 'Z' ISO) -> TR takvim tarihi 'YYYY-MM-DD'. Bar tarihi TR ekseninde oldugundan UTC tarihiyle
    karsilastirmak 21:00Z sonrasi cekimlerde (elle dispatch, 00:xx TR) bir gun kayardi (#1a eksen sinifi).
    Ayristirilamazsa '' -> cagiran taraf ARIZI sayar (T18). Bu donus TEK BASINA sinif DEGILDIR: siniflandirma
    otoritesi `bar_sinifi`, relabel kapsami `_relabel_kapsamda`. (ESKI metin "backfill = guvenli taraf" YANLISTI:
    gecersiz damgayi gecmis-gorus gibi gosteriyordu.)"""
    try:
        t = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if t.tzinfo is None:
        return ""
    return t.astimezone(TZ_TR).strftime("%Y-%m-%d")


_SINIF_SIRA = {"kapanis": 3, "slot": 2, BACKFILL: 1, ARIZI: 0}   # arizi satir gecerli satiri EZEMEZ


def bar_sinifi(row):
    """Satirin sinifi — DORT DURUM (sozlesme, 2026-09-22):
         fetched_at gecersiz        -> 'arizi'   (sessiz backfill DEGIL)
         bar tarihi > cekim TR gunu -> 'arizi'   (gelecek bar: uretilemez, veri hatasi)
         bar tarihi < cekim TR gunu -> 'backfill'
         bar tarihi == cekim TR gunu-> 'kapanis' (etiket kapanissa) ya da 'slot'
    Etiketi BACKFILL olan satir gecerli damgayla backfill sayilir; gecersiz damga once gelir."""
    cek = cekim_tr_tarihi(row.get("fetched_at", ""))
    if not cek:
        return ARIZI
    bar = row.get("date") or ""
    if bar > cek:
        return ARIZI
    if row.get("run_label") == BACKFILL or bar < cek:
        return BACKFILL
    return "kapanis" if row.get("run_label") == "kapanis" else "slot"


def sinif_sayimi(path):
    """Muhur girdisi — ARSIV-ICI sayim, birim = SATIR (kosum-olayi sayaclariyla KARISTIRILMAZ). Donus:
       {archive_future_row_count, archive_invalid_fetched_at_row_count, arizi_anahtar:[(tarih,hisse)...]}"""
    gelecek = gecersiz = 0
    anahtar = set()
    for r in _satir_oku(path):
        cek = cekim_tr_tarihi(r.get("fetched_at", ""))
        if not cek:
            gecersiz += 1; anahtar.add((r["date"], r["ticker"]))
        elif (r.get("date") or "") > cek:
            gelecek += 1; anahtar.add((r["date"], r["ticker"]))
    return {"archive_future_row_count": gelecek, "archive_invalid_fetched_at_row_count": gecersiz,
            "arizi_anahtar": sorted(anahtar)}


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


class ArsivBozuk(ValueError):
    """Arsiv dosyasi semaya uymuyor (eksik/fazla kolon, yarim satir). Sessiz kirpma YERINE gorunur hata."""


class ArsivArizi(ValueError):
    """Sinif SOZLESMESI ihlali: gecersiz fetched_at ya da GELECEK tarihli bar. Sessiz 'backfill' YERINE gorunur hata
    (2026-09-22 disaridan okuma: 'esit degilse backfill' kurali iki ayri arizayi gecmis-gorus gibi etiketliyordu)."""


def _satir_oku(path):
    """Arsiv satirlarini OKU ve SEMAYI DOGRULA. csv.DictReader eksik alani sessizce None yapar, fazlasini
    restkey'e atar; yarim satir (kesinti artigi) boylece 'gecerli veri' gibi gorunurdu -> ArsivBozuk.
    Donus: [dict]. Dosya yoksa []."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
        if rd.fieldnames is not None and rd.fieldnames != COLUMNS:
            # satir SAYISINDAN bagimsiz: yalniz (yanlis) baslik tasiyan dosya da bozuktur — eklenen satirlar
            # yanlis semaya yapisirdi. Bos dosya (0 bayt) -> fieldnames None -> satir yok, hata yok.
            raise ArsivBozuk(f"{os.path.basename(path)}: kolonlar COLUMNS ile ayni degil: {rd.fieldnames}")
    for i, r in enumerate(rows, start=2):                    # 1 = baslik satiri
        if None in r:                                        # fazla alan -> restkey
            raise ArsivBozuk(f"{os.path.basename(path)}:{i}: satirda FAZLA alan var (sema disi) -> karantina")
        if any(v is None for v in r.values()):               # eksik alan -> yarim satir
            eksik = [k for k, v in r.items() if v is None]
            raise ArsivBozuk(f"{os.path.basename(path)}:{i}: YARIM SATIR, eksik kolon {eksik} -> karantina "
                             "(append yapilmadi; dosya degistirilmedi; sessiz kirpma yok)")
    return rows


def _atomik(path, yaz):
    """Ayni dizinde gecici dosyaya yaz + fsync + os.replace. `yaz(fh)` patlarsa (kesinti mutasyonu) ya da
    replace PermissionError verirse (OneDrive): HEDEF DOSYA DOKUNULMAZ, temp SILINIR, hata YUKARI gider."""
    import tempfile
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".bars_", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            yaz(fh)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def _son_degerler(path):
    """Dosyadaki (tarih, hisse) -> son satirin (open, high, low, close, volume) metinleri."""
    son = {}
    for r in _satir_oku(path):
        son[(r["date"], r["ticker"])] = (r["open"], r["high"], r["low"], r["close"], r["volume"])
    return son


def son_barlar(path):
    """Tuketici: (tarih, hisse) -> SON gorus satiri (dict). Gunici kismi bar kapanisla, eski
    gorus revizyonla ezilir (dosyada ikisi de durur). Tek KANONIK bar icin kanonik_barlar()."""
    out = {}
    for r in _satir_oku(path):
        out[(r["date"], r["ticker"])] = r
    return out


def kanonik_barlar(path):
    """Tuketici: (tarih, hisse) -> TEK kanonik satir (dict + 'sinif'). Kural (modul docstring):
    kapanis > en son slot (fetched_at) > backfill. Sinif fetched_at kuralindan turetilir, etiket
    yanlis olsa da (eski satirlar). Backfill revizyonu kanonik kapanisi ezmez (PIT)."""
    out = {}
    for r in _satir_oku(path):
        r = dict(r); r["sinif"] = bar_sinifi(r)
        k = (r["date"], r["ticker"]); eski = out.get(k)
        if eski is None or (_SINIF_SIRA[r["sinif"]], r["fetched_at"]) >= (_SINIF_SIRA[eski["sinif"]], eski["fetched_at"]):
            out[k] = r
    return out


def _relabel_kapsamda(row):
    """Relabel KAPSAMI — TEK OTORITE `bar_sinifi`: yalniz sinifi BACKFILL olan (gecerli damga + gecmis bar)
    ama etiketi henuz backfill OLMAYAN satir. ARIZI satir (gelecek bar / gecersiz damga) KAPSAM DISIDIR:
    etiketini backfill'e cevirmek arizayi NORMAL gecmis-gorus gibi gosterir ve relabel olcumune katardi."""
    return bar_sinifi(row) == BACKFILL and row.get("run_label") != BACKFILL


def backfill_etiketle(path):
    """Eski satirlari yeniden etiketle — kapsam `_relabel_kapsamda` (tek otorite bar_sinifi; ARIZI satir HARIC).
    Idempotent; satir sayisi ve diger kolonlar aynen; atomik yazim, LF. Donus: degisen satir sayisi."""
    if not os.path.exists(path):
        return 0
    rows = _satir_oku(path)              # sema disi/yarim satir -> ArsivBozuk (fazla kolon sessizce dusurulurdu)
    n = 0
    for r in rows:
        if _relabel_kapsamda(r):
            r["run_label"] = BACKFILL; n += 1
    if n == 0:
        return 0

    def _yaz(fh):
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    _atomik(path, _yaz)
    return n


def relabel_kuru_kosum(path):
    """Relabel'in IKI YONLU kabul olcumu, dosyaya DOKUNMADAN (gecici kopya). Donus:
      relabel          : backfill_etiketle'nin degistirecegi satir sayisi (n); relabel_bagimsiz = ayni sayi yuklemden
      satir_ayni       : satir sayisi once == sonra (relabel SILMEZ; dosya salt-ekleme, PK yok)            (YON 1)
      kanonik_bozulan  : kanonik ciktida run_label HARIC (sinif/OHLCV/fetched_at) degisen anahtar -> 0      (YON 1)
      kanonik_degisen  : kanonik ciktida run_label'i degisen anahtar sayisi (olculen)
      karisik_anahtar  : kapsamli (yanlis etiketli) satirla kapsam-disi satiri BIRLIKTE tasiyan anahtar sayisi
      yan_sart_ihlal   : karisik anahtarlardan kanonigi KAPSAMLI satir olanlar (liste) -> bos olmali
      beklenen         : |kapsamli satiri olan anahtar| − |karisik ∧ kanonik kapsam-disi|
                         = relabel − Σ(r_k−1) − |karisik| (yan sart saglaniyorsa); kanonik kuralindan bagimsiz sayim (YON 2)
      tutuyor          : satir_ayni ∧ bozulan==0 ∧ degisen==beklenen ∧ n==relabel_bagimsiz ∧ yan_sart_ihlal==[]
    Karisik anahtar relabel penceresinde BEKLENIR (pencere gunlerinin revize barlari: eski yanlis etiket + yeni dogru
    backfill); yan sart 'kanonik = kapsam-disi satir' saglandikca genisletilmis form kesindir (09-22 kullanici)."""
    import shutil, tempfile
    bos = {"relabel": 0, "relabel_bagimsiz": 0, "satir_ayni": True, "kanonik_bozulan": 0, "kanonik_degisen": 0,
           "karisik_anahtar": 0, "yan_sart_ihlal": [], "beklenen": 0, "tutuyor": True}
    if not os.path.exists(path):
        return bos
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    kapsam = {}; toplam = {}
    for r in rows:
        k = (r["date"], r["ticker"]); toplam[k] = toplam.get(k, 0) + 1
        if _relabel_kapsamda(r):         # TEK OTORITE: arizi satir kapsamda DEGIL
            kapsam[k] = kapsam.get(k, 0) + 1
    n_bagimsiz = sum(kapsam.values())
    once = kanonik_barlar(path)
    karisik = [k for k, r in kapsam.items() if toplam[k] > r]
    ihlal = [k for k in karisik if _relabel_kapsamda(once[k])]
    beklenen = len(kapsam) - (len(karisik) - len(ihlal))
    with tempfile.TemporaryDirectory() as td:
        kopya = os.path.join(td, os.path.basename(path))
        shutil.copyfile(path, kopya)
        n = backfill_etiketle(kopya)
        with open(kopya, encoding="utf-8", newline="") as fh:
            satir_sonra = sum(1 for _ in csv.DictReader(fh))
        sonra = kanonik_barlar(kopya)
    alan = ("sinif", "open", "high", "low", "close", "volume", "fetched_at")
    bozulan = sum(1 for k in once if k not in sonra or any(once[k][a] != sonra[k][a] for a in alan)) + sum(1 for k in sonra if k not in once)
    degisen = sum(1 for k in once if k in sonra and once[k]["run_label"] != sonra[k]["run_label"])
    satir_ayni = satir_sonra == len(rows)
    return {"relabel": n, "relabel_bagimsiz": n_bagimsiz, "satir_ayni": satir_ayni, "kanonik_bozulan": bozulan,
            "kanonik_degisen": degisen, "karisik_anahtar": len(karisik), "yan_sart_ihlal": sorted(ihlal),
            "beklenen": beklenen,
            "tutuyor": satir_ayni and bozulan == 0 and degisen == beklenen and n == n_bagimsiz and not ihlal}


def _satirlar_ham(data, run_label, fetched_at):
    """Sozlesme KONTROLU YAPMADAN aday satirlar — yalniz REDDEDILEN batch'i saymak icin (yazima girmez)."""
    prices = data["prices"]
    bist = data.get("bist")
    for d in list(prices.index[-KUYRUK_GUN:]):
        ds = d.strftime("%Y-%m-%d")
        for t in prices.columns:
            if _num(_cell(prices, d, t)) != "":
                yield {"date": ds, "ticker": str(t)}
        if bist is not None:
            try:
                if _num(bist.loc[d]) != "":
                    yield {"date": ds, "ticker": XU100}
            except Exception:
                pass


def _satirlar(data, run_label, fetched_at):
    """Feed sozlugunden aday satirlar (son KUYRUK_GUN gun)."""
    prices = data["prices"]
    opens, mins, maxs, vols = (data.get(k) for k in ("opens", "mins", "maxs", "volumes"))
    bist = data.get("bist")
    # provenance: TAM kaynak dizgesi (orn. 'borsapy_fallback_from_yahoo' = birincil dustu), taban degil
    source = str(data.get("_source") or data.get("_source_base") or "")
    cekim_tarihi = cekim_tr_tarihi(fetched_at)            # TR tarih (bar tarihiyle ayni eksen)
    if not cekim_tarihi:
        raise ArsivArizi(f"fetched_at ayristirilamadi: {fetched_at!r} -> ARIZI (tum barlar sessizce backfill olurdu)")
    tarihler = list(prices.index[-KUYRUK_GUN:])
    gelecek = [d.strftime("%Y-%m-%d") for d in tarihler if d.strftime("%Y-%m-%d") > cekim_tarihi]
    if gelecek:
        raise ArsivArizi(f"GELECEK tarihli bar: {gelecek} > cekim {cekim_tarihi} -> ARIZI "
                         f"(sessiz backfill YOK; satir yazilmadi)")
    for d in tarihler:
        ds = d.strftime("%Y-%m-%d")
        etiket = run_label if ds == cekim_tarihi else BACKFILL   # gecmis gun = backfill, slot etiketi tasinmaz
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
                   "source": source, "run_label": etiket, "fetched_at": fetched_at}
        if bist is not None:
            try:
                bc = _num(bist.loc[d])
            except Exception:
                bc = ""
            if bc != "":
                yield {"date": ds, "ticker": XU100, "open": "", "high": "", "low": "", "close": bc, "volume": "",
                       "source": source, "run_label": etiket, "fetched_at": fetched_at}


def _durum_yaz(root, durum):
    p = os.path.join(root, "docs", "state", "bar_archive.json")

    def _yaz(fh):
        json.dump(durum, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    _atomik(p, _yaz)                     # kesinti: eski durum dosyasi saglam kalir (T17b)


def _fetched_at(now):
    """Cekim damgasi (UTC 'Z'). AYRI FONKSIYON: gecersiz-damga hata kolu boylece ERISILEBILIR ve test edilebilir
    (aksi halde append_bars damgayi kendi uretip her zaman gecerli yapardi -> kol olu kod olurdu)."""
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_bars(data, run_label, root, now=None):
    """Feed'in son gunlerini arsive ekle. Donus: durum sozlugu (docs/state/bar_archive.json ile ayni)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("append_bars: naive datetime kabul etmez (eksen belirsiz)")
    fetched_at = _fetched_at(now)
    source = str(data.get("_source_base") or data.get("_source") or "")
    durum = {"writer": WRITER, "generated_at": fetched_at, "run_label": run_label,
             "source": str(data.get("_source") or source),
             "rows_seen": 0, "rows_added": 0, "dates": [], "files": [], "skipped_reason": None,
             # MUHUR GIRDISI — iki AYRI kume, hepsi 0 OLMALI (birimleri karistirma):
             #   kosum olayi (bu kosumda ne REDDEDILDI)      : rejected_* (satir) + invalid_fetched_at_event_count (olay)
             #   arsiv ici   (dosyada ne DURUYOR)            : archive_* (satir)
             "rejected_future_row_count": 0, "rejected_batch_row_count": 0,
             "invalid_fetched_at_event_count": 0,
             "archive_future_row_count": 0, "archive_invalid_fetched_at_row_count": 0}
    if source in ARSIVLENMEZ_KAYNAK or str(data.get("_source", "")).startswith("file"):
        durum["skipped_reason"] = f"kaynak '{data.get('_source') or source}' donmus dosya: arsivlenmez"
        _durum_yaz(root, durum)
        return durum

    try:
        aday = list(_satirlar(data, run_label, fetched_at))
    except ArsivArizi as exc:                       # gelecek bar / gecersiz damga: TUM BATCH reddedilir, durum yazilir
        cek = cekim_tr_tarihi(fetched_at)
        if cek:
            # birim = SATIR (sinif_sayimi ile ayni birim); gelecek tarihli gunlerin satirlari + batch toplami
            gelecek_gun = {d.strftime("%Y-%m-%d") for d in list(data["prices"].index[-KUYRUK_GUN:])
                           if d.strftime("%Y-%m-%d") > cek}
            hepsi = list(_satirlar_ham(data, run_label, fetched_at))
            durum["rejected_future_row_count"] = sum(1 for r in hepsi if r["date"] in gelecek_gun)
            durum["rejected_batch_row_count"] = len(hepsi)
        else:
            # gecersiz damga: OLAY sayilir (satir UYDURULMAZ) ama reddedilen batch'in HAM satir sayisi yazilir
            # (eskiden 0 yaziliyordu: "tum batch reddedildi" ile celisiyordu). Kol ERISILEBILIR: _fetched_at seam'i.
            durum["invalid_fetched_at_event_count"] = 1
            durum["rejected_batch_row_count"] = len(list(_satirlar_ham(data, run_label, fetched_at)))
        durum["skipped_reason"] = f"ARIZI: {exc}"
        _durum_yaz(root, durum)
        raise
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
        yeni_dosya = not os.path.exists(p) or os.path.getsize(p) == 0
        if yeni_dosya:
            mevcut = ""
        else:
            with open(p, encoding="utf-8", newline="") as _fh:      # context manager: Windows/OneDrive'da acik tutma
                mevcut = _fh.read()
            if not mevcut.endswith("\n"):
                # sonu newline'siz GECERLI dosya (son satir eksiksiz): yeni satir eskisine YAPISMAMALI.
                # Yarim satir bu noktaya gelemez (_satir_oku eksik kolonu ArsivBozuk yapar); tek istisna,
                # kesintinin tam alan sinirinda olmasi — o durum ayirt edilemez, belgelendi.
                mevcut += "\n"

        def _yaz(fh, mevcut=mevcut, yeni_dosya=yeni_dosya, yeni=yeni):
            w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
            if yeni_dosya:
                w.writeheader()
            else:
                fh.write(mevcut)         # mevcut icerik AYNEN; yarim satir _satir_oku'da zaten yakalandi
            w.writerows(yeni)
        # salt-ekleme SEMANTIGI korunur, YAZIM atomiktir: kesinti yarim satir birakmaz (T17a/c)
        _atomik(p, _yaz)
        durum["rows_added"] += len(yeni)
        durum["files"].append(os.path.relpath(p, root).replace(os.sep, "/"))
    for _p in {b[0] for b in buffers.values()}:      # yazilan dosyalarda ARIZI satir kaldi mi (arsiv-ici, SATIR)
        _say = sinif_sayimi(_p)
        durum["archive_future_row_count"] += _say["archive_future_row_count"]
        durum["archive_invalid_fetched_at_row_count"] += _say["archive_invalid_fetched_at_row_count"]
    _durum_yaz(root, durum)
    return durum
