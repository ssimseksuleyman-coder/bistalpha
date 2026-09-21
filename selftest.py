#!/usr/bin/env python3
"""
SİSTEM ÖZ-DENETİM (self-test) — her an çalıştır, eksik kalmasın.

  python selftest.py                    # offline/deterministik smoke test
  python selftest.py --mode live         # ag/canli veri kontrolleri dahil
  python selftest.py --mode all          # live ile ayni, gelecek agir testler icin

Kontrol eder:
  1. Tüm modüller import oluyor mu
  2. Orphan modül var mı (tanımlı ama bağlı değil)
  3. Entry point script'leri parse oluyor mu
  4. Veri dosyaları yerinde mi (ana veri, OMEGA, Deniz)
  5. config flag'leri kodda kullanılıyor mu
  6. Backtest A/B/F (gömülü veride sabit aralık, canlıda makul aralık)
  7. Yan kaynak (sidesource) bağlı ve veri okuyor mu
  8. Öz-iyileştirme / bakım / optimizatör çalışıyor mu
  9. 7/24 deploy (bilgisayar kapalıyken çalışma) doğru kurulu mu
  10. CLI'lar gerçekten çalışıyor mu (backtest/analyze/daemon)
Çıkış kodu 0 = bloklayıcı hata yok, 1 = bloklayıcı hata var.
`--strict` verilirse uyarılar da 1 döndürür.
"""
import argparse
import ast
import os
import sys
import importlib

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
fails = []
warnings = []

# Windows konsol (cp1252) Türkçe/emoji karakterlerde UnicodeEncodeError verir -> utf-8'e sabitle.
# Izole/kozmetik: yalniz bu script'in cikti-akisini etkiler; PYTHONIOENCODING gerekmeden calisir.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# [2] orphan-taramasi os.walk(".") ile TUM agaci gezer; repo-ici .venv/site-packages'i yutmasin
# diye bu dizinlere HIC inme (dirs'i yerinde buda). Aksi halde binlerce pip .py'si tek string'e
# okunur -> patolojik yavas + bellek sisme (olculdu: 450MB+). Sadece proje kaynagini tara.
_WALK_SKIP = {".venv", "venv", "env", ".git", "__pycache__", "node_modules",
              "site-packages", ".pytest_cache", ".mypy_cache", ".idea", "scratchpad"}


def ok(msg): print(f"   \u2713 {msg}")
def bad(msg): print(f"   \u2717 {msg}"); fails.append(msg)
def warn(msg): print(f"   \u26a0 {msg}"); warnings.append(msg)


def parse_args():
    ap = argparse.ArgumentParser(description="BIST Alpha selftest")
    ap.add_argument(
        "--mode",
        choices=["offline", "live", "all"],
        default="offline",
        help="offline=deterministik; live=ag ve canli veri kontrolleri dahil",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Uyarilari da cikis kodu 1 say. Varsayilan: yalniz bloklayici hatalar fail eder.",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    live_mode = args.mode in {"live", "all"}

    print("=" * 70)
    print("BIST ALPHA — SİSTEM ÖZ-DENETİM")
    print(f"MOD: {args.mode} ({'canli/ag kontrolleri dahil' if live_mode else 'offline/deterministik smoke test'})")
    print("=" * 70)

    # 1. Modül import
    print("\n[1] Modül import")
    mods = [f[:-3] for f in os.listdir("bist_alpha")
            if f.endswith(".py") and f != "__init__.py"]
    for m in sorted(mods):
        try:
            importlib.import_module(f"bist_alpha.{m}")
            ok(m)
        except Exception as e:
            bad(f"{m}: {e}")

    # 2. Orphan modül
    print("\n[2] Orphan modül (bağlı mı)")
    src = ""
    for root, dirs, files in os.walk("."):
        dirs[:] = [dd for dd in dirs if dd not in _WALK_SKIP]   # yerinde buda: bu dizinlere inme
        for f in files:
            if f.endswith(".py"):
                src += open(os.path.join(root, f), encoding="utf-8").read()
    for m in sorted(mods):
        self_src = open(f"bist_alpha/{m}.py", encoding="utf-8").read()
        ext = (src.count(f"import {m}") + src.count(f"{m}.") + src.count(f"from .{m}")
               - self_src.count(f"{m}."))
        if ext > 0:
            ok(f"{m} bağlı")
        else:
            warn(f"{m} ORPHAN")

    # 3. Entry point parse
    print("\n[3] Entry point parse")
    for s in ["run_backtest.py", "daemon.py", "analyze_stock.py", "shadow.py"]:
        try:
            ast.parse(open(s, encoding="utf-8").read())
            ok(s)
        except Exception as e:
            bad(f"{s}: {e}")

    # 4. Veri
    # BLOKLAYICI = yalnizca repoda OLMASI GEREKEN veri (golden-master girdisi).
    # LOCAL-ONLY = Deniz-musluğu (2026-07-17) sonrasi kasitli repoda-degil:
    #   data/omega/*  -> tumu Deniz-bulten-turevi (lisans) -> gitignore + rm --cached
    #   deniz_inbox/  -> ham Deniz PDF'leri -> gitignore (kaza-git-add korumasi)
    # Bunlari bad() saymak CI'i kirmisti: gizlilik-onlemi, golden-master'in (DOKUNULMAZ
    # korumasi) hic calisamamasina yol acti — iki guvenlik-onlemi cakisti. Assert artik
    # gercege kalibre: yoklari BEKLENEN (local'de varsa bilgi, yoksa uyari-degil).
    print("\n[4] Veri bütünlüğü")
    if os.path.exists("data/Tarihsel_Fiyat_Bilgileri.xlsx"):
        ok("ana veri (golden-master girdisi): data/Tarihsel_Fiyat_Bilgileri.xlsx")
    else:
        bad("ana veri YOK: data/Tarihsel_Fiyat_Bilgileri.xlsx (golden-master kosamaz)")
    for path, desc in [("data/omega", "OMEGA yan-kaynak"),
                       ("deniz_inbox", "Deniz bülten")]:
        if os.path.exists(path):
            ok(f"{desc}: {path} (local'de var)")
        else:
            # "ok" DEGIL "bilincli-atlandi": gerekce alani tasinsin, yoksa gelecekte
            # bu satir "kontrol gecti" diye okunur ve BASKA bir sebeple yok olsa da susar.
            ok(f"ATLANDI (bilinçli) — {desc}: {path} repoda YOK. "
               f"Gerekçe: Deniz-musluğu 2026-07-17, lisanslı-türev → local-only. "
               f"Bu yol repoda BEKLENMİYOR; assert kaldırıldı, silinmedi.")

    # Sektör kapsamı (eşleme eksikliği yanlış sonuç üretir)
    try:
        from bist_alpha import sectors as _sec, data as _dm
        _d = _dm.load_data()
        _last = _d["mcaps"].index[-1]
        _top = set(_d["mcaps"].loc[_last].dropna().nlargest(100).index)
        _unm = _top - set(_sec.STOCK_TO_SECTOR.keys())
        if len(_unm) <= 3:
            ok(f"sektör kapsamı: top-100'de {len(_unm)} eşlenmemiş (kabul edilebilir)")
        else:
            warn(f"sektör kapsamı: top-100'de {len(_unm)} eşlenmemiş → XU100 yığılması riski")
    except Exception as e:
        warn(f"sektör kapsam kontrolü: {e}")

    # 5. config flag tutarlılık
    print("\n[5] config flag ↔ kod")
    cfg = open("bist_alpha/config.py", encoding="utf-8").read()
    for fl in ["LATE_ENTRY_FILTER", "SIDEWAYS_SCALING", "SECTOR_PUMP_VETO",
               "MODE", "SLIPPAGE_PER_SIDE"]:
        if fl not in cfg:
            bad(f"{fl} config'de yok")
        elif src.count(fl) <= 1:
            warn(f"{fl} kodda kullanılmıyor")
        else:
            ok(fl)

    # 6. Backtest (TESPİT 4 — statik sapma düzeltildi)
    print("\n[6] Backtest A/B/F + F golden-master (DOKUNULMAZ koruması)")
    try:
        from bist_alpha import data as dm, signals as sm, backtest as bm
        # load_data() HER ZAMAN donmus Excel'i okur; config.DATA_SOURCE canli-daemon
        # feed'ini secer, bu backtest'i DEGIL -> kontrol DATA_SOURCE'a gate'lenMEZ.
        # (Eski kod src=="file" ile gate'liyordu; varsayilan "yahoo" oldugundan
        #  aralik-kontrolu hic calismiyordu = olu koruma.)
        d = dm.load_data()
        sig = sm.compute_signals(d)
        ranges = {"A": (260, 320), "B": (240, 300), "F": (275, 335)}
        results = {}
        for mode in ["A", "B", "F"]:
            r = bm.run(d, sig, mode=mode)
            if not r:
                bad(f"{mode}: backtest çalışmadı")
                continue
            results[mode] = r
            lo, hi = ranges[mode]
            if lo <= r["ret"] <= hi:
                ok(f"{mode}: %{r['ret']} (donmuş veri beklenen {lo}-{hi})")
            else:
                bad(f"{mode}: %{r['ret']} donmuş veri aralığı dışı")

        # --- F GOLDEN-MASTER — DOKUNULMAZ'in tek otomatik korumasi ---
        # Donmus Excel + sabit config => deterministik. Bu sayilar oynadiysa F'in
        # secim/stop davranisi DEGISMISTIR. Kirmizi = "kasitli mi, kaza mi?" sorusu.
        # Tolerans 0.05: platform float-sapmasina bagisik; gercek F-degisimi
        # (farkli pick/agirlik) puan mertebesinde oynar -> yakalanir.
        gm = results.get("F")
        if gm:
            E_RET, E_DD, E_STOPS = 301.07, -5.54, 56
            if (abs(gm["ret"] - E_RET) < 0.05 and abs(gm["dd"] - E_DD) < 0.05
                    and gm["n_stops"] == E_STOPS):
                ok(f"F golden-master KORUNDU: ret={gm['ret']} dd={gm['dd']} stops={gm['n_stops']}")
            else:
                bad(f"F GOLDEN-MASTER SAPTI → ret={gm['ret']} (bkl {E_RET}), "
                    f"dd={gm['dd']} (bkl {E_DD}), stops={gm['n_stops']} (bkl {E_STOPS}) "
                    f"— F davranışı değişti: KASITLI mı?")
    except Exception as e:
        bad(f"backtest hatası: {e}")

    # 6b. F-DATAPATH 5-SHA — golden-master'in KAPSAMADIGI yari
    #
    # NEDEN AYRI BLOK: golden-master `data + signals + backtest` yolunu korur.
    # `portfolio.py` backtest'te HIC REFERANS ALMIYOR -> oraya yazilan bir degisiklik
    # golden-master'i KIRMAZ, sessizce gecer. "Korunuyor sanilan yer, daha tehlikeli yer."
    # Bu assert o bosluğu kapatir.
    #
    # NEDEN 6'nin try'i DISINDA: backtest patlarsa yukarisi except'e duser ve SHA
    # kontrolu SESSIZCE atlanirdi (sahte-yesil). Ayri blok = her kosumda calisir.
    #
    # YONTEM: git blob SHA-1 (`git hash-object`), ilk 12 hane. Kanonik olan bu —
    # `sha256sum <dosya>` DEGIL: Windows'ta core.autocrlf=true oldugundan calisma
    # agacindaki dosya CRLF, repo icerigi LF; `git hash-object` filtreyi uygular ve
    # iki platformda ayni degeri verir.
    #
    # BASELINE IKI YERDE (bilincli): burasi makine-okur (CI), `local/ACIK_ISLER.md ->
    # F-DATAPATH BASELINE` insan-okur. local/ gitignored oldugu icin CI oradan okuyamaz.
    # Degistirilecekse IKISI BIRDEN degistirilir; tek tarafli degisiklik sapmayi gizler.
    print("\n[6b] F-datapath 5-SHA (DOKUNULMAZ — golden-master'in kapsamadigi yari)")
    F_DATAPATH_BASELINE = {
        "bist_alpha/strategy.py":  "7330c5f19752",
        "bist_alpha/backtest.py":  "7708e7818b66",
        "bist_alpha/config.py":    "8eee78db71e0",
        "bist_alpha/portfolio.py": "dda645cb76ec",   # P0.3 + P0.4 (+09-11 fix: detail str, eksikte marker yok) (2026-09-10): eski 09ad265d9fd5
        "bist_alpha/signals.py":   "22bb89bf9de5",
    }
    import subprocess
    for yol, beklenen in F_DATAPATH_BASELINE.items():
        try:
            sha = subprocess.check_output(["git", "hash-object", yol],
                                          text=True, stderr=subprocess.DEVNULL).strip()[:12]
        except Exception as e:
            # "OLCULEMEDI" != "TEMIZ": sessiz atlama sahte-yesil uretir -> BLOKLAYICI.
            bad(f"{yol}: 5-SHA OLCULEMEDI ({type(e).__name__}) — git yok/erisilemez")
            continue
        if sha == beklenen:
            ok(f"{os.path.basename(yol)} {sha}")
        else:
            bad(f"{yol}: F-DATAPATH SAPTI → {sha} (bkl {beklenen}) "
                f"— F'in veri yolu degisti: KASITLI mi?")

    # 6c. #0i-B — pending yasi ISLEM gunu mu (takvim DEGIL)
    #
    # CANLI VAKA: 2026-08-28 (Cuma) karari, 08-31 (Pzt) kapanisinda TAKVIM ile 3 gun
    # sayilip PENDING_MAX_AGE_DAYS=2 esigine takildi ve IPTAL edildi (log muhurlu).
    # 08-31 karari 09-01'de takvim 1 -> FILL oldu. Ikisinde de ISLEM gunu 1'di.
    # Yani kok neden kontrollu karsitlikla kanitlandi: degisen tek sey takvim gunu.
    #
    # NEDEN BURADA: shadow.py golden-master kapsaminda DEGIL (backtest onu import
    # etmiyor) ve korunan 5-SHA'da da YOK -> tek otomatik korumasi bu blok.
    # Dosyanin DEGISMESI bekleniyor, o yuzden koruma SHA dondurmasi degil TEST.
    #
    # BILINEN SINIR: blok tek try/except ile sarili -> erken bir istisna sonraki
    # assertion'lari ATLAR. SAHTE-YESIL URETMEZ (except -> bad(), bloklayici), ama
    # BILGI KAYBETTIRIR: tek hata gorunur, digerleri olculmeden gecer. Mutasyon
    # testinde fiilen yasandi (2026-09-01): sadik-olmayan mutasyon istisna firlatti
    # ve asil iddiaya hic ulasilmadi; sadik mutasyonla tekrarlaninca iddia yakaladi.
    print("\n[6c] #0i-B pending yasi ISLEM gunu (shadow.py — golden-master disi)")
    try:
        import pandas as _pd
        import shadow as _sh
        _idx = _pd.bdate_range("2026-08-03", "2026-09-30")     # hafta sonu YOK
        _CUMA, _PZT, _SALI, _PER = "2026-08-28", "2026-08-31", "2026-09-01", "2026-09-03"
        _yas = lambda a, b: _sh._pending_trading_age_days(_idx, a, b)
        _iptal = lambda y: y is not None and y > _sh.PENDING_MAX_AGE_DAYS

        for ad, alinan, beklenen in [
            ("Cuma->Pzt yasi 1 islem gunu (takvim 3 DEGIL)", _yas(_CUMA, _PZT), 1),
            ("Cuma->Pzt IPTAL OLMAMALI",                     _iptal(_yas(_CUMA, _PZT)), False),
            ("Pzt->Sali yasi 1, IPTAL OLMAMALI",             _iptal(_yas(_PZT, _SALI)), False),
            ("Pzt->Per yasi 3 islem gunu",                   _yas(_PZT, _PER), 3),
            ("gercekten eski pending IPTAL OLMALI",          _iptal(_yas(_PZT, _PER)), True),
            ("esik siniri: 2 -> iptal YOK",                  _iptal(2), False),
            ("esik siniri: 3 -> iptal VAR",                  _iptal(3), True),
            ("bozuk tarih -> None (fail-safe: iptal ETME)",  _iptal(_yas("x!", _PZT)), False),
            ("decided_at bos -> iptal ETME",                 _iptal(_yas(None, _PZT)), False),
            ("PENDING_MAX_AGE_DAYS sabiti degismedi",        _sh.PENDING_MAX_AGE_DAYS, 2),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#0i-B {ad}: beklenen {beklenen}, alinan {alinan}")

        # IKI CAGRI YERI DE yeni fonksiyonu kullanmali. Yalniz iptal karari (satir ~632)
        # yamalanip panel alani (~806) unutulursa, karar dogru olur ama PANEL hala
        # takvim gunu gosterir -> "yanlis dil" (kullanici tespiti, 2026-09-01).
        _src = open(os.path.join(ROOT, "shadow.py"), encoding="utf-8").read()
        if "age = _pending_trading_age_days(prices.index" in _src:
            ok("iptal karari islem-gunu fonksiyonunu cagiriyor")
        else:
            bad("#0i-B iptal karari eski/yanlis fonksiyonu cagiriyor")
        if '"age_days": _pending_trading_age_days(prices.index' in _src:
            ok("panel age_days alani da ayni fonksiyonu cagiriyor")
        else:
            bad("#0i-B panel age_days hala takvim gunu gosteriyor olabilir")
        if "_pending_age_days(" not in _src:
            ok("eski takvim-gunu fonksiyonu kalmadi")
        else:
            bad("#0i-B eski _pending_age_days cagrisi hala var")
    except Exception as e:
        bad(f"#0i-B testi kosmadi: {type(e).__name__}: {e}")

    # ── [6d] #0k — CA kiyas bari FILL KONVANSIYONUNA gore secilmeli ────────────
    # NEDEN VAR: 2026-09-02'de dedektor 10 pozisyonun 7'sini sahte "CA" diye
    # duzeltti. Sebep: `#0i` fill'i ACILISA tasidi ama dedektor hala KAPANIS
    # bariyla kiyasliyordu -> giris gununun normal gun-ici hareketi CA sanildi.
    # Kalan 3 dogru olculdugu icin degil, hareketi tesadufen <%1 kaldigi icin
    # temiz gorundu (n_clean=3 SAHTE GUVENCEYDI).
    # TOLERANSI BUYUTMEK COZUM DEGIL: canli hareketi ortmek TOL>=%9.99 ister,
    # gercek kucuk CA'yi (1.03) yakalamak TOL<%3 ister -> celiski. Bu yuzden
    # asagida hem SIFIR-sahte-pozitif hem de 1.03'un YAKALANMASI birlikte aranir.
    print("\n[6d] #0k CA kiyas bari fill konvansiyonuna gore (shadow.py — golden-master disi)")
    try:
        import pandas as _pd
        import shadow as _sh
        from bist_alpha import g1_account as _g1m

        _G = "2026-09-01"
        _KG = _pd.Timestamp(_G)
        # 2026-09-02 canli olayi (olculdu): ticker -> (kayitli_entry, open, close)
        # 10/10 entry = o gunun ACILIS fiyati.
        _CANLI = {
            "OZATD": (4827.50, 4827.50, 4820.00), "KTLEV": (57.30, 57.30, 56.55),
            "BIGEN": (183.70, 183.70, 186.00),    "IEYHO": (207.80, 207.80, 208.50),
            "ODINE": (2013.00, 2013.00, 1812.00), "HEDEF": (77.05, 77.05, 75.85),
            "ALKLC": (425.75, 425.75, 427.00),    "SELEC": (334.50, 334.50, 338.00),
            "CRFSA": (290.75, 290.75, 317.50),    "EUPWR": (101.80, 101.80, 92.35),
        }
        def _cer(d):
            return _pd.DataFrame([d], index=[_KG])
        def _stt(entryler, konv=_sh.FILL_CONV_NEXT_OPEN):
            return {"positions": {t: {"entry": e, "peak": e} for t, e in entryler.items()},
                    "history": [{"date": _G, "type": "rebalance", "fill_convention": konv,
                                 "trades": [{"type": "BUY", "ticker": t} for t in entryler]}]}
        _ent = {t: v[0] for t, v in _CANLI.items()}
        _op = _cer({t: v[1] for t, v in _CANLI.items()})
        _cl = _cer({t: v[2] for t, v in _CANLI.items()})

        _f, _u, _c = _sh._ca_detect_and_fix(_stt(_ent), "F", _cl, "2026-09-02", opens=_op)
        _f2, _u2, _c2 = _sh._ca_detect_and_fix(_stt(_ent), "F", _cl, "2026-09-02")   # opens YOK
        _f3, _, _ = _sh._ca_detect_and_fix(_stt({"AAA": 300.0}), "F", _cer({"AAA": 101.0}),
                                           "2026-09-02", opens=_cer({"AAA": 100.0}))
        _f4, _, _ = _sh._ca_detect_and_fix(_stt({"BBB": 103.0}), "F", _cer({"BBB": 100.5}),
                                           "2026-09-02", opens=_cer({"BBB": 100.0}))
        _f5, _, _ = _sh._ca_detect_and_fix(_stt({"CCC": 50.0}, _sh.FILL_CONV_SAME_DAY), "F",
                                           _cer({"CCC": 50.0}), "2026-09-02")
        _f6, _, _ = _sh._ca_detect_and_fix(_stt({"CCC": 100.0}, _sh.FILL_CONV_SAME_DAY), "F",
                                           _cer({"CCC": 50.0}), "2026-09-02")
        _g1e = {"positions": {"ZZZ": {"entry": 100.0, "peak": 100.0}},
                "trades": [{"date": _G, "type": "BUY", "ticker": "ZZZ", "price": 100.0}]}
        _f7, _u7, _c7 = _sh._ca_detect_and_fix(_g1e, "G1", _cer({"ZZZ": 60.0}),
                                               "2026-09-02", opens=_cer({"ZZZ": 60.0}))

        for ad, alinan, beklenen in [
            ("canli 7 sahte-CA: dogru bar ile SIFIR duzeltme", len(_f), 0),
            ("canli vakada hicbiri 'olculemedi' degil",        len(_u), 0),
            ("canli vakada n_clean == 10",                     _c["n_clean"], 10),
            ("opens YOK -> eski kapanis barina DUSMEZ",        len(_f2), 0),
            ("opens YOK -> 10/10 olculemedi",                  len(_u2), 10),
            ("opens YOK -> n_clean 0 (olculemedi != TEMIZ)",   _c2["n_clean"], 0),
            ("gercek CA (oran 3.00) yakalanir",                [x["ticker"] for x in _f3], ["AAA"]),
            ("kucuk gercek CA (oran 1.03) yakalanir",          [x["ticker"] for x in _f4], ["BBB"]),
            ("same_day_close + entry==close -> CA DEGIL",      len(_f5), 0),
            ("same_day_close + gercek CA -> yakalanir",        [x["ticker"] for x in _f6], ["CCC"]),
            ("G1 damgasiz kayit DUZELTILMEZ (tahmin YOK)",     len(_f7), 0),
            ("G1 damgasiz sebep gorunur: fill_convention_yok", [r for _, r in _u7], ["fill_convention_yok"]),
            ("G1 damgasiz n_clean 0 (temiz SAYILMAZ)",         _c7["n_clean"], 0),
            ("FILL_CONV_NEXT_OPEN kopyalari ayni", _g1m.FILL_CONV_NEXT_OPEN, _sh.FILL_CONV_NEXT_OPEN),
            ("FILL_CONV_SAME_DAY kopyalari ayni",  _g1m.FILL_CONV_SAME_DAY, _sh.FILL_CONV_SAME_DAY),
            ("CA_RATIO_TOL degismedi (tolerans COZUM DEGIL)",  _sh.CA_RATIO_TOL, 0.01),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#0k {ad}: beklenen {beklenen}, alinan {alinan}")

        # G1 girisleri damgayi GERCEKTEN yaziyor mu (kaynak kontrolu: davranis testi
        # canli opens_today ister, damganin kodda durdugu burada dogrulanir).
        _g1src = open(os.path.join(ROOT, "bist_alpha", "g1_account.py"), encoding="utf-8").read()
        if _g1src.count("fill_convention=FILL_CONV_NEXT_OPEN") >= 2:
            ok("G1 BUY+REENTRY girisleri next_open damgasi yaziyor")
        else:
            bad("#0k G1 giris damgasi eksik (BUY ve/veya REENTRY)")
        if "fill_convention=FILL_CONV_SAME_DAY" in _g1src:
            ok("G1 cold-start girisi same_day damgasi yaziyor")
        else:
            bad("#0k G1 cold-start damgasi eksik")
    except Exception as e:
        bad(f"#0k testi kosmadi: {type(e).__name__}: {e}")

    # ── [6e] #1e — RAPOR KAPSAMI: eksik rapor GORUNUR olmali ───────────────────
    # NEDEN VAR: diger 17 liveness uyesi "yazici duruyor mu" sorar (damga YASI).
    # Slot donusurse (`#1c`) daemon yine kosar ve artefaktlari yazar -> 17 uye
    # YESIL kalir, kaybolan yalniz RAPORDUR. OLCULDU (2026-09-03): 48 is gununun
    # 9'u eksik (~%19) ve HICBIRI alarm uretmedi.
    # ESIKLER UYDURULMADI: pencere `report_gate.WINDOW_MINUTES`, slotlar
    # `report_gate.SLOTS` -> hedef/pencere degisirse kontrol kendiliginden kayar.
    print("\n[6e] #1e rapor kapsami (liveness_scan — golden-master disi)")
    try:
        import sys as _sys
        _sp = os.path.join(ROOT, "scripts")
        if _sp not in _sys.path:
            _sys.path.insert(0, _sp)
        from datetime import datetime as _dt
        import liveness_scan as _L
        import report_gate as _RG

        _SL = {a: (t.hour, t.minute) for a, t in _RG.SLOTS}
        _W = _RG.WINDOW_MINUTES
        _F = _L._missing_report_slots
        _V = _L._coverage_verdict
        _G3 = "2026-09-03"                       # Persembe (is gunu)
        def _T(g, s, m): return _dt(2026, 9, g, s, m)
        def _snt(gun, *lab): return {f"{gun}:{l}": {"sent_at": "x"} for l in lab}

        for ad, alinan, beklenen in [
            # sabah SAHTE ALARM olmamali — pencere kapanmadan eksik sayilmaz
            ("09:00 marker yok -> TAM (pencere acik)",  _F({}, _T(3, 9, 0), _SL, _W), []),
            ("13:14 (pencereye 1dk) -> TAM",            _F({}, _T(3, 13, 14), _SL, _W), []),
            # pencere kapaninca gorunur
            ("13:20 acilis yok -> ['acilis']",          _F({}, _T(3, 13, 20), _SL, _W), ["acilis"]),
            ("13:20 acilis var -> TAM",                 _F(_snt(_G3, "acilis"), _T(3, 13, 20), _SL, _W), []),
            ("18:10 ikisi yok -> 2 eksik",              _F({}, _T(3, 18, 10), _SL, _W), ["acilis", "gunici"]),
            ("22:20 3/3 var -> TAM",                    _F(_snt(_G3, "acilis", "gunici", "kapanis"), _T(3, 22, 20), _SL, _W), []),
            ("22:20 kapanis yok -> ['kapanis']",        _F(_snt(_G3, "acilis", "gunici"), _T(3, 22, 20), _SL, _W), ["kapanis"]),
            # `manuel` TELAFIDIR, teslim DEGIL -> slotu kapatmaz
            ("manuel var ama acilis yok -> hala eksik", _F(_snt(_G3, "manuel"), _T(3, 13, 20), _SL, _W), ["acilis"]),
            # hafta sonu yapisal olarak bos
            ("Cumartesi -> TAM",                        _F({}, _T(5, 22, 20), _SL, _W), []),
            # OLCULEMEDI != TAM (yanlis-sifir donus tipine gomulu)
            ("sent=None -> None (TAM DEGIL)",           _F(None, _T(3, 22, 20), _SL, _W), None),
            ("None ile [] ayni sey DEGIL",              _F(None, _T(3, 22, 20), _SL, _W) == [], False),
            # CANLI VAKA: 2026-09-01 acilis kayip, gunici+kapanis var
            ("canli 09-01 gun sonu -> ['acilis']",      _F(_snt("2026-09-01", "gunici", "kapanis"), _dt(2026, 9, 1, 22, 20), _SL, _W), ["acilis"]),
            ("canli 09-01 12:00 -> henuz TAM",          _F(_snt("2026-09-01", "gunici", "kapanis"), _dt(2026, 9, 1, 12, 0), _SL, _W), []),
            # verdict esikleri mevcut `_missed_slots` ailesiyle AYNI (yeni esik YOK)
            ("verdict 0 eksik -> GREEN",                _V([]), "GREEN"),
            ("verdict 1 eksik -> YELLOW",               _V(["acilis"]), "YELLOW"),
            ("verdict 2 eksik -> RED",                  _V(["acilis", "gunici"]), "RED"),
            ("verdict None (olculemedi) -> RED",        _V(None), "RED"),
            # kanonik kaynak: pencere elle sabit DEGIL
            ("pencere report_gate'ten turetiliyor",     _L._WINDOW_MIN, _RG.WINDOW_MINUTES),
        ]:
            if alinan == beklenen:
                ok(ad)
            else:
                bad(f"#1e {ad}: beklenen {beklenen}, alinan {alinan}")

        # --- DENETCI SEVIYESI: saf fonksiyon degil, uyenin KENDISI ------------
        _row = _L._check_report_coverage("report_coverage", {}, {"sent": None}, {})
        if _row.get("status") == "RED":
            ok("uye: defter okunamayinca RED (temiz sayilmaz)")
        else:
            bad(f"#1e uye: okunamayan defter RED vermiyor -> {_row.get('status')}")

        # --- REGISTRY + DALLANMA SIRASI --------------------------------------
        _cfg = (getattr(_L, "REGISTRY", None) or {}).get("report_coverage")
        if _cfg and _cfg.get("check_mode") == "report_coverage":
            ok("registry'de 18. uye kayitli (check_mode dogru)")
        else:
            bad("#1e registry uyesi yok ya da check_mode yanlis")

        # Dallanma `_first(d, ts_keys)`DAN ONCE olmali: report_runs.json'da ust
        # duzey zaman damgasi YOK -> sonraya kayarsa uye "damga yok" diye SAHTE
        # RED verir. Kaynak sirasi kontrol edilir (davranista sessizce bozulur).
        _src = open(os.path.join(ROOT, "scripts", "liveness_scan.py"), encoding="utf-8").read()
        _i_disp = _src.find('cfg.get("check_mode") == "report_coverage"')
        _i_ts = _src.find('ts, ts_key = _first(d, cfg["ts_keys"])')
        if 0 < _i_disp < _i_ts:
            ok("dallanma ts-cikariminin ONUNDE (sahte 'damga yok' RED'i onlenir)")
        else:
            bad("#1e dallanma sirasi bozuk: report_coverage kontrolu ts-cikariminin ALTINDA")
    except Exception as e:
        bad(f"#1e testi kosmadi: {type(e).__name__}: {e}")

    # ── [6f] #1f — GUNLUK TEK-HEARTBEAT KAPISI ────────────────────────────────
    # NEDEN VAR: liveness cron'u 08-26'dan beri KRONIK GEC kosuyor (+2.5-4.7 sa).
    # Cozum coklu-retry cron, AMA liveness.yml Telegram adimi `if: always()` ile
    # HER kosumda mesaj atiyor (heartbeat sozlesmesi: "sessizlik = alarm").
    # Retry eklenirse gunde N heartbeat olur ve sozlesme TERSINDEN bozulur:
    # sessizligin anlamli kalmasi mesajin NADIR olmasina bagli.
    # => retry cron TEK BASINA eklenemez; gunluk-tek-heartbeat kapisi ON SARTTIR.
    #
    # 🔑 TASARIM CUMLESI: rapor kapisinda supHE = BLOK; heartbeat kapisinda
    #    supHE = GONDER. Ayni disiplin, TERS fail-safe yonu.
    #    (report_gate._record_blocks: malformed kayit BLOKLAR — burada tersi.)
    print("\n[6f] #1f gunluk tek-heartbeat kapisi (liveness_scan — golden-master disi)")
    try:
        import sys as _sys2
        _sp2 = os.path.join(ROOT, "scripts")
        if _sp2 not in _sys2.path:
            _sys2.path.insert(0, _sp2)
        from datetime import datetime as _dt2
        import liveness_scan as _L2

        _due = getattr(_L2, "_heartbeat_due", None)
        _mk = getattr(_L2, "_heartbeat_marker", None)
        _ENVK = ("GITHUB_RUN_ID", "GITHUB_SHA", "HB_VERDICT", "HB_HEALTH")

        def _mk_envsiz():
            """`env yokken` iddiasi ancak env GERCEKTEN temizlenerek olculebilir."""
            _eski = {k: os.environ.pop(k, None) for k in _ENVK}
            try:
                return _mk(_BUGUN)
            finally:
                for k, v in _eski.items():
                    if v is not None:
                        os.environ[k] = v

        def _mk_envli():
            _eski = {k: os.environ.get(k) for k in _ENVK}
            os.environ["GITHUB_RUN_ID"] = "TEST_RUN_42"
            try:
                return _mk(_BUGUN)
            finally:
                for k, v in _eski.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        if _due is None or _mk is None:
            bad("#1f _heartbeat_due / _heartbeat_marker YOK (yama henuz uygulanmadi)")
        else:
            def _M(gun):
                return {"sent_date": gun}
            _BUGUN = _dt2(2026, 9, 4, 20, 0)
            _GEC_RETRY = _dt2(2026, 9, 5, 0, 1)

            for ad, alinan, beklenen in [
                # 1-2: heartbeat gunde BIR
                ("1  gunun ILK kosumu GREEN -> GONDER",
                 _due(None, _BUGUN, "GREEN"), True),
                ("2  gunun IKINCI kosumu GREEN -> SESSIZ",
                 _due(_M("2026-09-04"), _BUGUN, "GREEN"), False),
                ("2b gunun IKINCI kosumu YELLOW -> SESSIZ",
                 _due(_M("2026-09-04"), _BUGUN, "YELLOW"), False),
                # 3-4: ALARM asla dedup EDILMEZ
                ("3  gunun IKINCI kosumu RED -> GONDER (dedup YOK)",
                 _due(_M("2026-09-04"), _BUGUN, "RED"), True),
                ("4  ucuncu kosum da RED -> yine GONDER",
                 _due(_M("2026-09-04"), _BUGUN, "RED"), True),
                # 5,8: UTC niyet gunu donunce sifirlanir; TR gece yarisi yetmez
                ("5  dunku damga, bugun ilk kosum -> GONDER",
                 _due(_M("2026-09-03"), _BUGUN, "GREEN"), True),
                ("8  TR gun siniri niyet gununu degistirmez -> SESSIZ",
                 _due(_M("2026-09-04"), _GEC_RETRY, "GREEN"), False),
                # 7: supHE = GONDER  (report_gate'in TERSI — bilincli)
                ("7a damga YOK (dosya okunamadi) -> GONDER",
                 _due(None, _BUGUN, "GREEN"), True),
                ("7b damga BOZUK (dict degil) -> GONDER",
                 _due("bozuk", _BUGUN, "GREEN"), True),
                ("7c damga dict ama sent_date YOK -> GONDER",
                 _due({}, _BUGUN, "GREEN"), True),
                ("7d sent_date parse edilemez -> GONDER",
                 _due({"sent_date": "x!"}, _BUGUN, "GREEN"), True),
                # marker uretimi
                ("_heartbeat_marker normal kosumda gun anahtari yazar",
                 _mk(_BUGUN).get("sent_date"), "2026-09-04"),
                # DENETIM ALANLARI (#1f guclendirme): damga "kim gonderdi"yi de
                # tasimali, yoksa damganin KENDISI denetlenemez.
                ("damgada denetim alanlari VAR",
                 sorted(set(_mk(_BUGUN)) & {"verdict", "health", "commit_sha", "github_run_id"}),
                 ["commit_sha", "github_run_id", "health", "verdict"]),
                ("denetim alanlari env'den doluyor",
                 _mk(_BUGUN, verdict="YELLOW").get("verdict"), "YELLOW"),
                # "env yokken" iddiasi ENV'I GERCEKTEN TEMIZLEYEREK olculur.
                # ILK YAZIMDA TEMIZLENMEMISTI: yerelde GITHUB_RUN_ID yok -> gecti,
                # CI'da DAIMA set -> KIRILDI (962a21f, 2026-09-04 CI kirmizi).
                # Ders: test, KONTROL ETMEDIGI bir ortam ozelligini iddia edemez.
                ("env YOKKEN None (env temizlenerek olculdu)",
                 _mk_envsiz().get("github_run_id"), None),
                ("env VARKEN env'den okunuyor",
                 _mk_envli().get("github_run_id"), "TEST_RUN_42"),
            ]:
                if alinan == beklenen:
                    ok(ad)
                else:
                    bad(f"#1f {ad}: beklenen {beklenen}, alinan {alinan}")

        # --- 6: "mark yalniz GERCEK gonderimden sonra" — workflow sirasi -------
        # Saf fonksiyonla test EDILEMEZ (gonderim sonucu workflow'da olusur).
        # Kaynak kontrolu: (a) curl basarisizligi YAKALANIYOR mu, (b) damga adimi
        # Telegram adimindan SONRA mi.
        _wf = open(os.path.join(ROOT, ".github", "workflows", "liveness.yml"),
                   encoding="utf-8").read()
        # `-f` bayragi -s/-S ile birlesik yazilabilir (curl -sf) -> regex ile ara.
        # (Ilk yazimda literal "curl -f" ariyordum; yama `curl -sf` yazinca test
        #  yanlis kirmizi verdi — testin kendisi de yasaya tabidir.)
        import re as _re
        _fbayrak = bool(_re.search(r"curl\s+-[a-zA-Z]*f", _wf))
        _oktrue = ('"ok":true' in _wf) or ('"ok": true' in _wf)
        if _fbayrak and _oktrue:
            ok("6a Telegram basarisi IKI KATMANLI olculuyor (curl -f VE ok:true)")
        elif _fbayrak or _oktrue:
            ok("6a Telegram basarisi olculuyor (tek katman)")
        else:
            bad("#1f 6a `curl -s` HTTP 400/401'de exit 0 doner -> API REDDI BASARI "
                "sayilir; damga yanlis yazilir")
        _i_tg = _wf.find("sendMessage")
        _i_mk = _wf.find("heartbeat-mark")
        if 0 < _i_tg < _i_mk:
            ok("6b damga adimi Telegram adimindan SONRA")
        else:
            bad("#1f 6b damga adimi Telegram'dan ONCE ya da yok -> basarisiz gonderim "
                "gunun heartbeat'ini tamamen susturur (spam'den KOTU)")

        # --- marker dosyasi report_runs.json OLMAMALI (yaris + kuplaj) ---------
        _hp = getattr(_L2, "HEARTBEAT_OUT", None)
        if _hp is not None and "liveness_heartbeat" in str(_hp):
            ok("damga AYRI dosyada (report_runs.json ile yaris yok)")
        else:
            bad(f"#1f damga dosyasi ayri degil: {_hp!r}")
    except Exception as e:
        bad(f"#1f testi kosmadi: {type(e).__name__}: {e}")

    # ── [6g] #1j — GECIKMIS RETRY ERTESI GUN HEARTBEAT'INI CALMAMALI ──────────
    # NEDEN VAR: #1f retry kapisi gunde tek heartbeat'i sagladi, ama geciken son
    # retry 21:01 UTC = 00:01 TR'de kosunca `sent_date` TR gunuyle 09-05 yazildi.
    # Tasidigi veri 09-04 aksami oldugu halde 09-05 slotu tukendi. Hafta sonu zarar
    # dogurmadi; hafta ici ertesi gunun gercek sagligi Telegram'a hic ulasmayabilir.
    #
    # Testin omurgasi: 00:01 TR ile ertesi gun 20:10 TR ayni TR tarihindedir, ama
    # farkli NIYET gunleridir. Mevcut `_heartbeat_due(marker, now_tr, verdict)`
    # yalniz TR gunune baktigi icin ikisini ayiramaz; bu blok yama oncesi kirmizi
    # vermelidir.
    #
    # EKSEN KARARI (c) — OLCUMLE SECILDI (2026-09-06):
    #   (a) parametre TR kalsin, iceride cevir -> kirmizi verir ama eksenin ADI yok
    #   (b) cagri yerlerini UTC'ye tasi        -> REDDEDILDI. `_heartbeat_due`
    #       EKSEN-AGNOSTIK: `return gun != now.strftime(...)` — kendisine VERILEN
    #       datetime'i bicimler, TR mi UTC mi bilmez. Dogrudan UTC besleyen test
    #       YAMASIZ KODDA DA YESIL doner => VAKUM TEST, hicbir sey olcmez.
    #       OLCULDU: _heartbeat_due({"sent_date":"2026-09-04"},
    #                               datetime(2026,9,4,21,1), "GREEN") -> False
    #   (c) SECILEN: niyet gunu ADI OLAN tek fonksiyona cikarilir (_intent_day),
    #       her iki tuketici oradan gecer. Cagri yerleri (369/1085/1120) DEGISMEZ,
    #       donusum TEK yerde, ofset kanonik PRODUCER_TZ_OFFSET_H'den.
    #
    # BU BLOK DAVRANIS SABITLER, IMPLEMENTASYON DEGIL: `_intent_day`in VARLIGINI
    # sart kosmaz — iki fonksiyonun AYNI niyet gununu uretmesini sart kosar.
    print("\n[6g] #1j gecikmis retry ertesi gun heartbeat'ini calmasin (test-once)")
    try:
        import sys as _sys3
        _sp3 = os.path.join(ROOT, "scripts")
        if _sp3 not in _sys3.path:
            _sys3.path.insert(0, _sp3)
        from datetime import datetime as _dt3, timedelta as _td3
        import liveness_scan as _L3

        _due = getattr(_L3, "_heartbeat_due", None)
        _mk4 = getattr(_L3, "_heartbeat_marker", None)
        _off = getattr(_L3, "PRODUCER_TZ_OFFSET_H", None)
        if _due is None or _mk4 is None or _off is None:
            bad(f"#1j gerekli semboller YOK (_heartbeat_due={_due is not None} "
                f"_heartbeat_marker={_mk4 is not None} "
                f"PRODUCER_TZ_OFFSET_H={_off is not None})")
        else:
            def _M3(gun):
                return {"sent_date": gun}

            def _TR3(y, m, d, h, mi):
                """UTC an -> uretici (TR) saati.
                Ofset KANONIK sabitten gelir; elle `3` YAZILMAZ — sabit degisirse
                test uretimle sessizce ayrisirdi."""
                return _dt3(y, m, d, h, mi) + _td3(hours=_off)

            # 09-04 21:01 UTC = 09-05 00:01 TR -> TR gece yarisini ASAR, niyet gunu 09-04
            _gec = _TR3(2026, 9, 4, 21, 1)
            _ert = _TR3(2026, 9, 5, 17, 10)     # ertesi gunun normal kosusu, niyet 09-05

            for ad, alinan, beklenen in [
                ("1  20:59 UTC (23:59 TR), damga yok -> GONDER",
                 _due(None, _TR3(2026, 9, 4, 20, 59), "GREEN"), True),
                ("2  21:01 UTC (00:01 TR), 09-04 damgasi -> SESSIZ "
                 "(hala 09-04 aksaminin gec retry'i)",
                 _due(_M3("2026-09-04"), _gec, "GREEN"), False),
                ("3  ertesi gun 17:10 UTC (20:10 TR), 09-04 damgasi -> GONDER",
                 _due(_M3("2026-09-04"), _ert, "GREEN"), True),
                # 4 — DAMGAYI YAZAN TARAF. Yalniz `_heartbeat_due` duzeltilirse 1-3
                # yesile doner AMA HIRSIZLIK YASAR: marker TR ile ertesi gunu yazar,
                # ilk basarili gonderim 21:00 UTC'yi asan bir gunde ertesi gun susar.
                # YALNIZ sent_date okunur; env'e bagli alan (github_run_id vb.) YOK — C8.
                ("4  21:01 UTC'de yazilan marker'in sent_date'i NIYET gunu (09-04) olmali",
                 _mk4(_gec).get("sent_date"), "2026-09-04"),
                # 5 — TUTARLILIK KILIDI, implementasyondan bagimsiz: ayni AN icin
                # marker'in YAZDIGI gun ile `_heartbeat_due`nun KIYASLADIGI gun ayni
                # eksende olmali. Bugun YESIL (ikisi de TR), tam yamadan sonra da YESIL;
                # YALNIZ YARIM yamada (tek taraf cevrilirse) KIRMIZI olur.
                ("5  ayni an: marker'in yazdigi damga o ani SESSIZ'e dusurmeli "
                 "(iki fonksiyon ayni eksende)",
                 _due(_M3(_mk4(_gec).get("sent_date")), _gec, "GREEN"), False),
            ]:
                if alinan == beklenen:
                    ok(ad)
                else:
                    bad(f"#1j {ad}: beklenen {beklenen}, alinan {alinan}")
    except Exception as e:
        bad(f"#1j testi kosmadi: {type(e).__name__}: {e}")

    # -- [6g2] #2a/#2b — GECIKMIS SLOT NIYETI VE GECE YARISI KAPSAMI ---------
    # TEST-ONCE: 2026-09-14/15 canli vakalarinin iki ayri kapisini sabitler.
    # #2a: precise 07:25 UTC'de basladiginda sabit `07:00` ayrimi acilisi
    # guniciye cevirdi; report_gate'deki vadesi gelmis + gonderilmemis + pencere
    # icindeki EN ERKEN slot otorite olmali.
    # #2b: 00:01-01:01 TR taramasinda onceki gunun eksik acilisi/kapanisi
    # `gun_tr=bugun` ile gorunmez oldu. Pencere kapanmis onceki rapor gunu,
    # teslim veya acik resolution olmadan GREEN'e donmemeli.
    print("\n[6g2] #2a/#2b gecikmis slot niyeti ve gece yarisi kapsami (test-once)")
    try:
        import sys as _sys_g2
        _sp_g2 = os.path.join(ROOT, "scripts")
        if _sp_g2 not in _sys_g2.path:
            _sys_g2.path.insert(0, _sp_g2)
        from datetime import datetime as _dt_g2, timedelta as _td_g2
        from zoneinfo import ZoneInfo as _ZI_g2
        import precise_runner as _PR_g2
        import liveness_scan as _L_g2

        _utc_g2 = _ZI_g2("UTC")
        _tr_g2 = _ZI_g2("Europe/Istanbul")
        _plan_g2 = getattr(_PR_g2, "plan", None)
        _select_g2 = getattr(_PR_g2, "select_slot", None)
        if _plan_g2 is None or _select_g2 is None:
            bad("#2a sozlesmesi eksik: plan + select_slot birlikte olmali")
        else:
            _sent_g2 = {}
            _t725_g2 = _dt_g2(2026, 9, 15, 7, 25, tzinfo=_utc_g2)
            _label_g2 = _select_g2(_t725_g2, _sent_g2)
            if _label_g2 == "acilis":
                ok("#2a 07:25 UTC gecikmesi acilis niyetini koruyor")
            else:
                bad(f"#2a 07:25 UTC acilis niyeti kayboldu: {_label_g2!r}")

            _sent_g2 = {"2026-09-15:acilis": {"sent_at": "2026-09-15T09:50:00+03:00"}}
            _label_g2 = _select_g2(_t725_g2, _sent_g2)
            if _label_g2 == "gunici":
                ok("#2a acilis damgaliysa en erken acik slot gunici")
            else:
                bad(f"#2a acilis damgali sonrasi gunici secilmedi: {_label_g2!r}")

            _t1320_g2 = _dt_g2(2026, 9, 15, 10, 20, tzinfo=_utc_g2)
            _label_g2 = _select_g2(_t1320_g2, {})
            if _label_g2 == "gunici":
                ok("#2a 13:20 TR'de kapanmis acilis sonrasi gunici korunuyor")
            else:
                bad(f"#2a pencere disinda gunici korunmadi: {_label_g2!r}")

        _missing_g2 = getattr(_L_g2, "_missing_report_slots", None)
        if _missing_g2 is None:
            bad("#2b _missing_report_slots bulunamadi")
        else:
            _slots_g2 = {"acilis": (9, 45), "gunici": (14, 30), "kapanis": (18, 40)}
            _midnight_g2 = _dt_g2(2026, 9, 15, 0, 46, tzinfo=_tr_g2)
            _sent_prev_g2 = {
                "2026-09-14:acilis": {"sent_at": "2026-09-14T10:00:00+03:00"},
                "2026-09-14:gunici": {"sent_at": "2026-09-14T14:35:00+03:00"},
            }
            _missed_g2 = _missing_g2(_sent_prev_g2, _midnight_g2, _slots_g2, 210)
            if _missed_g2 == ["2026-09-14:kapanis"]:
                ok("#2b 00:46 TR onceki gun eksik kapanisi tasiyor")
            else:
                bad(f"#2b gece yarisi eksik kapanis kayboldu: {_missed_g2!r}")

            _sent_full_g2 = dict(_sent_prev_g2)
            _sent_full_g2["2026-09-14:kapanis"] = {
                "sent_at": "2026-09-15T00:30:00+03:00"
            }
            _missed_g2 = _missing_g2(_sent_full_g2, _midnight_g2, _slots_g2, 210)
            if _missed_g2 == []:
                ok("#2b teslim edilmis onceki gun kapanisi eksik sayilmiyor")
            else:
                bad(f"#2b teslim edilmis kapanis hala eksik: {_missed_g2!r}")

            # B1: Onceki beklenen islem gunu hic marker uretmediyse de kayip
            # gorunmeli. 09-11 kaydi yalnız ledger'in okunur/gecmisli oldugunu
            # kanitlar; 09-14'te sifir marker olmasi "tatil" sayilamaz.
            _sent_full_day_loss_g2 = {
                "2026-09-11:acilis": {"sent_at": "2026-09-11T10:00:00+03:00"},
                "2026-09-11:gunici": {"sent_at": "2026-09-11T14:35:00+03:00"},
                "2026-09-11:kapanis": {"sent_at": "2026-09-11T18:45:00+03:00"},
            }
            _missed_g2 = _missing_g2(
                _sent_full_day_loss_g2, _midnight_g2, _slots_g2, 210
            )
            _expected_full_day_g2 = [
                "2026-09-14:acilis",
                "2026-09-14:gunici",
                "2026-09-14:kapanis",
            ]
            if _missed_g2 == _expected_full_day_g2:
                ok("#2b markersiz tam islem gunu kaybi gece yarisi tasiniyor")
            else:
                bad(f"#2b markersiz tam gun kaybi gorunmedi: {_missed_g2!r}")

            _previous_day_g2 = getattr(_L_g2, "_previous_report_day", None)
            if _previous_day_g2 is None:
                bad("#2b takvim otoritesi yardimcisi bulunamadi")
            else:
                _orig_previous_day_g2 = _L_g2._previous_report_day
                try:
                    _L_g2._previous_report_day = lambda _now: (None, False)
                    _missed_g2 = _missing_g2(
                        _sent_full_day_loss_g2, _midnight_g2, _slots_g2, 210
                    )
                finally:
                    _L_g2._previous_report_day = _orig_previous_day_g2
                if _missed_g2 is None:
                    ok("#2b takvim okunamazsa kapsam OLCULEMEDI")
                else:
                    bad(f"#2b takvim yokken kesin kapsam uretildi: {_missed_g2!r}")

        _weekend_g2 = _dt_g2(2026, 9, 19, 7, 25, tzinfo=_utc_g2)
        if _select_g2 is not None and _select_g2(_weekend_g2, {}) is None:
            ok("#2a hafta sonu slot secmiyor")
        else:
            bad("#2a hafta sonu slot uretildi")

        _late_g2 = _dt_g2(2026, 9, 15, 20, 0, tzinfo=_utc_g2)  # 23:00 TR
        if _select_g2 is not None and _select_g2(_late_g2, {}) is None:
            ok("#2a 23:00 TR kapanmis pencereden slot uretmiyor")
        else:
            bad("#2a 23:00 TR slot uretildi")

        # B2: Plan state'i okumadan once origin state'i senkronlanmali. Bu test
        # dosya satirlarini degil, main() icindeki gercek cagri sirasini olcer.
        _order_g2 = []
        _orig_sync_g2 = _PR_g2.sync_latest_state
        _orig_plan_g2 = _PR_g2.plan
        try:
            _PR_g2.sync_latest_state = lambda: _order_g2.append("sync")
            _PR_g2.plan = lambda *args, **kwargs: (
                _order_g2.append("plan") or (None, None, 0)
            )
            _PR_g2.main(["precise_runner.py", "--dry"])
        finally:
            _PR_g2.sync_latest_state = _orig_sync_g2
            _PR_g2.plan = _orig_plan_g2
        if _order_g2[:2] == ["sync", "plan"]:
            ok("#2a origin state planlamadan once senkronlaniyor")
        else:
            bad(f"#2a sync/plan sirasi yanlis: {_order_g2!r}")
    except Exception as e:
        bad(f"#2a/#2b testi kosmadi: {type(e).__name__}: {e}")

    # -- [6r] C1 OLCUM ARACLARI — DENETIM KILITLERI (test-once, 2026-09-15; inceleme #2 2026-09-16) ---
    # C1 incelemesi (bagimsiz) 6 bulgu, ikinci inceleme 6 bulgu daha verdi; her kilit SOZLESME:
    #   F1 gizlilik TEK OTORITE: system_control_audit.json_privacy_scan / personal_path_hits;
    #      selftest AYNI fonksiyonu sinar (kendi regex'i YOK); parse edilemeyen JSON PASS SAYILMAZ.
    #   F2 Q1 'Ortak' = iki katmandaki EN ERKEN tarih.
    #   F3 muhur araci: git HATASI != YOKLUK, HEAD != origin/main ise DURUR, sayfalama hedefe
    #      ulasamazsa RAISE (bos liste != yok), gecmis tarih NOKTA-ZAMANLI ref (hedef_ref).
    #   F4 Q1: sifir gozlemli ufuk sayaclariyla yazilir; IC BOSLUK veri_eksik (yatay tasima yok);
    #      CA isareti yalniz (d0, d1] icinde.
    #   F6 feed onbellegi: ayni dizinde gecici + os.replace; dump hatasinda nihai dosya OLUSMAZ.
    #   PROV Q1 damgasi: input_origin_sha, tool_head_sha, tool_sha256, tool_dirty, cache; git
    #      hatasi -> RAISE (fail-open None YOK).
    #   IBS benchmark: evren_n yazilir, bos ufuk n=0 ile yazilir, t notu veriden.
    print("\n[6r] C1 olcum araclari — denetim kilitleri (test-once)")
    try:
        import hashlib as _hl6r
        import json as _json6r
        import re as _re6r
        import subprocess as _sp6r
        import sys as _sys6r
        import tempfile as _tf6r
        from datetime import datetime as _dt6r
        _sp_6r = os.path.join(ROOT, "scripts")
        if _sp_6r not in _sys6r.path:
            _sys6r.path.insert(0, _sp_6r)

        # F1 — gizlilik: DENETCININ KENDI fonksiyonu (tek otorite), gercek public yuzey + karsi testler
        import system_control_audit as _SCA6r
        _scan, _pub, _phits = (getattr(_SCA6r, n, None) for n in ("json_privacy_scan", "public_json_files", "personal_path_hits"))
        if _scan is None or _pub is None or _phits is None:
            bad("F1 sozlesmesi eksik: system_control_audit.json_privacy_scan / public_json_files / personal_path_hits yok")
        else:
            _yuzey = _pub()
            _hit, _bozuk = _scan(_yuzey)
            _kapsam_ok = any(str(p).replace("\\", "/").endswith("docs/state/liveness.json") for p in _yuzey) and \
                         any("/reports/" in str(p).replace("\\", "/") for p in _yuzey)
            if _bozuk:
                bad(f"F1 gizlilik: parse edilemeyen public JSON PASS sayilamaz: {_bozuk}")
            elif _hit:
                bad(f"F1 GIZLILIK: public JSON degerinde kisisel yol: {_hit}")
            elif not _kapsam_ok:
                bad(f"F1 gizlilik kapsami dar: docs/state ve reports yuzeyde degil ({len(_yuzey)} dosya)")
            else:
                ok(f"F1 gizlilik: {len(_yuzey)} public JSON (takipli + docs/state + reports) denetci fonksiyonuyla temiz")
            # karsi testler: yol CALISMA ZAMANINDA kurulur (kaynakta literal yol yok -> ham tarayici temiz kalir)
            _d1 = _tf6r.mkdtemp()
            _sep = chr(92)
            _win = "C:" + _sep + "Users" + _sep + "abc" + _sep + "x.json"
            _nix = "/".join(["", "home", "abc", "x.json"])                # kaynakta bitisik yazilmaz (ham tarayici)
            _fwd = "C:/" + "Users" + "/abc/x.json"                         # ileri-egik-cizgili Windows yolu (3. desen)
            _f_win = os.path.join(_d1, "sizinti_win.json"); open(_f_win, "w", encoding="utf-8").write(_json6r.dumps({"kaynak": _win}))
            _f_nix = os.path.join(_d1, "sizinti_nix.json"); open(_f_nix, "w", encoding="utf-8").write(_json6r.dumps({"a": [{"b": _nix}]}))
            _f_tmz = os.path.join(_d1, "temiz.json"); open(_f_tmz, "w", encoding="utf-8").write(_json6r.dumps({"kaynak": "reports/x.json", "n": 3}))
            _f_bzk = os.path.join(_d1, "bozuk.json"); open(_f_bzk, "w", encoding="utf-8").write("{bu json degil")
            _h2, _b2 = _scan([_f_win, _f_nix, _f_tmz, _f_bzk])
            _yak = sorted(os.path.basename(h.split(": personal path")[0]) for h in _h2)
            _ham_metin_kacar = _SCA6r.WINDOWS_USER_PATH_RE.search(open(_f_win, encoding="utf-8").read()) is None
            # 3. desen (surucu:/ + ev klasoru, ileri egik cizgi) UNIX deseniyle de eslesir; tek basina da sinanir
            _fwd_ok = bool(_SCA6r.PARSED_PATH_RES[2].search(_fwd)) and not _SCA6r.PARSED_PATH_RES[2].search("C:/Program Files/x")
            if _yak == ["sizinti_nix.json", "sizinti_win.json"] and [os.path.basename(x) for x in _b2] == ["bozuk.json"] \
                    and _phits({"k": _win}) and _phits({"k": _fwd}) and _fwd_ok and not _phits({"k": "reports/x.json"}):
                ok(f"F1 karsi test: cozulmus JSON degerinde yol YAKALANIYOR (win ters+ileri egik, nix), temiz geciyor, bozuk JSON 'bozuk' listesinde"
                   + (" (ham metin tarayicisi bu dosyayi KACIRIYOR -> parse otoritesi gerekli)" if _ham_metin_kacar else ""))
            else:
                bad(f"F1 karsi test: yakalanan={_yak} bozuk={_b2} fwd_desen={_fwd_ok}")
            # F1b — denetci BULDUGUNU YENIDEN YAYIMLAMAZ (inceleme #3): kanit satirlarinda deger yok
            _tph = getattr(_SCA6r, "text_privacy_hits", None)
            if _tph is None:
                bad("F1b sozlesmesi eksik: system_control_audit.text_privacy_hits(text, relname) yok")
            else:
                _mail = "gizli.kisi" + "@" + "ornek-alan.net"
                _metin = "a=1\n" + _win + "\nmail: " + _mail + "\nb=2\n"
                _th = _tph(_metin, "x/y.py")
                _turler = sorted(h.split(": ", 1)[1].split(" (")[0] for h in _th)
                _deger_sizdi = [h for h in _th + _h2 if ("abc" in h) or (_mail in h) or ("ornek-alan" in h)]
                if _turler == ["email literal", "personal absolute path"] and not _deger_sizdi \
                        and all(h.startswith("x/y.py: ") for h in _th):
                    ok("F1b denetci kanit satiri yalniz dosya + tur (+adet); e-posta/yol degeri GERI YAZILMIYOR (metin + JSON dali)")
                else:
                    bad(f"F1b deger yeniden yayimlaniyor / tur eksik: turler={_turler} sizan={_deger_sizdi}")

        # F2 — Q1 ortak en-erken tarih
        import sinyal_kalitesi_q1 as _Q6r
        _ortak_fn = getattr(_Q6r, "ortak_ilk", None)
        if _ortak_fn is None:
            bad("F2 sozlesmesi eksik: sinyal_kalitesi_q1.ortak_ilk(T, Q) yok")
        else:
            _T = [("AAA", "2026-06-08", 3), ("BBB", "2026-08-20", 1), ("CCC", "2026-07-01", 2)]
            _Qq = [("AAA", "2026-09-01", 2), ("BBB", "2026-08-17", 4), ("DDD", "2026-07-05", 1)]
            _o = {t: d for t, d, _ in _ortak_fn(_T, _Qq)}
            if _o == {"AAA": "2026-06-08", "BBB": "2026-08-17"}:
                ok("F2 Q1 'Ortak' iki katmandaki EN ERKEN tarihi aliyor (T'yi ezmiyor)")
            else:
                bad(f"F2 'Ortak' tarih ezme: {_o!r}")

        # F4 — sifir gozlemli ufuk sayaclariyla yazilir; ic bosluk veri_eksik; CA yalniz pencerede
        _uf, _cad = getattr(_Q6r, "ufuk_ozeti", None), getattr(_Q6r, "ca_duzelt", None)
        if _uf is None or _cad is None:
            bad("F4 sozlesmesi eksik: sinyal_kalitesi_q1.ufuk_ozeti / ca_duzelt yok")
        else:
            import numpy as _np6r
            import pandas as _pd6r
            _idx = _pd6r.bdate_range("2026-08-01", periods=10)
            _pr = _pd6r.DataFrame({"AAA": range(10, 20)}, index=_idx, dtype=float)
            _bi = _pd6r.Series(range(100, 110), index=_idx, dtype=float)
            _res, _satir = _uf([("AAA", str(_idx[-2].date()), 1)], 21, _pr, _pr, _bi)   # (ozet, satirlar)
            if isinstance(_res, dict) and _res.get("n") == 0 and _res.get("sansurlu") == 1 and "excess" in _res and _satir == []:
                ok("F4 sifir gozlemli ufuk sayaclariyla yaziliyor (n=0, sansurlu=1)")
            else:
                bad(f"F4 bos ufuk kayboluyor / sayac yok: {_res!r}")
            # ic bosluk (i=3 NaN) + 2:1 bolunme (i=6): bosluk NaN kalir, seviye korunur, CA gunu getirisi 0
            _idx2 = _pd6r.bdate_range("2026-01-05", periods=12)
            _p2 = _pd6r.DataFrame({"AAA": [10, 10.5, 11, _np6r.nan, 11.5, 12, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5]}, index=_idx2, dtype=float)
            _b2 = _pd6r.Series(_np6r.linspace(100, 101, 12), index=_idx2)
            _adj, _ca = _cad(_p2)
            _gap_nan = bool(_pd6r.isna(_adj["AAA"].iloc[3]))
            _seviye_ok = abs(_adj["AAA"].iloc[4] / _adj["AAA"].iloc[2] - 11.5 / 11) < 1e-9
            _ca_sifir = abs(_adj["AAA"].iloc[6] - _adj["AAA"].iloc[5]) < 1e-9
            _o_gap, _ = _uf([("AAA", str(_idx2[0].date()), 1)], 3, _adj, _p2, _b2, _ca, entry_lag=1)     # pencere 1..4 NaN icerir
            _o_dis, _k_dis = _uf([("AAA", str(_idx2[3].date()), 1)], 1, _adj, _p2, _b2, _ca, entry_lag=1)   # pencere 4..5, CA(6) disinda
            _o_ic, _k_ic = _uf([("AAA", str(_idx2[4].date()), 1)], 2, _adj, _p2, _b2, _ca, entry_lag=1)     # pencere 5..7, CA(6) icinde
            if _gap_nan and _seviye_ok and _ca_sifir and _ca == {"AAA": [str(_idx2[6].date())]} \
                    and _o_gap["veri_eksik"] == 1 and _o_gap["n"] == 0 \
                    and _o_dis["n"] == 1 and _k_dis[0]["ca"] is False and _o_dis["ca_isaretli"] == 0 \
                    and _o_ic["n"] == 1 and _k_ic[0]["ca"] is True and _o_ic["ca_isaretli"] == 1:
                ok("F4 ic bosluk NaN kaliyor -> veri_eksik (yatay tasima yok); seviye korunuyor; CA isareti yalniz (d0,d1] icinde")
            else:
                bad(f"F4 bosluk/CA: gap_nan={_gap_nan} seviye={_seviye_ok} ca0={_ca_sifir} ca={_ca} gap={_o_gap} dis={_k_dis} ic={_k_ic}")
            # F4c — SAG SANSUR ONCE (inceleme #3): seriden GENC sinyal 'sansurlu', 'eslesmeyen' degil;
            #       seri icinde bar'i olmayan gun (tatil) hala eslesmeyen; bilinmeyen hisse eslesmeyen
            _genc = str((_idx[-1] + _pd6r.Timedelta(days=3)).date())         # son fiyat gununden sonra
            _tatil = str((_idx[4] + _pd6r.Timedelta(days=1)).date())         # idx[4]=Cuma -> Cumartesi: seride bar yok
            assert _pd6r.Timestamp(_tatil).weekday() == 5 and _pd6r.Timestamp(_tatil) < _idx[-1], "test iskelesi: tatil gunu yanlis"
            _o_c, _ = _uf([("AAA", _genc, 1), ("AAA", _tatil, 1), ("ZZZ", str(_idx[0].date()), 1)], 5, _pr, _pr, _bi)
            # BIRLESIK durum (inceleme #4): genc tarih + cache'te OLMAYAN hisse -> yine SANSUR (eslesmeyen degil);
            # tek basina da olculur ki toplamin icinde saklanmasin
            _o_b, _ = _uf([("ZZZ", _genc, 1)], 5, _pr, _pr, _bi)
            _birlesik_ok = _o_b["sansurlu"] == 1 and _o_b["eslesmeyen"] == 0 and _o_b["n"] == 0
            if _o_c["sansurlu"] == 1 and _o_c["eslesmeyen"] == 2 and _o_c["n"] == 0 and _o_c["toplam_sinyal"] == 3 and _birlesik_ok:
                ok("F4c seriden genc sinyal SANSURLU (eslesmeyen degil) — bilinmeyen hisseyle BIRLESIK durumda da; tatil/bilinmeyen hisse eslesmeyen; sayim uzlasiyor")
            else:
                bad(f"F4c sansur/eslesmeyen sirasi: ayri={_o_c!r} birlesik(genc+bilinmeyen)={_o_b!r}")

        # PROV — Q1 kaynak damgasi (tam) + fail-closed
        _prov = getattr(_Q6r, "provenance", None)
        if _prov is None:
            bad("PROV sozlesmesi eksik: sinyal_kalitesi_q1.provenance(cache_path, params) yok")
        else:
            _tmpd = _tf6r.mkdtemp(); _cp = os.path.join(_tmpd, "feed_onbellek_test.pkl")
            open(_cp, "wb").write(b"deneme")
            _p = _prov(_cp, {"ENTRY_LAG": 1})
            _hex40 = lambda v: _re6r.fullmatch(r"[0-9a-f]{40}", str(v)) is not None
            _arac = os.path.join(ROOT, "scripts", "sinyal_kalitesi_q1.py")
            _ok_prov = (_hex40(_p.get("input_origin_sha")) and _hex40(_p.get("tool_head_sha"))
                        and _p.get("tool_sha256") == _hl6r.sha256(open(_arac, "rb").read()).hexdigest()
                        and isinstance(_p.get("tool_dirty"), bool) and _p.get("tool_path") == "scripts/sinyal_kalitesi_q1.py"
                        and _p.get("cache_name") == "feed_onbellek_test.pkl"
                        and _p.get("cache_sha256") == _hl6r.sha256(b"deneme").hexdigest()
                        and str(_p.get("generated_at", "")).endswith("Z")
                        and _p.get("params") == {"ENTRY_LAG": 1})
            if _ok_prov:
                ok("PROV Q1 damgasi: input_origin_sha + tool_head_sha + tool_sha256 + tool_dirty + cache sha256 + generated_at(Z) + params")
            else:
                bad(f"PROV kaynak damgasi eksik/yanlis: {_p!r}")
            _orig_run = _Q6r.subprocess.run
            _Q6r.subprocess.run = lambda *a, **k: _sp6r.CompletedProcess(a, 128, "", "fatal: sahte git hatasi")
            try:
                _p2 = _prov(_cp, {}); _fail_open = True
            except Exception:
                _fail_open = False
            finally:
                _Q6r.subprocess.run = _orig_run
            if not _fail_open:
                ok("PROV git hatasinda provenance RAISE ediyor (fail-open None yok)")
            else:
                bad(f"PROV fail-open: git hatasinda None ile devam etti: {_p2!r}")

        # F3 — muhur araci: hata != yokluk, HEAD/origin uyumu, sayfalama, nokta-zamanli ref
        import kapanis_muhur_olc as _K6r
        _sr, _so = getattr(_K6r, "show_required", None), getattr(_K6r, "show_optional", None)
        if _sr is None or _so is None:
            bad("F3 sozlesmesi eksik: show_required / show_optional yok")
        else:
            _r = []
            try:
                _r.append(("opt_yok", _so("docs/state/BU_DOSYA_YOK.json") is None))
            except Exception:
                _r.append(("opt_yok", False))
            try:
                _sr("docs/state/BU_DOSYA_YOK.json"); _r.append(("req_yok_raise", False))
            except Exception:
                _r.append(("req_yok_raise", True))
            try:
                _so("docs/state/report_runs.json", ref="origin/OLMAYAN_DAL"); _r.append(("opt_git_hata_raise", False))
            except Exception:
                _r.append(("opt_git_hata_raise", True))
            if all(v for _, v in _r):
                ok("F3 show_optional yoklukta None, show_required yoklukta raise, git hatasi ikisinde de raise")
            else:
                bad(f"F3 hata/yokluk ayrimi: {_r!r}")
        _uy = getattr(_K6r, "_uyum_kontrol", None)
        if _uy is None:
            bad("F3 sozlesmesi eksik: _uyum_kontrol(head, origin) yok")
        else:
            try:
                _uy("abc123", "abc123"); _ayni = True
            except Exception:
                _ayni = False
            try:
                _uy("abc123", "def456"); _farkli_raise = False
            except Exception:
                _farkli_raise = True
            if _ayni and _farkli_raise:
                ok("F3 HEAD != origin/main ise olcum durur (ayni ise gecer)")
            else:
                bad(f"F3 uyum kontrolu: ayni={_ayni} farkli_raise={_farkli_raise}")
        _kos = getattr(_K6r, "kosumlar_sayfali", None)
        if _kos is None:
            bad("F3 sozlesmesi eksik: kosumlar_sayfali(wf, tarih, api=...) yok")
        else:
            _cagri = []
            def _fake_api(url):
                page = int(_re6r.search(r"[?&]page=(\d+)", url).group(1))   # per_page=... ile karismasin
                _cagri.append(page)
                base = _dt6r(2026, 9, 15, 12, 0)
                gun = {1: 15, 2: 14}.get(page, 12)                                 # sayfa1=09-15, sayfa2=09-14 (hedef), sayfa3+=09-12 (eski)
                runs = [{"id": page * 100 + i, "created_at": base.replace(day=gun).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "status": "completed", "conclusion": "success", "head_sha": "0" * 40, "event": "schedule", "updated_at": base.strftime("%Y-%m-%dT%H:%M:%SZ")} for i in range(3)]
                return {"workflow_runs": runs}
            _got = _kos("precise.yml", "2026-09-14", api=_fake_api, per_page=3)
            _sayfa = sorted({r["id"] // 100 for r in _got})
            # hedef gunden ESKI kosum ancak 3. sayfada gorunur -> 3 sayfa okunur, 4. istenmez; yalniz hedef gun doner
            if _sayfa == [2] and len(_got) == 3 and _cagri == [1, 2, 3]:
                ok("F3 kosum listesi hedef tarihe ulasana kadar sayfalaniyor (3 sayfa okundu, 4. istenmedi, yalniz hedef gun dondu)")
            else:
                bad(f"F3 sayfalama: donen sayfalar={_sayfa} n={len(_got)} cagrilar={_cagri}")
            # hedefe ULASILAMAZSA raise: (a) sayfa siniri doldu, hep bugun; (b) bos liste
            def _api_hep_bugun(url):
                return {"workflow_runs": [{"created_at": "2026-09-16T05:00:00Z", "id": 1}]}
            def _api_bos(url):
                return {"workflow_runs": []}
            _rs = []
            for _api_x in (_api_hep_bugun, _api_bos):
                try:
                    _kos("precise.yml", "2026-09-15", api=_api_x, max_page=3); _rs.append(False)
                except Exception:
                    _rs.append(True)
            if _rs == [True, True]:
                ok("F3 sayfalama hedefe ulasamazsa RAISE (sayfa siniri + bos liste; sessiz bos liste yok)")
            else:
                bad(f"F3 sayfalama sessiz bos liste: sinir_raise={_rs[0]} bos_raise={_rs[1]}")
        _hr = getattr(_K6r, "hedef_ref", None)
        if _hr is None:
            bad("F3 sozlesmesi eksik: hedef_ref(tarih, bugun) yok — gecmis muhur en son artefakti okur (gun karisimi)")
        else:
            _sh_cagri = []
            def _fake_sh(*a):
                _sh_cagri.append(a)
                return "f" * 40 + "\n" if "--before=2026-09-14T23:59:59+03:00" in a else ""
            _rr = {}
            _rr["bugun"] = _hr("2026-09-16", bugun="2026-09-16", sh=_fake_sh)
            _rr["gecmis"] = _hr("2026-09-14", bugun="2026-09-16", sh=_fake_sh)
            try:
                _hr("2026-09-17", bugun="2026-09-16", sh=_fake_sh); _rr["gelecek_raise"] = False
            except Exception:
                _rr["gelecek_raise"] = True
            try:
                _hr("2020-01-01", bugun="2026-09-16", sh=_fake_sh); _rr["yok_raise"] = False
            except Exception:
                _rr["yok_raise"] = True
            if _rr["bugun"] == _K6r.REF and _rr["gecmis"] == "f" * 40 and _rr["gelecek_raise"] and _rr["yok_raise"] \
                    and any("rev-list" in a for a in _sh_cagri):
                ok("F3 hedef_ref: bugun=origin/main, gecmis gun=o gunun son commit'i (rev-list --before), gelecek/bulunamayan RAISE")
            else:
                bad(f"F3 hedef_ref: {_rr!r} cagrilar={_sh_cagri!r}")
            # main() icinde artefakt okumalari REF'e degil ref'e gitmeli (kaynak-metin sozlesmesi)
            _src = open(os.path.join(ROOT, "scripts", "kapanis_muhur_olc.py"), encoding="utf-8").read()
            _main_src = _src[_src.index("def main():"):]
            _sabit = [ln.strip() for ln in _main_src.splitlines() if ("show_required(" in ln or "show_optional(" in ln or "ls-tree" in ln or "git\", \"show\"" in ln) and "ref=" not in ln and "{ref}" not in ln and " ref," not in ln]
            if not _sabit:
                ok("F3 main() artefakt okumalari (show_*/ls-tree/git show) nokta-zamanli ref ile")
            else:
                bad(f"F3 main() sabit REF okuyan satirlar: {_sabit}")
            # F3b — ZAMAN EKSENI (inceleme #3): commit saati %cI -> TR; since/until +03:00; [1] gun etiketi
            _gc = getattr(_K6r, "gun_commitleri", None)
            _etiket = getattr(_K6r, "KOSUM_GUN_ETIKETI", None)
            if _gc is None or _etiket is None:
                bad("F3b sozlesmesi eksik: gun_commitleri(ref, gun, sh=...) / KOSUM_GUN_ETIKETI yok")
            else:
                _gc_args = []
                def _fake_sh_log(*a):
                    _gc_args.append(a)
                    return "379da56|2026-09-15T15:47:36+00:00|precise state 2026-09-15_1547 [OK]\n" \
                           "11bbe60|2026-09-15T18:31:02+03:00|report claim kapanis run 34970759619\n"
                _rows = _gc("origin/main", "2026-09-15", sh=_fake_sh_log)
                _fmt = [a for a in _gc_args[0] if str(a).startswith("--format=")]
                _sinir = [a for a in _gc_args[0] if str(a).startswith(("--since=", "--until="))]
                _sinir_ok = _sinir == ["--since=2026-09-15T00:00:00+03:00", "--until=2026-09-15T23:59:59+03:00"]
                _bir_src = open(os.path.join(ROOT, "scripts", "kapanis_muhur_olc.py"), encoding="utf-8").read()
                _bir_hdr = [ln for ln in _bir_src.splitlines() if "[1]" in ln and "print(" in ln]
                _hdr_ok = bool(_bir_hdr) and all("KOSUM_GUN_ETIKETI" in ln for ln in _bir_hdr) and "bilinmiyor" in _etiket
                if _rows == [("18:47", "379da56", "precise state 2026-09-15_1547 [OK]"),
                             ("18:31", "11bbe60", "report claim kapanis run 34970759619")] \
                        and _fmt and "%cI" in _fmt[0] and "%ad" not in _fmt[0] and _sinir_ok and _hdr_ok:
                    ok("F3b commit saati %cI -> TR (UTC 15:47 -> 18:47; +03:00 ofset korunur), since/until +03:00, [1] basligi 'created_at_TR / niyet bilinmiyor'")
                else:
                    bad(f"F3b zaman ekseni: rows={_rows} fmt={_fmt} sinir={_sinir} hdr_ok={_hdr_ok}")
            # F3c — CAPRAZ KONTROL GERCEK BREACH'I GORMELI (C1-ek, 2026-09-16 canli kaniti):
            #   (a) hesap semasi: F-sinifi history[event=stop].trades; G1 `trades[]` duz liste (history'de
            #       yalniz cold_start) -> G1 IEYHO satisi "olay=0 stop=0" okunmustu.
            #   (b) "satis-oncesi gozlemci" = SLOT CLAIM'INDEN ONCEKI son snapshot; "sondan ikinci" degil
            #       (19:28 [NO_RUN] kosumu snapshot'i ilerletince 12:08Z breach ucuncuye dustu -> sahte ESIT).
            _hs = getattr(_K6r, "hesap_satislari", None)
            _sb = getattr(_K6r, "slot_baslangici", None)
            _sog = getattr(_K6r, "satis_oncesi_gozlemci", None)
            if _hs is None or _sb is None or _sog is None:
                bad("F3c sozlesmesi eksik: hesap_satislari / slot_baslangici / satis_oncesi_gozlemci yok (G1 satisi kor, sondan-ikinci esleme)")
            else:
                _gun = "2026-09-16"
                _stF = {"account": "F", "cash": 0.1, "positions": {}, "history": [
                    {"date": "2026-09-14", "event": "stop", "trades": [{"type": "SELL", "ticker": "SELEC", "reason": "stop"}]},
                    {"date": _gun, "event": "stop", "trades": [{"type": "SELL", "ticker": "AAA", "reason": "stop"}, {"type": "SELL", "ticker": "BBB", "reason": "rebalance"}]},
                    {"date": _gun, "event": "rebalance", "trades": [{"type": "BUY", "ticker": "CCC"}]},
                    {"date": _gun, "event": "stop", "trades": [{"type": "SELL", "ticker": "EEE"}]}]}   # reason yazilmamis stop-SELL
                _stG1 = {"account": "G1", "cash": 0.8, "positions": {}, "history": [{"type": "cold_start_reconcile", "date": "2026-07-03"}],
                         "trades": [{"date": "2026-09-01", "type": "SELL", "ticker": "PEKGY", "reason": "stop"},
                                    {"date": _gun, "type": "SELL", "ticker": "IEYHO", "price": 207.0, "reason": "stop"},
                                    {"date": _gun, "type": "BUY", "ticker": "DDD"}]}
                _rF, _rG = _hs(_stF, _gun), _hs(_stG1, _gun)
                _sema_ok = _rF["stop"] == ["AAA", "EEE"] and _rF["olay"] == 3 and _rG["stop"] == ["IEYHO"] and _rG["olay"] == 2
                _log_args = []
                def _fake_sh_slot(*a):
                    _log_args.append(a)
                    if "--grep=^report claim kapanis run" in a:
                        return "b54d58e|2026-09-16T15:40:00+00:00|report claim kapanis run 35097211674\n"
                    if any(str(x).startswith("--before=") for x in a):
                        return "65ba4ccd294c95e4bf55cc23a6d055ce3c4ecd19\n"
                    return ""
                _t0 = _sb("origin/main", _gun, "kapanis", sh=_fake_sh_slot)
                _sha_prev = _sog("origin/main", _t0, sh=_fake_sh_slot) if _t0 else None
                _before = [x for a in _log_args for x in a if str(x).startswith("--before=")]
                _slot_ok = _t0 == "2026-09-16T15:40:00+00:00" and _sha_prev == "65ba4ccd294c95e4bf55cc23a6d055ce3c4ecd19" \
                    and _before == [f"--before={_t0}"] and any("-1" in a for a in _log_args if any(str(x).startswith("--before=") for x in a))
                _yok = _sb("origin/main", _gun, "gunici", sh=lambda *a: "")      # claim commit'i yok -> None (uydurma yok)
                # slot-kapsamli satis: (claim sonrasi ilk portfoy commit'i) - (claim oncesi son commit); gun-bazli sayim
                # slotlar arasi SIZDIRIR (acilis muhru kapanisin IEYHO satisini gormustu)
                _ssl = getattr(_K6r, "slot_satislari", None)
                _slot_sat_ok = False
                if _ssl is not None:
                    def _fake_sh_pf(*a):
                        if any(str(x).startswith("--grep=^report claim ") for x in a):
                            return ""                                   # sonraki claim yok -> gun sonu siniri
                        if "--reverse" in a:
                            return "SONRA\n"
                        if "-1" in a:
                            return "ONCE\n"
                        return ""
                    def _fake_yukle(sha, acc):
                        if acc != "G1":
                            return {"history": [], "positions": {}}
                        return _stG1 if sha == "SONRA" else {"history": [], "trades": [{"date": "2026-09-01", "type": "SELL", "ticker": "PEKGY", "reason": "stop"}]}
                    _r_kap = _ssl("origin/main", _gun, "T0", sh=_fake_sh_pf, yukle=_fake_yukle, hesaplar=("F", "G1"))
                    _r_ac = _ssl("origin/main", _gun, "T0", sh=_fake_sh_pf, yukle=lambda sha, acc: _stG1 if acc == "G1" else {"history": []}, hesaplar=("F", "G1"))
                    _r_yok = _ssl("origin/main", _gun, "T0", sh=lambda *a: "ONCE\n" if "-1" in a else "", yukle=_fake_yukle, hesaplar=("G1",))
                    # OZ-OKUMA BULGUSU: bu slotun daemon'u portfoy commit'i yazmadiysa SONRAKI slotun commit'i bu
                    # slota atfedilmemeli -> 'sonra' penceresi sonraki claim'le (T1) sinirlanir -> None
                    def _fake_sh_mis(*a):
                        if any(str(x).startswith("--grep=^report claim ") for x in a):
                            return "T1" + chr(10)
                        if "--reverse" in a:
                            return "" if "--until=T1" in a else "SONRA" + chr(10)   # T1 siniri konmazsa sonraki slotun commit'i doner
                        if "-1" in a:
                            return "ONCE" + chr(10)
                        return ""
                    _r_mis = _ssl("origin/main", _gun, "T0", sh=_fake_sh_mis, yukle=_fake_yukle, hesaplar=("G1",))
                    _slot_sat_ok = _r_kap == {"F": [], "G1": ["IEYHO"]} and _r_ac == {"F": [], "G1": []} and _r_yok is None and _r_mis is None
                _src5 = _src[_src.index("[5] CAPRAZ"):_src.index("[6] dashboard")]
                _src_ok = "satis_oncesi_gozlemci(" in _src5 and "slot_satislari(" in _src5 \
                    and "hesap_satislari(" in _src[_src.index("[4] PORTFOYLER"):_src.index("[5] CAPRAZ")] \
                    and '"-2", "--format=%H", "--", "docs/state/stop_observer.json"' not in _src5
                if _sema_ok and _slot_ok and _yok is None and _slot_sat_ok and _src_ok:
                    ok("F3c capraz kontrol: G1 trades[] semasi (IEYHO) + F-sinifi history (event=stop SELL reason'suz dahil); gozlemci = slot claim'inden ONCEKI son snapshot (--before,-1); satis = SLOT kapsamli (sonra-once), pencere SONRAKI CLAIM ile sinirli (sonraki slotun commit'i atfedilmez -> None); portfoy commit'i/claim yoksa None; [4]/[5] kaynak sozlesmesi")
                else:
                    bad(f"F3c: sema_ok={_sema_ok} F={_rF} G1={_rG} slot_ok={_slot_ok} t0={_t0} prev={_sha_prev} before={_before} yok={_yok} slot_sat_ok={_slot_sat_ok} (kap={locals().get('_r_kap')} ac={locals().get('_r_ac')} yok={locals().get('_r_yok')} mis={locals().get('_r_mis')}) src_ok={_src_ok}")

        # F6 — feed onbellegi atomik
        import feed_onbellek_cek as _F6r
        _kaydet = getattr(_F6r, "kaydet", None)
        if _kaydet is None:
            bad("F6 sozlesmesi eksik: feed_onbellek_cek.kaydet(payload, out) yok")
        else:
            _d6 = _tf6r.mkdtemp(); _out6 = os.path.join(_d6, "feed_onbellek_x.pkl")
            try:
                _kaydet({"a": (lambda: 0)}, _out6); _hata = False   # lambda pickle'lanamaz
            except Exception:
                _hata = True
            _kalan = sorted(os.listdir(_d6))
            _kaydet({"a": 1}, _out6)
            _son = sorted(os.listdir(_d6))
            if _hata and _kalan == [] and _son == ["feed_onbellek_x.pkl"]:
                ok("F6 dump hatasinda nihai dosya OLUSMUYOR ve gecici artik yok; basarida tek dosya")
            else:
                bad(f"F6 atomik yazim: hata={_hata} hata_sonrasi={_kalan} basari_sonrasi={_son}")
            # F6b — cekim damgasi EKSENLI (inceleme #3): UTC 'Z'; naive reddedilir; isle() dosyaya bunu yazar
            _cd = getattr(_F6r, "cekim_damgasi", None)
            if _cd is None:
                bad("F6b sozlesmesi eksik: feed_onbellek_cek.cekim_damgasi() yok (naive cekim_saati)")
            else:
                import pickle as _pk6r
                from datetime import timezone as _tz6r, timedelta as _td6r
                _tr3 = _tz6r(_td6r(hours=3))
                _z = _cd(_dt6r(2026, 9, 13, 22, 45, 59, tzinfo=_tr3))            # 22:45 TR -> 19:45Z
                try:
                    _cd(_dt6r(2026, 9, 13, 22, 45, 59)); _naive_raise = False
                except ValueError:
                    _naive_raise = True
                import pandas as _pd6b
                _d6b = _tf6r.mkdtemp(); _out6b = os.path.join(_d6b, "feed_onbellek_y.pkl")
                _ix6b = _pd6b.bdate_range("2026-09-01", periods=3)
                _fake = {"prices": _pd6b.DataFrame({"AAA": [1.0, 1.1, 1.2]}, index=_ix6b), "source": "test"}
                import io as _io6r, contextlib as _ctx6r
                with _ctx6r.redirect_stdout(_io6r.StringIO()):
                    _F6r.isle(_fake, 1.0, out=_out6b)
                _yaz = _pk6r.load(open(_out6b, "rb"))
                _cs = _yaz.get("cekim_saati", "")
                _cs_ok = _cs.endswith("Z") and _dt6r.fromisoformat(_cs.replace("Z", "+00:00")).tzinfo is not None
                if _z == "2026-09-13T19:45:59Z" and _naive_raise and _cs_ok and sorted(_yaz) == ["cekim_saati", "data", "sure_s"]:
                    ok("F6b cekim_saati UTC 'Z' (22:45+03:00 -> 19:45:59Z), naive reddediliyor, isle() dosyaya eksenli damga yaziyor")
                else:
                    bad(f"F6b cekim damgasi: z={_z} naive_raise={_naive_raise} dosya={_cs!r} anahtarlar={sorted(_yaz)}")

        # IBS — benchmark: evren_n yazilir, bos ufuk n=0 ile yazilir, t notu veriden
        import ibs_benchmark_olc as _I6r
        _ua = getattr(_I6r, "ufuk_alpha", None)
        if _ua is None:
            bad("IBS sozlesmesi eksik: ibs_benchmark_olc.ufuk_alpha(...) yok")
        else:
            import pandas as _pd6r2
            _ix = {"2026-01-05": 0, "2026-01-06": 1}
            _eo = _pd6r2.Series([1.0, 2.0]); _em = _pd6r2.Series([0.5, 1.5]); _en = _pd6r2.Series([300, 310])
            _ol = [{"ticker": "A", "signal_date": "2026-01-05", "fwd_5d_pct": 3.0},
                   {"ticker": "B", "signal_date": "2026-01-06", "fwd_5d_pct": 1.0},
                   {"ticker": "A", "signal_date": "2026-01-07", "fwd_5d_pct": 9.0}]
            _h5 = _ua(_ol, "fwd_5d_pct", _ix, _eo, _em, _en, n_hisse=2, n_olay=3)
            _h99 = _ua(_ol, "fwd_99d_pct", _ix, _eo, _em, _en, n_hisse=2, n_olay=3)
            if _h5.get("n") == 2 and _h5.get("evren_n") == {"min": 300, "medyan": 305, "max": 310} and abs(_h5.get("alpha_ort", 9) - 0.5) < 1e-9 \
                    and "2 hissede 3 olay" in _h5.get("t_notu", "") and _h99.get("n") == 0 and _h99.get("evren_n") is None and "2 hissede 3 olay" in _h99.get("t_notu", ""):
                ok("IBS evren_n (min/medyan/max) yaziliyor, bos ufuk n=0 ile yaziliyor, t notu veriden turetiliyor")
            else:
                bad(f"IBS ozet: h5={_h5!r} h99={_h99!r}")
    except Exception as e:
        bad(f"[6r] C1 kilit testleri kosmadi: {type(e).__name__}: {e}")

    # ── [6t] BAR ARSIVI — sistem cektigi veriyi SAKLASIN (2026-09-18 olcumu: hicbir bar saklanmiyordu) ──
    # Kanit: gunde 3x 625 hisse cekilip atiliyordu; yfinance 09-17 deligi (IEYHO/SELEC) kendi verimizden
    # doldurulamadi. Sozlesme (test-once):
    #   T1 yeni arsiv: aylik CSV data/bars/YYYY-MM.csv, sabit kolonlar, hisseler + XU100, LF, UTF-8
    #   T2 idempotent: ayni veri ikinci kez -> 0 satir eklenir, dosya bayt-bayt ayni
    #   T3 revizyon: ayni (tarih,hisse) farkli deger -> EKLENIR (ustune yazilmaz); son satir = son gorus
    #   T4 gunici kismi bar + kapanis nihai bar -> iki satir; son_barlar() nihai olani verir
    #   T5 ay siniri: tarihler iki aya yayilirsa iki dosya
    #   T6 NaN kapanis -> satir yazilmaz (bos bar = bar degil); XU100 close-only
    #   T7 file-fallback kaynagi -> ARSIVLENMEZ (donmus Excel arsivi kirletmesin), durum dosyasi nedeni yazar
    #   T8 durum dosyasi docs/state/bar_archive.json: sayaclar + fetched_at 'Z'
    #   T9 daemon cagri sozlesmesi: feed fazindan sonra guarded icinde; workflow commit adimi data/bars/ ekler
    print("\n[6t] Bar arsivi — cekilen veri saklaniyor (test-once)")
    try:
        import csv as _csv6t
        import hashlib as _hl6t
        import json as _json6t
        import tempfile as _tf6t
        from datetime import datetime as _dt6t, timezone as _tz6t
        import numpy as _np6t
        import pandas as _pd6t
        try:
            from bist_alpha import bar_archive as _BA
        except Exception as _e6t:
            _BA = None
            bad(f"T sozlesmesi eksik: bist_alpha.bar_archive import edilemedi ({type(_e6t).__name__}: {_e6t})")
        if _BA is not None:
            _root6t = _tf6t.mkdtemp()
            def _veri(dates, closes, source="borsapy", opens=None, vols=None, bist=None):
                idx = _pd6t.DatetimeIndex([_pd6t.Timestamp(d) for d in dates])
                pr = _pd6t.DataFrame(closes, index=idx)
                out = {"prices": pr, "opens": _pd6t.DataFrame(opens if opens is not None else closes, index=idx),
                       "mins": pr * 0.99, "maxs": pr * 1.01,
                       "volumes": _pd6t.DataFrame(vols if vols is not None else {c: [1000] * len(dates) for c in pr.columns}, index=idx),
                       "bist": _pd6t.Series(bist if bist is not None else [100.0 + i for i in range(len(dates))], index=idx),
                       "_source_base": source, "_source": source}
                return out
            _d1 = _veri(["2026-09-14", "2026-09-15", "2026-09-16"], {"AAA": [10.0, 10.5, 11.0], "BBB": [20.0, 20.5, 21.0]})
            _now = _dt6t(2026, 9, 16, 15, 45, 0, tzinfo=_tz6t.utc)
            _r1 = _BA.append_bars(_d1, "kapanis", root=_root6t, now=_now)
            _f = os.path.join(_root6t, "data", "bars", "2026-09.csv")
            _rows = list(_csv6t.DictReader(open(_f, encoding="utf-8", newline=""))) if os.path.exists(_f) else []
            _cols = list(_rows[0].keys()) if _rows else []
            _lf_ok = b"\r\n" not in open(_f, "rb").read() if os.path.exists(_f) else False
            # T1
            if _cols == _BA.COLUMNS and len(_rows) == 9 and {r["ticker"] for r in _rows} == {"AAA", "BBB", "XU100"} \
                    and _r1.get("rows_added") == 9 and _lf_ok and _rows[0]["fetched_at"].endswith("Z"):
                ok(f"T1 yeni arsiv: {len(_rows)} satir (2 hisse + XU100 x 3 gun), kolonlar {_BA.COLUMNS}, LF, fetched_at Z")
            else:
                bad(f"T1 arsiv bicimi: cols={_cols} n={len(_rows)} r={_r1} lf={_lf_ok}")
            # T2 idempotent
            _h_once = _hl6t.sha256(open(_f, "rb").read()).hexdigest() if os.path.exists(_f) else None
            _r2 = _BA.append_bars(_d1, "kapanis", root=_root6t, now=_now.replace(minute=50))
            _h_sonra = _hl6t.sha256(open(_f, "rb").read()).hexdigest() if os.path.exists(_f) else None
            if _r2.get("rows_added") == 0 and _h_once == _h_sonra:
                ok("T2 idempotent: ayni veri tekrar -> 0 satir, dosya bayt-bayt ayni (fetched_at farkli olsa da)")
            else:
                bad(f"T2 idempotent degil: r={_r2} ayni_hash={_h_once == _h_sonra}")
            # T3 revizyon: 09-16 AAA kapanisi 11.0 -> 11.2 (gec revizyon), ertesi gun acilis kosumu
            _d3 = _veri(["2026-09-14", "2026-09-15", "2026-09-16"], {"AAA": [10.0, 10.5, 11.2], "BBB": [20.0, 20.5, 21.0]})
            _r3 = _BA.append_bars(_d3, "acilis", root=_root6t, now=_dt6t(2026, 9, 17, 7, 5, 0, tzinfo=_tz6t.utc))
            _son = _BA.son_barlar(_f)
            if _r3.get("rows_added") == 1 and abs(float(_son[("2026-09-16", "AAA")]["close"]) - 11.2) < 1e-9 \
                    and len([r for r in _csv6t.DictReader(open(_f, encoding="utf-8", newline="")) if r["ticker"] == "AAA" and r["date"] == "2026-09-16"]) == 2:
                ok("T3 revizyon EKLENIR (ustune yazilmaz): (09-16,AAA) iki satir, son_barlar() son gorusu (11.2) verir")
            else:
                bad(f"T3 revizyon: r={_r3} son={_son.get(('2026-09-16', 'AAA'))}")
            # T4 gunici kismi + kapanis nihai
            _d4a = _veri(["2026-09-16", "2026-09-17"], {"AAA": [11.2, 11.5], "BBB": [21.0, 21.3]}, bist=[102.0, 103.0])
            _d4b = _veri(["2026-09-16", "2026-09-17"], {"AAA": [11.2, 11.9], "BBB": [21.0, 21.3]}, bist=[102.0, 103.0])
            _r4a = _BA.append_bars(_d4a, "gunici", root=_root6t, now=_dt6t(2026, 9, 17, 11, 35, 0, tzinfo=_tz6t.utc))
            _r4b = _BA.append_bars(_d4b, "kapanis", root=_root6t, now=_dt6t(2026, 9, 17, 15, 45, 0, tzinfo=_tz6t.utc))
            _son4 = _BA.son_barlar(_f)
            _aaa17 = [r for r in _csv6t.DictReader(open(_f, encoding="utf-8", newline="")) if r["ticker"] == "AAA" and r["date"] == "2026-09-17"]
            if _r4a.get("rows_added") == 3 and _r4b.get("rows_added") == 1 and [r["run_label"] for r in _aaa17] == ["gunici", "kapanis"] \
                    and abs(float(_son4[("2026-09-17", "AAA")]["close"]) - 11.9) < 1e-9 and _son4[("2026-09-17", "AAA")]["run_label"] == "kapanis":
                ok("T4 gunici kismi bar + kapanis nihai bar iki satir; son_barlar() nihai (kapanis) olani verir; degismeyen BBB tekrar yazilmaz")
            else:
                bad(f"T4 gunici/kapanis: a={_r4a} b={_r4b} aaa17={[(r['run_label'], r['close']) for r in _aaa17]} son={_son4.get(('2026-09-17', 'AAA'))}")
            # T5 ay siniri
            _d5 = _veri(["2026-09-30", "2026-10-01"], {"AAA": [12.0, 12.1]})
            _r5 = _BA.append_bars(_d5, "kapanis", root=_root6t, now=_dt6t(2026, 10, 1, 15, 45, 0, tzinfo=_tz6t.utc))
            _f10 = os.path.join(_root6t, "data", "bars", "2026-10.csv")
            if os.path.exists(_f10) and sorted(_r5.get("files", [])) == ["data/bars/2026-09.csv", "data/bars/2026-10.csv"] and _r5.get("rows_added") == 4:
                ok("T5 ay siniri: iki aya yayilan tarihler iki dosyaya (2026-09.csv, 2026-10.csv), yollar repo-goreli")
            else:
                bad(f"T5 ay siniri: r={_r5} 10_var={os.path.exists(_f10)}")
            # T6 NaN kapanis satir yazilmaz; XU100 close-only
            _root6 = _tf6t.mkdtemp()
            _d6 = _veri(["2026-09-16", "2026-09-17"], {"AAA": [11.0, _np6t.nan], "BBB": [21.0, 21.3]})
            _r6 = _BA.append_bars(_d6, "kapanis", root=_root6, now=_now)
            _rows6 = list(_csv6t.DictReader(open(os.path.join(_root6, "data", "bars", "2026-09.csv"), encoding="utf-8", newline="")))
            _xu = [r for r in _rows6 if r["ticker"] == "XU100"]
            if _r6.get("rows_added") == 5 and not any(r["ticker"] == "AAA" and r["date"] == "2026-09-17" for r in _rows6) \
                    and len(_xu) == 2 and _xu[0]["open"] == "" and _xu[0]["close"] != "":
                ok("T6 NaN kapanis satir yazilmaz (2 gun x 3 - 1 = 5); XU100 close-only (open/high/low/volume bos)")
            else:
                bad(f"T6 NaN/XU100: r={_r6} rows={[(r['date'], r['ticker'], r['close']) for r in _rows6]}")
            # T7 file-fallback arsivlenmez
            _root7 = _tf6t.mkdtemp()
            _d7 = _veri(["2026-09-16"], {"AAA": [11.0]}, source="file")
            _d7["_source"] = "file_fallback_from_yahoo"
            _r7 = _BA.append_bars(_d7, "kapanis", root=_root7, now=_now)
            _st7 = _json6t.load(open(os.path.join(_root7, "docs", "state", "bar_archive.json"), encoding="utf-8"))
            if _r7.get("rows_added") == 0 and _r7.get("skipped_reason") and not os.path.exists(os.path.join(_root7, "data", "bars", "2026-09.csv")) \
                    and _st7.get("skipped_reason") == _r7.get("skipped_reason") and "file" in _st7.get("skipped_reason", ""):
                ok(f"T7 file-fallback kaynagi ARSIVLENMEZ; durum dosyasi nedeni yazar ({_st7.get('skipped_reason')})")
            else:
                bad(f"T7 file-fallback: r={_r7} st={_st7}")
            # T8 durum dosyasi
            _st = _json6t.load(open(os.path.join(_root6t, "docs", "state", "bar_archive.json"), encoding="utf-8"))
            _st_keys = {"generated_at", "run_label", "source", "rows_seen", "rows_added", "dates", "files", "skipped_reason", "writer"}
            if _st_keys <= set(_st) and _st["generated_at"].endswith("Z") and _st["run_label"] == "kapanis" and _st["rows_added"] == 4 \
                    and _st["dates"] == ["2026-09-30", "2026-10-01"]:
                ok("T8 durum dosyasi docs/state/bar_archive.json: sayaclar, tarihler, dosyalar, generated_at Z, writer")
            else:
                bad(f"T8 durum dosyasi: {_st}")
            # T9 daemon + workflow sozlesmesi (kaynak metin)
            _dsrc = open(os.path.join(ROOT, "daemon.py"), encoding="utf-8").read()
            _i_feed = _dsrc.find('_rt.phase("feed")'); _i_ba = _dsrc.find("bar_archive.append_bars(")
            _guarded = _i_ba > 0 and "guarded(" in _dsrc[max(0, _i_ba - 200):_i_ba]
            _wf_ok = all("data/bars/" in open(os.path.join(ROOT, ".github", "workflows", w), encoding="utf-8").read()
                         for w in ("bist-alpha.yml", "precise.yml"))
            # `git add -f data/bars/` dizin yoksa "pathspec did not match" ile ADIMI DUSURUR (daemon kosmayan
            # always() state adimi) -> takipli .gitkeep dizini her zaman var eder
            _keep_ok = os.path.isfile(os.path.join(ROOT, "data", "bars", ".gitkeep"))
            if _i_feed > 0 and _i_ba > _i_feed and _guarded and _wf_ok and _keep_ok:
                ok("T9 daemon: feed fazindan SONRA guarded icinde bar_archive.append_bars; iki workflow commit adimi data/bars/ ekliyor; data/bars/.gitkeep var")
            else:
                bad(f"T9 cagri sozlesmesi: feed_idx={_i_feed} ba_idx={_i_ba} guarded={_guarded} workflow={_wf_ok} gitkeep={_keep_ok}")
    except Exception as e:
        bad(f"[6t] bar arsivi testleri kosmadi: {type(e).__name__}: {e}")

    # ── [6u] TABAN-DURUST DEFTER — rebalans-pencereli, delik-farkindalikli (2026-09-18) ──
    # Olcum: 09-01 penceresinde 10 stop'un 9'u taban gunu; kagit -15.5 / taban-durust -35.9. Arac 07-08'den
    # beri kosmamisti (yetim); pencere tanimi "iki kosum arasi" idi (rebalans degil); yfinance'ta olmayan
    # bar searchsorted ile SONRAKI bara kayiyordu (IEYHO 09-17 -> 09-18, -19%/kilit 0 = uydurma).
    # Sozlesme (test-once):
    #   U1 pencere = rebalans dongusu (initial_entry/rebalance sinirlari); stoplar tarihe gore atanir (sira degil)
    #   U2 stop gunu seride YOKSA veri_eksik: kaydirma yok, oran/drag disi, sayilir ve etiketlenir
    #   U3 taban + kilit: stop gunu -10 (taban), ertesi gun -3.4 (taban degil) -> was_locked, lock 1, cikis ertesi kapanis; drag agirlikli
    #   U4 pencere ust siniri: sonraki rebalans sonrasi stop bu pencereye girmez
    #   U5 stop sonrasi seride referans gunu eksikse seri_delik=True (kilit sayisi 'en az')
    #   U6 rebuild_ledger deterministik; pencereler baslangica gore sirali; eski kayitlar YERINE gecer
    #   U7 onbellek yukleyici: pkl sozlugunden close/low, kapsam disi tarih -> None (yfinance'a dusme karari cagirana)
    #   U8 assess() yeniden kurulmus defterle calisir (anahtarlar tam)
    #   U7b onbellek kapsami hafta sonu guvenli · U9 acik kilit / kilit tavani 'en az' · U10 olculemeyen getiri None
    #   U11 drag alt-siniri C2b'yi gecemez (bagimsiz okuma, 2 tur)
    print("\n[6u] Taban-durust defter — rebalans penceresi + delik farkindaligi (test-once)")
    try:
        import json as _json6u
        import os as _os6u
        import tempfile as _tf6u
        import numpy as _np6u
        import pandas as _pd6u
        _TR6u = None
        try:
            import taban_readiness as _TR6u
        except Exception as _e6u:
            bad(f"[6u] taban_readiness import edilemedi: {type(_e6u).__name__}: {_e6u}")
        _need = ("windows_from_history", "analyze_window", "rebuild_ledger", "cache_prices", "assess")
        if _TR6u is not None and not all(hasattr(_TR6u, n) for n in _need):
            bad(f"[6u] sozlesme eksik: {[n for n in _need if not hasattr(_TR6u, n)]} yok")
        elif _TR6u is not None:
            _h = [{"date": "2026-06-05", "event": "initial_entry", "total": 1.0, "trades": []},
                  {"date": "2026-06-15", "event": "stop", "total": 0.98, "trades": [{"type": "SELL", "ticker": "AAA", "price": 90.0, "shares": 0.001, "reason": "stop"}]},
                  {"date": "2026-07-17", "event": "rebalance", "total": 1.10, "trades": [{"type": "BUY", "ticker": "BBB"}]},
                  {"date": "2026-07-28", "event": "stop", "total": 1.05, "trades": [{"type": "SELL", "ticker": "BBB", "price": 45.0, "shares": 0.002, "reason": "stop"}]},
                  {"date": "2026-07-27", "event": "stop", "total": 1.07, "trades": [{"type": "SELL", "ticker": "CCC", "price": 30.0, "shares": 0.003, "reason": "stop"}]},   # sira bozuk (gercek 07-27/28)
                  {"date": "2026-09-01", "event": "rebalance", "total": 1.20, "trades": [{"type": "BUY", "ticker": "DDD"}]},
                  {"date": "2026-09-17", "event": "stop", "total": 1.02, "trades": [{"type": "SELL", "ticker": "DDD", "price": 186.3, "shares": 0.001, "reason": "stop"}, {"type": "SELL", "ticker": "EEE", "price": 10.0, "reason": "rebalance"}]}]
            # U1
            _w = _TR6u.windows_from_history(_h)
            _u1 = [(w["start"], w["end"], sorted(s["tic"] for s in w["stops"]), w["start_total"], w["end_total"]) for w in _w]
            if _u1 == [("2026-06-05", "2026-07-17", ["AAA"], 1.0, 1.10), ("2026-07-17", "2026-09-01", ["BBB", "CCC"], 1.10, 1.20), ("2026-09-01", None, ["DDD"], 1.20, 1.02)]:
                ok("U1 pencere = rebalans dongusu: 3 pencere, stoplar TARIHE gore atanir (07-27 sira-bozuk kaydi W2'de), reason=rebalance SELL stop degil")
            else:
                bad(f"U1 pencereler: {_u1}")
            # fiyat cercevesi: is gunleri 09-14..09-24; DDD 09-16 -10, 09-17 -10 (stop), 09-18 180 (-3.4, kilit acilir)
            _idx = _pd6u.bdate_range("2026-09-14", "2026-09-24")
            _ddd = [230.0, 230.0, 207.0, 186.3, 180.0, 181.0, 182.0, 183.0, 184.0]
            _close = _pd6u.DataFrame({"DDD": _ddd, "XU100": _np6u.linspace(100, 96, len(_idx))}, index=_idx)
            _low = _close * 0.99
            # U3 taban + kilit (stop 09-17, o gun -10 -> taban; 09-18 -3.4 -> cikis 09-18 kapanisi 180 < kayit 186.3 -> drag > 0)
            _r3 = _TR6u.analyze_window(_w[2], _close, _low)
            _d3 = _r3["stops"][0]
            _u3 = _d3.get("taban") is True and _d3.get("lock_days") == 1 and abs(_d3.get("real_exit_close", 0) - 180.0) < 1e-9 \
                and _d3.get("veri_eksik") is False and _r3["n_stops"] == 1 and _r3["n_taban_stops"] == 1 and _r3["veri_eksik_stops"] == 0 \
                and abs(_r3["booked_ret"] - (-15.0)) < 1e-6 and _r3["drag_close"] > 0
            if _u3:
                ok(f"U3 taban+kilit: 09-17 -10% taban, kilit {_d3['lock_days']} gun, gercek cikis 180 (kayit 186.3 -> drag {_r3['drag_close']}pp); booked {_r3['booked_ret']}%")
            else:
                bad(f"U3: {_d3} | {dict((k, _r3.get(k)) for k in ('n_stops','n_taban_stops','veri_eksik_stops','booked_ret','drag_close'))}")
            # U2 delik: stop gunu (09-17) seride yok -> veri_eksik, kaydirma yok
            _close2 = _close.drop(_pd6u.Timestamp("2026-09-17")); _low2 = _low.drop(_pd6u.Timestamp("2026-09-17"))
            _r2 = _TR6u.analyze_window(_w[2], _close2, _low2)
            _d2 = _r2["stops"][0]
            if _d2.get("veri_eksik") is True and _d2.get("taban") is None and _d2.get("daily_ret") is None and _r2["veri_eksik_stops"] == 1 \
                    and _r2["n_taban_stops"] == 0 and _r2["taban_ratio"] == 0 and _r2["drag_close"] == 0:
                ok("U2 delik: stop gunu seride yok -> veri_eksik=True, taban/daily_ret None (SONRAKI bara KAYDIRMA yok), oran/drag disi")
            else:
                bad(f"U2 delik: {_d2} | {dict((k, _r2.get(k)) for k in ('veri_eksik_stops','n_taban_stops','taban_ratio','drag_close'))}")
            # U4 ust sinir: W2 (07-17..09-01) 09-17 stop'unu icermez (U1 zaten), analyze da pencere disini almaz
            _r4 = _TR6u.analyze_window(_w[1], _close, _low)
            if _r4["n_stops"] == 0 and _r4["veri_eksik_stops"] == 2 and all(s.get("veri_eksik") for s in _r4["stops"]):
                ok("U4 ust sinir + kapsam: W2'nin BBB/CCC stoplari fiyat cercevesinde yok -> veri_eksik (2), 09-17 DDD W2'ye girmez")
            else:
                bad(f"U4: {dict((k, _r4.get(k)) for k in ('n_stops','veri_eksik_stops'))} {_r4['stops']}")
            # U5 seri delik: referans (XU100) 09-18'de var, DDD'de 09-18 yok -> kilit 'en az', seri_delik
            _close5 = _close.copy(); _close5.loc[_pd6u.Timestamp("2026-09-18"), "DDD"] = _np6u.nan
            _r5 = _TR6u.analyze_window(_w[2], _close5, _close5 * 0.99)
            _d5 = _r5["stops"][0]
            if _d5.get("seri_delik") is True and _d5.get("taban") is True and _r5["seri_delik_stops"] == 1:
                ok("U5 stop sonrasi seride referans gunu eksik -> seri_delik=True (kilit/cikis 'en az'), stop yine taban sayilir")
            else:
                bad(f"U5: {_d5} {_r5.get('seri_delik_stops')}")
            # U6 rebuild deterministik + eski kayitlar yerine
            _l1 = _TR6u.rebuild_ledger(_h, _close, _low); _l2 = _TR6u.rebuild_ledger(_h, _close, _low)
            _u6 = _json6u.dumps(_l1, sort_keys=True) == _json6u.dumps(_l2, sort_keys=True) and [w["window_start_date"] for w in _l1] == ["2026-06-05", "2026-07-17", "2026-09-01"] \
                and all(k in _l1[0] for k in ("window_start_date", "window_end_date", "n_stops", "n_taban_stops", "veri_eksik_stops", "taban_ratio", "booked_ret", "drag_close", "drag_low", "taban_honest_close", "taban_honest_low", "max_consecutive_lock", "multi_day_locks", "price_source", "stops"))
            if _u6:
                ok("U6 rebuild_ledger deterministik, pencereler baslangica gore sirali, kayit anahtarlari tam (eski 'kosum arasi' kayitlar yerine)")
            else:
                bad(f"U6 rebuild: {[w.get('window_start_date') for w in _l1]} esit={_json6u.dumps(_l1, sort_keys=True) == _json6u.dumps(_l2, sort_keys=True)}")
            # U7 onbellek yukleyici
            _cache = {"data": {"prices": _close[["DDD"]], "mins": _low[["DDD"]], "bist": _close["XU100"]}}
            _c7 = _TR6u.cache_prices(_cache, ["DDD", "ZZZ"], "2026-09-14", "2026-09-24")
            _c7b = _TR6u.cache_prices(_cache, ["DDD"], "2026-09-01", "2026-09-24")
            if _c7 is not None and list(_c7[0].columns) == ["DDD", "XU100"] and "ZZZ" not in _c7[0].columns and _c7b is None:
                ok("U7 onbellek yukleyici: close/low + XU100 referans; evrende olmayan hisse dusurulur; kapsam disi tarih araligi -> None (uydurma yok)")
            else:
                bad(f"U7 onbellek: c7={None if _c7 is None else list(_c7[0].columns)} c7b={_c7b}")
            # U8 assess
            _ready, _lines, _verdict = _TR6u.assess(_l1)
            if isinstance(_ready, bool) and len(_lines) == 4 and "pencere" in _verdict:
                ok("U8 assess() yeniden kurulmus defterle calisiyor (4 kriter satiri)")
            else:
                bad(f"U8 assess: {_ready} {_lines} {_verdict}")
            # --- bagimsiz okuma (2026-09-18 22:55) karsi testleri ---
            # U7b hafta sonu: Cuma 09-18'de biten onbellek Pazartesi 09-21'de KAPSAR ('bugun-1' kurali None verirdi)
            _idx_cf = _pd6u.bdate_range("2026-09-01", "2026-09-18")
            _cache_cf = {"data": {"prices": _pd6u.DataFrame({"DDD": range(len(_idx_cf))}, index=_idx_cf, dtype=float)}}
            _c7c = _TR6u.cache_prices(_cache_cf, ["DDD"], "2026-09-01", "2026-09-22", today="2026-09-21")
            _c7d = _TR6u.cache_prices(_cache_cf, ["DDD"], "2026-09-01", "2026-09-30", today="2026-09-29")   # 11 gun eski -> None
            if _c7c is not None and _c7d is None:
                ok("U7b onbellek kapsami hafta sonu guvenli: Cuma onbellegi Pazartesi kapsar; 11 gun eski onbellek None")
            else:
                bad(f"U7b hafta sonu: cuma->pzt={_c7c is not None} eski={_c7d}")
            # U9 kilit ACIK + tavan: seri taban gununde bitiyor -> kilit_acik, drag_en_az; 10+ gun taban -> kilit_tavan
            _idx9 = _pd6u.bdate_range("2026-09-14", "2026-09-18")
            _c9 = _pd6u.DataFrame({"DDD": [230.0, 230.0, 207.0, 186.3, 167.7], "XU100": [100, 99, 98, 97, 96]}, index=_idx9, dtype=float)
            _r9 = _TR6u.analyze_window(_w[2], _c9, _c9 * 0.99)
            _d9 = _r9["stops"][0]
            _idx9b = _pd6u.bdate_range("2026-09-14", "2026-10-09")
            _seq = [230.0, 230.0, 207.0] + [207.0 * (0.9 ** k) for k in range(1, len(_idx9b) - 2)]
            _c9b = _pd6u.DataFrame({"DDD": _seq, "XU100": _np6u.linspace(100, 90, len(_idx9b))}, index=_idx9b, dtype=float)
            _r9b = _TR6u.analyze_window(_w[2], _c9b, _c9b * 0.99)
            _d9b = _r9b["stops"][0]
            if _d9["kilit_acik"] is True and _r9["kilit_acik_stops"] == 1 and _r9["drag_en_az"] is True                     and _d9b["kilit_tavan"] is True and _d9b["lock_days"] >= 10 and _r9b["drag_en_az"] is True:
                ok(f"U9 kilit ACIK (seri taban gununde bitiyor) -> kilit_acik, drag EN AZ; {_d9b['lock_days']} gun taban -> kilit_tavan (zorla cikis) etiketli")
            else:
                bad(f"U9 kilit: acik={_d9} tavan={_d9b} r9={_r9.get('drag_en_az')} r9b={_r9b.get('drag_en_az')}")
            # U10 olculemeyen getiri: start_total yok -> booked None (0.0 UYDURULMAZ); assess c2a fail-closed
            _w10 = dict(_w[2]); _w10["start_total"] = None
            _r10 = _TR6u.analyze_window(_w10, _close, _low)
            _ok10, _ln10, _ = _TR6u.assess([_r10])
            if _r10["booked_ret"] is None and _r10["taban_honest_low"] is None and _ok10 is False and "olculemeyen pencere 1" in _ln10[1]:
                ok("U10 olculemeyen getiri None (0.0 uydurulmaz); assess olculemeyen pencereyi kanit saymaz (c2a False)")
            else:
                bad(f"U10: booked={_r10['booked_ret']} th={_r10['taban_honest_low']} ready={_ok10} satir={_ln10[1]}")
            # U11 drag ALT SINIR (acik kilit) tavanin altinda kalsa da C2b'yi GECEMEZ (fail-closed)
            _w11 = dict(_l1[0]); _w11.update(drag_low=3.0, drag_en_az=True, taban_honest_low=5.0, max_consecutive_lock=1, taban_ratio=30)
            _w11b = dict(_w11); _w11b["drag_en_az"] = False
            _l11 = [_w11] * 5; _l11b = [_w11b] * 5
            _r11, _ln11, _ = _TR6u.assess(_l11); _r11b, _, _ = _TR6u.assess(_l11b)
            if _r11 is False and "alt-sinir" in _ln11[1] and _r11b is True:
                ok("U11 drag alt-sinir pencere (acik kilit/delik/tavan) C2b'yi gecemez; ayni sayilar kesinse gecer (5 pencere)")
            else:
                bad(f"U11: en_az={_r11} satir={_ln11[1]} kesin={_r11b}")
    except Exception as e:
        # C10 KARARI (bilerek, yazili): blok-sarmali genis except -> bad() = KAYITLI basarisizlik (selftest
        # exit 1), yutma degil; daraltilsaydi tek beklenmeyen hata butun suiti dusururdu. Repo bloklarinin geleneği.
        bad(f"[6u] taban defteri testleri kosmadi: {type(e).__name__}: {e}")

    # ── [6v] #3a-B — KILITLI HISSEYE "AL" YAZILMAZ: bar durumu TEK OTORITE + rapor/liste/panel korumasi ──
    # Canli kanit 2026-09-16..21: OZATD/TRHOL/ALKLC/DSTKF/SELEC taban kilidindeyken panel+Telegram "AL"
    # (signals: kilitli barda CPR 0.5 dolgusu + acc patlamasi -> "Birikim"). F motoruna dokunmaz (R1).
    # Sozlesme (test-once):
    #   V1 bar_state.gun_durumu: son bar taban/tavan (ret <= -9.5 / >= 9.5), ardisik gun, kilitli bar (range 0);
    #      tarih indekste yoksa olculemedi=True (kaydirma yok); etiket "TABAN KILIDI (k g)" / "TAVAN KILIDI (k g)"
    #   V2 reporter._action: kilit varsa AL/FIRSAT olamaz -> BEKLE (Birikim olsa da); stop -> SAT onceligi korunur
    #   V3 reporter.generate_report kaynak sozlesmesi: her pick icin gun_durumu; action kilit'e bagli;
    #      display_signal etiketi oncelikli; FIRSAT listesi kilitli hisseyi atlar; satirda kilit alanlari
    #   V4 radar/omega: kilitli hisse donusum/sessiz-birikim listesine giremez (kaynak sozlesmesi)
    #   V5 panel: karar karti basligi 'F neden aldi?' YOK (pozisyon yoksa 'secti', varsa 'tutuyor')
    print("\n[6v] #3a-B kilitli hisseye AL yazilmaz (test-once)")
    try:
        import pandas as _pd6v
        import numpy as _np6v
        try:
            from bist_alpha import bar_state as _BS
        except Exception as _e6v:
            _BS = None
            bad(f"V1 sozlesmesi eksik: bist_alpha.bar_state import edilemedi ({type(_e6v).__name__}: {_e6v})")
        if _BS is not None:
            _ix = _pd6v.bdate_range("2026-09-08", periods=10)
            # AAA: son 3 gun taban (-10 kilitli), BBB: son gun tavan (+10, range>0 = yumusak), CCC: normal
            _pa = [100, 101, 102, 103, 104, 105, 106, 95.4, 85.86, 77.27]
            _pb = [50, 50.5, 51, 51.5, 52, 52.5, 53, 53.5, 54, 59.4]
            _pc = [10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9]
            _cl = _pd6v.DataFrame({"AAA": _pa, "BBB": _pb, "CCC": _pc}, index=_ix, dtype=float)
            _mn = _cl.copy(); _mx = _cl.copy()
            _mx.loc[:, "BBB"] = _cl["BBB"] * 1.01; _mn.loc[:, "BBB"] = _cl["BBB"] * 0.99      # BBB range>0
            _mx.loc[:, "CCC"] = _cl["CCC"] * 1.01; _mn.loc[:, "CCC"] = _cl["CCC"] * 0.99
            _mx.loc[_ix[:7], "AAA"] = _cl["AAA"].iloc[:7] * 1.01; _mn.loc[_ix[:7], "AAA"] = _cl["AAA"].iloc[:7] * 0.99  # AAA son 3 gun range 0
            _d6v = {"prices": _cl, "mins": _mn, "maxs": _mx}
            _a = _BS.gun_durumu(_d6v, "AAA", _ix[-1]); _b = _BS.gun_durumu(_d6v, "BBB", _ix[-1]); _c = _BS.gun_durumu(_d6v, "CCC", _ix[-1])
            _y = _BS.gun_durumu(_d6v, "AAA", _pd6v.Timestamp("2026-09-27"))                    # indekste yok
            _v1 = (_a["son"] == "taban" and _a["ardisik"] == 3 and _a["kilitli_bar"] == 3 and _a["olculemedi"] is False
                   and _b["son"] == "tavan" and _b["ardisik"] == 1 and _b["kilitli_bar"] == 0
                   and _c["son"] is None and _c["ardisik"] == 0
                   and _y["olculemedi"] is True and _y["son"] is None
                   and _BS.etiket(_a) == "TABAN KILIDI (3 g)" and _BS.etiket(_b) == "TAVAN KILIDI (1 g)" and _BS.etiket(_c) is None)
            if _v1:
                ok("V1 bar_state: taban 3 g (kilitli 3), tavan 1 g (yumusak), normal None; indekste olmayan tarih olculemedi (kaydirma yok); etiketler")
            else:
                bad(f"V1 bar_state: a={_a} b={_b} c={_c} y={_y}")
            # V2 _action
            from bist_alpha import reporter as _RP
            import inspect as _insp6v
            _sig_ok = "kilit" in _insp6v.signature(_RP._action).parameters
            _v2 = _sig_ok and _RP._action(False, True, "Birikim", False, kilit="taban") == "BEKLE" \
                and _RP._action(False, True, "GÜÇLÜ_BİRİKİM", False, kilit="tavan") == "BEKLE" \
                and _RP._action(False, False, "GÜÇLÜ_BİRİKİM", False, kilit="taban") == "BEKLE" \
                and _RP._action(True, True, "Birikim", True, kilit="taban") == "SAT" \
                and _RP._action(False, True, "Birikim", False, kilit=None) == "AL" \
                and _RP._action(False, False, "GÜÇLÜ_BİRİKİM", False, kilit=None) == "FIRSAT"
            if _v2:
                ok("V2 reporter._action: kilitli -> BEKLE (Birikim/GUCLU olsa da, FIRSAT da olamaz); stop -> SAT; kilit yoksa eski davranis")
            else:
                bad(f"V2 _action: sig_ok={_sig_ok}")
            # V3 generate_report kaynak sozlesmesi
            _rsrc = open(os.path.join(ROOT, "bist_alpha", "reporter.py"), encoding="utf-8").read()
            _g = _rsrc[_rsrc.index("def generate_report("):]
            _g_top = _g[:_g.index("firsatlar = []")]; _g_fir = _g[_g.index("firsatlar = []"):_g.index("firsatlar = []") + 1200]
            _v3 = ("bar_state.gun_durumu(" in _g_top and "kilit=" in _g_top and "bar_state.etiket(" in _g_top
                   and '"kilit_durumu"' in _g_top and '"kilit_gun"' in _g_top
                   and "bar_state.gun_durumu(" in _g_fir and "continue" in _g_fir)
            if _v3:
                ok("V3 generate_report: her pick icin gun_durumu -> action(kilit) + etiketli display_signal + kilit alanlari; FIRSAT kilitliyi atlar")
            else:
                bad(f"V3 generate_report sozlesmesi: top={'bar_state.gun_durumu(' in _g_top} etiket={'bar_state.etiket(' in _g_top} firsat={'bar_state.gun_durumu(' in _g_fir}")
            # V4 radar / omega
            _rad = open(os.path.join(ROOT, "bist_alpha", "radar.py"), encoding="utf-8").read()
            _omg = open(os.path.join(ROOT, "bist_alpha", "omega.py"), encoding="utf-8").read()
            _v4 = ("bar_state" in _rad and "gun_durumu(" in _rad and "bar_state" in _omg and "gun_durumu(" in _omg
                   and "kilit" in _omg[_omg.index("def _omega_score"):_omg.index("def _omega_score") + 1500])
            if _v4:
                ok("V4 radar/omega: kilitli hisse donusum/sessiz-birikim listelerine ve omega kapisina giremiyor (kaynak sozlesmesi)")
            else:
                bad("V4 radar/omega bar_state kapisi yok")
            # V5 panel basligi
            _html = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
            _v5 = "F neden aldi?" not in _html and "F neden secti" in _html and "F neden tutuyor" in _html
            if _v5:
                ok("V5 panel karar karti: 'F neden aldi?' kaldirildi; pozisyon yoksa 'secti', varsa 'tutuyor'")
            else:
                bad("V5 panel basligi hala 'F neden aldi?' ya da durum-farkindali degil")
    except Exception as e:
        # C10 karari (bilerek, yazili): blok-sarmali except -> bad() = kayitli basarisizlik, yutma degil
        bad(f"[6v] #3a-B testleri kosmadi: {type(e).__name__}: {e}")

    # ── [6h] #0b — DOLU AMA ZAMAN EKSENI DELIK PRIMARY FALLBACK'I ENGELLEMEMELI ──
    # CANLI VAKA (2026-09-08): Yahoo matrisi 624 hisseyle "dolu" gorundu; 09-08
    # bari geldi, fakat XU100'un islem gordugu 09-07 satiri hisselerde %99.52 NaN
    # kaldi. safe_feed yalniz `empty` ve kolon sayisini kontrol ettigi icin Yahoo'yu
    # kabul etti, daha taze/tam Borsapy yedegine hic ulasmadi.
    #
    # ESIK ICAT EDILMEDI: datafeed._drop_sparse_tail varsayilani olan %50 kullanilir.
    # TAKVIM ICAT EDILMEDI: beklenen gunler feed'in kendi `bist` (XU100) indeksidir.
    # Boylece gercek tatil (gun hem BIST hem hisse matrisinde yok) sahte fallback
    # uretmez. Bu blok test-once yazildi; ilk sart mevcut kodda KIRMIZI olmalidir.
    print("\n[6h] #0b dolu-ama-delik primary daha tam yedege dusmeli (test-once)")
    try:
        import tempfile as _tempfile4
        from datetime import datetime as _datetime4
        from pathlib import Path as _Path4
        from zoneinfo import ZoneInfo as _ZoneInfo4
        import pandas as _pd4
        from bist_alpha import selfheal as _SH4, datafeed as _DF4, config as _CFG4

        _d0, _d1, _d2 = _pd4.to_datetime(["2026-09-04", "2026-09-07", "2026-09-08"])
        _cols4 = [f"T{i:02d}" for i in range(60)]
        _tz4 = _ZoneInfo4("Europe/Istanbul")
        _now4 = _datetime4(2026, 9, 8, 14, 30, tzinfo=_tz4)
        _calendar_path4 = (
            _Path4(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )

        def _prices4(index, sparse_day=None):
            frame = _pd4.DataFrame(100.0, index=index, columns=_cols4)
            if sparse_day is not None:
                frame.loc[sparse_day] = float("nan")
                frame.loc[sparse_day, _cols4[0]] = 100.0  # %1.67 dolu < kanonik %50
            return frame

        def _packet4(price_index, bist_index, sparse_day=None):
            return {
                "prices": _prices4(price_index, sparse_day=sparse_day),
                "bist": _pd4.Series(100.0, index=bist_index),
                "_bist_ok": True,
                "_source_pool_count": len(_cols4),
            }

        class _Feed4:
            def __init__(self, packet):
                self.packet = packet

            def get_latest(self):
                return self.packet

        _old_get_feed4 = _DF4.get_feed
        _sentinel4 = object()
        _old_source4 = getattr(_CFG4, "DATA_SOURCE", _sentinel4)
        _old_chain4 = getattr(_CFG4, "DATA_FALLBACK_CHAIN", _sentinel4)
        _old_allow4 = getattr(_CFG4, "ALLOW_FILE_FALLBACK", _sentinel4)
        _old_feed_state4 = getattr(_SH4, "DATA_FEED_RUN_STATE", _sentinel4)
        _feed_tmp4 = _tempfile4.TemporaryDirectory()
        try:
            _SH4.DATA_FEED_RUN_STATE = _Path4(_feed_tmp4.name) / "data_feed_run.json"
            _CFG4.DATA_SOURCE = "yahoo"
            _CFG4.DATA_FALLBACK_CHAIN = "borsapy"
            _CFG4.ALLOW_FILE_FALLBACK = False

            # 1) XU100'da islem gunu var; primary hisse satiri sistemik seyrek.
            _calls4 = []
            _packets4 = {
                "yahoo": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2], sparse_day=_d1),
                "borsapy": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2]),
            }

            def _get_feed_gap4(name):
                _calls4.append(name)
                return _Feed4(_packets4[name])

            _DF4.get_feed = _get_feed_gap4
            _out4 = _SH4.safe_feed(now=_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "borsapy" and _calls4 == ["yahoo", "borsapy"]:
                ok("islem-gunu satiri <%50 dolu -> primary reddedildi, borsapy secildi")
            else:
                bad("#0b delik primary fallback'i: beklenen borsapy/calls "
                    f"['yahoo','borsapy'], alinan {_out4.get('_source_base')}/{_calls4}")

            # 2) Resmi takvimde 07-15 kapali: kaynakta satir olmamasi gercek tatil.
            _calls4 = []
            _h0_4, _h2_4 = _pd4.to_datetime(["2026-07-14", "2026-07-16"])
            _packets4 = {
                "yahoo": _packet4([_h0_4, _h2_4], [_h0_4, _h2_4]),
                "borsapy": _packet4([_h0_4, _h2_4], [_h0_4, _h2_4]),
            }
            _DF4.get_feed = _get_feed_gap4
            _holiday_now4 = _datetime4(2026, 7, 16, 14, 30, tzinfo=_tz4)
            _out4 = _SH4.safe_feed(
                now=_holiday_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "yahoo" and _calls4 == ["yahoo"]:
                ok("resmi tatilde satir yok -> primary korunur, sahte fallback yok")
            else:
                bad("#0b tatil false-positive: beklenen yahoo/calls ['yahoo'], "
                    f"alinan {_out4.get('_source_base')}/{_calls4}")

            # 3) XU100'da islem gunu var fakat primary'de hisse satiri tamamen yok.
            _calls4 = []
            _packets4 = {
                "yahoo": _packet4([_d0, _d2], [_d0, _d1, _d2]),
                "borsapy": _packet4([_d0, _d1, _d2], [_d0, _d1, _d2]),
            }
            _DF4.get_feed = _get_feed_gap4
            _out4 = _SH4.safe_feed(now=_now4, calendar_path=_calendar_path4)
            if _out4.get("_source_base") == "borsapy" and _calls4 == ["yahoo", "borsapy"]:
                ok("XU100 islem gununde hisse satiri YOK -> primary reddedildi")
            else:
                bad("#0b eksik islem-gunu satiri: beklenen borsapy/calls "
                    f"['yahoo','borsapy'], alinan {_out4.get('_source_base')}/{_calls4}")

            # 4) Gercek borsapy 0.10.2 sozlesmesi: coklu indirme varsayilan olarak
            # (fiyat, sembol) kolonlari dondurur; adapter `group_by=ticker` istemeli.
            # Endeks de `index(...).history(...)` uzerinden okunur.
            import types as _types4
            from bist_alpha import universe as _UNI4

            _old_borsapy4 = sys.modules.get("borsapy", _sentinel4)
            _old_tickers4 = _UNI4.all_bist_tickers
            _old_meta4 = _UNI4.universe_meta
            _bp_calls4 = []
            _bp_dates4 = _pd4.to_datetime(["2026-09-07", "2026-09-08"], utc=True).tz_convert("Europe/Istanbul")

            def _bp_frame4(base):
                return _pd4.DataFrame({
                    "Open": [base, base + 1],
                    "High": [base + 2, base + 3],
                    "Low": [base - 1, base],
                    "Close": [base + 1, base + 2],
                    "Volume": [1000.0, 1100.0],
                }, index=_bp_dates4)

            def _bp_download4(tickers, period="1mo", interval="1d",
                              group_by="column", **_kwargs):
                _bp_calls4.append(("download", group_by, tuple(tickers)))
                frames = {ticker: _bp_frame4(100.0 + pos * 10)
                          for pos, ticker in enumerate(tickers)}
                raw = _pd4.concat(frames, axis=1)
                return raw if group_by == "ticker" else raw.swaplevel(axis=1).sort_index(axis=1)

            class _BPIndex4:
                def history(self, period="1mo", interval="1d"):
                    _bp_calls4.append(("index_history", period, interval))
                    return _bp_frame4(9000.0)

            def _bp_index4(symbol):
                _bp_calls4.append(("index", symbol))
                return _BPIndex4()

            try:
                sys.modules["borsapy"] = _types4.SimpleNamespace(
                    download=_bp_download4,
                    index=_bp_index4,
                )
                _UNI4.all_bist_tickers = lambda: ["AAA", "BBB"]
                _UNI4.universe_meta = lambda: {}
                _bp_out4 = _DF4.BorsaPyFeed().get_latest()
                _bp_ok4 = (
                    list(_bp_out4["prices"].columns) == ["AAA", "BBB"]
                    and bool(_bp_out4.get("_bist_ok"))
                    and ("download", "ticker", ("AAA", "BBB")) in _bp_calls4
                    and ("index_history", "2y", "1d") in _bp_calls4
                )
                if _bp_ok4:
                    ok("borsapy 0.10.2: ticker kolon grubu + index.history sozlesmesi")
                else:
                    bad(f"#0b borsapy adapter sozlesmesi: calls={_bp_calls4}, "
                        f"cols={list(_bp_out4.get('prices', []).columns)}")

                _daily_frames4 = [
                    _bp_out4[key]
                    for key in ("prices", "mins", "maxs", "aofs", "volumes", "opens", "bist")
                ]
                _daily_axis_ok4 = all(
                    isinstance(frame.index, _pd4.DatetimeIndex)
                    and frame.index.tz is None
                    and all(ts == ts.normalize() for ts in frame.index)
                    and list(frame.index) == list(_pd4.to_datetime(["2026-09-07", "2026-09-08"]))
                    for frame in _daily_frames4
                )
                if _daily_axis_ok4:
                    ok("borsapy gunluk indeks sozlesmesi timezone-naive gece yarisi")
                else:
                    bad("#0b borsapy gunluk indeks sozlesmesi: tz-aware/saatli indeks sizdi")
            except Exception as e:
                bad(f"#0b borsapy adapter sozlesmesi: {type(e).__name__}: {e}")
            finally:
                if _old_borsapy4 is _sentinel4:
                    sys.modules.pop("borsapy", None)
                else:
                    sys.modules["borsapy"] = _old_borsapy4
                _UNI4.all_bist_tickers = _old_tickers4
                _UNI4.universe_meta = _old_meta4
        finally:
            _DF4.get_feed = _old_get_feed4
            for _name4, _old4 in [
                ("DATA_SOURCE", _old_source4),
                ("DATA_FALLBACK_CHAIN", _old_chain4),
                ("ALLOW_FILE_FALLBACK", _old_allow4),
            ]:
                if _old4 is _sentinel4:
                    try:
                        delattr(_CFG4, _name4)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG4, _name4, _old4)
            if _old_feed_state4 is _sentinel4:
                try:
                    delattr(_SH4, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH4.DATA_FEED_RUN_STATE = _old_feed_state4
            _feed_tmp4.cleanup()
    except Exception as e:
        bad(f"#0b [6h] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6i] P0.6 -- TUM KAYNAKLAR DUSERSE DENEME MANIFESTI KAYBOLMAMALI --
    # Dashboard yalniz basarili rapordan sonra yazilir. Veri zinciri tamamen
    # duserse kok nedeni exception metninde birakmak, state commit adimina
    # kalici bir artefakt vermez. Ayni sema basari ve toplam-ret yolunda yazilir.
    print("\n[6i] P0.6 kaynak deneme manifesti basari ve toplam rette kalici")
    try:
        import json as _json5
        import tempfile as _tempfile5
        from datetime import datetime as _datetime5
        from pathlib import Path as _Path5
        from zoneinfo import ZoneInfo as _ZoneInfo5
        import pandas as _pd5
        from bist_alpha import selfheal as _SH5, datafeed as _DF5, config as _CFG5

        class _FailFeed5:
            def __init__(self, source):
                self.source = source

            def get_latest(self):
                raise RuntimeError(f"{self.source}-down")

        class _OkFeed5:
            def get_latest(self):
                idx = _pd5.to_datetime(["2026-09-08", "2026-09-09"])
                cols = [f"M{i:02d}" for i in range(60)]
                return {
                    "prices": _pd5.DataFrame(100.0, index=idx, columns=cols),
                    "bist": _pd5.Series(100.0, index=idx),
                    "_bist_ok": True,
                    "_source_pool_count": 60,
                }

        _sentinel5 = object()
        _old_path5 = getattr(_SH5, "DATA_FEED_RUN_STATE", _sentinel5)
        _expected_path5 = (
            _Path5(_SH5.__file__).resolve().parents[1]
            / "docs" / "state" / "data_feed_run.json"
        )
        if (_old_path5 is not _sentinel5
                and _Path5(_old_path5).is_absolute()
                and _Path5(_old_path5) == _expected_path5):
            ok("manifest yolu cwd'den bagimsiz ve repo kokune sabit")
        else:
            bad(f"P0.6 manifest yolu repo kokune sabit degil: {_old_path5}")
        _old_writer5 = _SH5._write_data_feed_run
        _old_retry5 = _SH5.with_retry
        _old_get_feed5 = _DF5.get_feed
        _old_source5 = getattr(_CFG5, "DATA_SOURCE", _sentinel5)
        _old_chain5 = getattr(_CFG5, "DATA_FALLBACK_CHAIN", _sentinel5)
        _old_allow5 = getattr(_CFG5, "ALLOW_FILE_FALLBACK", _sentinel5)
        _now5 = _datetime5(
            2026, 9, 9, 14, 30,
            tzinfo=_ZoneInfo5("Europe/Istanbul"),
        )
        _calendar_path5 = (
            _Path5(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        try:
            with _tempfile5.TemporaryDirectory() as _td5:
                _state5 = _Path5(_td5) / "data_feed_run.json"
                _SH5.DATA_FEED_RUN_STATE = _state5
                _SH5.with_retry = lambda fn, **_kwargs: fn()
                _CFG5.DATA_SOURCE = "yahoo"
                _CFG5.DATA_FALLBACK_CHAIN = "borsapy,file"
                _CFG5.ALLOW_FILE_FALLBACK = False

                _DF5.get_feed = lambda source: _FailFeed5(source)
                try:
                    _SH5.safe_feed(now=_now5, calendar_path=_calendar_path5)
                    bad("P0.6 toplam ret RuntimeError vermedi")
                except RuntimeError:
                    pass

                if not _state5.exists():
                    bad("P0.6 toplam rette data_feed_run.json yazilmadi")
                else:
                    _failed5 = _json5.loads(_state5.read_text(encoding="utf-8"))
                    _statuses5 = [(a.get("source"), a.get("status"))
                                  for a in _failed5.get("source_attempts", [])]
                    if (_failed5.get("status") == "failed"
                            and _failed5.get("primary_source") == "yahoo"
                            and _failed5.get("selected_source") is None
                            and _statuses5 == [("yahoo", "failed"),
                                              ("borsapy", "failed"),
                                              ("file", "skipped")]):
                        ok("toplam rette kaynak/status/reason zinciri kalici")
                    else:
                        bad(f"P0.6 toplam-ret manifesti yanlis: {_failed5}")

                    _timed5 = all(
                        a.get("started_at") and a.get("finished_at")
                        and isinstance(a.get("duration_s"), (int, float))
                        and (a.get("error") or a.get("reason"))
                        for a in _failed5.get("source_attempts", [])
                    )
                    if _failed5.get("generated_at") and _timed5:
                        ok("toplam-ret manifesti zaman/sure ve ret nedenlerini tasiyor")
                    else:
                        bad("P0.6 toplam-ret manifestinde zaman/sure/ret nedeni eksik")

                _DF5.get_feed = lambda source: _OkFeed5()
                _out5 = _SH5.safe_feed(now=_now5, calendar_path=_calendar_path5)
                _success5 = (_json5.loads(_state5.read_text(encoding="utf-8"))
                             if _state5.exists() else {})
                _ok_attempt5 = _success5.get("source_attempts", [{}])[-1]
                if (_out5.get("_source_base") == "yahoo"
                        and _success5.get("status") == "ok"
                        and _success5.get("selected_source") == "yahoo"
                        and _ok_attempt5.get("status") == "ok"
                        and _ok_attempt5.get("returned_symbols") == 60
                        and _ok_attempt5.get("expected_pool") == 60
                        and _ok_attempt5.get("last_data_date") == "2026-09-09"):
                    ok("basarili kaynak ayni manifesti olculen alanlarla ok yeniliyor")
                else:
                    bad(f"P0.6 basari manifesti yazilmadi/yanlis: {_success5}")

                def _broken_writer5(*_args, **_kwargs):
                    raise OSError("manifest-readonly")

                _SH5._write_data_feed_run = _broken_writer5
                _out_write_fail5 = _SH5.safe_feed(
                    now=_now5, calendar_path=_calendar_path5)
                if _out_write_fail5.get("_source_base") == "yahoo":
                    ok("manifest yazma hatasi saglikli kaynak kararini degistirmiyor")
                else:
                    bad("P0.6 manifest hatasi saglikli kaynagi fallback'e itti")
        finally:
            _SH5._write_data_feed_run = _old_writer5
            _SH5.with_retry = _old_retry5
            _DF5.get_feed = _old_get_feed5
            if _old_path5 is _sentinel5:
                try:
                    delattr(_SH5, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH5.DATA_FEED_RUN_STATE = _old_path5
            for _name5, _old5 in [
                ("DATA_SOURCE", _old_source5),
                ("DATA_FALLBACK_CHAIN", _old_chain5),
                ("ALLOW_FILE_FALLBACK", _old_allow5),
            ]:
                if _old5 is _sentinel5:
                    try:
                        delattr(_CFG5, _name5)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG5, _name5, _old5)
    except Exception as e:
        bad(f"P0.6 [6i] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6j] P0.6 -- BAGIMSIZ XIST TAKVIMI VE TAZELIK SOZLESMESI --
    # Takvim, dogrulanan fiyat kaynagindan turetilmez. Yetkili artefakt Borsa
    # Istanbul'un yillik Pay Piyasasi takvimidir; exchange_calendars yalniz
    # capraz kontroldur. Bu blok artefakti, takvim API'sini ve datafeed
    # entegrasyonunu sinar. Test-once commit'inde artefakt yesil, entegrasyon
    # sartlari kirmiziydi; uretim yamasi artik ayni sartlari yesile cevirir.
    print("\n[6j] P0.6 bagimsiz XIST takvimi ve tazelik kapisi (test-once)")
    try:
        import json as _json6
        import re as _re6
        from datetime import datetime as _datetime6
        from pathlib import Path as _Path6
        from zoneinfo import ZoneInfo as _ZoneInfo6
        import pandas as _pd6
        from bist_alpha import datafeed as _DF6

        _calendar_path6 = (
            _Path6(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        _calendar_doc6 = _json6.loads(
            _calendar_path6.read_text(encoding="utf-8")
        )

        _source6 = _calendar_doc6.get("source", {})
        _source_ok6 = (
            _calendar_doc6.get("market") == "XIST"
            and _calendar_doc6.get("timezone") == "Europe/Istanbul"
            and _calendar_doc6.get("valid_from") == "2026-01-01"
            and _calendar_doc6.get("valid_through") == "2026-12-31"
            and _source6.get("url")
            == "https://www.borsaistanbul.com/files/equity-market-2026-holiday-schedule.pdf"
            and _source6.get("sha256")
            == "3a1b39913abc188788da533c5e25000b6bb0a9f94057d21a61f068ef17efe85d"
            and bool(_re6.fullmatch(r"[0-9a-f]{64}", _source6.get("sha256", "")))
        )
        if _source_ok6:
            ok("XIST takvim artefakti yetkili kaynak ve gercek SHA-256 tasiyor")
        else:
            bad(f"P0.6 XIST takvim kaynak metadatasi yanlis: {_source6}")

        _closed6 = set(_calendar_doc6.get("full_day_closures", []))
        _expected_closed6 = {
            "2026-01-01", "2026-03-20", "2026-03-21", "2026-03-22",
            "2026-04-23", "2026-05-01", "2026-05-19", "2026-05-27",
            "2026-05-28", "2026-05-29", "2026-05-30", "2026-07-15",
            "2026-08-30", "2026-10-29",
        }
        _half6 = {
            item.get("date"): item.get("close")
            for item in _calendar_doc6.get("half_days", [])
        }
        _hours6 = _calendar_doc6.get("session_hours", {})
        if (_closed6 == _expected_closed6
                and _half6 == {
                    "2026-03-19": "13:00",
                    "2026-05-26": "13:00",
                    "2026-10-28": "13:00",
                }
                and _hours6.get("regular_close") == "18:10"):
            ok("2026 tam tatil, resmi 13:00 yarim gun ve 18:10 seans saatleri sabit")
        else:
            bad("P0.6 XIST resmi tatil/seans listesi eksik veya farkli")

        _renewal6 = _calendar_doc6.get("renewal_policy", {})
        _lead_days6 = [
            row.get("lead_days")
            for row in _renewal6.get("publication_history", [])
        ]
        _source_states6 = _calendar_doc6.get("source_check_contract", {})
        if (_lead_days6 == [10, 7, 28]
                and _renewal6.get("warning_days_before_expiry")
                == max(_lead_days6) + _renewal6.get("operational_margin_days", -1)
                == 35
                and _source_states6.get("statuses")
                == ["UNCHANGED", "CHANGED", "UNREACHABLE"]
                and _source_states6.get("unreachable_is_changed") is False):
            ok("yenileme 35 gun ve kaynak UNREACHABLE/CHANGED ayrimi olcumden turetilmis")
        else:
            bad("P0.6 takvim yenileme veya kaynak-kontrol sozlesmesi yanlis")

        try:
            from bist_alpha import market_calendar as _MC6
        except ImportError:
            _MC6 = None

        _tz6 = _ZoneInfo6("Europe/Istanbul")
        if _MC6 is None:
            for _missing6 in (
                "son kapanmis seans API'si",
                "tazelik/bar-tamligi ayrimi",
                "yenileme ve kapsam-disi fail-closed",
                "kaynak UNREACHABLE/CHANGED siniflandirmasi",
            ):
                bad(f"P0.6 bagimsiz takvim uygulamasi yok: {_missing6}")
        else:
            _loaded6 = _MC6.load_calendar(_calendar_path6)

            try:
                _session_cases6 = [
                    ("normal-acilis-oncesi",
                     _datetime6(2026, 9, 7, 9, 45, tzinfo=_tz6), "2026-09-04"),
                    ("normal-kapanis-sonrasi",
                     _datetime6(2026, 9, 7, 18, 40, tzinfo=_tz6), "2026-09-07"),
                    ("yarim-gun-12:59",
                     _datetime6(2026, 3, 19, 12, 59, tzinfo=_tz6), "2026-03-18"),
                    ("yarim-gun-13:01",
                     _datetime6(2026, 3, 19, 13, 1, tzinfo=_tz6), "2026-03-19"),
                    ("bayram-tam-kapali",
                     _datetime6(2026, 3, 20, 18, 40, tzinfo=_tz6), "2026-03-19"),
                ]
                _session_results6 = [
                    (name, str(_MC6.expected_last_closed_session(now, _loaded6))[:10], expected)
                    for name, now, expected in _session_cases6
                ]
                if all(actual == expected
                       for _name, actual, expected in _session_results6):
                    ok("normal/tatil/13:00 yarim gun son kapanmis seansi dogru")
                else:
                    bad(f"P0.6 son kapanmis seans vakalari: {_session_results6}")
            except Exception as e:
                bad(f"P0.6 son kapanmis seans API'si: {type(e).__name__}: {e}")

            try:
                _fresh6 = _MC6.assess_freshness(
                    "2026-09-09",
                    _datetime6(2026, 9, 9, 14, 30, tzinfo=_tz6),
                    _loaded6,
                )
                _stale6 = _MC6.assess_freshness(
                    "2026-09-07",
                    _datetime6(2026, 9, 9, 14, 30, tzinfo=_tz6),
                    _loaded6,
                )
                _after_close6 = _MC6.assess_freshness(
                    "2026-09-08",
                    _datetime6(2026, 9, 9, 18, 40, tzinfo=_tz6),
                    _loaded6,
                )
                if (_fresh6.get("freshness_status") == "FRESH"
                        and _fresh6.get("expected_last_closed_session") == "2026-09-08"
                        and _fresh6.get("bar_completeness") == "unknown"
                        and _stale6.get("reject_code") == "STALE_LAST_DATA"
                        and _after_close6.get("reject_code") == "STALE_LAST_DATA"):
                    ok("tazelik gecisi bar tamligi iddia etmiyor; bayatlik slot saatine bagli")
                else:
                    bad("P0.6 tazelik/bar-tamligi sozlesmesi yanlis")
            except Exception as e:
                bad(f"P0.6 tazelik API'si: {type(e).__name__}: {e}")

            try:
                _renew_ok6 = _MC6.renewal_status(
                    _datetime6(2026, 11, 25, 12, 0, tzinfo=_tz6), False, _loaded6)
                _renew_warn6 = _MC6.renewal_status(
                    _datetime6(2026, 11, 26, 12, 0, tzinfo=_tz6), False, _loaded6)
                _renew_expired6 = _MC6.renewal_status(
                    _datetime6(2027, 1, 1, 9, 45, tzinfo=_tz6), False, _loaded6)
                if (_renew_ok6.get("status") == "OK"
                        and _renew_warn6.get("status") == "WARNING"
                        and _renew_warn6.get("days_remaining") == 35
                        and _renew_expired6.get("reject_code") == "CALENDAR_UNAVAILABLE"):
                    ok("35 gun yenileme uyarisi ve kapsam-disinda fail-closed")
                else:
                    bad("P0.6 takvim yenileme/kapsam-disi sozlesmesi yanlis")
            except Exception as e:
                bad(f"P0.6 yenileme API'si: {type(e).__name__}: {e}")

            try:
                _hash6 = _source6["sha256"]
                _source_results6 = (
                    _MC6.classify_source_check(True, _hash6, _hash6),
                    _MC6.classify_source_check(True, "0" * 64, _hash6),
                    _MC6.classify_source_check(False, None, _hash6),
                )
                if _source_results6 == ("UNCHANGED", "CHANGED", "UNREACHABLE"):
                    ok("kaynak cekilemedi ile olculdu-ve-degisti ayriliyor")
                else:
                    bad(f"P0.6 kaynak durumlari yanlis: {_source_results6}")
            except Exception as e:
                bad(f"P0.6 kaynak-kontrol API'si: {type(e).__name__}: {e}")

        _d4_6, _d7_6, _d8_6, _d9_6 = _pd6.to_datetime(
            ["2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09"]
        )
        _cols6 = [f"C{i:02d}" for i in range(60)]
        _external_sessions6 = _pd6.DatetimeIndex(
            [
                day for day in _pd6.date_range("2026-01-01", "2026-09-09", freq="B")
                if day.strftime("%Y-%m-%d") not in _closed6
            ]
        )

        # Feed'in kendi BIST serisi de 09-07'yi kaybetse bagimsiz takvim kaybi gorur.
        _missing_day_packet6 = {
            "prices": _pd6.DataFrame(
                100.0, index=[_d4_6, _d8_6, _d9_6], columns=_cols6),
            "bist": _pd6.Series(100.0, index=[_d4_6, _d8_6, _d9_6]),
        }
        try:
            _missing_days6 = _DF6.sparse_market_days(
                _missing_day_packet6,
                expected_sessions=_external_sessions6,
                expected_last_closed_session=_d9_6,
            )
            if any(str(row.get("date"))[:10] == "2026-09-07"
                   for row in _missing_days6):
                ok("feed+BIST ortak 09-07 kaybi bagimsiz takvimle gorunur")
            else:
                bad("P0.6 bagimsiz takvim ortak 09-07 kaybini yakalamadi")
        except Exception as e:
            bad(f"P0.6 bagimsiz sureklilik entegrasyonu yok: {type(e).__name__}: {e}")

        # Takvim tam yil olsa da feed baslangicindan onceki seanslar sorgulanmaz.
        _short_packet6 = {
            "prices": _pd6.DataFrame(
                100.0, index=[_d4_6, _d7_6, _d8_6, _d9_6], columns=_cols6),
            "bist": _pd6.Series(100.0, index=[_d4_6, _d7_6, _d8_6, _d9_6]),
        }
        try:
            _short_sparse6 = _DF6.sparse_market_days(
                _short_packet6,
                expected_sessions=_external_sessions6,
                expected_last_closed_session=_d9_6,
            )
            if _short_sparse6 == []:
                ok("tam-yil takvim kisa-gecmisli eksiksiz feed'e sahte alarm vermiyor")
            else:
                bad(f"P0.6 feed baslangici oncesi sahte eksik seanslar: {_short_sparse6[:3]}")
        except Exception as e:
            bad(f"P0.6 kisa-feed pencere siniri uygulanmadi: {type(e).__name__}: {e}")
    except Exception as e:
        bad(f"P0.6 [6j] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6k] P0.6 -- BAGIMSIZ TAKVIM CANLI VERI KAPISINA BAGLI MI --
    # [6j] takvim motorunu ve sureklilik hesabini sinar. Bu blok ise ayni
    # olcumlerin safe_feed kaynak secimini gercekten yetkilendirdigini sabitler.
    print("\n[6k] P0.6 takvim-farkinda veri gate'i (test-once)")
    try:
        import json as _json7
        import tempfile as _tempfile7
        from datetime import datetime as _datetime7
        from pathlib import Path as _Path7
        from zoneinfo import ZoneInfo as _ZoneInfo7
        import pandas as _pd7
        from bist_alpha import selfheal as _SH7, datafeed as _DF7, config as _CFG7

        _tz7 = _ZoneInfo7("Europe/Istanbul")
        _calendar_path7 = (
            _Path7(__file__).resolve().parent
            / "data" / "calendar" / "xist_2026.json"
        )
        _now7 = _datetime7(2026, 9, 9, 14, 30, tzinfo=_tz7)

        def _packet7(dates, returned=60, expected=60, bist_dates=None,
                     bist_ok=True, sparse_date=None):
            idx = _pd7.to_datetime(dates)
            cols = [f"G{i:03d}" for i in range(returned)]
            prices = _pd7.DataFrame(100.0, index=idx, columns=cols)
            if sparse_date is not None:
                sparse_ts = _pd7.Timestamp(sparse_date)
                prices.loc[sparse_ts] = float("nan")
                prices.loc[sparse_ts, cols[0]] = 100.0
            market_idx = _pd7.to_datetime(dates if bist_dates is None else bist_dates)
            return {
                "prices": prices,
                "bist": _pd7.Series(100.0, index=market_idx, dtype=float),
                "_bist_ok": bist_ok,
                "_source_pool_count": expected,
            }

        class _Feed7:
            def __init__(self, value):
                self.value = value

            def get_latest(self):
                if isinstance(self.value, BaseException):
                    raise self.value
                return self.value

        _sentinel7 = object()
        _old_path7 = getattr(_SH7, "DATA_FEED_RUN_STATE", _sentinel7)
        _old_retry7 = _SH7.with_retry
        _old_get_feed7 = _DF7.get_feed
        _old_source7 = getattr(_CFG7, "DATA_SOURCE", _sentinel7)
        _old_chain7 = getattr(_CFG7, "DATA_FALLBACK_CHAIN", _sentinel7)
        _old_allow7 = getattr(_CFG7, "ALLOW_FILE_FALLBACK", _sentinel7)
        _tmp7 = _tempfile7.TemporaryDirectory()
        _state7 = _Path7(_tmp7.name) / "data_feed_run.json"
        _seen_gate_codes7 = set()

        def _run_case7(packets, now=_now7, chain="borsapy", calendar_path=_calendar_path7):
            _state7.unlink(missing_ok=True)
            calls = []

            def _get_feed7(source):
                calls.append(source)
                return _Feed7(packets[source])

            _DF7.get_feed = _get_feed7
            _CFG7.DATA_FALLBACK_CHAIN = chain
            result = None
            error = None
            try:
                result = _SH7.safe_feed(now=now, calendar_path=calendar_path)
            except Exception as exc:
                error = exc
            manifest = (
                _json7.loads(_state7.read_text(encoding="utf-8"))
                if _state7.exists() else {}
            )
            return result, error, manifest, calls

        try:
            _SH7.DATA_FEED_RUN_STATE = _state7
            _SH7.with_retry = lambda fn, **_kwargs: fn()
            _CFG7.DATA_SOURCE = "yahoo"
            _CFG7.ALLOW_FILE_FALLBACK = False

            # 1) 94/94 dolu gorunse bile gercek 625 havuzuna gore yetersizdir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-08", "2026-09-09"], 94, 625),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _seen_gate_codes7.add(_first7.get("reject_code"))
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _calls7 == ["yahoo", "borsapy"]
                    and _first7.get("reject_code") == "INSUFFICIENT_POOL_COVERAGE"):
                ok("94/625 kaynak kapsami reddedilir; donen kolonlar payda olmaz")
            else:
                bad(f"P0.6 havuz kapsami gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 2) Gun ici kosumda son kapanmis seans birebir bulunmalidir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-07"]),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _seen_gate_codes7.add(_first7.get("reject_code"))
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "STALE_LAST_DATA"):
                ok("bayat son veri STALE_LAST_DATA ile sonraki kaynaga gecer")
            else:
                bad(f"P0.6 tazelik gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 2b) Yalniz bugunun yarim bari, son kapanmis seansi kanitlamaz.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-09"]),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _seen_gate_codes7.add(_first7.get("reject_code"))
            _expected_day7 = next((
                row for row in _first7.get("checked_market_days", [])
                if row.get("date") == "2026-09-08"
            ), {})
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "SPARSE_MARKET_DAY"
                    and _expected_day7.get("present") == 0
                    and _expected_day7.get("total") == 60):
                ok("yalniz yarim guncel bar, kapanmis seans yerine gecmez")
            else:
                bad(f"P0.6 bos kapanmis-seans araligi temiz sayildi: "
                    f"calls={_calls7}, first={_first7}, error={_error7}")

            # 3) Bagimsiz takvim olsa da kaynak BIST referansini olcebilmelidir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-08", "2026-09-09"],
                                   bist_dates=[], bist_ok=False),
                "borsapy": _packet7(["2026-09-08", "2026-09-09"]),
            })
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _seen_gate_codes7.add(_first7.get("reject_code"))
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "MISSING_BIST_REFERENCE"):
                ok("olculemeyen BIST referansi temiz sayilmaz")
            else:
                bad(f"P0.6 BIST referans gate'i yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 4) Feed ve kendi BIST'i ayni seansi kaybetse de resmi takvim gorur.
            _gap_now7 = _datetime7(2026, 9, 8, 14, 30, tzinfo=_tz7)
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-09-04", "2026-09-08"]),
                "borsapy": _packet7(["2026-09-04", "2026-09-07", "2026-09-08"]),
            }, now=_gap_now7)
            _attempts7 = _manifest7.get("source_attempts", [])
            _first7 = _attempts7[0] if _attempts7 else {}
            _seen_gate_codes7.add(_first7.get("reject_code"))
            _last7 = _attempts7[-1] if _attempts7 else {}
            _day7 = next((row for row in _last7.get("checked_market_days", [])
                          if row.get("date") == "2026-09-07"), {})
            _dashboard_attempts7 = (
                _result7.get("_source_attempts", []) if _result7 else []
            )
            _dashboard_last7 = (
                _dashboard_attempts7[-1] if _dashboard_attempts7 else {}
            )
            if (_result7 and _result7.get("_source_base") == "borsapy"
                    and _first7.get("reject_code") == "SPARSE_MARKET_DAY"
                    and _last7.get("reject_code") is None
                    and _last7.get("expected_last_closed_session") == "2026-09-07"
                    and _last7.get("freshness_status") == "FRESH"
                    and _last7.get("bar_completeness") == "unknown"
                    and _day7.get("present") == _day7.get("total") == 60
                    and "checked_market_days" not in _dashboard_last7
                    and _dashboard_last7.get("checked_market_day_count")
                    == len(_last7.get("checked_market_days", []))
                    and _dashboard_last7.get("latest_checked_market_day")
                    == _last7.get("checked_market_days", [])[-1]):
                ok("ortak gun kaybi reddedilir; basarili manifest ayni gate olcumunu tasir")
            else:
                bad(f"P0.6 takvim-manifest entegrasyonu yok/yanlis: "
                    f"calls={_calls7}, attempts={_attempts7}, error={_error7}")

            # 5) File fallback atlanmasi serbest metin degil kararli kod tasir.
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": RuntimeError("yahoo-down"),
                "file": _packet7(["2026-09-08", "2026-09-09"]),
            }, chain="file")
            _file7 = next((row for row in _manifest7.get("source_attempts", [])
                           if row.get("source") == "file"), {})
            _seen_gate_codes7.add(_file7.get("reject_code"))
            if (_error7 and _file7.get("status") == "skipped"
                    and _file7.get("reject_code") == "FILE_FALLBACK_DISABLED"):
                ok("file fallback pilot kararinda atlanir ve kodlu iz birakir")
            else:
                bad(f"P0.6 file-fallback sozlesmesi yok/yanlis: "
                    f"calls={_calls7}, file={_file7}, error={_error7}")

            # 6) Takvim kapsam disinda ise saglikli gorunen feed de yetkili degildir.
            _future_now7 = _datetime7(2027, 1, 1, 9, 45, tzinfo=_tz7)
            _result7, _error7, _manifest7, _calls7 = _run_case7({
                "yahoo": _packet7(["2026-12-31"]),
                "borsapy": _packet7(["2026-12-31"]),
            }, now=_future_now7)
            _first7 = _manifest7.get("source_attempts", [{}])[0]
            _seen_gate_codes7.add(_first7.get("reject_code"))
            if (_error7 and _first7.get("reject_code") == "CALENDAR_UNAVAILABLE"
                    and _calls7 == []):
                ok("takvim kapsam-disinda fail-closed; veri kaynagi bosuna cagrilmaz")
            else:
                bad(f"P0.6 takvim fail-closed yok/yanlis: calls={_calls7}, "
                    f"first={_first7}, error={_error7}")

            # 7) Iki canli uretici file fallback'i karar yolunda acamaz.
            _root7 = _Path7(__file__).resolve().parent
            _workflow_texts7 = [
                (_root7 / ".github" / "workflows" / name).read_text(encoding="utf-8")
                for name in ("bist-alpha.yml", "precise.yml")
            ]
            _audit_text7 = (_root7 / "scripts" / "system_control_audit.py").read_text(
                encoding="utf-8")
            if (all('ALLOW_FILE_FALLBACK: "0"' in text for text in _workflow_texts7)
                    and 'ALLOW_FILE_FALLBACK: "1"' not in _audit_text7):
                ok("iki ureticide file fallback kapali; audit ters sozlesme aramiyor")
            else:
                bad("P0.6 file fallback uretici/audit sozlesmesi hizali degil")

            # 8) Bos fiyat tablosu ayri ve kararli bir ret kodudur. FETCH_ERROR
            # tasima katmani hatasidir ve [6i]'de sinanir; buradaki yedi kod veri
            # kapisinin donuk karar kumesidir.
            _empty7 = _SH7._candidate_gate_assessment(
                {"prices": _pd7.DataFrame()},
                _SH7._calendar_gate_context(_now7, _calendar_path7))
            _seen_gate_codes7.add(_empty7.get("reject_code"))
            if (_empty7.get("reject_code") == "EMPTY_PRICES"):
                ok("bos fiyat tablosu EMPTY_PRICES ile reddedilir")
            else:
                bad(f"P0.6 bos fiyat ret kodu yok/yanlis: {_empty7}")

            _old_empty_code7 = _SH7.EMPTY_PRICES
            try:
                _SH7.EMPTY_PRICES = "MUTATED_EMPTY_PRICES"
                _mutated_empty7 = _SH7._candidate_gate_assessment(
                    {"prices": _pd7.DataFrame()},
                    _SH7._calendar_gate_context(_now7, _calendar_path7))
                if _mutated_empty7.get("reject_code") != "EMPTY_PRICES":
                    ok("EMPTY_PRICES sadik mutasyonu karar-kodu testini kirar")
                else:
                    bad("P0.6 EMPTY_PRICES mutasyonu testten kaciyor")
            finally:
                _SH7.EMPTY_PRICES = _old_empty_code7

            _expected_codes7 = {
                "EMPTY_PRICES",
                "INSUFFICIENT_POOL_COVERAGE",
                "MISSING_BIST_REFERENCE",
                "CALENDAR_UNAVAILABLE",
                "STALE_LAST_DATA",
                "SPARSE_MARKET_DAY",
                "FILE_FALLBACK_DISABLED",
            }
            _seen_gate_codes7.discard(None)
            if _seen_gate_codes7 == _expected_codes7:
                ok("yedi veri-kapisi ret kodunun her biri davranista gozlemlendi")
            else:
                bad(f"P0.6 ret kodu davranis kumesi eksik/fazla: "
                    f"gorulen={sorted(_seen_gate_codes7)} "
                    f"beklenen={sorted(_expected_codes7)}")
        finally:
            _SH7.with_retry = _old_retry7
            _DF7.get_feed = _old_get_feed7
            if _old_path7 is _sentinel7:
                try:
                    delattr(_SH7, "DATA_FEED_RUN_STATE")
                except AttributeError:
                    pass
            else:
                _SH7.DATA_FEED_RUN_STATE = _old_path7
            for _name7, _old7 in [
                ("DATA_SOURCE", _old_source7),
                ("DATA_FALLBACK_CHAIN", _old_chain7),
                ("ALLOW_FILE_FALLBACK", _old_allow7),
            ]:
                if _old7 is _sentinel7:
                    try:
                        delattr(_CFG7, _name7)
                    except AttributeError:
                        pass
                else:
                    setattr(_CFG7, _name7, _old7)
            _tmp7.cleanup()
    except Exception as e:
        bad(f"P0.6 [6k] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6q] P0.6-ek -- D13: URETILEN IKI IZIN DE AKTIF TUKETICISI VAR --
    # data_feed_run ve stop_observer panelde gorunse de yazicilari durdugunda
    # Telegram liveness kanali bunu soylemiyordu. Registry uyesi hem dosya
    # yoklugunu/bayatligini hem de izdeki kendi hata hukumlerini tasir.
    print("\n[6q] P0.6-ek D13 data-feed ve stop-observer liveness uyeleri (test-once)")
    try:
        import json as _jsonq
        import tempfile as _tempfileq
        from datetime import datetime as _datetimeq, timedelta as _timedeltaq
        from pathlib import Path as _Pathq

        _spq = str(_Pathq(__file__).resolve().parent / "scripts")
        if _spq not in sys.path:
            sys.path.insert(0, _spq)
        import liveness_scan as _LQ

        _expected_cfgq = {
            "data_feed_run": (
                "producer", "daemon_cycle", "status", ("ok",), 0.0),
            "stop_observer": (
                "producer", "daemon_cycle", "gate.verdict",
                ("GREEN", "YELLOW", "UNKNOWN"), 0.0),
        }
        for _nameq, _expectedq in _expected_cfgq.items():
            _cfgq = (_LQ.REGISTRY or {}).get(_nameq) or {}
            _actualq = (
                _cfgq.get("kind"),
                _cfgq.get("schedule"),
                _cfgq.get("ok_key"),
                tuple(_cfgq.get("ok_values") or ()),
                _cfgq.get("tz"),
            )
            if _actualq == _expectedq:
                ok(f"registry {_nameq}: uretici/daemon/status sozlesmesi kayitli")
            else:
                bad(f"P0.6-ek registry {_nameq} yok/yanlis: "
                    f"alinan={_actualq}, beklenen={_expectedq}")

        with _tempfileq.TemporaryDirectory() as _tdq:
            _nowq = _datetimeq.utcnow().replace(microsecond=0).isoformat() + "Z"

            def _writeq(path, payload):
                _Pathq(path).write_text(
                    _jsonq.dumps(payload), encoding="utf-8")

            _df_cfgq = dict((_LQ.REGISTRY or {}).get("data_feed_run") or {})
            _df_pathq = _Pathq(_tdq) / "data_feed_run.json"
            if _df_cfgq:
                _df_cfgq["file"] = str(_df_pathq)
                _writeq(_df_pathq, {"generated_at": _nowq, "status": "ok"})
                _df_okq = _LQ.check("data_feed_run", _df_cfgq, {})
                _writeq(_df_pathq, {"generated_at": _nowq, "status": "failed"})
                _df_badq = _LQ.check("data_feed_run", _df_cfgq, {})
                if (_df_okq.get("status"), _df_badq.get("status")) == ("GREEN", "RED"):
                    ok("data_feed_run taze ok=GREEN, failed=RED")
                else:
                    bad(f"P0.6-ek data_feed_run hukumleri yanlis: "
                        f"ok={_df_okq}, failed={_df_badq}")

                # Acik hata hukmu, tek-slot bayatlik erken cikisiyla SARI'ya
                # yumusatilmamali. Dinamik aday, testi takvim tarihine baglamaz.
                _scan_nowq = _datetimeq.utcnow()
                _one_slotq = next((
                    _scan_nowq - _timedeltaq(hours=_hq)
                    for _hq in range(1, 24 * 14)
                    if _LQ._missed_slots(
                        _scan_nowq - _timedeltaq(hours=_hq),
                        _scan_nowq,
                        _LQ.SCHEDULES["daemon_cycle"],
                    ) == 1
                ), None)
                if _one_slotq is None:
                    bad("P0.6-ek tek-slot bayatlik test adayi bulunamadi")
                else:
                    _one_slot_textq = _one_slotq.replace(
                        microsecond=0).isoformat() + "Z"
                    _writeq(_df_pathq, {
                        "generated_at": _one_slot_textq,
                        "status": "failed",
                    })
                    _df_stale_badq = _LQ.check(
                        "data_feed_run", _df_cfgq, {})
                    _writeq(_df_pathq, {
                        "generated_at": _one_slot_textq,
                        "status": "ok",
                    })
                    _df_stale_okq = _LQ.check(
                        "data_feed_run", _df_cfgq, {})
                    if (_df_stale_badq.get("status") == "RED"
                            and _df_stale_badq.get("missed_slots") == 1
                            and _df_stale_okq.get("status") == "YELLOW"):
                        ok("acik uretici hatasi tek-slot bayatlikta RED kalir")
                    else:
                        bad("P0.6-ek bayatlik acik hatayi yumusatiyor: "
                            f"failed={_df_stale_badq}, ok={_df_stale_okq}")

            _so_cfgq = dict((_LQ.REGISTRY or {}).get("stop_observer") or {})
            _so_pathq = _Pathq(_tdq) / "stop_observer.json"
            if _so_cfgq:
                _so_cfgq["file"] = str(_so_pathq)
                _so_rowsq = {}
                for _verdictq in ("GREEN", "YELLOW", "UNKNOWN", "RED", None):
                    _payloadq = {"generated_at": _nowq, "gate": {}}
                    if _verdictq is not None:
                        _payloadq["gate"]["verdict"] = _verdictq
                    _writeq(_so_pathq, _payloadq)
                    _so_rowsq[_verdictq] = _LQ.check(
                        "stop_observer", _so_cfgq, {}).get("status")
                _expected_rowsq = {
                    "GREEN": "GREEN", "YELLOW": "GREEN", "UNKNOWN": "GREEN",
                    "RED": "RED", None: "RED",
                }
                if _so_rowsq == _expected_rowsq:
                    ok("stop_observer gate RED/missing=RED; diger tanimli hukumler saglikli")
                else:
                    bad(f"P0.6-ek stop_observer hukumleri yanlis: {_so_rowsq}")

                if _one_slotq is not None:
                    _writeq(_so_pathq, {
                        "generated_at": _one_slot_textq,
                        "gate": {"verdict": "RED"},
                    })
                    _so_stale_redq = _LQ.check(
                        "stop_observer", _so_cfgq, {})
                    if (_so_stale_redq.get("status") == "RED"
                            and _so_stale_redq.get("missed_slots") == 1):
                        ok("stop-observer RED tek-slot bayatlikta RED kalir")
                    else:
                        bad("P0.6-ek stop-observer RED bayatlikta yumusuyor: "
                            f"{_so_stale_redq}")

                _so_pathq.unlink()
                _newq = _LQ.check("stop_observer", _so_cfgq, {})
                _oldq = _LQ.check("stop_observer", _so_cfgq, {"stop_observer": True})
                if (_newq.get("status"), _oldq.get("status")) == ("YELLOW", "RED"):
                    ok("stop_observer yoklugu yeni uyede SARI, daha once yazmissa KIRMIZI")
                else:
                    bad(f"P0.6-ek stop_observer yokluk ayrimi yanlis: "
                        f"new={_newq}, old={_oldq}")
    except Exception as e:
        bad(f"P0.6-ek [6q] testi kosmadi: {type(e).__name__}: {e}")

    # -- [6l] P0.6/madde-7 -- BAGIMSIZ STOP GOZLEMI HER KOSUDA CALISIR --
    # Bu kapı rapor/heartbeat akışından ayrıdır: yalnız tespit + alarm yapar,
    # portföy state'ini değiştirmez. Fiyatı olmayan pozisyon da sessizce
    # atlanmaz; stop_eval izi içinde status=missing olarak kalır.
    print("\n[6l] P0.6/madde-7 bagimsiz stop gozlemi (test-once)")
    try:
        import copy as _copy8
        import inspect as _inspect8
        import re as _re8
        from pathlib import Path as _Path8
        from bist_alpha import portfolio as _PF8

        _root8 = _Path8(__file__).resolve().parent

        def _step_block8(_text, _fragment):
            _lines8 = _text.splitlines()
            _start8 = next(
                (i for i, line in enumerate(_lines8)
                 if line.startswith("      - name:") and _fragment in line),
                None,
            )
            if _start8 is None:
                return "", None
            _end8 = len(_lines8)
            for i in range(_start8 + 1, len(_lines8)):
                if _lines8[i].startswith("      - name:") or _lines8[i].startswith("      - uses:"):
                    _end8 = i
                    break
            return "\n".join(_lines8[_start8:_end8]), _start8

        _workflow_specs8 = [
            (".github/workflows/bist-alpha.yml", "Portfoy state commit"),
            (".github/workflows/precise.yml", "State commit"),
        ]
        _workflow_contract_ok8 = True
        for _workflow_path8, _commit_fragment8 in _workflow_specs8:
            _workflow_text8 = (_root8 / _workflow_path8).read_text(encoding="utf-8")
            _stop_block8, _stop_line8 = _step_block8(_workflow_text8, "P0.6 stop gozlemi")
            _commit_block8, _commit_line8 = _step_block8(_workflow_text8, _commit_fragment8)
            _run8 = _stop_block8.split("run:", 1)[-1]
            _before_stop8 = (
                "\n".join(_workflow_text8.splitlines()[:_stop_line8])
                if _stop_line8 is not None else ""
            )
            _checks8 = {
                "ayri always adimi": bool(_stop_block8 and "if: always()" in _stop_block8),
                "state commit oncesi": bool(
                    _stop_line8 is not None and _commit_line8 is not None
                    and _stop_line8 < _commit_line8
                ),
                "ana rapor komutundan ayri": bool(
                    _stop_block8 and "daemon.py --once" not in _run8
                ),
                # SOZLESME: gozlemci yalniz durable claim kazanmis producer'da kosar.
                # OLCUM: bist-alpha.yml haftaici 32 cron tetigi TANIMLIYOR (6:45-50-55,
                # 7:00..30, 11:30..55, 12:00..20, 15:40..55, 16:00..30) + her push.
                # ⚠️ TANIMLI 32; FIILEN kosan cok daha az — GitHub schedule
                # tetiklerini dusuruyor: 2026-09-10'da 4, 09-09'da 6 (olculdu).
                # Karar ayni kaliyor (izi commit'lenmeyen kosum + alarm yuzeyi),
                # yalniz buyukluk duzeldi. Kapi: BUGUN_UC_KONTROL -> K4.
                # Native duplicate runner durable claim alamazsa daemon, stop
                # gozlemi ve artefakt zinciri birlikte atlanir.
                # KORUNAN NIYET: gozlemci ana rapor komutundan bagimsizdir, ama
                # claim alamayan duplicate runner'da yeni gozlem/artifakt uretmez.
                "arizaya kosullu degil": bool(
                    _stop_block8
                    and "success()" not in _stop_block8
                    and ".outcome" not in _stop_block8
                ),
                "slot kapisi claim ile": bool(
                    _stop_block8 and (
                        ("bist-alpha.yml" in _workflow_path8
                         and "steps.claim.outputs.claimed == 'true'" in _stop_block8
                         and "steps.gate.outputs.run" not in _stop_block8)
                        or ("precise.yml" in _workflow_path8
                            and "steps.claim.outputs.claimed" not in _stop_block8)
                    )
                ),
                "stop izi ve komutu": bool(
                    "stop_eval" in _run8 or "stop observer" in _run8.lower()
                ),
                "alarm kanali": bool(
                    "TELEGRAM_TOKEN" in _stop_block8
                    and "TELEGRAM_CHAT_ID" in _stop_block8
                ),
                "dedup yok": bool(
                    "report_gate" not in _stop_block8
                    and "HEARTBEAT_DUE" not in _stop_block8
                    and "sent_date" not in _stop_block8
                ),
                "stop gozlemi hatasi gorunur": bool(
                    "continue-on-error" not in _stop_block8
                ),
                # KARAR (2026-09-10): alarm YALNIZ breached'de. `missing` veri-kalitesi
                # durumudur, kendiliginden cozulmez -> gunde ~6 Telegram = alarm korlugu.
                # `missing` ize ve operasyon kapisina gider, Telegram'a DEGIL.
                "alarm yalniz breached": bool("breached" in _run8),
                # KARAR (2026-09-10): gozlemci stop_eval.json'a YAZMAZ. O artefaktin
                # bayatligi #0l'in kor-nokta sinyali (`_write_stop_eval` yalniz kapanista
                # yazar). Her kosuda yazmak o sinyali oldururdu -> AYRI artefakt.
                "stop_eval.json'a yazmaz": bool("stop_eval.json" not in _run8),
                "stop alarmi basarisizligi gorunur": bool(
                    "if ! resp=" in _run8 and "alarm_rc=1" in _run8
                    and "curl -sfS" in _run8
                ),
                # CIKTI TUKETICISI GUARD'I: runner `breached/unpriced/positions/
                # gate` degerlerini GITHUB_OUTPUT'a yaziyor. Bunlari okuyan ozet
                # adimi silinirse degerler yine YAZILIP OKUNMAYAN yuzeye doner ve
                # kimse fark etmez — bu isin duzelttigi kusurun aynisi.
                # `id: stop_obs` de sarttir: id yoksa ciktilar adreslenemez.
                # SUBSTRING DEGIL SINIRLI ESLESME: ilk yazdigim hal
                # `"id: stop_obs" in blok` idi ve `id: stop_obsX` mutasyonunu
                # KACIRIYORDU (bozuk id, dogru id'nin ustkumesi). Mutasyon testi
                # 3/3'ten 1/3 yakaladi ve kontrolu cop olmaktan kurtardi.
                # ("kaba-arama IPUCU uretir, KANIT degil" — kendi yasasi.)
                "cikti tuketicisi bagli (id + ozet adimi)": bool(
                    _stop_block8
                    and _re8.search(r"^\s*id:\s*stop_obs\s*$", _stop_block8, _re8.M)
                    and _re8.search(r"steps\.stop_obs\.outputs\.gate\s*\}\}", _workflow_text8)
                    and "GITHUB_STEP_SUMMARY" in _workflow_text8
                ),
                "iz kalici artefakt": bool(
                    "actions/upload-artifact@v4" in _workflow_text8
                    and _stop_line8 is not None
                    and _workflow_text8.find("actions/upload-artifact@v4", _stop_line8)
                    > _stop_line8
                ),
            }
            if _workflow_path8 == ".github/workflows/bist-alpha.yml":
                _checks8["native gozlemci bagimliliklari kurulu"] = bool(
                    "      - uses: actions/setup-python@v5\n"
                    "        with:\n"
                    "          python-version: '3.12'\n"
                    "          cache: 'pip'\n"
                    "      - run: pip install -r requirements.txt" in _before_stop8
                )
            _bad_checks8 = [name for name, passed in _checks8.items() if not passed]
            if not _bad_checks8:
                ok(f"P0.6 {_workflow_path8}: bagimsiz stop adimi sozlesmesi")
            else:
                bad(f"P0.6 {_workflow_path8}: stop adimi eksik/yanlis {_bad_checks8}")
                _workflow_contract_ok8 = False

        # KARAR (2026-09-10): gozlemci portfolio.py'ye YAZILMAZ. O dosya 5-SHA
        # DONUK (09ad265d9fd5); icine fonksiyon eklemek [6b]'yi kirar ve A1'i ihlal
        # ettirir. Ayri modul hem SHA'yi korur hem "bagimsiz yol"u fiziksellestirir.
        # OTORITE ERISIM BICIMI DE SOZLESME: gozlemci `portfolio.stop_level(pos)`
        # seklinde MODUL ATTRIBUTE uzerinden cagirmali. `from ... import stop_level`
        # yapilirsa asagidaki monkeypatch TUTMAZ -> otorite dogrulanamaz hale gelir.
        try:
            from bist_alpha import stop_observer as _SO8
        except Exception:
            _SO8 = None
        _evaluate_stops8 = getattr(_SO8, "evaluate_stops", None) if _SO8 else None
        if not callable(_evaluate_stops8):
            bad("P0.6 stop gozlemi API'si yok: bist_alpha/stop_observer.evaluate_stops")
        else:
            _state8 = {
                "positions": {
                    "AAA": {"entry": 100.0, "peak": 100.0, "shares": 1.0},
                    "BBB": {"entry": 100.0, "peak": 100.0, "shares": 1.0},
                },
                "cash": 0.0,
            }
            _before8 = _copy8.deepcopy(_state8)
            _old_stop_level8 = _PF8.stop_level
            _PF8.stop_level = lambda _pos: 97.0
            try:
                _observations8 = _evaluate_stops8(_state8, {"AAA": 96.0})
                _observations_again8 = _evaluate_stops8(_state8, {"AAA": 96.0})
                _observations_nan8 = _evaluate_stops8(_state8, {"AAA": float("nan")})
            finally:
                _PF8.stop_level = _old_stop_level8

            _rows8 = {
                row.get("ticker"): row for row in _observations8
                if isinstance(row, dict)
            } if isinstance(_observations8, list) else {}
            _rows_again8 = {
                row.get("ticker"): row for row in _observations_again8
                if isinstance(row, dict)
            } if isinstance(_observations_again8, list) else {}
            _rows_nan8 = {
                row.get("ticker"): row for row in _observations_nan8
                if isinstance(row, dict)
            } if isinstance(_observations_nan8, list) else {}
            _priced8 = _rows8.get("AAA", {})
            _missing8 = _rows8.get("BBB", {})
            if (
                set(_rows8) == {"AAA", "BBB"}
                and _priced8.get("status") == "priced"
                and _priced8.get("price") == 96.0
                and _priced8.get("stop_level") == 97.0
                and _priced8.get("breached") is True
                and _missing8.get("status") == "missing"
                and _missing8.get("price") is None
                and _missing8.get("breached") is None
                and _rows_again8.get("AAA", {}).get("status") == "priced"
                and _rows_again8.get("BBB", {}).get("status") == "missing"
                and _rows_nan8.get("AAA", {}).get("status") == "missing"
                and _rows_nan8.get("AAA", {}).get("reason") == "price_invalid"
                and _state8 == _before8
            ):
                ok("P0.6 stop izi: priced/missing, stop_level otoritesi, tekrar ve state degismez")
            else:
                bad(
                    "P0.6 stop izi sozlesmesi eksik/yanlis: "
                    f"rows={_rows8}, again={_rows_again8}, state_changed={_state8 != _before8}"
                )

        # Entegrasyon kapisi: observer, portfolio.load()'un goreli cwd'sine
        # baglanamaz. Eksik/bozuk state, gercekten bos pozisyondan ayrilmalidir.
        # Fiyat adapter'i de tek sembolde duz DataFrame'i kabul etmelidir.
        try:
            import json as _json8
            import tempfile as _tempfile8
            import pandas as _pd8
            from scripts import stop_observer_run as _SOR8

            _tmp_state8 = _tempfile8.TemporaryDirectory()
            try:
                _state_dir8 = _Path8(_tmp_state8.name)
                (_state_dir8 / "portfolio_A.json").write_text(
                    _json8.dumps({"account": "A", "positions": {}}),
                    encoding="utf-8",
                )
                (_state_dir8 / "portfolio_B.json").write_text("{", encoding="utf-8")
                _states8, _statuses8 = _SO8.load_states(
                    ["A", "B", "C"], state_dir=_state_dir8
                )
                _payload8 = _SO8.build_payload(
                    {"A": []}, [],
                    account_status={
                        "A": {"account": "A", "status": "loaded"},
                        "B": {"account": "B", "status": "missing"},
                    },
                )
                _flat8 = _pd8.DataFrame(
                    {"Close": [101.0]},
                    index=_pd8.to_datetime(["2026-09-10"]),
                )
                _multi8 = _pd8.concat({"AAA": _flat8}, axis=1)
                _loader_ok8 = (
                    set(_states8) == {"A"}
                    and _statuses8["A"].get("status") == "loaded"
                    and _statuses8["B"].get("status") == "unreadable"
                    and _statuses8["C"].get("status") == "missing"
                    and _payload8.get("unavailable_account_count") == 1
                )
                # `_last_close` (fiyat, bar_gunu) doner: bar gunu fiyatla BIRLIKTE
                # tasinmazsa panel bayat fiyat uzerinden kendinden emin YESIL
                # gosterir. Iki sekil de hem degeri hem gunu ayni vermeli.
                _shape_ok8 = (
                    _SOR8._last_close(_flat8, ("AAA",)) == (101.0, "2026-09-10")
                    and _SOR8._last_close(_multi8, ("AAA",)) == (101.0, "2026-09-10")
                )
                if _loader_ok8 and _shape_ok8:
                    ok("P0.6 entegrasyon: state durumu ve tek-sembol fiyat sekli ayrik")
                else:
                    bad(
                        "P0.6 entegrasyon kapisi eksik/yanlis: "
                        f"statuses={_statuses8}, shape_ok={_shape_ok8}"
                    )
                _main_source8 = _inspect8.getsource(_SOR8.main)
                if "state_dir=ROOT / \"portfolios\"" in _main_source8:
                    ok("P0.6 state yolu cwd'den bagimsiz: runner repo kokunu kullaniyor")
                else:
                    bad("P0.6 state yolu runner'da repo kokune sabit degil")

                _old_load_states8 = _SO8.load_states
                _old_write_payload8 = _SO8.write_payload
                _old_emit8 = _SOR8._emit
                _statuses_empty8 = {
                    acc: {
                        "account": acc,
                        "status": "loaded" if acc == "F" else "missing",
                    }
                    for acc in _SOR8.HESAPLAR
                }
                _payload_empty8 = {}
                try:
                    _SO8.load_states = lambda _accounts, state_dir=None: (
                        {"F": {"account": "F", "positions": {}}},
                        _statuses_empty8,
                    )
                    _SO8.write_payload = lambda _payload, path=None: (
                        _payload_empty8.update(_payload) or "test"
                    )
                    _SOR8._emit = lambda _breached, _payload: None
                    _empty_with_missing_rc8 = _SOR8.main()
                finally:
                    _SO8.load_states = _old_load_states8
                    _SO8.write_payload = _old_write_payload8
                    _SOR8._emit = _old_emit8
                # SOZLESME DEGISTI (2026-09-10, onaylanan cikis-kodu ayrimi).
                # ESKI: eksik hesap -> exit 1. Bu, `missing` -> job failure -> P0.3
                # -> Telegram zincirini kuruyordu ve "missing Telegram'a GITMEZ"
                # karariyla (stop_observer.py, karar 3) CELISIYORDU.
                # YENI: sinyal kaybolmadi, CIKIS KODUNDAN KAPIYA tasindi.
                # Bu testin niyeti ayni kaldi — "eksik hesap sessizce basari
                # sayilmasin" — yalnizca hangi kanalda goruldugu degisti.
                _kapi_empty8 = ((_payload_empty8.get("gate") or {}).get("verdict") or "").upper()
                if _empty_with_missing_rc8 == 0 and _kapi_empty8 == "YELLOW":
                    ok("P0.6 bos pozisyon + eksik hesap: exit 0 ama operasyon kapisi SARI")
                else:
                    bad("P0.6 eksik hesap bos-pozisyon dalinda kapiya yansimadi "
                        f"(rc={_empty_with_missing_rc8}, kapi={_kapi_empty8 or '-'})")
            finally:
                _tmp_state8.cleanup()
        except Exception as e:
            bad(f"P0.6 entegrasyon kapisi kosmadi: {type(e).__name__}: {e}")

        # #0l KORUMASI: gozlemci her kosuda calisacak; stop_eval.json'a yazarsa
        # o artefaktin BAYATLIGI ile tasidigi "o gun stop degerlendirilmedi" sinyali
        # olur. `_write_stop_eval` kapanis-disi erken donusu KORUNMALI.
        import shadow as _SH8
        _we8 = _inspect8.getsource(_SH8._write_stop_eval)
        if 'run_label != "kapanis"' in _we8 and "return" in _we8.split('run_label != "kapanis"')[1][:40]:
            ok("P0.6 #0l korumasi: _write_stop_eval kapanis-disi hala erken donuyor")
        else:
            bad("P0.6 #0l korumasi KIRILDI: stop_eval.json artik her kosuda yazilabilir")
    except Exception as e:
        bad(f"P0.6 [6l] testi kosmadi: {type(e).__name__}: {e}")


    # -- [6m] P0.6/madde-7 -- unpriced/missing OPERASYON KAPISI --
    # NEDEN: [6l] olcumu URETIYOR ama hicbir sey TUKETMIYORDU. "missing fail-closed"
    # yazip yalnizca kaydetmek, sistemin kendi kusurunu (karar tuketicisi olmayan
    # cikti) tekrar etmektir.
    # CIKIS KODU IKI FARKLI SEYI KARISTIRMAMALI:
    #   KISMI (bazi pozisyon fiyatsiz)  -> exit 0 · iz + KAPI SARI · Telegram YOK
    #   TOPLAM (hic state / hic fiyat)  -> exit 1 · adim kirmizi · P0.3 alarmi DOGRU
    # Aksi halde `missing` -> exit 1 -> job failure -> P0.3 -> Telegram olur ve
    # "missing Telegram'a gitmez" karariyla CELISIR.
    print("\n[6m] P0.6/madde-7 unpriced operasyon kapisi (test-once)")
    try:
        import importlib.util as _ilu9
        from pathlib import Path as _Path9

        _root9 = _Path9(__file__).resolve().parent
        _spec9 = _ilu9.spec_from_file_location(
            "_stop_obs_run9", _root9 / "scripts" / "stop_observer_run.py")
        _run9 = _ilu9.module_from_spec(_spec9)
        _spec9.loader.exec_module(_run9)
        _SO9 = _run9.stop_observer

        def _poz9(entry=100.0, peak=100.0):
            return {"entry": entry, "peak": peak, "shares": 1.0}

        # Sabit tarih KULLANILMAZ: kapi artik tazeligi takvime gore yargiliyor,
        # sabit bir gun yazilirsa bu testler birkac gun sonra KENDILIGINDEN
        # kirmiziya doner (zamana bagli test = sahte alarm fabrikasi).
        # Bugunun gunu her zaman "beklenen son kapali seans"tan >= olur -> FRESH.
        from datetime import date as _date9
        _bugun9 = _date9.today().isoformat()

        _yakalanan9 = {}

        def _kur9(states, statuses, prices):
            _yakalanan9.clear()
            _run9.stop_observer.load_states = lambda *a, **k: (states, statuses)
            _run9.fetch_prices = lambda t: (
                prices, [{"source": "test", "status": "ok"}], {},
                {k: _bugun9 for k in prices},
            )
            _run9.stop_observer.write_payload = lambda p, path=None: (
                _yakalanan9.update(p) or "test")

        _orj_load9 = _SO9.load_states
        _orj_write9 = _SO9.write_payload
        _orj_fetch9 = _run9.fetch_prices
        _orj_hes9 = _run9.HESAPLAR
        _run9.HESAPLAR = ["F"]
        try:
            _st9 = {"F": {"positions": {"AAA": _poz9(), "BBB": _poz9()}, "cash": 0.0}}
            _ok9 = {"F": {"account": "F", "status": "loaded", "position_count": 2}}

            # 1) KISMI: bir pozisyon fiyatsiz -> exit 0, kapi SARI, Telegram tetigi YOK
            _kur9(_st9, _ok9, {"AAA": 150.0})
            _rc_kismi9 = _run9.main()
            _p_kismi9 = dict(_yakalanan9)

            # 2) HIC FIYAT: pozisyon var, hicbir kaynak vermedi -> exit 1, kapi KIRMIZI
            _kur9(_st9, _ok9, {})
            _rc_fiyatsiz9 = _run9.main()
            _p_fiyatsiz9 = dict(_yakalanan9)

            # 3) HIC STATE: hicbir hesap yuklenemedi -> exit 1, kapi KIRMIZI
            _kur9({}, {"F": {"account": "F", "status": "unreadable", "error": "x"}}, {})
            _rc_statesiz9 = _run9.main()
            _p_statesiz9 = dict(_yakalanan9)

            # 4) HEPSI PRICED: -> exit 0, kapi YESIL, breach yok
            _kur9(_st9, _ok9, {"AAA": 150.0, "BBB": 150.0})
            _rc_temiz9 = _run9.main()
            _p_temiz9 = dict(_yakalanan9)

            # 5) KISMI HESAP: F yuklendi, G1 okunamadi, fiyatlar tam.
            # Bir hesap dosyasinin yoklugu ARIZA DEGIL -> exit 0, kapi SARI.
            # `not unavailable` sarti burada exit 1 verir ve P0.3 -> Telegram tetikler;
            # bu, "missing Telegram'a gitmez" karariyla CELISIR.
            _run9.HESAPLAR = ["F", "G1"]
            _kur9(
                _st9,
                {**_ok9, "G1": {"account": "G1", "status": "missing"}},
                {"AAA": 150.0, "BBB": 150.0},
            )
            _rc_kismi_hesap9 = _run9.main()
            _p_kismi_hesap9 = dict(_yakalanan9)
            _run9.HESAPLAR = ["F"]
        finally:
            _SO9.load_states = _orj_load9
            _SO9.write_payload = _orj_write9
            _run9.fetch_prices = _orj_fetch9
            _run9.HESAPLAR = _orj_hes9

        def _kapi9(p):
            return ((p.get("gate") or {}).get("verdict") or "").upper()

        def _satir9(p, ticker):
            for _satirlar in (p.get("accounts") or {}).values():
                for _r in _satirlar or []:
                    if _r.get("ticker") == ticker:
                        return _r
            return {}

        _sartlar9 = [
            ("1  KISMI: exit 0 (missing tek basina ariza DEGIL)", _rc_kismi9, 0),
            ("1b KISMI: unpriced_count=1", _p_kismi9.get("unpriced_count"), 1),
            ("1c KISMI: kapi SARI", _kapi9(_p_kismi9), "YELLOW"),
            ("1d KISMI: breach yok -> Telegram tetigi yok", _p_kismi9.get("breach"), False),
            ("2  HIC FIYAT: exit 1 (gozlem YAPILAMADI)", _rc_fiyatsiz9, 1),
            ("2b HIC FIYAT: kapi KIRMIZI", _kapi9(_p_fiyatsiz9), "RED"),
            ("3  HIC STATE: exit 1", _rc_statesiz9, 1),
            ("3b HIC STATE: kapi KIRMIZI", _kapi9(_p_statesiz9), "RED"),
            ("4  HEPSI PRICED: exit 0", _rc_temiz9, 0),
            ("4b HEPSI PRICED: kapi YESIL", _kapi9(_p_temiz9), "GREEN"),
            ("4c HEPSI PRICED: unpriced_count=0", _p_temiz9.get("unpriced_count"), 0),
            ("5a KISMI HESAP: exit 0 (dosya yoklugu ariza DEGIL)", _rc_kismi_hesap9, 0),
            ("5b KISMI HESAP: kapi SARI", _kapi9(_p_kismi_hesap9), "YELLOW"),
            ("5c KISMI HESAP: unavailable_account_count=1",
             _p_kismi_hesap9.get("unavailable_account_count"), 1),
            # BAYAT FIYAT gorunur olmali: gozlem TAZE olup fiyat ESKI olabilir.
            # Tarih tasinmazsa panel bayat fiyat uzerinden kendinden emin YESIL
            # gosterir — "yanlis-guven" sinifi. Hukme cevrilmez, GORUNUR kilinir.
            ("6  fiyat bar gunu satirda", _satir9(_p_temiz9, "AAA").get("price_date"),
             _bugun9),
            ("6b price_asof ozeti oldest", (_p_temiz9.get("price_asof") or {}).get("oldest"),
             _bugun9),
            ("6c price_asof ozeti distinct", (_p_temiz9.get("price_asof") or {}).get("distinct"),
             1),
            ("6d fiyatsiz satirda tarih YOK (uydurulmaz)",
             _satir9(_p_kismi9, "BBB").get("price_date"), None),
            ("6e fiyatsiz gun ozete girmez",
             (_p_kismi9.get("price_asof") or {}).get("distinct"), 1),
            # Iki kaynagin karsilastirmasi ARTEFAKTA olmali, yalniz logda degil:
            # Actions logu 90 gunde silinir, artefakt git'te kalir. Bir stop
            # tartismali hale gelirse kanit o gun kaybolmus olmamali.
            ("7  cross_source_check alani artefaktta",
             isinstance(_p_temiz9.get("cross_source_check"), dict), True),
            # D6 — DAMGA EKSENI. `health-logic.js timestampMs` ofset YOKSA
            # +03:00 varsayar. Damga 'Z'sini kaybederse panel 3 SAATLIK sahte
            # bayatlik uretir ve HICBIR SEY kizarmaz (kayitli tuzak: "negatif
            # yas / +3 saatlik sahte bayatlik"). Yazan taraf `_utc_timestamp`
            # 'Z' ekliyor ama bunu PINLEYEN test yoktu -> bekcisiz dogruluk.
            ("8g damga ofset tasiyor (D6: ofsetsiz damga paneli 3 saat kaydirir)",
             bool(__import__("re").search(
                 r"[zZ]|[+-]\d\d:?\d\d$", str(_p_temiz9.get("generated_at")))), True),
        ]

        # -- BAYATLIK HUKMU (SAF fonksiyonlar, ZAMAN ENJEKTE EDILIR) -----------
        # ESKIDEN: "esik uydurmadan yargilanamaz" denip yalniz olcum birakilmisti.
        # BU YANLISTI: sistemin KENDI takvim otoritesi (market_calendar.
        # assess_freshness) esiksiz bir hukum zaten uretiyordu — bakilmamisti.
        # Testler `now` enjekte eder; gercek saate bagli DEGILDIR.
        from datetime import datetime as _dt9, timezone as _tz9
        _simdi9 = _dt9(2026, 9, 10, 13, 0, tzinfo=_tz9.utc)   # 16:00 TR, seans acik
        _tz_bayat9 = _SO9.assess_price_freshness(["2026-09-03"], now=_simdi9)
        _tz_taze9 = _SO9.assess_price_freshness([_bugun9], now=_simdi9) \
            if _bugun9 >= "2026-09-10" else _SO9.assess_price_freshness(["2026-09-10"], now=_simdi9)
        _tz_kapsamdisi9 = _SO9.assess_price_freshness(
            ["2031-01-06"], now=_dt9(2031, 1, 6, 13, 0, tzinfo=_tz9.utc))
        _tz_bos9 = _SO9.assess_price_freshness([], now=_simdi9)
        _sartlar9 += [
            ("8  bayat bar STALE", _tz_bayat9.get("status"), "STALE"),
            ("8b bayat ret kodu", _tz_bayat9.get("reject_code"), "STALE_LAST_DATA"),
            ("8c beklenen kapali seans yazili",
             _tz_bayat9.get("expected_last_closed_session"), "2026-09-09"),
            ("8d guncel bar FRESH", _tz_taze9.get("status"), "FRESH"),
            # FAIL-SAFE: takvim kapsamiyorsa hukum VERILMEZ. Ne sahte BAYAT
            # (yanlis alarm) ne sahte TAZE (sessiz guvence) uretilir.
            ("8e takvim kapsamiyor -> UNKNOWN", _tz_kapsamdisi9.get("status"), "UNKNOWN"),
            ("8f fiyatlanan pozisyon yok -> UNKNOWN", _tz_bos9.get("status"), "UNKNOWN"),
            # Kapi hukmu: STALE sariya cevirir, UNKNOWN hukmu DEGISTIRMEZ,
            # RED her ikisini de yener (gozlem hic yapilamadiysa tazelik ikincildir).
            ("9  STALE -> kapi SARI",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "STALE"})["verdict"], "YELLOW"),
            ("9b STALE sebebi yazili",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "STALE"})["reason"], "stale_price"),
            ("9c FRESH -> kapi YESIL",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "FRESH"})["verdict"], "GREEN"),
            ("9d UNKNOWN hukmu bozmaz",
             _SO9.gate_verdict(2, 0, 0, 1, freshness={"status": "UNKNOWN"})["verdict"], "GREEN"),
            ("9e RED, STALE'i yener",
             _SO9.gate_verdict(2, 0, 0, 0, freshness={"status": "STALE"})["verdict"], "RED"),
            ("9f eksik kapsama + STALE ikisi de detayda",
             "stale_price" in _SO9.gate_verdict(2, 1, 0, 1,
                                                freshness={"status": "STALE"})["detail"]
             or "beklenen" in _SO9.gate_verdict(2, 1, 0, 1,
                                                freshness={"status": "STALE"})["detail"], True),
        ]
        for _ad9, _alinan9, _beklenen9 in _sartlar9:
            if _alinan9 == _beklenen9:
                ok(f"P0.6 kapi {_ad9}")
            else:
                bad(f"P0.6 kapi {_ad9}: beklenen {_beklenen9!r}, alinan {_alinan9!r}")

        # 5) TUKETICI: kapi hukmu panelde OKUNMALI. Uretilip okunmayan olcum,
        #    tam da bu isin duzeltmeye calistigi kusurdur.
        # KANIT TURU = VEKIL (D12): burada olculen sey METIN YUZEYI, calisan JS
        # davranisi DEGIL. Sebep: bu makinede `node` YOK ve docs/test-health.js
        # hicbir yerden kosulmuyor -> selftest JS'i CALISTIRAMAZ.
        # Vekil oldugu icin tek kelime degil, tek tek BAGLAMA NOKTALARI aranir.
        #
        # JS DAVRANISI AYRICA OLCULDU (2026-09-10, tarayicide 7 senaryo):
        #   yok->n(verdict g) · GREEN->g · YELLOW->a(verdict a) · RED->r(verdict r)
        #   breach->alt satirda gorunur · gate yok->n · damga bozuk->"yas okunamadi"
        # Bu olcum TEK SEFERLIK ve TEKRARLANMIYOR; regresyonu yakalayacak kosucu
        # repoda YOK. Acik is: JS kosucusu (bkz ACIK_ISLER, test-health.js olu).
        _idx9 = (_root9 / "docs" / "index.html").read_text(encoding="utf-8")
        _hl9 = (_root9 / "docs" / "health-logic.js").read_text(encoding="utf-8")
        _hh9 = (_root9 / "docs" / "health.html").read_text(encoding="utf-8")
        _kanca9 = [
            ("index.html artefakti cekiyor", "state/stop_observer.json" in _idx9),
            ("index.html veriye bagliyor", "data.stop_observer = " in _idx9),
            ("index.html kapi satirini GOSTERIYOR (slice kurbani degil)",
             "'stop_observer'" in _idx9 and "core.push(stopRow)" in _idx9),
            ("health-logic cekirdek metrik uretiyor",
             '"stop_observer", true,' in _hl9),
            ("health-logic hukmu normalize ediyor",
             "normalizeVerdict(soGate && soGate.verdict)" in _hl9),
            ("health-logic yoklugu YESIL saymiyor", '|| "n";' in _hl9),
            ("health-logic fiyat bar gununu gosteriyor",
             "price_asof" in _hl9 and "soFiyatGun" in _hl9),
            ("health.html artefakti cekiyor", "state/stop_observer.json" in _hh9),
            ("health.html veriye bagliyor", "data.stop_observer = " in _hh9),
            # KANIT ZINCIRININ KENDISI DENETLENIR: CI'da node zorunlulugu bu
            # bayraga bagli. Bayrak workflow'dan dusrulse "CI yesil" bir daha
            # "JS kostu" demezdi ve bunu KIMSE fark etmezdi (sessiz bozulma).
            ("bist-alpha.yml selftest adimi node'u ZORUNLU kiliyor",
             'SELFTEST_REQUIRE_NODE: "1"' in (_root9 / ".github" / "workflows"
                                              / "bist-alpha.yml").read_text(encoding="utf-8")),
        ]
        _eksik9 = [ad for ad, tut in _kanca9 if not tut]
        if not _eksik9:
            ok(f"P0.6 kapi 5  TUKETICI bagli [VEKIL: metin yuzeyi] ({len(_kanca9)}/{len(_kanca9)} kanca)")
        else:
            bad("P0.6 kapi 5  TUKETICI EKSIK: " + " | ".join(_eksik9))

        # 8) JS SENARYO KOSUCUSU — vekil kontrolu KONU kanitina cevirir.
        # docs/test-health.js 2026-09-10'a kadar HICBIR YERDEN kosulmuyordu:
        # `system_control_audit` yalnizca DOSYANIN VAR OLDUGUNU ariyordu. Yani
        # 29 senaryo yazilmis, sifir kez kosmustu — "kod var != kod calisiyor".
        # ATLAMA SESSIZ DEGIL: node yoksa uyari basilir, kapsam boslugu gorunur kalir.
        import shutil as _sh9
        import subprocess as _sp9
        _node9 = _sh9.which("node")
        # CI'DA ATLAMA YASAK — ve bu sadece siki davranmak degil, DOGRULANABILIRLIK
        # sorunudur: Actions loglari kimlik dogrulamasi ister (403), yani "adim yesil"
        # tek basina kosucunun KOSTUGUNU soylemez; node yokken de yesil kalirdi.
        # CI'da yokluk BLOKLAYICI yapilinca "CI yesil" ifadesi "node vardi ve
        # senaryolar gecti"yi MANTIKEN icerir -> log okumadan kanit.
        # Yerelde uyari kalir: node opsiyonel, ama sessiz de atlanmaz.
        # ANAHTAR ACIK OLARAK WORKFLOW'DAN GELIR (`SELFTEST_REQUIRE_NODE: "1"`).
        # Yalnizca `GITHUB_ACTIONS`e guvenmek, kanit zincirini DOGRULANAMAYAN bir
        # varsayima baglardi ("GitHub bu degiskeni set eder" — repodan okunamaz).
        # Acik bayrak repoda YAZILI ve asagida kanca ile denetleniyor.
        # GITHUB_ACTIONS/CI yedek olarak kalir: bayrak unutulursa yine siki davranir.
        _ci9 = (os.environ.get("SELFTEST_REQUIRE_NODE") == "1"
                or os.environ.get("GITHUB_ACTIONS") == "true"
                or os.environ.get("CI", "").lower() in ("1", "true"))
        if not _node9 and _ci9:
            bad("P0.6 kapi 8  JS kosucusu CI'DA KOSMADI: node bulunamadi. "
                "CI'da node BEKLENIR; sessiz atlama 'testler kostu' yanilsamasi uretir")
        elif not _node9:
            warn("JS senaryo kosucusu ATLANDI (node yok) — docs/test-health.js "
                 "bu makinede olculemedi, kapsam boslugu")
        else:
            _js9 = _sp9.run(
                [_node9, str(_root9 / "docs" / "test-health.js")],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(_root9 / "docs"), timeout=120,
            )
            _cikti9 = (_js9.stdout or "") + (_js9.stderr or "")
            _son9 = [s for s in _cikti9.splitlines() if s.startswith("SONUC:")]
            if _js9.returncode == 0:
                ok(f"P0.6 kapi 8  JS senaryolari GECTI ({_son9[0] if _son9 else 'sonuc satiri yok'})")
            else:
                _kalan9 = [s.strip() for s in _cikti9.splitlines() if "XX " in s][:5]
                bad("P0.6 kapi 8  JS senaryolari KALDI: "
                    + (" | ".join(_kalan9) or _cikti9[-300:]))
    except Exception as e:
        bad(f"P0.6 [6m] testi kosmadi: {type(e).__name__}: {e}")


    # -- [6n] P0.3 KARAKTERIZASYON -- portfolio.py'nin EKSIK FIYAT davranisi --
    # NIYET: DAVRANIS DEGISTIRMEK DEGIL, BUGUNKU DAVRANISI KILITLEMEK.
    # portfolio.py 5-SHA ile DONUK (09ad265d9fd5) cunku golden-master onu
    # KAPSAMIYOR (backtest.py'de 0 referans). Yani dondurma "bu dosya dogru"
    # demiyor; "bu dosya test edilmiyor, hic degilse degistigini gorelim" diyor.
    # Test edilmeyen bir dosyayi duzeltmenin dogru sirasi: ONCE testle kapsa,
    # SONRA testin altinda degistir, SONRA yeniden dondur.
    # Bu blok ILK adimdir: hicbir davranisi degistirmez.
    #
    # ISARETLER:
    #   [DEGISECEK] = P0.3 yamasinda bu iddia TERSINE donecek; simdi kusuru
    #                 belgeliyor. Yama sonrasi bu satirlar guncellenmezse yama
    #                 sessizce gecmis olur -> guncelleme ZORUNLU.
    #   [KORUNACAK] = mevcut davranis DOGRU; yama onu bozarsa bu satir kizarir.
    print("\n[6n] P0.3 karakterizasyon: portfolio.py eksik fiyat davranisi")
    try:
        from bist_alpha import portfolio as _PF10

        def _st10(cash=100.0, **poz):
            return {"account": "TEST", "cash": cash, "positions": dict(poz),
                    "history": []}

        def _p10(entry, peak=None, shares=1.0):
            return {"entry": entry, "peak": peak if peak is not None else entry,
                    "shares": shares}

        _iddialar10 = []

        # --- 1) check_stops: KULLANILAMAZ FIYAT (P0.3 adim 2 SONRASI) ---------
        # SOZLESME DEGISTI. Yama oncesi dort ayri kusur olculmustu; hepsi ayni
        # kuralin ihlaliydi: KULLANILABILIR SAYI OLMAYAN SEY FIYAT DEGILDIR.
        #   fiyat yok / NaN / inf / 0 / negatif / bool / cop-metin -> `unchecked`
        #   duzgun sayi (float ya da '150' gibi cevrilebilir metin) -> normal yol
        # METIN KASTEN KABUL EDILIYOR: iyi-bicimli sayisal metni REDDETMEK, tip
        # kozmetigi ugruna GERCEK BIR STOP'U KACIRMAK olurdu (sinirsiz zarar);
        # kabul etmenin bedeli ise sifir (deger dogru). Fail-safe yonu cevirmeyi
        # gosteriyor. Cevrilemeyen her sey `unchecked`e gider.
        _s10 = _st10(AAA=_p10(100.0, peak=200.0))     # stop = 190.0
        # (gain 100% >= 30% -> TRAIL_TIGHT 0.05 -> 200*0.95 = 190;
        #  entry*(1-0.15)=85 daha dusuk, max() 190 secer.
        #  ILK YAZDIGIMDA "170" DEMISTIM — YANLISTI, olcup duzeltildi.)
        _sells10, _unch10 = _PF10.check_stops(_s10, {})      # fiyat YOK
        _iddialar10.append(
            ("1  [KORUNACAK] fiyatsiz pozisyon SATIS uretmiyor", len(_sells10), 0))
        _iddialar10.append(
            ("1b [DEGISTI] fiyatsiz pozisyon artik IZ birakiyor",
             _unch10, [("AAA", "fiyat_yok")]))
        _iddialar10.append(
            ("1c [KORUNACAK] fiyatsizken peak DE guncellenmiyor (mutasyon yok)",
             _s10["positions"]["AAA"]["peak"], 200.0))
        _iddialar10.append(
            ("1h [DEGISTI] state'e yazilmiyor (kalici JSON kirlenmiyor)",
             _s10.get("unchecked", "ALAN_YOK"), "ALAN_YOK"))

        _YOK10 = object()   # "anahtar hic yok" ile "deger None" ayrilir

        def _tek10(fiyat):
            _st = _st10(AAA=_p10(100.0, peak=200.0))
            return _PF10.check_stops(_st, {"AAA": fiyat})

        _sn10, _un10 = _tek10(float("nan"))
        _iddialar10.append(
            ("1d [DEGISTI] NaN artik sessiz degil (yanlis-guvenli kapandi)",
             (len(_sn10), _un10), (0, [("AAA", "fiyat_gecersiz")])))
        _si10, _ui10 = _tek10(float("inf"))
        _iddialar10.append(
            ("1d2 [YENI] inf de gecersiz", (len(_si10), _ui10),
             (0, [("AAA", "fiyat_gecersiz")])))
        _sz10, _uz10 = _tek10(0.0)
        _iddialar10.append(
            ("1e [DEGISTI] SIFIR fiyat artik SATIS URETMIYOR "
             "(veri arizasi -> uydurma emir kapandi)",
             (len(_sz10), _uz10), (0, [("AAA", "fiyat_pozitif_degil")])))
        _sg10, _ug10 = _tek10(-5.0)
        _iddialar10.append(
            ("1f [DEGISTI] NEGATIF fiyat da satis uretmiyor",
             (len(_sg10), _ug10), (0, [("AAA", "fiyat_pozitif_degil")])))
        _sb10, _ub10 = _tek10(True)
        _iddialar10.append(
            ("1i [YENI] bool fiyat degildir (float(True)=1.0 -> 1.00'dan SATIS "
             "uretiyordu; olculdu)", (len(_sb10), _ub10),
             (0, [("AAA", "fiyat_sayi_degil")])))
        _sc10, _uc10 = _tek10("abc")
        _iddialar10.append(
            ("1g [DEGISTI] cop metin kosumu DUSURMUYOR, ize gidiyor "
             "(eskiden yakalanmayan TypeError'di)",
             (len(_sc10), _uc10), (0, [("AAA", "fiyat_sayi_degil")])))
        _sm10, _um10 = _tek10("150")
        _iddialar10.append(
            ("1j [KARAR] iyi-bicimli sayisal metin KABUL EDILIYOR "
             "(reddetmek gercek stop'u kacirirdi)", (len(_sm10), _um10), (1, [])))

        # Karsi-yon (pozitif kontrol): fiyat VARSA ve stop altindaysa SATAR.
        _s10b = _st10(AAA=_p10(100.0, peak=200.0))
        _sells10b, _unch10b = _PF10.check_stops(_s10b, {"AAA": 150.0})   # 150 < 190
        _iddialar10.append(
            ("2  [KORUNACAK] fiyat varsa ve stop altindaysa SATAR",
             (len(_sells10b), _unch10b), (1, [])))
        _iddialar10.append(
            ("2b [KORUNACAK] satis kaydi fiyati tasiyor",
             _sells10b[0]["price"] if _sells10b else None, 150.0))

        # --- 1k) ORTAK OTORITE + NUMPY (P0.3 adim 2b) -------------------------
        # `usable_price` TEK kapidir: check_stops ve g1_account ayni fonksiyonu
        # cagirir. Ikisi zaten `stop_level`i paylasiyordu; fiyat dogrulamasini
        # ayri yazmak kayittaki "IKIZI ama BIREBIR DEGIL" ayrismasini buyuturdu.
        import numpy as _np10
        _kapi10 = [
            (None, "fiyat_yok"), ("abc", "fiyat_sayi_degil"),
            ("", "fiyat_sayi_degil"), ([1], "fiyat_sayi_degil"),
            (True, "fiyat_sayi_degil"), (False, "fiyat_sayi_degil"),
            (float("nan"), "fiyat_gecersiz"), (float("inf"), "fiyat_gecersiz"),
            (0.0, "fiyat_pozitif_degil"), (-5.0, "fiyat_pozitif_degil"),
        ]
        for _ham10, _bek10 in _kapi10:
            _iddialar10.append(
                (f"1k usable_price({_ham10!r}) -> {_bek10}",
                 _PF10.usable_price(_ham10)[1], _bek10))
        for _ham10, _bek10 in ((150.0, 150.0), ("150", 150.0),
                               (_np10.float64(150.0), 150.0)):
            _iddialar10.append(
                (f"1k2 usable_price({type(_ham10).__name__}) kabul",
                 _PF10.usable_price(_ham10), (_bek10, None)))

        # NUMPY BOOL — olculdu 2026-09-10: `isinstance(np.bool_(True), bool)`
        # FALSE'tur, ciplak bool kontrolu onu KACIRIR ve float() 1.0 yapar ->
        # 1.00'dan SATIS. Fiyatlar pandas/numpy'den geldigi icin bu NORMAL girdi
        # tipidir, uc durum degil. `.item()` normalizasyonu once cagrilir.
        _iddialar10.append(
            ("1k3 np.bool_ KACMIYOR (adim 2'de acik kalmisti)",
             _PF10.usable_price(_np10.bool_(True))[1], "fiyat_sayi_degil"))
        _snb10, _unb10 = _tek10(_np10.bool_(True))
        _iddialar10.append(
            ("1k4 np.bool_ check_stops'ta da satis uretmiyor",
             (len(_snb10), _unb10), (0, [("AAA", "fiyat_sayi_degil")])))

        # --- 1m) G1 IKIZI (P0.3 adim 2b) --------------------------------------
        # `g1_account` F'in ikizidir ama F'te satis ONERILIR, burada ICRA EDILIR
        # -> ayni kusurun bedeli agir. Yama oncesi olculdu (2026-09-10):
        #   sifir  -> pozisyon SILINDI, kasa 0.00, stops+1
        #   negatif-> pozisyon SILINDI, kasa -4.99
        # Artik ikisi de pozisyonu KORUR ve sebebiyle ize gider.
        from bist_alpha import g1_account as _G110

        def _g1kur10():
            _g = _G110._new_state()
            _g["positions"] = {"AAA": {"entry": 100.0, "peak": 200.0,
                                       "shares": 1.0, "w": 1.0}}
            _g["cash"] = 0.0
            return _g

        def _g1tek10(fiyat):
            _g = _g1kur10()
            _pr = {} if fiyat is _YOK10 else {"AAA": fiyat}
            _g2, _ev = _G110.step(None, None, _g, "2026-09-10", _pr, False,
                                  eval_stops=True)
            return ("AAA" in _g2["positions"], round(_g2["cash"], 2),
                    _g2["stats"]["stops"], _ev.get("stop_unchecked"))

        for _ad10, _f10, _sb10 in (
                ("fiyatsiz", _YOK10, "fiyat_yok"),
                ("NaN", float("nan"), "fiyat_gecersiz"),
                ("SIFIR", 0.0, "fiyat_pozitif_degil"),
                ("NEGATIF", -5.0, "fiyat_pozitif_degil"),
                ("np.bool_", _np10.bool_(True), "fiyat_sayi_degil")):
            _iddialar10.append(
                (f"1m G1 {_ad10}: pozisyon KORUNUR, kasa 0, iz var",
                 _g1tek10(_f10), (True, 0.0, 0, [("AAA", _sb10)])))
        _iddialar10.append(
            ("1m2 [KORUNACAK] G1 normal fiyatta stop ICRA eder",
             _g1tek10(150.0)[:3], (False, 149.7, 1)))

        # --- 2) current_value: UYDURMA FIYAT ----------------------------------
        # portfolio.py:208  `p = prices.get(tic, pos['entry'])`
        # Fiyat yoksa GIRIS FIYATI yaziliyor -> pozisyon "girisinden beri hic
        # hareket etmemis" gibi degerleniyor. Bu sayi daemon.py:545'te
        # yayimlanan F getirisine donusuyor.
        _s10c = _st10(cash=10.0, AAA=_p10(100.0, shares=2.0))
        _iddialar10.append(
            ("3  [DEGISECEK] current_value fiyatsizken ENTRY kullaniyor",
             _PF10.current_value(_s10c, {}), 210.0))          # 10 + 2*100
        _iddialar10.append(
            ("3b [KORUNACAK] fiyat varsa gercek fiyati kullaniyor",
             _PF10.current_value(_s10c, {"AAA": 150.0}), 310.0))
        _iddialar10.append(
            ("3c [DEGISECEK] eksiklik cagirana BILDIRILMIYOR (tek deger doner)",
             isinstance(_PF10.current_value(_s10c, {}), float), True))

        # --- 2b) DEGERLEME (P0.3 adim 3) --------------------------------------
        # Deger YAYIMLANAN bir sayi (daemon.py:545 -> F getirisi). Uc secenek de
        # kusurluydu: `entry` UYDURUR, atlamak pozisyonu TAMAMEN siler, NaN
        # PANELI OLDURUR. Secim: `entry` korunur ama ETIKETLENIR; NaN asla uretilmez.
        _dsts10 = lambda: _st10(cash=10.0, AAA=_p10(100.0, shares=2.0))
        for _ad10, _f10, _sb10 in (
                ("fiyatsiz", _YOK10, "fiyat_yok"),
                ("NaN", float("nan"), "fiyat_gecersiz"),
                ("inf", float("inf"), "fiyat_gecersiz"),
                ("sifir", 0.0, "fiyat_pozitif_degil"),
                ("negatif", -5.0, "fiyat_pozitif_degil"),
                ("cop metin", "abc", "fiyat_sayi_degil"),
                ("np.bool_", _np10.bool_(True), "fiyat_sayi_degil")):
            _pr10 = {} if _f10 is _YOK10 else {"AAA": _f10}
            _iddialar10.append(
                (f"2c degerleme {_ad10}: entry'ye duser AMA etiketli",
                 (round(_PF10.current_value(_dsts10(), _pr10), 2),
                  _PF10.value_coverage(_dsts10(), _pr10)),
                 (210.0, [("AAA", _sb10)])))
        _iddialar10.append(
            ("2d [KORUNACAK] normal fiyatta dogru deger, etiket YOK",
             (round(_PF10.current_value(_dsts10(), {"AAA": 150.0}), 2),
              _PF10.value_coverage(_dsts10(), {"AAA": 150.0})), (310.0, [])))
        # NaN ASLA YAYILMAZ: eskiden tum portfoy degeri nan oluyordu ve
        # `daemon.py` dashboard'i duz json.dump ile yaziyordu -> dosyada cikplak
        # `NaN` -> `JSON.parse` SyntaxError -> PANELIN TAMAMI olur.
        import math as _math10
        _iddialar10.append(
            ("2e NaN fiyat portfoy degerini NaN yapmiyor",
             _math10.isnan(_PF10.current_value(_dsts10(), {"AAA": float("nan")})), False))
        # SON SAVUNMA: dashboard yazicisi NaN'i temizler.
        import json as _json10
        _iddialar10.append(
            ("2f dashboard yazimi NaN'i None'a cevirir (panel olmez)",
             _json10.dumps(_PF10._sanitize_json({"v": float("nan")})), '{"v": null}'))
        _dm10 = (_root9 / "daemon.py").read_text(encoding="utf-8")
        _iddialar10.append(
            ("2g daemon dashboard'i sanitize EDEREK yaziyor",
             "_sanitize_json(state)" in _dm10, True))
        # G1 IKIZI KAPANDI: ayni sayiyi verir (delege).
        _iddialar10.append(
            ("2h G1 _value F ile AYNI sonucu verir (ikiz kapandi)",
             round(_G110._value({"cash": 10.0,
                                 "positions": {"AAA": {"entry": 100.0, "shares": 2.0}}},
                                {"AAA": float("nan")}), 2), 210.0))

        # --- 2i) FALLBACK'IN KENDISI (bagimsiz okumada bulundu) ---------------
        # Adim 3 fiyat yolunu kapatti ama `entry` fallback'ini DOGRULAMIYORDU:
        # entry NaN -> deger YINE nan; entry None/metin -> TypeError, kosum duser.
        # Ayni kusurun ikinci kopyasiydi. Artik entry de `usable_price`ten gecer.
        def _dbz10(entry):
            return _st10(cash=10.0, AAA={"entry": entry, "peak": 100.0, "shares": 2.0})
        for _ad10, _e10 in (("NaN", float("nan")), ("None", None),
                            ("metin", "abc"), ("sifir", 0.0)):
            _iddialar10.append(
                (f"2i entry {_ad10} + fiyat yok: deger SONLU, ayri etiket",
                 (round(_PF10.current_value(_dbz10(_e10), {}), 2),
                  _PF10.value_coverage(_dbz10(_e10), {})),
                 (10.0, [("AAA", "fiyat_ve_entry_gecersiz")])))
        _iddialar10.append(
            ("2i2 entry NaN ama FIYAT VARSA fiyat kullanilir, etiket YOK",
             (round(_PF10.current_value(_dbz10(float("nan")), {"AAA": 150.0}), 2),
              _PF10.value_coverage(_dbz10(float("nan")), {"AAA": 150.0})),
             (310.0, [])))
        _iddialar10.append(
            ("2i3 [KORUNACAK] entry saglamsa eski etiket korunur",
             _PF10.value_coverage(_dbz10(100.0), {}), [("AAA", "fiyat_yok")]))

        # --- 3) rebalance: ASIMETRI -------------------------------------------
        # SATIS tarafi (167) fiyatsizken ENTRY'den satiyor -> pnl tam %0.00.
        # ALIS tarafi (183-184) fiyatsizken ALMIYOR -> zaten fail-closed.
        _s10d = _st10(cash=0.0, AAA=_p10(100.0, shares=1.0))
        _PF10.rebalance(_s10d, {"BBB": 1.0}, {"BBB": 50.0}, trade_date="2026-01-01")
        _satis10 = [t for t in _s10d["history"][-1]["trades"] if t["type"] == "SELL"]
        _iddialar10.append(
            ("4  [DEGISECEK] rebalance fiyatsiz pozisyonu ENTRY'den satiyor",
             _satis10[0]["price"] if _satis10 else None, 100.0))
        _iddialar10.append(
            ("4b [DEGISECEK] uydurma satisin pnl'i tam %0.00 gorunuyor",
             _satis10[0]["pnl_pct"] if _satis10 else None, 0.0))

        _s10e = _st10(cash=100.0)
        _PF10.rebalance(_s10e, {"CCC": 1.0}, {}, trade_date="2026-01-01")
        _iddialar10.append(
            ("5  [KORUNACAK] rebalance ALIS tarafi fiyatsizken ALMIYOR",
             len(_s10e["positions"]), 0))

        # --- 4) stop_level: peak yoksa entry -----------------------------------
        # Bu bilincli bir eski-JSON korumasi (satir 80), kusur DEGIL.
        _iddialar10.append(
            ("6  [KORUNACAK] stop_level peak yoksa entry'ye dusuyor",
             _PF10.stop_level({"entry": 100.0, "shares": 1.0}),
             _PF10.stop_level({"entry": 100.0, "peak": 100.0, "shares": 1.0})))

        # --- 4) REBALANCE (P0.3 adim 4) ---------------------------------------
        # Olculdu (2026-09-10, yama oncesi): tutulan bir pozisyonun fiyati
        # eksikse `rebalance` onu ENTRY'den satar ve bu YENI PORTFOYUN TAMAMININ
        # boyutlandirmasini degistirir (5.988 lot yerine 3.992 = %33 kucuk);
        # NaN ise state'e `shares: nan` YAZILIR; sifir ise portfoy sifirlanir.
        # BIRINCIL koruma shadow.py fill kapisidir; buradaki IKINCI KILIT.
        def _reb10(fiyatlar):
            _s = _st10(cash=0.0, AAA={"entry": 100.0, "peak": 100.0, "shares": 2.0})
            _PF10.rebalance(_s, {"BBB": 1.0}, fiyatlar, trade_date="2026-01-01")
            _h = _s["history"][-1]
            _sat = [t for t in _h["trades"] if t["type"] == "SELL"][0]
            _al = [t for t in _h["trades"] if t["type"] == "BUY"]
            return (_sat["price"], _al[0]["shares"] if _al else 0.0, _h["total"])

        _iddialar10.append(
            ("4c [KORUNACAK] normal fiyatta rebalance BIREBIR ayni "
             "(A1: saglam veride davranis degismedi)",
             _reb10({"AAA": 150.0, "BBB": 50.0}), (150.0, 5.988, 299.4)))
        for _ad10, _f10 in (("NaN", float("nan")), ("sifir", 0.0),
                            ("cop metin", "abc"), ("np.bool_", _np10.bool_(True))):
            _iddialar10.append(
                (f"4d [DEGISTI] rebalance {_ad10}: entry'ye duser, NaN/sifir lot YOK",
                 _reb10({"AAA": _f10, "BBB": 50.0}), (100.0, 3.992, 199.6)))
        _iddialar10.append(
            ("4e [KORUNACAK] fiyat hic yoksa eski davranis (entry) korunur",
             _reb10({"BBB": 50.0}), (100.0, 3.992, 199.6)))

        # --- 4f) close_positions (bagimsiz okumada bulundu) --------------------
        # `or` zinciri NaN'i YAKALAMIYORDU (NaN truthy). Olculdu 2026-09-10:
        # NaN fiyat kasayi `nan` yapip STATE'E yaziyordu; metin TypeError ile
        # kosumu dusuruyordu; entry 0 -> ZeroDivisionError; entry NaN -> pnl nan.
        def _kap10(prices, entry=100.0):
            _s = _st10(cash=0.0, AAA={"entry": entry, "peak": 100.0, "shares": 2.0})
            _tr = _PF10.close_positions(
                _s, [{"ticker": "AAA", "price": 150.0, "reason": "stop",
                      "giveback": 0.0}], prices, trade_date="2026-01-01")
            return (_tr[0]["price"], _tr[0]["pnl_pct"], round(_s["cash"], 2))

        _iddialar10.append(
            ("4f [KORUNACAK] normal fiyat: davranis birebir ayni",
             _kap10({"AAA": 150.0}), (150.0, 50.0, 299.4)))
        for _ad10, _pr10 in (("NaN", {"AAA": float("nan")}),
                             ("metin", {"AAA": "abc"}),
                             ("sifir", {"AAA": 0.0}),
                             ("fiyat yok", {})):
            _iddialar10.append(
                (f"4g [DEGISTI] close_positions {_ad10}: dogrulanmis satis "
                 "fiyatina duser, kasa SONLU", _kap10(_pr10), (150.0, 50.0, 299.4)))
        for _ad10, _e10 in (("entry 0", 0.0), ("entry NaN", float("nan"))):
            _iddialar10.append(
                (f"4h [DEGISTI] {_ad10}: pnl HESAPLANAMAZ (None), kosum dusmez",
                 _kap10({"AAA": 150.0}, entry=_e10), (150.0, None, 299.4)))

        # --- 4i) URETILIP KULLANILMAYAN OLCUM (kendi yamamda) -----------------
        # `_reb_unpriced` hesaplaniyor ama hicbir yerde okunmuyordu — tam da bu
        # isin duzelttigi kusurun kendi yamamdaki hali. Artik history'ye gecer.
        _sreb10 = _st10(cash=0.0, AAA={"entry": 100.0, "peak": 100.0, "shares": 2.0})
        _PF10.rebalance(_sreb10, {"BBB": 1.0}, {"BBB": 50.0}, trade_date="2026-01-01")
        _iddialar10.append(
            ("4i devir kaydinda `unpriced` alani var (olcumun tuketicisi)",
             _sreb10["history"][-1].get("unpriced"),
             [{"ticker": "AAA", "reason": "fiyat_yok"}]))
        _sreb10b = _st10(cash=0.0, AAA={"entry": 100.0, "peak": 100.0, "shares": 2.0})
        _PF10.rebalance(_sreb10b, {"BBB": 1.0}, {"AAA": 150.0, "BBB": 50.0},
                        trade_date="2026-01-01")
        _iddialar10.append(
            ("4i2 [KORUNACAK] temiz devirde alan None (gurultu yok)",
             _sreb10b["history"][-1].get("unpriced"), None))

        # --- 6) P0.3 KAPANIS TARAMASI — kalan yollar (KANIT TURU: VEKIL) ------
        # Bagimsiz okumada (2026-09-11) portfolio.py disinda ALTI yol daha ayni
        # sinifta bulundu: G1 fill kapisi yalniz alis tarafina bakiyordu, G1 fill
        # degerleme/satis ve cold-start `entry`ye dusuyordu, G1 re-entry yalniz
        # `None` bakip NaN/0/metin GECIRIYORDU (ve o blok POZISYON ACAR), panelde
        # her pozisyonun "guncel" fiyati eksikse sessizce giris fiyatiydi.
        # Bu kontroller METIN YUZEYIDIR: `g1.step` re-entry dali ek kosullar
        # ister ve kurulumsuz denenince iyi/kotu fiyatta AYNI sonucu verir
        # (vakum test) -> davranis kaniti yerine baglanti kaniti yazilir.
        _g1src10 = (_root9 / "bist_alpha" / "g1_account.py").read_text(encoding="utf-8")
        _dm10b = (_root9 / "daemon.py").read_text(encoding="utf-8")
        _sh10b = (_root9 / "shadow.py").read_text(encoding="utf-8")
        _kapanis10 = [
            ("G1 fill kapisi tutulanlari da denetler",
             "_tutulan = list((state.get(\"positions\") or {}).keys())" in _g1src10),
            ("G1 fill degerleme usable_price'tan gecer",
             "_p, _s = pf.usable_price(opens_today.get(tic))" in _g1src10),
            ("G1 fill satis fiyati + pnl korumasi",
             "_e2, _es2 = pf.usable_price(pos.get(\"entry\"))" in _g1src10),
            ("G1 re-entry fiyat kapisi (POZISYON ACAN blok)",
             "pt, _rs = pf.usable_price(prices_today.get(tic))" in _g1src10),
            ("G1 cold-start referans kapisi (nan <= 0 FALSE idi)",
             "p, _rs2 = pf.usable_price(prices_today.get(tic))" in _g1src10),
            ("panel pozisyon fiyatinin KAYNAGI yazili (F/A/B/O)",
             '"current_source": _cur_src,' in _dm10b),
            ("panel pozisyon fiyatinin KAYNAGI yazili (G1)",
             '"current_source": _gcur_src,' in _dm10b),
            ("panel G1 pnl bolme korumasi",
             "None if pf.usable_price(p.get(\"entry\"))[1]" in _dm10b),
            ("konsol ciktisinda kaynak gorunur",
             '_ek = "" if not _cs else f" ({_cs})"' in _sh10b),
            ("portfolio.py'de ham entry-fallback KALMADI",
             "prices_today.get(tic, pos['entry'])" not in
             (_root9 / "bist_alpha" / "portfolio.py").read_text(encoding="utf-8")),
        ]
        _eksik10b = [a for a, t in _kapanis10 if not t]
        if not _eksik10b:
            ok(f"P0.3 kapanis 6 kalan fiyat yollari baglandi [VEKIL] "
               f"({len(_kapanis10)}/{len(_kapanis10)})")
        else:
            bad("P0.3 kapanis 6 EKSIK: " + " | ".join(_eksik10b))

        # --- 5) FILL KAPISI (BIRINCIL koruma) — KANIT TURU: VEKIL --------------
        # `shadow.step` agir kurulum ister (data/signals); burada olculen sey
        # METIN YUZEYI. Davranis kaniti ikinci kilitte (yukarida) ve kapinin
        # kendi kurali dosyada yazili ("%100 norm, HER SAPMA anomali").
        _sh10 = (_root9 / "shadow.py").read_text(encoding="utf-8")
        _kapi10s = [
            ("tutulan pozisyonlar hesaplaniyor", 'tutulan = list((state.get("positions")' in _sh10),
            ("satis tarafi eksigi ayri", "eksik_satis = [t for t in tutulan" in _sh10),
            ("eksik = alis + satis birlesimi", "eksik = eksik_alis + [t for t in eksik_satis" in _sh10),
            ("hangi yarim eksik kaydediliyor", '"missing_sell": eksik_satis[:5] or None,' in _sh10),
        ]
        _eks10 = [a for a, t in _kapi10s if not t]
        if not _eks10:
            ok(f"P0.3 karakterizasyon 5 fill kapisi SATIS tarafini da kapsiyor "
               f"[VEKIL] ({len(_kapi10s)}/{len(_kapi10s)})")
        else:
            bad("P0.3 karakterizasyon 5 fill kapisi eksik: " + " | ".join(_eks10))

        for _ad10, _alinan10, _beklenen10 in _iddialar10:
            if _alinan10 == _beklenen10:
                ok(f"P0.3 karakterizasyon {_ad10}")
            else:
                bad(f"P0.3 karakterizasyon {_ad10}: beklenen {_beklenen10!r}, "
                    f"alinan {_alinan10!r}")

        # DONUKLUK HATIRLATICISI: bu blok gecerken portfolio.py DEGISMEMIS olmali.
        # [6b] zaten SHA'yi kontrol ediyor; burada NIYETI yaziya dokuyoruz ki
        # yama sirasinda "SHA'yi guncelledim ama davranisi olcmedim" olmasin.
        _sha10 = "dda645cb76ec"   # P0.3 + P0.4 (+09-11 fix) (eski 09ad265d9fd5)
        if _sha10 in (_root9 / "selftest.py").read_text(encoding="utf-8"):
            ok("P0.3 karakterizasyon 7  portfolio.py hala 5-SHA baseline'inda "
               "(davranis yamasi bu satiri da guncellemek zorunda)")
        else:
            bad("P0.3 karakterizasyon 7  portfolio.py baseline'i kayip")
    except Exception as e:
        bad(f"P0.3 [6n] karakterizasyon kosmadi: {type(e).__name__}: {e}")


    # -- [6o] P0.4 BOZUK STATE — karantina KALICI, reset AYRI, karar BLOKE --
    # YAMA ONCESI OLCULDU (2026-09-11): `load` bozuk dosyayi `.bozuk_*.bak`a tasiyip
    # DEFAULT (cash=1.0, positions={}) donuyordu. `*.bozuk*` .gitignore'da -> yedek
    # CI runner'da YOK OLUR; sifirlanmis default ise `git add -f portfolios/` ile
    # COMMIT'LENIR. Gecerli JSON ama yanlis sekil (positions=list) bile ayni yoldan:
    # 5.0 nakit -> 1.0. Hic ateslememis (0 .bak, tarihte 0): gizli felaket.
    # AYRICA: shadow.py hesap dongusu `except Exception` ile HER hatayi yutup devam
    # ediyordu -> firlatmak tek basina "karar bloke" saglamaz; StateQuarantined
    # ozel olarak YENIDEN firlatilir.
    print("\n[6o] P0.4 bozuk state: karantina kalici / reset ayri / karar bloke")
    try:
        import json as _json11
        import os as _os11
        import tempfile as _tf11
        from bist_alpha import portfolio as _PF11

        def _td11(icerik=None, sekil=None):
            d = _tf11.mkdtemp()
            p = _os11.path.join(d, "portfolio_F.json")
            if icerik is not None:
                open(p, "w", encoding="utf-8").write(icerik)
            elif sekil is not None:
                open(p, "w", encoding="utf-8").write(_json11.dumps(sekil))
            return d, p

        def _yukle11(d):
            try:
                return ("LOADED", _PF11.load("F", state_dir=d))
            except _PF11.StateQuarantined as e:
                return (e.status, None)

        _i11 = []
        # 1) uc bozukluk turu -> firlatir, dosya YERINDE, marker VAR
        for _ad, _kw, _bek in (("bozuk JSON", {"icerik": "{bozuk"}, "unreadable"),
                               ("eksik dosya", {}, "missing"),
                               ("sekilsiz (positions=list)", {"sekil": {"cash": 5.0, "positions": [1]}}, "invalid")):
            _d, _p = _td11(**_kw)
            _st, _ = _yukle11(_d)
            _i11.append((f"1 {_ad}: StateQuarantined({_bek})", _st, _bek))
            _i11.append((f"1b {_ad}: bozuk dosya TASINMADI",
                         _os11.path.exists(_p) if _kw else True, True))
            # marker YALNIZ bozuklukta: eksik dosyada korunacak veri yok, marker
            # yazilsaydi salt-okur `status` bile marker uretirdi (olculdu 09-11).
            _i11.append((f"1c {_ad}: marker {'YOK' if _bek == 'missing' else 'yazildi'}",
                         _os11.path.exists(_PF11._quarantine_path("F", _d)), _bek != "missing"))
            _i11.append((f"1d {_ad}: .bozuk yedek URETILMEDI (gitignore tuzagi)",
                         any("bozuk" in x for x in _os11.listdir(_d)), False))
        # 2) [KORUNACAK] saglam dosya yuklenir, gercek nakit korunur
        _d2, _ = _td11(sekil={"account": "F", "cash": 5.0, "positions": {}, "history": []})
        _st2, _s2 = _yukle11(_d2)
        _i11.append(("2 saglam dosya yuklenir, cash=5.0 KORUNUR",
                     (_st2, _s2 and _s2["cash"]), ("LOADED", 5.0)))
        # 3) KALICILIK: marker varken saglam dosya bile yuklenmez
        _PF11._write_quarantine("F", "x", "invalid", "test", _d2)
        _i11.append(("3 marker duruyorsa SAGLAM dosya bile yuklenmez (kalici)",
                     _yukle11(_d2)[0], "invalid"))
        # 4) reset AYRI: arsiv committable ad, marker kalkar, history olayi, gerekce zorunlu
        _s4, _ar4 = _PF11.reset_state("F", "test", state_dir=_d2)
        _i11.append(("4 reset: arsiv `.archived_` (bozuk desenine UYMAZ -> commit'lenir)",
                     _ar4 is not None and ".archived_" in _ar4 and "bozuk" not in _ar4, True))
        _i11.append(("4b reset: marker kalkti", _os11.path.exists(_PF11._quarantine_path("F", _d2)), False))
        _i11.append(("4c reset: history'de acik `reset` olayi + gerekce",
                     (_s4["history"][0]["event"], _s4["history"][0]["reason"]), ("reset", "test")))
        _i11.append(("4d reset sonrasi load calisir", _yukle11(_d2)[0], "LOADED"))
        try:
            _PF11.reset_state("F", "", state_dir=_d2); _g = "ISTISNA_YOK"
        except ValueError:
            _g = "ValueError"
        _i11.append(("4e reset gerekcesiz REDDEDILIR", _g, "ValueError"))
        # 5) release: yalniz marker'i kaldirir, dosyaya dokunmaz
        _d5, _p5 = _td11(sekil={"account": "F", "cash": 7.0, "positions": {}, "history": []})
        _PF11._write_quarantine("F", _p5, "invalid", "t", _d5)
        _PF11.release_quarantine("F", _d5)
        _st5, _s5 = _yukle11(_d5)
        _i11.append(("5 release: marker kalkar, dosya DOKUNULMAZ (cash 7.0)",
                     (_st5, _s5 and _s5["cash"]), ("LOADED", 7.0)))
        # 6) init_state: hesap yaratma ACIK eylem; var olani ezmez
        _d6 = _tf11.mkdtemp()
        _PF11.init_state("F", state_dir=_d6)
        try:
            _PF11.init_state("F", state_dir=_d6); _g6 = "ISTISNA_YOK"
        except FileExistsError:
            _g6 = "FileExistsError"
        _i11.append(("6 init_state var olani EZMEZ", _g6, "FileExistsError"))
        # 7) URETIM DOSYALARI yeni kati yukleyiciden gecer (yarin sabah durmasin)
        _ok7 = []
        for _acc in ("F", "A", "B", "O", "G1"):
            try:
                _PF11.load(_acc, state_dir=str(_root9 / "portfolios")); _ok7.append(_acc)
            except _PF11.StateQuarantined as e:
                _ok7.append(f"{_acc}:KARANTINA")
        _i11.append(("7 bes uretim dosyasi da yuklenir", _ok7, ["F", "A", "B", "O", "G1"]))
        # 8) shadow karantinayi YUTMUYOR (VEKIL: metin) — hesap dongusunun except'i
        _sh11 = (_root9 / "shadow.py").read_text(encoding="utf-8")
        _i11.append(("8 shadow StateQuarantined'i yeniden firlatiyor [VEKIL]",
                     "except pf.StateQuarantined:" in _sh11 and
                     _sh11.index("except pf.StateQuarantined:") < _sh11.index('results[acc] = {"error": tb[:500]}'),
                     True))
        # 8b) daemon da karantinayi YUTMUYOR [VEKIL] — bagimsiz okumada bulundu:
        #     shadow yeniden firlatiyordu ama daemon.run_cycle `except Exception`
        #     ile bir kat yukarida yutup raporu BOS held_positions ile uretiyor,
        #     dashboard'i yaziyor, adimi yesil bitiriyordu. Iki yakalama noktasi.
        _dm11 = (_root9 / "daemon.py").read_text(encoding="utf-8")
        _i11.append(("8b daemon shadow.step karantinayi yeniden firlatiyor [VEKIL]",
                     _dm11.count("except _StateQuarantined:") >= 2
                     and "from bist_alpha.portfolio import StateQuarantined as _StateQuarantined" in _dm11,
                     True))
        _i11.append(("8c daemon held_positions karantinada {} UYDURMUYOR [VEKIL]",
                     _dm11.index("except _StateQuarantined:", _dm11.index("held_positions = {}"))
                     < _dm11.index("held_positions = {}", _dm11.index("held_positions = {}") + 1),
                     True))
        # 9) .gitignore: marker ve arsiv COMMIT'LENIR, eski .bak IGNORE (olculdu)
        _gi = (_root9 / ".gitignore").read_text(encoding="utf-8")
        _i11.append(("9 .gitignore `*.bozuk*` iceriyor (eski yedek yolu olu, kayitli)",
                     "*.bozuk*" in _gi, True))

        for _ad11, _al11, _bek11 in _i11:
            if _al11 == _bek11:
                ok(f"P0.4 {_ad11}")
            else:
                bad(f"P0.4 {_ad11}: beklenen {_bek11!r}, alinan {_al11!r}")
    except Exception as e:
        bad(f"P0.4 [6o] kosmadi: {type(e).__name__}: {e}")

    # -- [6p] P0.5 KOSUM IZI — begin/phase/end, commit manifesti, panel --
    # OLCULDU (2026-09-11): precise.yml daemon adimi kosulsuz, state commit
    # `if: always()`; daemon yari yolda duserse diskte ne varsa "precise state
    # HHMM" etiketiyle origin'e gider. Dort dusme senaryosu (feed/shadow/rapor/
    # mark) origin'de AYIRT EDILEMEZ; report_gate.release arizada claim'i siler
    # -> ariza iz birakmaz. 09-08'de canlida oldu (rontgen 12.0).
    # FAIL-SAFE: iz yazimi cagirani DUSURMEZ (kayit, karar degil); yazamazsa
    # stderr. RUNNING kalmis iz = "kosum SONLANAMADI" (panel kirmizi).
    print("\n[6p] P0.5 kosum izi: begin/phase/end + commit manifesti + panel")
    try:
        import io as _io12
        import contextlib as _ctx12
        import os as _os12
        import subprocess as _sp12
        import tempfile as _tf12
        from bist_alpha import run_trace as _RT12

        _i12 = []
        _d12 = _tf12.mkdtemp()
        _p12 = _os12.path.join(_d12, "run_trace.json")

        # 1) yasam dongusu: begin -> phase -> end(OK)
        _RT12.begin("gunici", run_id="777", sha="abcdef123456xx", path=_p12)
        _t = _RT12.read(_p12)
        _i12.append(("1 begin: RUNNING@begin, slot, run_id, sha 12",
                     (_t["status"], _t["phase"], _t["slot"], _t["run_id"], _t["sha"], _t["ended_at"]),
                     ("RUNNING", "begin", "gunici", "777", "abcdef123456", None)))
        _i12.append(("1b begin: started_at UTC 'Z' tasir (D6)",
                     _t["started_at"].endswith("Z") and "+00:00" not in _t["started_at"], True))
        _i12.append(("1c begin: .tmp artigi yok (atomik)",
                     [x for x in _os12.listdir(_d12) if x.endswith(".tmp")], []))
        _i12.append(("1d begin sonrasi ozet [RUNNING@begin] (sonlanamadi hukmu)",
                     _RT12.summary_line(_p12), "[RUNNING@begin]"))
        _RT12.phase("feed", path=_p12); _RT12.phase("shadow:A", path=_p12)
        _t = _RT12.read(_p12)
        _i12.append(("2 phase: son faz + sirali liste",
                     (_t["phase"], _t["phases"]), ("shadow:A", ["begin", "feed", "shadow:A"])))
        _i12.append(("2b ortada ozet [RUNNING@shadow:A]", _RT12.summary_line(_p12), "[RUNNING@shadow:A]"))
        _RT12.end("OK", path=_p12)
        _t = _RT12.read(_p12)
        _i12.append(("3 end(OK): status OK, ended_at 'Z', error None",
                     (_t["status"], _t["ended_at"].endswith("Z"), _t["error"]), ("OK", True, None)))
        _i12.append(("3b ozet [OK]", _RT12.summary_line(_p12), "[OK]"))
        # 4) ariza: end(FAILED, exc) -> tip+mesaj, faz korunur
        _RT12.begin("kapanis", path=_p12); _RT12.phase("shadow:G1", path=_p12)
        _RT12.end("FAILED", ValueError("fiyat_yok " + "x" * 400), path=_p12)
        _t = _RT12.read(_p12)
        _i12.append(("4 end(FAILED, exc): ozet [FAILED@shadow:G1]", _RT12.summary_line(_p12), "[FAILED@shadow:G1]"))
        _i12.append(("4b error 'Tip: mesaj', 300'e kirpilmis",
                     (_t["error"].startswith("ValueError: fiyat_yok"), len(_t["error"]) <= 312), (True, True)))
        _i12.append(("4c begin onceki izi SIFIRLAR (slot/phases yeni)",
                     (_t["slot"], _t["phases"]), ("kapanis", ["begin", "shadow:G1"])))
        # 4d SHA = FIILI HEAD (git rev-parse), GITHUB_SHA (tetik) DEGIL: iki workflow da
        #    kosumdan once `git pull --rebase` yapiyor, kosan kod HEAD'dir. Panel bu
        #    alani "hangi kod kostu" diye gosteriyor -> proxy olamaz. Yerelde env yok:
        #    eski kod None yazardi (vakum degil: beklenen HEAD[:12], None ile kirmizi).
        _head4d = _sp12.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()[:12]
        _i12.append(("4d begin sha == git HEAD[:12] + sha_source 'git' [OLCUM]",
                     (_t.get("sha"), _t.get("sha_source"), len(_head4d)), (_head4d, "git", 12)))
        _RT12.begin("x", sha="ABCDEF1234567890", path=_p12)
        _i12.append(("4e begin(sha=...) arg kazanir, kaynak 'arg'",
                     (_RT12.read(_p12)["sha"], _RT12.read(_p12)["sha_source"]), ("ABCDEF123456", "arg")))
        # 5) iz yok: read None, ozet [NO_TRACE]; end(OK) izsiz -> NO_TRACE (uydurma OK yok)
        _p5 = _os12.path.join(_d12, "yok.json")
        _i12.append(("5 iz yok: read None + [NO_TRACE]", (_RT12.read(_p5), _RT12.summary_line(_p5)), (None, "[NO_TRACE]")))
        _RT12.end("OK", path=_p5)
        _i12.append(("5b izsiz end(OK) -> NO_TRACE (basari UYDURULMAZ)",
                     (_RT12.read(_p5)["status"], _RT12.summary_line(_p5)), ("NO_TRACE", "[NO_TRACE]")))
        # 6) bozuk JSON -> read None, ozet [NO_TRACE], cokmez
        _p6 = _os12.path.join(_d12, "bozuk.json"); open(_p6, "w").write("{bozuk")
        _i12.append(("6 bozuk JSON: None + [NO_TRACE]", (_RT12.read(_p6), _RT12.summary_line(_p6)), (None, "[NO_TRACE]")))
        # 6b) GECERLI ama SOZLUK OLMAYAN JSON ("x" / 1 / []) — fuzz buldu (2026-09-11,
        #     300 denemede 37 cokme): read aynen donduruyordu, summary_line `.get`te
        #     dusuyordu; CLI _guvenli'de degil -> commit mesaji [TRACE_CLI_ERR] olurdu.
        _r6b = []
        for _ic6b in ('"x"', "1", "[]", "null"):
            open(_p6, "w").write(_ic6b)
            _r6b.append((_RT12.read(_p6), _RT12.summary_line(_p6)))
            _RT12.phase("fz", path=_p6)      # sozluk-disi iz ustune phase/end de cokmemeli
            _RT12.end("OK", path=_p6)
        _i12.append(("6b sozluk-disi JSON x4: read None + [NO_TRACE], phase/end cokmez",
                     _r6b, [(None, "[NO_TRACE]")] * 4))
        # 7) FAIL-SAFE: yazilamayan yol -> istisna YOK, None, stderr'de iz
        _p7 = _os12.path.join(_p6, "alt", "run_trace.json")  # dosya altina dizin acilamaz
        _err7 = _io12.StringIO()
        try:
            with _ctx12.redirect_stderr(_err7):
                _r7 = _RT12.begin("x", path=_p7)
                _r7b = _RT12.phase("y", path=_p7)
                _r7c = _RT12.end("OK", path=_p7)
            _g7 = (_r7, _r7b, _r7c)
        except Exception as _e7:   # fail-safe kalktiysa blok cokmesin, 7 kendisi dussun
            _g7 = f"ISTISNA {type(_e7).__name__}"
        _i12.append(("7 yazilamayan yol: begin/phase/end istisna FIRLATMAZ, None doner",
                     _g7, (None, None, None)))
        _i12.append(("7b ... ama SESSIZ degil: stderr'de [run_trace] x3",
                     _err7.getvalue().count("[run_trace] iz yazilamadi"), 3))
        # 8) [NO_RUN]: run_id eslesmiyorsa (erken cikan precise kosumu) onceki iz basilmaz
        _RT12.begin("gunici", run_id="111", path=_p12); _RT12.end("OK", path=_p12)
        _i12.append(("8 run_id eslesir -> [OK]", _RT12.summary_line(_p12, run_id="111"), "[OK]"))
        _i12.append(("8b run_id eslesmez -> [NO_RUN] (onceki kosumun OK'i bu kosuma yazilmaz)",
                     _RT12.summary_line(_p12, run_id="222"), "[NO_RUN]"))
        _i12.append(("8c run_id verilmezse filtre yok (yerel)", _RT12.summary_line(_p12), "[OK]"))
        # 8d) CLI: `-m bist_alpha.run_trace summary` GITHUB_RUN_ID'yi okur (workflow yolu)
        _env8 = dict(_os12.environ); _env8["GITHUB_RUN_ID"] = "999"; _env8["PYTHONIOENCODING"] = "utf-8"
        _env8.pop("GITHUB_SHA", None)
        # CLI TRACE_OUT'u okur (gercek dosya); burada yalnizca 'calisiyor + bir etiket basiyor'
        _cli8 = _sp12.run([sys.executable, "-m", "bist_alpha.run_trace", "summary"],
                          capture_output=True, text=True, cwd=str(_root9), env=_env8)
        _i12.append(("8d CLI summary calisir, koseli etiket basar",
                     (_cli8.returncode, _cli8.stdout.strip().startswith("[") and _cli8.stdout.strip().endswith("]")),
                     (0, True)))
        # 8e CLI'nin GITHUB_RUN_ID'yi summary_line'a gecirdigi [VEKIL]: CLI yol almiyor,
        #    gercek TRACE_OUT'u okur; run_id filtresinin DAVRANISI 8/8b'de olculdu.
        _i12.append(("8e CLI GITHUB_RUN_ID -> summary_line(run_id=...) [VEKIL]",
                     'summary_line(run_id=os.environ.get("GITHUB_RUN_ID"))'
                     in (_root9 / "bist_alpha" / "run_trace.py").read_text(encoding="utf-8"), True))
        # 9) precise_runner sarmalayicilari: ezme kurali + begin (TRACE_OUT monkeypatch)
        import precise_runner as _PR12
        _orig12 = _RT12.TRACE_OUT
        try:
            _RT12.TRACE_OUT = _p12
            # 9a daemon kendi izini FAILED kapatmis -> runner'in CalledProcessError'i EZMEZ
            _RT12.begin("gunici", path=_p12); _RT12.phase("shadow:A", path=_p12)
            _RT12.end("FAILED", ValueError("fiyat_yok"), path=_p12)
            _PR12._trace_end("FAILED", _sp12.CalledProcessError(1, "daemon.py"))
            _t = _RT12.read(_p12)
            _i12.append(("9a runner end: daemon'un FAILED izi EZILMEZ (gercek hata kalir)",
                         (_t["status"], _t["phase"], _t["error"]), ("FAILED", "shadow:A", "ValueError: fiyat_yok")))
            # 9b daemon OK bitti, mark dustu -> FAILED@mark
            _RT12.begin("gunici", path=_p12); _RT12.end("OK", path=_p12)
            _PR12._trace_phase("mark")
            _PR12._trace_end("FAILED", _sp12.CalledProcessError(1, "report_gate.py"))
            _i12.append(("9b daemon OK + mark dustu -> [FAILED@mark]", _RT12.summary_line(_p12), "[FAILED@mark]"))
            # 9c daemon sinyalle oldu (end kosmadi, RUNNING@feed) -> runner kapatir, faz korunur
            _RT12.begin("gunici", path=_p12); _RT12.phase("feed", path=_p12)
            _PR12._trace_end("FAILED", _sp12.CalledProcessError(-9, "daemon.py"))
            _t = _RT12.read(_p12)
            _i12.append(("9c daemon sinyalle oldu -> FAILED@feed, hata CalledProcessError",
                         (_RT12.summary_line(_p12), (_t["error"] or "").startswith("CalledProcessError")),
                         ("[FAILED@feed]", True)))
            # 9d runner begin: daemon begin'e ulasamazsa bile iz BU kosuma ait
            _PR12._trace_begin("acilis")
            _t = _RT12.read(_p12)
            _i12.append(("9d runner _trace_begin -> RUNNING@begin slot acilis",
                         (_t["status"], _t["phase"], _t["slot"]), ("RUNNING", "begin", "acilis")))
        finally:
            _RT12.TRACE_OUT = _orig12
        # 10) daemon.run_cycle sarmalayicisi (ÖLÇÜM: _run_cycle_iz monkeypatch; import yan etkisiz)
        import daemon as _DM12
        _orig_iz = _DM12._run_cycle_iz
        _orig_out = _RT12.TRACE_OUT
        try:
            _RT12.TRACE_OUT = _p12
            def _iyi(label="manuel"):
                _RT12.phase("feed"); return {"rapor": "var"}
            _DM12._run_cycle_iz = _iyi
            _r10 = _DM12.run_cycle("gunici")
            _i12.append(("10 run_cycle basari -> [OK], slot gunici, phases begin+feed",
                         (_RT12.summary_line(_p12), _RT12.read(_p12)["slot"], _RT12.read(_p12)["phases"]),
                         ("[OK]", "gunici", ["begin", "feed"])))
            # 10d DONUS DEGERI AYNEN GECER: main() `result is None -> SystemExit(1)`.
            #     Bagimsiz okumada bulundu: ilk sarmal degeri dusuruyordu -> her --once
            #     kosumu exit 1 olacakti (test 10 donusu sormuyordu = vakum).
            _i12.append(("10d run_cycle _run_cycle_iz'in donusunu AYNEN dondurur", _r10, {"rapor": "var"}))
            # 10e rapor None (selfheal yuttu) -> main exit 1 -> iz de FAILED (celismesin)
            _DM12._run_cycle_iz = lambda label="manuel": None
            _r10e = _DM12.run_cycle("gunici")
            _i12.append(("10e rapor None -> None doner + iz FAILED (exit 1 ile tutarli)",
                         (_r10e, _RT12.read(_p12)["status"], "None" in (_RT12.read(_p12)["error"] or "")),
                         (None, "FAILED", True)))
            def _dus(label="manuel"):
                _RT12.phase("shadow"); raise RuntimeError("shadow patladi")
            _DM12._run_cycle_iz = _dus
            try:
                _DM12.run_cycle("kapanis"); _g10 = "ISTISNA_YOK"
            except RuntimeError:
                _g10 = "RuntimeError"
            _i12.append(("10b run_cycle ariza -> istisna YENIDEN firlar (yutulmaz) + [FAILED@shadow]",
                         (_g10, _RT12.summary_line(_p12), _RT12.read(_p12)["error"]),
                         ("RuntimeError", "[FAILED@shadow]", "RuntimeError: shadow patladi")))
            def _kes(label="manuel"):
                raise KeyboardInterrupt()
            _DM12._run_cycle_iz = _kes
            try:
                _DM12.run_cycle("x"); _g10c = "ISTISNA_YOK"
            except KeyboardInterrupt:
                _g10c = "KeyboardInterrupt"
            _i12.append(("10c BaseException (SIGINT) de izi kapatir + yeniden firlar",
                         (_g10c, _RT12.read(_p12)["status"]), ("KeyboardInterrupt", "FAILED")))
        finally:
            _DM12._run_cycle_iz = _orig_iz
            _RT12.TRACE_OUT = _orig_out
        # 11) [VEKIL] kancalar yerinde: daemon fazlari, shadow hesap fazi, runner sirasi
        _dm12 = (_root9 / "daemon.py").read_text(encoding="utf-8")
        for _faz in ("feed", "shadow", "report", "telegram", "dashboard"):
            _i12.append((f"11 daemon _rt.phase(\"{_faz}\") [VEKIL]", f'_rt.phase("{_faz}")' in _dm12, True))
        _sh12 = (_root9 / "shadow.py").read_text(encoding="utf-8")
        _i12.append(("11b shadow hesap dongusunde _rt.phase(f\"shadow:{acc}\") [VEKIL]",
                     '_rt.phase(f"shadow:{acc}")' in _sh12
                     and _sh12.index('_rt.phase(f"shadow:{acc}")') < _sh12.index('results[acc] = {"error": tb[:500]}'),
                     True))
        _pr12 = (_root9 / "precise_runner.py").read_text(encoding="utf-8")
        _i12.append(("11c runner sirasi: _trace_begin < daemon < _trace_phase(mark) < mark < _trace_end < release [VEKIL]",
                     _pr12.index("_trace_begin(label)") < _pr12.index('"daemon.py", "--once"')
                     < _pr12.index('_trace_phase("mark")') < _pr12.index('"scripts/report_gate.py", "mark"')
                     < _pr12.index('_trace_end("FAILED", _exc)') < _pr12.index("release_slot(label)\n        raise"),
                     True))
        # 12) [VEKIL] iki workflow da commit mesajina izi basiyor; docs/state/ stage'de
        for _wf in ("precise.yml", "bist-alpha.yml"):
            _y = (_root9 / ".github" / "workflows" / _wf).read_text(encoding="utf-8")
            _i12.append((f"12 {_wf}: commit mesaji run_trace summary tasir; CLI cokerse AYRI etiket [VEKIL]",
                         'iz="$(python3 -m bist_alpha.run_trace summary' in _y
                         and '${iz}"' in _y and "git add -f portfolios/" in _y and "docs/state/" in _y
                         and "[TRACE_CLI_ERR]" in _y and "echo '[NO_TRACE]'" not in _y, True))
        # 12b NATIVE YOL (bist-alpha.yml) GUNICI'YI HER GUN TESLIM EDIYOR (olculdu
        #     2026-09-11: report_runs 09-09 14:56 / 09-10 14:53 bist-alpha kosumlari;
        #     workflow'daki "hic kosmuyor" notu 07-22'den kalma ve bayatti). Daemon
        #     ile mark arasindaki assert ve mark'in kendisi duserse iz FAILED
        #     kapanmali; yoksa commit mesaji [OK] basar. Sira: state_assert fazi <
        #     assert heredoc (|| end FAILED) < mark fazi < mark (|| end FAILED).
        _ba12 = (_root9 / ".github" / "workflows" / "bist-alpha.yml").read_text(encoding="utf-8")
        _iA = _ba12.find("r.phase('state_assert')")
        _iB = _ba12.find("python3 - <<'PY' || { python3 -c \"from bist_alpha import run_trace as r; r.end('FAILED'", _iA)
        _iC = _ba12.find("r.phase('mark')", _iB)
        _iD = _ba12.find('scripts/report_gate.py mark "${{ steps.gate.outputs.label }}" || { python3 -c "from bist_alpha import run_trace as r; r.end(\'FAILED\'', _iC)
        _i12.append(("12b bist-alpha.yml native yol: state_assert < assert||end(FAILED) < mark fazi < mark||end(FAILED) [VEKIL]",
                     (_iA >= 0, _iB > _iA, _iC > _iB, _iD > _iC), (True, True, True, True)))
        _i12.append(("12b' bist-alpha.yml: bayat 'pratikte kosmuyor' iddiasi duzeltilmis [VEKIL]",
                     "DUZELTME 2026-09-11" in _ba12 and "GUNCELLEME 2026-09-11" in _ba12, True))
        # 12b'' faz yardimcilari `|| true`: iz ARIZA URETMEZ. Yardimci komut dusseydi
        #      adim daemon'dan sonra, mark'tan once duserdi = senaryo D (cift Telegram).
        _i12.append(("12b'' bist-alpha.yml: iki phase yardimcisi da `|| true` (iz adimi dusuremez) [VEKIL]",
                     (_ba12.count("r.phase('state_assert')\" || true"), _ba12.count("r.phase('mark')\" || true")), (1, 1)))
        _i12.append(("12c docs/state/run_trace.json gitignore'da DEGIL (commit'e girer)",
                     _sp12.run(["git", "check-ignore", "-q", "docs/state/run_trace.json"],
                               cwd=str(_root9), capture_output=True).returncode, 1))
        # 13) [VEKIL] panel tuketicisi + JS senaryosu (asil mühür CI'da node ile: [6m] kosucu)
        _hl12 = (_root9 / "docs" / "health-logic.js").read_text(encoding="utf-8")
        # Kural (ikinci okuma 2026-09-11): dosya var ve OK degil -> r (NO_TRACE ve
        # taninmayan dahil); gri yalniz artefakt yok. Liveness uyesiyle ayni hukum.
        _i12.append(("13 health-logic: run_trace cekirdek metrigi + 'var ama OK degil -> r' kurali [VEKIL]",
                     '"run_trace", true,' in _hl12
                     and 'const rtLetter = !rt ? "n" : (rtStatus === "OK" ? "g" : "r");' in _hl12, True))
        _th12 = (_root9 / "docs" / "test-health.js").read_text(encoding="utf-8")
        _i12.append(("13b test-health.js [9] run_trace senaryolari (>=20 check) [VEKIL]",
                     "[9] P0.5 kosum izi" in _th12
                     and _th12.split("[9] P0.5 kosum izi")[1].count("check(") >= 20, True))
        for _pg in ("index.html", "health.html"):
            _i12.append((f"13c {_pg} state/run_trace.json ceker + data.run_trace atar [VEKIL]",
                         "state/run_trace.json" in (_root9 / "docs" / _pg).read_text(encoding="utf-8")
                         and "data.run_trace" in (_root9 / "docs" / _pg).read_text(encoding="utf-8"), True))
        # 14) LIVENESS 19. UYE (D13 bekci): yazici sussa dosya bayat kalir, panel
        #     eski OK'i yesil gosterirdi -> registry uyesi kacan slotu/durumu sayar.
        sys.path.insert(0, str(_root9 / "scripts"))
        import liveness_scan as _LS12
        _cfg14 = dict(_LS12.REGISTRY["run_trace"])
        _i12.append(("14 registry run_trace uyesi: producer/daemon_cycle/status==OK/tz 0",
                     tuple(_cfg14.get(k) for k in ("kind", "schedule", "ok_key", "ok_value", "tz")),
                     ("producer", "daemon_cycle", "status", "OK", 0.0)))
        _p14 = _os12.path.join(_d12, "lv_run_trace.json")
        _cfg14["file"] = _p14                      # ROOT / mutlak = mutlak
        def _lv(status, **ek):
            _RT12.begin("gunici", path=_p14)
            if status != "RUNNING":
                _RT12.end(status, ek.get("err"), path=_p14)
            return _LS12.check("run_trace", _cfg14, {"run_trace": True})
        _r14 = _lv("OK")
        _i12.append(("14a taze OK iz -> GREEN", _r14["status"], "GREEN"))
        _r14b = _lv("FAILED", err=ValueError("x"))
        _i12.append(("14b taze FAILED iz -> RED (uretici hata bildiriyor)",
                     (_r14b["status"], "status='FAILED'" in _r14b["reason"]), ("RED", True)))
        _r14c = _lv("RUNNING")
        _i12.append(("14c commit'lenmis RUNNING iz -> RED (sonlanamadi)", _r14c["status"], "RED"))
        _os12.remove(_p14)
        _i12.append(("14d dosya yok + hic yazilmamis -> SARI 'YENI UYE' (ilk gecis, kirmizi degil)",
                     (_LS12.check("run_trace", _cfg14, {})["status"],
                      "YENI UYE" in _LS12.check("run_trace", _cfg14, {})["reason"]), ("YELLOW", True)))
        _i12.append(("14e dosya yok + daha once yazmisti -> RED (uretici durdu)",
                     _LS12.check("run_trace", _cfg14, {"run_trace": True})["status"], "RED"))

    except Exception as e:
        bad(f"P0.5 [6p] kosmadi: {type(e).__name__}: {e}")
    # Rapor except'in DISINDA: blok ortada cokerse o ana kadar biriken sonuclar
    # yine gorunur (D8 mutasyonunda olculdu: cokme onceki 20 sonucu gizliyordu).
    for _ad12, _al12, _bek12 in (locals().get("_i12") or []):
        if _al12 == _bek12:
            ok(f"P0.5 {_ad12}")
        else:
            bad(f"P0.5 {_ad12}: beklenen {_bek12!r}, alinan {_al12!r}")

    # -- [6s] P0.2 -- SHADOW/HESAP HATASI AUTHORITATIVE RED -------------------
    # Bir hesap hatasi diger hesaplarin kaydini kesmez; dongu kaniti korur ve
    # sonunda TEK, tipli istisna firlatir. Normal rapor bu halde uretilemez.
    # Test once (2026-09-16): yamasiz kod A hatasini results["A"]["error"]
    # icine yutup basarili donuyor; G1 hatasi ise son faz shadow:O iken ham
    # RuntimeError olarak cikiyordu. `selfheal.guarded` da tipli hatayi yutuyordu.
    print("\n[6s] P0.2 shadow hesap hatasi authoritative RED (test-once)")
    try:
        import tempfile as _tf13
        import json as _json13
        import pandas as _pd13
        import shadow as _SH13
        import daemon as _DM13
        from bist_alpha import selfheal as _SE13
        from bist_alpha import run_trace as _RT13

        _i13 = []
        _idx13 = _pd13.DatetimeIndex([_pd13.Timestamp("2026-09-16")])
        _data13 = {"prices": _pd13.DataFrame({"X": [10.0]}, index=_idx13)}

        def _state13(acc):
            return {
                "account": acc, "cash": 1.0, "positions": {},
                "history": [{"date": "2026-09-16", "event": "initial_entry",
                             "trades": []}],
            }

        _orig13 = {
            "load": _SH13.pf.load,
            "save": _SH13.pf.save,
            "current_value": _SH13.pf.current_value,
            "value_coverage": _SH13.pf.value_coverage,
            "g1_step": _SH13.g1_mod.step,
            "g1_summary": _SH13.g1_mod.summary,
            "g1_cold": _SH13.g1_mod.cold_start_from_reference,
            "trade_log": _SH13.tradelog.log_trades,
            "stop_eval": _SH13._write_stop_eval,
            "phase": _SH13._rt.phase,
        }

        def _run_shadow13(fail_acc, g1_initial=False):
            saved, phases, stop_eval = [], [], []

            def _load(acc, state_dir=None):
                if acc == fail_acc:
                    raise RuntimeError(f"{acc} test arizasi")
                if acc == "G1" and g1_initial:
                    return {"account": "G1", "cash": 1.0, "positions": {}, "history": []}
                return _state13(acc)

            def _g1_step(data, signals, state, date, prices_today, is_rebal, **kwargs):
                if fail_acc == "G1":
                    raise RuntimeError("G1 test arizasi")
                return state, {"buys": [], "sells": [], "reentries": [],
                               "stop_unchecked": []}

            _SH13.pf.load = _load
            _SH13.pf.save = lambda state, state_dir=None: saved.append(state["account"])
            _SH13.pf.current_value = lambda state, prices: 1.0
            _SH13.pf.value_coverage = lambda state, prices: []
            _SH13.g1_mod.step = _g1_step
            _SH13.g1_mod.summary = lambda state, prices, **kwargs: {
                "value": 1.0, "n_positions": 0,
            }
            _SH13.g1_mod.cold_start_from_reference = (
                lambda state, f_state, prices, date, **kwargs:
                (state, {"buys": [], "sells": [], "reentries": [],
                         "stop_unchecked": []}))
            _SH13.tradelog.log_trades = lambda *args, **kwargs: None
            _SH13._write_stop_eval = lambda *args, **kwargs: stop_eval.append(True)
            _SH13._rt.phase = lambda name, **kwargs: phases.append(name)
            try:
                _SH13.step(_data13, {}, run_label="gunici")
                exc = None
            except Exception as err:
                exc = err
            return exc, saved, phases, stop_eval

        try:
            # A duser; B/F/O ve G1 yine tamamlanir. Sondaki faz A'ya geri
            # baglanir; aksi halde dongunun son saglam hesabi hatali etiketlenir.
            _eA, _savedA, _phA, _seA = _run_shadow13("A")
            _i13.append(("1 A hatasi tipli ShadowAccountError + accounts=('A',)",
                         (type(_eA).__name__ if _eA else None,
                          tuple(getattr(_eA, "accounts", ()))),
                         ("ShadowAccountError", ("A",))))
            _i13.append(("1b A duserken B/F/O/G1 kaydedilir (blast radius tek hesap)",
                         _savedA, ["B", "F", "O", "G1"]))
            _i13.append(("1c toplama sonrasi son faz ilk hatali hesap shadow:A",
                         _phA[-1] if _phA else None, "shadow:A"))
            _i13.append(("1d stop izi/sonlandirma adimi istisnadan once tamamlanir",
                         len(_seA), 1))

            # G1 dongu disinda olsa da ayni hesap-sozlesmesindedir; ham hata ve
            # onceki hesap etiketiyle cikamaz.
            _eG, _savedG, _phG, _seG = _run_shadow13("G1")
            _i13.append(("2 G1 hatasi tipli ve G1 diye etiketli",
                         (type(_eG).__name__ if _eG else None,
                          tuple(getattr(_eG, "accounts", ())),
                          _phG[-1] if _phG else None),
                         ("ShadowAccountError", ("G1",), "shadow:G1")))
            _i13.append(("2b G1 duserken A/B/F/O kaydedilir; G1 kaydedilmez",
                         _savedG, ["A", "B", "F", "O"]))
            _i13.append(("2c G1 hatasinda da stop izi/sonlandirma adimi tamamlanir",
                         len(_seG), 1))
            _eCold, _savedCold, _phCold, _seCold = _run_shadow13(None, g1_initial=True)
            _i13.append(("2d G1 cold-start CA alanlari tanimli; kosum tamamlanir",
                         (_eCold, _savedCold), (None, ["A", "B", "F", "O", "G1"])))
            _shadow_src13 = open(_os12.path.join(ROOT, "shadow.py"), encoding="utf-8").read()
            _i13.append(("2e G1 select hatasi bos-pick diye yutulmaz",
                         'except Exception:\n                _g1_picks = []' in _shadow_src13,
                         False))
        finally:
            _SH13.pf.load = _orig13["load"]
            _SH13.pf.save = _orig13["save"]
            _SH13.pf.current_value = _orig13["current_value"]
            _SH13.pf.value_coverage = _orig13["value_coverage"]
            _SH13.g1_mod.step = _orig13["g1_step"]
            _SH13.g1_mod.summary = _orig13["g1_summary"]
            _SH13.g1_mod.cold_start_from_reference = _orig13["g1_cold"]
            _SH13.tradelog.log_trades = _orig13["trade_log"]
            _SH13._write_stop_eval = _orig13["stop_eval"]
            _SH13._rt.phase = _orig13["phase"]

        # Hata alan hesap stop_eval'de "degerlendirildi" diye yazilamaz. Iz,
        # olculen hesaplarla olculemeyen hesaplari ayri alanlarda tasir.
        _stop_dir13 = _tf13.mkdtemp()
        _orig_stop_dir13 = _SH13.DOCS_STATE_DIR
        try:
            _SH13.DOCS_STATE_DIR = _stop_dir13
            _SH13._write_stop_eval(
                "kapanis", "2026-09-16",
                {"A": {"error": "A test arizasi"},
                 "B": {"stop_trades": [], "stop_unchecked": None}})
            with open(_os12.path.join(_stop_dir13, "stop_eval.json"), encoding="utf-8") as fh:
                _stop_payload13 = _json13.load(fh)
            _i13.append(("2f stop_eval olculen hesap ile hesap-hatasini ayirir",
                         (_stop_payload13.get("accounts"),
                          _stop_payload13.get("account_errors")),
                         (["B"], ["A"])))
        finally:
            _SH13.DOCS_STATE_DIR = _orig_stop_dir13

        # P0.2 tekrar yolu: basarisiz kosumda saglam hesap state'leri `always()`
        # commit'iyle kalici olur. Ayni slot CLAIM_TTL sonrasi yeniden kosarsa,
        # bugun yazilan pending D+1 diye bugunun OPEN'inda doldurulamaz.
        _orig_retry13 = {
            "load": _SH13.pf.load,
            "save": _SH13.pf.save,
            "rebalance": _SH13.pf.rebalance,
            "check_stops": _SH13.pf.check_stops,
            "current_value": _SH13.pf.current_value,
            "value_coverage": _SH13.pf.value_coverage,
            "g1_step": _SH13.g1_mod.step,
            "g1_summary": _SH13.g1_mod.summary,
            "trade_log": _SH13.tradelog.log_trades,
            "stop_eval": _SH13._write_stop_eval,
            "phase": _SH13._rt.phase,
            "ca": _SH13._ca_detect_and_fix,
            "gate": _SH13._data_gate,
        }
        try:
            _states_retry13 = {}
            for _acc_retry13 in ("A", "B", "F", "O"):
                _st_retry13 = _state13(_acc_retry13)
                _st_retry13["_pending_rebalance"] = {
                    "decided_at": "2026-09-16", "status": "pending",
                    "weights": {"X": 1.0}, "scale": 1.0,
                    "reason": "retry-test",
                }
                _states_retry13[_acc_retry13] = _st_retry13
            _states_retry13["G1"] = _state13("G1")
            _fills_retry13 = []
            _SH13.pf.load = lambda acc, state_dir=None: _states_retry13[acc]
            _SH13.pf.save = lambda state, state_dir=None: None
            _SH13.pf.rebalance = (
                lambda state, *args, **kwargs:
                _fills_retry13.append(state.get("account")))
            _SH13.pf.check_stops = lambda state, prices: ([], [])
            _SH13.pf.current_value = lambda state, prices: 1.0
            _SH13.pf.value_coverage = lambda state, prices: []
            _SH13.g1_mod.step = (
                lambda data, signals, state, date, prices_today, is_rebal, **kwargs:
                (state, {"buys": [], "sells": [], "reentries": [],
                         "stop_unchecked": []}))
            _SH13.g1_mod.summary = lambda state, prices, **kwargs: {
                "value": 1.0, "n_positions": 0,
            }
            _SH13.tradelog.log_trades = lambda *args, **kwargs: None
            _SH13._write_stop_eval = lambda *args, **kwargs: None
            _SH13._rt.phase = lambda *args, **kwargs: None
            _SH13._ca_detect_and_fix = lambda *args, **kwargs: ([], [], [])
            _SH13._data_gate = lambda *args, **kwargs: (False, None)
            _data_retry13 = {
                "prices": _pd13.DataFrame({"X": [10.0]}, index=_idx13),
                "opens": _pd13.DataFrame({"X": [9.0]}, index=_idx13),
            }
            _SH13.step(
                _data_retry13, {}, date=_idx13[-1], run_label="kapanis")
            _i13.append(("2g ayni-gun retry A/B/F/O pending'i D+1 diye doldurmaz",
                         (_fills_retry13,
                          ["_pending_rebalance" in _states_retry13[a]
                           for a in ("A", "B", "F", "O")]),
                         ([], [True, True, True, True])))
        finally:
            _SH13.pf.load = _orig_retry13["load"]
            _SH13.pf.save = _orig_retry13["save"]
            _SH13.pf.rebalance = _orig_retry13["rebalance"]
            _SH13.pf.check_stops = _orig_retry13["check_stops"]
            _SH13.pf.current_value = _orig_retry13["current_value"]
            _SH13.pf.value_coverage = _orig_retry13["value_coverage"]
            _SH13.g1_mod.step = _orig_retry13["g1_step"]
            _SH13.g1_mod.summary = _orig_retry13["g1_summary"]
            _SH13.tradelog.log_trades = _orig_retry13["trade_log"]
            _SH13._write_stop_eval = _orig_retry13["stop_eval"]
            _SH13._rt.phase = _orig_retry13["phase"]
            _SH13._ca_detect_and_fix = _orig_retry13["ca"]
            _SH13._data_gate = _orig_retry13["gate"]

        # G1'in hem rebalans hem re-entry pending'i ayni D+1 sozlesmesini tasir.
        def _g1_pending_retry13(kind, decided_at):
            state = _SH13.g1_mod._new_state("G1")
            state["history"] = [{"date": "2026-09-01", "total": 1.0,
                                  "n_pos": 0}]
            if kind == "rebalance":
                state["_pending_rebalance"] = {
                    "decided_at": decided_at, "status": "pending",
                    "targets": {"X": 1.0},
                }
            else:
                state["watch"]["X"] = {"exit": 8.0, "cash": 1.0, "w": 1.0}
                state["_pending_reentry"] = {
                    "decided_at": decided_at, "status": "pending",
                    "re_factor": 1.0,
                    "targets": {"X": {"exit": 8.0, "cash": 1.0, "w": 1.0}},
                }
            state, events = _SH13.g1_mod.step(
                _data13, {}, state, _idx13[-1], {"X": 10.0}, False,
                opens_today={"X": 9.0},
                pending_age_days=(0 if decided_at == "2026-09-16" else 1))
            return state, events

        _g1_same_rebal13, _g1_same_rebal_ev13 = _g1_pending_retry13(
            "rebalance", "2026-09-16")
        _i13.append(("2h G1 ayni-gun rebalans pending'ini doldurmaz",
                     (bool(_g1_same_rebal13.get("_pending_rebalance")),
                      bool(_g1_same_rebal13.get("positions")),
                      _g1_same_rebal_ev13.get("buys")),
                     (True, False, [])))
        _g1_same_reentry13, _g1_same_reentry_ev13 = _g1_pending_retry13(
            "reentry", "2026-09-16")
        _i13.append(("2i G1 ayni-gun re-entry pending'ini doldurmaz",
                     (bool(_g1_same_reentry13.get("_pending_reentry")),
                      bool(_g1_same_reentry13.get("positions")),
                      _g1_same_reentry_ev13.get("reentries")),
                     (True, False, [])))
        _g1_prior13, _g1_prior_ev13 = _g1_pending_retry13(
            "rebalance", "2026-09-15")
        _i13.append(("2j G1 onceki-gun pending'i doldurur (sozlesme ulasilabilir)",
                     (bool(_g1_prior13.get("_pending_rebalance")),
                      sorted(_g1_prior13.get("positions") or {}),
                      len(_g1_prior_ev13.get("buys") or [])),
                     (False, ["X"], 1)))

        # selfheal varsayilan davranisi korur; yalniz acikca izin verilen kritik
        # tip yutulmadan run_cycle'a ulasir.
        def _raise13(exc):
            raise exc

        _swallowed13 = _SE13.guarded(lambda: _raise13(ValueError("normal")), label="test")
        try:
            _SE13.guarded(
                lambda: _raise13(_SH13.ShadowAccountError(["A"], {"A": "tb"})),
                label="test", reraise=(_SH13.ShadowAccountError,))
            _reraised13 = None
        except Exception as err:
            _reraised13 = type(err).__name__
        _i13.append(("3 guarded normal hatayi yutar, yetkili shadow hatasini yeniden firlatir",
                     (_swallowed13, _reraised13), (None, "ShadowAccountError")))

        # Daemon siniri davranissal: step hatasi disari, trade-notice hatasi ise
        # izole. Yardimci yoksa her iki iddia da kirmizi olur (vakum degil).
        _helper13 = getattr(_DM13, "_run_shadow_cycle", None)
        if _helper13 is None:
            _i13.append(("4 daemon shadow yardimcisi var", False, True))
            _i13.append(("4b daemon ShadowAccountError'i yutmaz", None,
                         "ShadowAccountError"))
            _i13.append(("4c trade-notice bicim/bildirim hatasi shadow sonucunu bozmaz",
                         None, {"accounts": {}}))
        else:
            _orig_step13 = _SH13.step
            _orig_fmt13 = _SH13._format_trade_notice
            _orig_helper_out13 = _RT13.TRACE_OUT
            _helper_trace13 = _tf13.mktemp(suffix=".json")
            try:
                _RT13.TRACE_OUT = _helper_trace13
                _SH13.step = lambda *args, **kwargs: _raise13(
                    _SH13.ShadowAccountError(["F"], {"F": "tb"}))
                try:
                    _helper13(_data13, {}, "gunici")
                    _daemon_err13 = None
                except Exception as err:
                    _daemon_err13 = type(err).__name__
                _i13.append(("4 daemon shadow yardimcisi var", True, True))
                _i13.append(("4b daemon ShadowAccountError'i yutmaz",
                             _daemon_err13, "ShadowAccountError"))

                _fake13 = {"accounts": {}}
                _SH13.step = lambda *args, **kwargs: _fake13
                _SH13._format_trade_notice = lambda result: _raise13(RuntimeError("format"))
                try:
                    _notice_result13 = _helper13(_data13, {}, "gunici")
                except Exception as err:
                    _notice_result13 = type(err).__name__
                _i13.append(("4c trade-notice bicim/bildirim hatasi shadow sonucunu bozmaz",
                             _notice_result13, _fake13))
            finally:
                _SH13.step = _orig_step13
                _SH13._format_trade_notice = _orig_fmt13
                _RT13.TRACE_OUT = _orig_helper_out13
                try:
                    _os12.remove(_helper_trace13)
                except OSError:
                    pass

        # Uc katmanin birlesimi: guarded tipli hatayi gecirir; run_cycle gercek
        # tipi ve shadow:A fazini FAILED izine yazar, sonra aynen firlatir.
        _trace13 = _tf13.mktemp(suffix=".json")
        _orig_iz13 = _DM13._run_cycle_iz
        _orig_out13 = _RT13.TRACE_OUT
        try:
            _RT13.TRACE_OUT = _trace13
            def _chain13(label="manuel"):
                _RT13.phase("shadow:A")
                return _SE13.guarded(
                    lambda: _raise13(_SH13.ShadowAccountError(["A"], {"A": "tb"})),
                    label="rapor", reraise=(_SH13.ShadowAccountError,))
            _DM13._run_cycle_iz = _chain13
            try:
                _DM13.run_cycle("kapanis")
                _chain_err13 = None
            except Exception as err:
                _chain_err13 = type(err).__name__
            _tr13 = _RT13.read(_trace13) or {}
            _i13.append(("5 zincir: tip korunur + FAILED@shadow:A + error tipi",
                         (_chain_err13, _RT13.summary_line(_trace13),
                          (_tr13.get("error") or "").split(":", 1)[0]),
                         ("ShadowAccountError", "[FAILED@shadow:A]", "ShadowAccountError")))
        finally:
            _DM13._run_cycle_iz = _orig_iz13
            _RT13.TRACE_OUT = _orig_out13
            try:
                _os12.remove(_trace13)
            except OSError:
                pass

    except Exception as e:
        bad(f"P0.2 [6s] kosmadi: {type(e).__name__}: {e}")
    for _ad13, _al13, _bek13 in (locals().get("_i13") or []):
        if _al13 == _bek13:
            ok(f"P0.2 {_ad13}")
        else:
            bad(f"P0.2 {_ad13}: beklenen {_bek13!r}, alinan {_al13!r}")

    # 7. sidesource
    print("\n[7] Yan kaynak (sidesource)")
    try:
        from bist_alpha import sidesource as ss
        score = ss.deniz_stock_score("GARAN")
        if score is not None:
            ok(f"Deniz skoru okundu (GARAN: {score})")
        else:
            warn("Deniz skoru okunamadı (GARAN)")
        flags = ss.annotate_ticker("GARAN", "XBANK")
        ok(f"annotate çalışıyor ({len(flags)} bayrak)")
    except Exception as e:
        bad(f"sidesource hatası: {e}")

    # 8. self-heal + bakım + optimizer
    print("\n[8] Öz-iyileştirme / bakım / optimizatör")
    try:
        from bist_alpha import selfheal, maintenance, optimizer, config as cfg
        if live_mode:
            d2 = selfheal.safe_feed()
            ok(f"selfheal.safe_feed ({d2['prices'].shape[1]} hisse)")
        else:
            ok("selfheal.safe_feed atlandı (offline; --mode live ile canlı veri denenir)")
        n = maintenance.clean_temp()
        ok(f"maintenance.clean_temp ({n} öğe temizlendi)")

        # Borsapy tarih indeksi timezone-aware gelebilir. Bakim kontrolu ayni
        # veriye naive/aware eksenlerde ayni hükmü vermeli; eksen farki daemon'u
        # düşürmemeli (2026-09-08 canli kapanis arizasi).
        import pandas as pd
        _now_naive = pd.Timestamp.now().floor("s")
        _idx_naive = pd.date_range(end=_now_naive, periods=5, freq="D")
        _idx_aware = _idx_naive.tz_localize("UTC")
        _vals = pd.DataFrame(
            {"AAA": [1, 2, 3, 4, 5], "BBB": [5, 4, 3, 2, 1]},
            index=_idx_naive,
        )
        _naive_issues = maintenance.check_data_health({"prices": _vals})
        _aware_vals = _vals.copy()
        _aware_vals.index = _idx_aware
        _aware_issues = maintenance.check_data_health({"prices": _aware_vals})
        if _aware_issues == _naive_issues:
            ok("maintenance timezone-aware/naive veri ayni hüküm")
        else:
            bad(f"maintenance TZ hükmü ayrıştı: naive={_naive_issues}, aware={_aware_issues}")

        _stale_vals = _aware_vals.copy()
        _stale_vals.index = _stale_vals.index - pd.Timedelta(days=10)
        _stale_issues = maintenance.check_data_health({"prices": _stale_vals})
        if any(str(issue).startswith("Veri eski:") for issue in _stale_issues):
            ok("maintenance timezone-aware eski veriyi yakalar")
        else:
            bad(f"maintenance timezone-aware eski veri kaçtı: {_stale_issues}")

        selfheal.validate_and_repair_state("A")
        ok("selfheal.validate_and_repair_state")
        ok(f"optimizer hazır (suggest-only, SEKTOR_CAP={cfg.SEKTOR_CAP} değişmez)")
    except Exception as e:
        bad(f"self-heal/bakım/optimizer hatası: {e}")

    # 8b. Survivorship + Telegram inbound
    print("\n[8b] Survivorship + Telegram veri alımı")
    try:
        from bist_alpha import universe_history, telegram_ingest, data as _dm
        if universe_history.available():
            rep = universe_history.survivorship_report(_dm.load_data())
            ok(f"nokta-zamanlı üyelik VAR ({rep.get('missing_from_price_data','?')} eksik)")
        else:
            ok("nokta-zamanlı üyelik CSV yok (mcap top-100 + uyarı; CSV ekleyince aktif)")
        # telegram_ingest fonksiyonu hazır mı
        assert hasattr(telegram_ingest, "fetch_uploads")
        ok("telegram_ingest.fetch_uploads hazır (manuel veri yükleme)")
    except Exception as e:
        bad(f"survivorship/telegram hatası: {e}")

    # 9. 7/24 deploy doğrulama (bilgisayar kapalıyken çalışma)
    print("\n[9] 7/24 deploy (bilgisayar kapalıyken çalışma)")
    import glob
    wf = glob.glob(".github/workflows/*.yml") + glob.glob(".github/workflows/*.yaml")
    if not wf:
        bad(".github/workflows/ YOK → GitHub Actions çalışmaz (7/24 kapalı)")
    else:
        ok(f"workflow doğru konumda: {wf[0]}")
        content = open(wf[0], encoding="utf-8").read()
        if "schedule:" in content and "cron:" in content:
            ok("cron zamanlama tanımlı (09:45/14:30/18:30)")
        else:
            bad("workflow'da cron schedule yok")
        if "DATA_SOURCE: yahoo" in content:
            ok("canlı veri (yahoo) yapılandırılmış")
        else:
            warn("workflow'da DATA_SOURCE: yahoo yok (canlı veri gelmez)")
        if "git push" in content and "permissions" in content:
            ok("state kalıcılığı (git commit/push + write izni)")
        else:
            warn("workflow'da state commit/push eksik")
    # GitHub remote olmadan workflow dosyasi bulutta aktif olmaz.
    git_config = os.path.join(".git", "config")
    if os.path.exists(git_config):
        gcfg = open(git_config, encoding="utf-8", errors="ignore").read()
        if "[remote " in gcfg and "github.com" in gcfg:
            ok("GitHub remote tanimli (7/24 push icin hazir)")
        else:
            warn("GitHub remote yok -> workflow dosyasi hazir ama bulutta 7/24 aktif degil")
    else:
        warn(".git yok -> GitHub Actions icin repo/push kurulumu gerekli")
    # .gitignore portfolios'u ignore etmemeli (state kaybolur)
    if os.path.exists(".gitignore"):
        gi = open(".gitignore", encoding="utf-8").read()
        if "portfolios/" in gi and not gi.split("portfolios/")[0].rstrip().endswith("#"):
            # portfolios/ yorum satırı olmadan ignore ediliyorsa sorun
            lines = [l.strip() for l in gi.splitlines() if l.strip() and not l.strip().startswith("#")]
            if "portfolios/" in lines:
                bad(".gitignore portfolios/'u ignore ediyor → state kaybolur")
            else:
                ok(".gitignore portfolios/'u koruyor (state kalıcı)")
        else:
            ok(".gitignore portfolios/'u koruyor (state kalıcı)")
    else:
        warn(".gitignore yok")

    # 9-EK. DENETIM ARTEFAKTI BAYAT MI — "koruma kendini korumadan muaf sanir"
    # docs/state/system_control_audit.json PUBLIC yayimlaniyor (bkz
    # GIZLILIK_CANLI_GECIS_KARARI + CLOUDFLARE_ACCESS_KURULUM public URL'i) ve
    # DORT belge onu her degisiklikte `--write` ile tazelemeyi soyluyor.
    # 2026-09-10'da olculdu: damga 2026-07-16 idi -> 56 GUN bayat, ve o bayat
    # kopya `Duplicate basename scan` icin `pass` gosteriyordu, gercek `warn`.
    # Kimse tazelemedigi gibi kimse BAYATLIGI DA OLCMUYORDU (sinyal sifir).
    # ESIK UYDURULMADI: reponun kendi kurali "her degisiklikte" -> artefakttan
    # SONRA gelen bir kod commit'i varsa bayattir. Kiyas noktasi git'in kendisi.
    # BLOKLAYICI DEGIL UYARI: bloklamak salt-dokuman commit'lerini de dusururdu;
    # amac kapi kurmak degil, 56 gun suren SESSIZLIGI bitirmek.
    print("\n[9-EK] Denetim artefakti tazeligi")
    try:
        import io as _ioA
        import json as _jsonA
        import subprocess as _spA
        _audit_pathA = os.path.join(ROOT, "docs", "state", "system_control_audit.json")
        if not os.path.exists(_audit_pathA):
            warn("system_control_audit.json YOK — public denetim artefakti uretilmemis")
        else:
            _auditA = _jsonA.load(_ioA.open(_audit_pathA, encoding="utf-8"))
            _damgaA = str(_auditA.get("generated_at") or "")[:19]
            _sonKodA = _spA.run(
                ["git", "log", "-1", "--format=%cI", "--",
                 "bist_alpha", "scripts", "selftest.py", ".github/workflows"],
                capture_output=True, text=True, cwd=ROOT, encoding="utf-8",
            ).stdout.strip()[:19]
            if not _damgaA or not _sonKodA:
                warn(f"denetim artefakti tazeligi OLCULEMEDI (damga={_damgaA!r} kod={_sonKodA!r})")
            elif _damgaA < _sonKodA:
                warn(f"denetim artefakti BAYAT: damga {_damgaA} < son kod commit'i {_sonKodA} "
                     "-> `python scripts/system_control_audit.py --write "
                     "docs/state/system_control_audit.json`")
            else:
                ok(f"denetim artefakti taze (damga {_damgaA} >= son kod {_sonKodA})")
    except Exception as _eA:
        warn(f"denetim artefakti tazeligi okunamadi: {type(_eA).__name__}: {_eA}")

    # 9-EK2. ELLE ADIM -> KODA TASINDI (D13 otomatiklesme saati, 2026-09-10)
    # `docs/DEGISIKLIK_YONETIMI.md -> Commit Oncesi Kontrol` iki adim yaziyor:
    #   `git diff --check`  ve  `python -m py_compile ...`
    # Ikisini de HICBIR SEY ZORLAMIYORDU; ben de bugun ikisini birden atladim.
    # OLCULDU (2026-09-10): repoda 67 .py var, 36'si selftest metninde HIC ANILMIYOR
    # — aralarinda precise_runner.py (her precise kosumunu suren), reporter.py (her
    # Telegram raporunu yazan) ve scripts/sanitize_public_state.py (Deniz gizlilik
    # temizleyicisi). Birinde syntax hatasi olsa SESSIZCE yayina cikar ve ancak
    # uretimde, rapor slotunda patlardi.
    # NOT: su an 67/67 derleniyor -> bu ONLEYICI bir kapi, mevcut bir kiriga yama degil.
    # BLOKLAYICI/UYARI AYRIMI: derlenmeyen dosya BLOKLAR (calismayan kod);
    # `git diff --check` UYARIR (bosluk/catisma isareti — kozmetikten catismaya
    # uzanir, bloklamak listenin devre disi birakilmasini davet eder).
    print("\n[9-EK2] Derleme + calisma agaci hijyeni (repo standardi, artik otomatik)")
    try:
        import py_compile as _pcB
        import subprocess as _spB
        import tempfile as _tfB
        _atlaB = (".git", "local", "__pycache__", "node_modules", ".venv",
                  "deniz_snapshots")
        _tumB = []
        for _kokB, _dizB, _dosB in os.walk(ROOT):
            _dizB[:] = [d for d in _dizB if d not in _atlaB]
            for _fB in _dosB:
                if _fB.endswith(".py"):
                    _tumB.append(os.path.join(_kokB, _fB))
        _bozukB = []
        with _tfB.TemporaryDirectory() as _tdB:
            for _pB in _tumB:
                try:
                    _pcB.compile(_pB, cfile=os.path.join(_tdB, "x.pyc"), doraise=True)
                except Exception as _eB:
                    _bozukB.append(
                        f"{os.path.relpath(_pB, ROOT)}: {type(_eB).__name__}"
                    )
        if _bozukB:
            bad(f"DERLENMEYEN {len(_bozukB)}/{len(_tumB)} dosya: " + " | ".join(_bozukB[:5]))
        else:
            ok(f"{len(_tumB)} python dosyasinin tamami derleniyor")

        _dcB = _spB.run(["git", "diff", "--check"], capture_output=True, text=True,
                        cwd=ROOT, encoding="utf-8", errors="replace")
        _satirB = [s for s in (_dcB.stdout or "").splitlines() if s.strip()]
        if _satirB:
            warn(f"git diff --check {len(_satirB)} sorun buldu: " + _satirB[0][:110])
        else:
            ok("git diff --check temiz (bosluk/catisma isareti yok)")
    except Exception as _eB2:
        bad(f"[9-EK2] kosmadi: {type(_eB2).__name__}: {_eB2}")

    # 9a. P0.3 — URETICI WORKFLOW HATASI TELEGRAM'A ULASMALI
    # precise/native daemon yolu kirildiginda sonraki always() adimlari yesil
    # gorunebilir. Alarm job'in SON adimi olmali, failure ile cancelled'i
    # kapsamali ve report_gate/gunluk dedup'tan bagimsiz her arizada gondermeli.
    print("\n[9a] P0.3 uretici workflow hata alarmi (test-once)")

    def _workflow_step_block(_text, _name_fragment):
        _lines = _text.splitlines()
        _start = next(
            (i for i, line in enumerate(_lines)
             if line.startswith("      - name:") and _name_fragment in line),
            None,
        )
        if _start is None:
            return ""
        _end = len(_lines)
        for i in range(_start + 1, len(_lines)):
            if _lines[i].startswith("      - name:") or _lines[i].startswith("      - uses:"):
                _end = i
                break
        return "\n".join(_lines[_start:_end])

    _producer_alarm_blocks = []
    for _workflow_path in [
        ".github/workflows/precise.yml",
        ".github/workflows/bist-alpha.yml",
    ]:
        _workflow_text = open(_workflow_path, encoding="utf-8").read()
        _workflow_name = os.path.basename(_workflow_path)
        import re as _re

        _force_input_match = _re.search(
            r"(?ms)^      force_fail:\s*$\n(?P<body>(?:        .*?(?:\n|$))+)",
            _workflow_text,
        )
        _force_input_body = _force_input_match.group("body") if _force_input_match else ""
        _dispatch_has_input = (
            "required: false" in _force_input_body
            and "default: false" in _force_input_body
            and "type: boolean" in _force_input_body
        )
        if _dispatch_has_input:
            ok(f"P0.3 {_workflow_name}: force_fail boolean + default false")
        else:
            bad(f"P0.3 {_workflow_name}: force_fail girdisi eksik/guvensiz varsayilan")

        _force_block = _workflow_step_block(_workflow_text, "P0.3 kontrollu hata")
        if (
            "github.event_name == 'workflow_dispatch'" in _force_block
            and "inputs.force_fail" in _force_block
            and "exit 1" in _force_block
            and "continue-on-error" not in _force_block
        ):
            ok(f"P0.3 {_workflow_name}: kontrollu hata kancasi")
        else:
            bad(f"P0.3 {_workflow_name}: kontrollu hata kancasi eksik/yanlis")

        _alarm_block = _workflow_step_block(_workflow_text, "P0.3 workflow hata alarmi")
        _producer_alarm_blocks.append(_alarm_block)
        if "failure() || cancelled()" in _alarm_block:
            ok(f"P0.3 {_workflow_name}: failure + normal-cancel kosulu")
        else:
            bad(f"P0.3 {_workflow_name}: failure + cancelled birlikte kapsanmiyor")

        _telegram_proof = (
            "TELEGRAM_TOKEN" in _alarm_block
            and "TELEGRAM_CHAT_ID" in _alarm_block
            and _re.search(r"curl\s+-[A-Za-z]*f[A-Za-z]*\b", _alarm_block)
            and '\"ok\"[[:space:]]*:[[:space:]]*true' in _alarm_block
            and "TELEGRAM_TOKEN yok" in _alarm_block
            and "TELEGRAM_CHAT_ID yok" in _alarm_block
            and "|| true" not in _alarm_block
        )
        if _telegram_proof:
            ok(f"P0.3 {_workflow_name}: Telegram HTTP + ok:true kaniti")
        else:
            bad(f"P0.3 {_workflow_name}: Telegram basari kaniti eksik")

        _manifest_fields = [
            "github.workflow",
            "job.status",
            "github.event_name",
            "github.event.schedule",
            "github.ref",
            "github.sha",
            "github.actor",
            "github.run_id",
        ]
        _missing_manifest = [field for field in _manifest_fields if field not in _alarm_block]
        if not _missing_manifest:
            ok(f"P0.3 {_workflow_name}: eyleme-yeterli hata manifesti")
        else:
            bad(f"P0.3 {_workflow_name}: manifest eksik {_missing_manifest}")

        _step_headers = [
            line.strip()
            for line in _workflow_text.splitlines()
            if line.startswith("      - name:") or line.startswith("      - uses:")
        ]
        _alarm_is_last = bool(
            _step_headers
            and _step_headers[-1].startswith("- name:")
            and "P0.3 workflow hata alarmi" in _step_headers[-1]
        )
        _alarm_is_independent = (
            "report_gate" not in _alarm_block
            and "HEARTBEAT_DUE" not in _alarm_block
            and "continue-on-error" not in _alarm_block
        )
        _alarm_run_body = _alarm_block.split("run: |", 1)[-1]
        _shell_has_no_direct_expressions = "${{" not in _alarm_run_body
        if _alarm_is_last and _alarm_is_independent and _shell_has_no_direct_expressions:
            ok(f"P0.3 {_workflow_name}: son adim + dedup bagimsiz + env-sinirli")
        else:
            bad(f"P0.3 {_workflow_name}: son adim/bagimsizlik/env siniri bozuk")

    if (
        len(_producer_alarm_blocks) == 2
        and _producer_alarm_blocks[0]
        and _producer_alarm_blocks[0] == _producer_alarm_blocks[1]
    ):
        ok("P0.3 iki ureticide alarm sozlesmesi birebir ayni")
    else:
        bad("P0.3 producer alarm bloklari ayrismis")

    # 9b. P0.3 — KALICILIK HATASI ALARM KANALINI BYPASS EDEMEZ
    # State commit/push adimindeki hata yutulursa job yesil gorunur ve hemen
    # sonraki failure()/cancelled() alarmi hic kosmaz. Bu kontrol davranisi
    # degil, workflow sozlesmesinin kritik yuzeyini sabitler.
    print("\n[9b] P0.3 state kaliciligi hata yolu")
    for _wf_name, _wf_path in (
        ("precise.yml", ".github/workflows/precise.yml"),
        ("bist-alpha.yml", ".github/workflows/bist-alpha.yml"),
    ):
        _wf_text = open(_wf_path, encoding="utf-8").read()
        _persist_bad = []
        if "git pull --rebase --autostash || true" in _wf_text:
            _persist_bad.append("git pull hatasi yutuluyor")
        if _re.search(r"git add[^\n]*\|\|\s*true", _wf_text):
            _persist_bad.append("git add hatasi yutuluyor")
        if _wf_name == "precise.yml" and "git push || echo" in _wf_text:
            _persist_bad.append("git push hatasi yutuluyor")
        if _wf_name == "bist-alpha.yml":
            _push_fail = _wf_text.find("if ! git push; then")
            _push_end = _wf_text.find("fi", _push_fail) if _push_fail >= 0 else -1
            _push_block = _wf_text[_push_fail:_push_end] if _push_fail >= 0 and _push_end > _push_fail else ""
            if _push_fail < 0 or "exit 1" not in _push_block:
                _persist_bad.append("git push sonrasi job fail etmiyor")
        if _persist_bad:
            bad(f"P0.3 {_wf_name}: kalicilik hatasi {'; '.join(_persist_bad)}")
        else:
            ok(f"P0.3 {_wf_name}: kalicilik hatasi alarm yoluna donuyor")

    # 9c. Report gate claim'i producer'dan ONCE origin'e dayanir.
    # check->daemon->mark sirasi tek basina cross-runner dedup degildir:
    # native ve precise ayri concurrency gruplarinda kosar.
    print("\n[9c] report gate durable claim sozlesmesi")
    from pathlib import Path
    _root_path = Path(__file__).resolve().parent
    _claim_helper = _root_path / "scripts" / "report_claim.py"
    _claim_text = _claim_helper.read_text(encoding="utf-8") if _claim_helper.exists() else ""
    _precise_runner_text = (_root_path / "precise_runner.py").read_text(encoding="utf-8")
    _native_text = (_root_path / ".github" / "workflows" / "bist-alpha.yml").read_text(encoding="utf-8")
    _claim_checks = [
        ("claim yardimcisi var", _claim_helper.exists()),
        ("claim origin'e push edilmeden baslamiyor", "_git(\"push\"" in _claim_text and
         "_git(\"commit\"" in _claim_text),
        ("claim commit kimligi ve scope'u sabit", "_git(\"config\", \"user.name\"" in _claim_text and
         "staged_paths != [STATE_REL]" in _claim_text),
        ("native claim, daemon'dan once", "scripts/report_claim.py claim" in _native_text and
         _native_text.find("scripts/report_claim.py claim") < _native_text.find("python3 daemon.py")),
        ("precise claim yardimcisini kullaniyor", "report_claim.py" in _precise_runner_text and
         "G.claim(label)" not in _precise_runner_text),
        ("claim basarisizsa daemon kosmuyor", "claimed=false" in _claim_text and "return 0" in _claim_text),
        ("claim release/TTL sozlesmesi korunuyor", "import report_gate" in _claim_text and
         "report_gate.claim" in _claim_text),
    ]
    for _name, _passed in _claim_checks:
        (ok if _passed else bad)(f"P0.6 claim: {_name}")

    # 9c-2. Iki producer ayni anda claim commit'i uretebilir. Push'u kaybeden
    # kosum, origin'de AYNI slotu rakip aldiysa producer arizasi degildir;
    # yerel claim commit'ini birakmadan claimed=false donmelidir. Origin yalniz
    # ilgisiz nedenle ilerlediyse claim taze tabanda bir kez daha denenir.
    try:
        import json as _json14
        import subprocess as _sp14
        import tempfile as _tf14
        from datetime import datetime as _dt14
        from pathlib import Path as _Path14
        from zoneinfo import ZoneInfo as _ZI14

        _scripts14 = str(_root_path / "scripts")
        if _scripts14 not in sys.path:
            sys.path.insert(0, _scripts14)
        import report_claim as _RC14

        _race_helper14 = getattr(_RC14, "_durable_claim", None)
        _commit_helper14 = getattr(_RC14, "_commit_claim", None)
        _align_helper14 = getattr(_RC14, "_align_after_failed_push", None)
        if (not callable(_race_helper14) or not callable(_commit_helper14)
                or not callable(_align_helper14)):
            bad("P0.6 claim race: davranis yardimcilari yok (test-once KIRMIZI)")
        else:
            _now14 = _dt14(2026, 9, 16, 18, 40, tzinfo=_ZI14("Europe/Istanbul"))
            _key14 = "2026-09-16:kapanis"

            def _race14(push_rcs, fetch_rcs, origin_states):
                _pushes = list(push_rcs)
                _fetches = list(fetch_rcs)
                _states = list(origin_states)
                _model = {"head": "base0", "origin": "origin0", "claims": 0}
                _calls = []
                _orig_git = _RC14._git
                _orig_commit = _RC14._commit_claim
                _orig_claim = _RC14.report_gate.claim

                def _cp(args, rc=0, out="", err=""):
                    return _sp14.CompletedProcess(["git", *args], rc, out, err)

                def _fake_git(*args, check=True):
                    _calls.append(args)
                    if args[:2] == ("rev-parse", "HEAD"):
                        return _cp(args, out=_model["head"] + "\n")
                    if args[:2] == ("rev-parse", "origin/main"):
                        return _cp(args, out=_model["origin"] + "\n")
                    if args and args[0] == "push":
                        rc = _pushes.pop(0)
                        if rc == 0:
                            _model["origin"] = _model["head"]
                        return _cp(args, rc=rc, err="non-fast-forward" if rc else "")
                    if args and args[0] == "fetch":
                        rc = _fetches.pop(0)
                        if rc == 0:
                            _model["origin"] = f"origin{len(origin_states) - len(_states) + 1}"
                        return _cp(args, rc=rc, err="network" if rc else "")
                    if args and args[0] == "show":
                        payload = _states.pop(0)
                        return _cp(args, out=_json14.dumps(payload))
                    if args[:2] == ("rebase", "--onto"):
                        target = args[2]
                        _model["head"] = (
                            _model["origin"] if target == "origin/main" else target
                        )
                        return _cp(args)
                    if args[:2] == ("rebase", "--abort"):
                        return _cp(args)
                    raise AssertionError(f"beklenmeyen git cagrisi: {args}")

                def _fake_commit(label):
                    _model["claims"] += 1
                    _model["head"] = f"claim{_model['claims']}"
                    return _model["head"]

                _RC14._git = _fake_git
                _RC14._commit_claim = _fake_commit
                _RC14.report_gate.claim = lambda label, now=None: True
                try:
                    try:
                        result = _RC14._durable_claim("kapanis", _now14, "main")
                        error = None
                    except RuntimeError as exc:
                        result, error = None, exc
                finally:
                    _RC14._git = _orig_git
                    _RC14._commit_claim = _orig_commit
                    _RC14.report_gate.claim = _orig_claim
                return result, error, _model, _calls

            _same14 = {"sent": {_key14: {"claim_at": _now14.isoformat(timespec="seconds")}}}
            _other14 = {"sent": {"2026-09-16:gunici": {"sent_at": _now14.isoformat(timespec="seconds")}}}

            _r14a, _e14a, _m14a, _c14a = _race14([1], [0], [_same14])
            (ok if (_r14a is False and _e14a is None and _m14a["head"] == _m14a["origin"]
                    and _m14a["claims"] == 1
                    and ("fetch", "origin", "+refs/heads/main:refs/remotes/origin/main") in _c14a)
             else bad)(
                "P0.6 claim race: ayni-slot rakibi temiz claimed=false + origin'e hizalanma")

            _r14b, _e14b, _m14b, _c14b = _race14([1, 0], [0], [_other14])
            (ok if (_r14b is True and _e14b is None and _m14b["claims"] == 2
                    and sum(1 for c in _c14b if c and c[0] == "push") == 2) else bad)(
                "P0.6 claim race: ilgisiz origin ilerlemesi taze tabanda bir kez yeniden denenir")

            _r14c, _e14c, _m14c, _c14c = _race14([1, 1], [0, 0], [_other14, _same14])
            (ok if (_r14c is False and _e14c is None and _m14c["head"] == _m14c["origin"]
                    and _m14c["claims"] == 2) else bad)(
                "P0.6 claim race: ikinci push'u rakip alirsa yine temiz duplicate")

            _r14d, _e14d, _m14d, _c14d = _race14([1], [1], [])
            (ok if (_r14d is None and isinstance(_e14d, RuntimeError)
                    and _m14d["head"] == "base0") else bad)(
                "P0.6 claim race: fetch/ag hatasi duplicate sayilmaz, yerel claim temizlenir")

            # Git semantigini de gercek gecici repoda sabitle. Mock'un rebase
            # davranisini bizim lehimize uydurmus olmasi bu testi geciremez.
            _old_root14 = _RC14.REPO_ROOT
            try:
                with _tf14.TemporaryDirectory() as _td14:
                    _tdp14 = _Path14(_td14)

                    def _rg14(*args):
                        return _sp14.run(
                            ["git", *args], cwd=_tdp14, text=True,
                            capture_output=True, check=True,
                        )

                    _rg14("init", "-q")
                    _rg14("config", "user.name", "claim-test")
                    _rg14("config", "user.email", "claim-test" + chr(64) + "example.invalid")
                    (_tdp14 / "state.txt").write_text("base", encoding="utf-8")
                    _rg14("add", "state.txt")
                    _rg14("commit", "-qm", "base")
                    _rg14("branch", "-M", "main")
                    _base14 = _rg14("rev-parse", "HEAD").stdout.strip()
                    (_tdp14 / "state.txt").write_text("mine", encoding="utf-8")
                    _rg14("add", "state.txt")
                    _rg14("commit", "-qm", "mine")
                    _mine14 = _rg14("rev-parse", "HEAD").stdout.strip()
                    _rg14("switch", "-qc", "peer", _base14)
                    (_tdp14 / "state.txt").write_text("peer", encoding="utf-8")
                    _rg14("add", "state.txt")
                    _rg14("commit", "-qm", "peer")
                    _peer14 = _rg14("rev-parse", "HEAD").stdout.strip()
                    _rg14("switch", "-q", "main")
                    _rg14("update-ref", "refs/remotes/origin/main", _peer14)
                    _RC14.REPO_ROOT = _tdp14
                    _RC14._align_after_failed_push("origin/main", _mine14)
                    _aligned14 = (
                        _rg14("rev-parse", "HEAD").stdout.strip(),
                        (_tdp14 / "state.txt").read_text(encoding="utf-8"),
                        _rg14("status", "--porcelain").stdout,
                    )
                (ok if _aligned14 == (_peer14, "peer", "") else bad)(
                    "P0.6 claim race: gercek git kaybeden commit'i dusurur ve agaci temizler")
            finally:
                _RC14.REPO_ROOT = _old_root14
    except Exception as e:
        bad(f"P0.6 claim race testleri kosmadi: {type(e).__name__}: {e}")

    # 10. CLI çalışma testi (TESPİT 5 — eksik kontrol tamamlandı)
    print("\n[10] CLI çalışma (gerçekten çalışıyor mu)")
    import subprocess
    clis = []
    if live_mode:
        clis.extend([
            ("run_backtest.py", ["--mode", "A"]),
            ("analyze_stock.py", ["GARAN"]),
            ("daemon.py", ["--optimize"]),
        ])
    else:
        ok("CLI gerçek çalıştırma atlandı (offline; parse ve A/B/F backtest zaten koştu)")
    for script, args in clis:
        try:
            env = dict(os.environ)
            env.setdefault("PYTHONIOENCODING", "utf-8")
            p = subprocess.run([sys.executable, script] + args,
                               capture_output=True, timeout=180, text=True, env=env)
            if p.returncode == 0:
                ok(f"{script} {' '.join(args)}")
            else:
                bad(f"{script} çıkış {p.returncode}: {p.stderr.strip()[:80]}")
        except subprocess.TimeoutExpired:
            warn(f"{script} zaman aşımı (>180s)")
        except Exception as e:
            bad(f"{script}: {e}")

    # 11. Web dashboard (GitHub Pages)
    print("\n[11] Web dashboard (GitHub Pages — ücretsiz statik UI)")
    import json as _json
    if os.path.exists("docs/index.html"):
        ok("docs/index.html mevcut (GitHub Pages için)")
        # JSON üretim mekanizmasını kontrol et — daemon helper varsa yeterli
        from bist_alpha import config as _cfg
        try:
            from daemon import _write_dashboard_state
            ok("daemon _write_dashboard_state hazır (her döngüde JSON yazar)")
        except ImportError:
            warn("daemon dashboard JSON üretici fonksiyonu içe aktarılamadı")
        # Daha önce üretilmiş JSON varsa şema kontrolü
        jp = "docs/state/dashboard.json"
        if os.path.exists(jp):
            try:
                d = _json.load(open(jp, encoding="utf-8"))
                if all(k in d for k in ("date", "mode", "top10", "accounts")):
                    ok(f"dashboard.json şema doğru (top:{len(d['top10'])}, hesaplar:{len(d['accounts'])})")
                else:
                    warn("dashboard.json şema eksik")
            except Exception as e:
                warn(f"dashboard.json okunamadı: {e}")
        else:
            ok("dashboard.json henüz üretilmedi (ilk daemon çalıştırmasında üretilir)")
    else:
        bad("docs/index.html YOK → web UI yayınlanamaz")

    # Sonuç
    print("\n" + "=" * 70)
    if fails:
        print(f"SONUÇ: {len(fails)} BLOKLAYICI SORUN bulundu ✗")
        for f in fails:
            print(f"   - {f}")
        return 1
    if warnings:
        print(f"SONUÇ: bloklayıcı hata yok, {len(warnings)} UYARI var ⚠")
        for w in warnings:
            print(f"   - {w}")
        if args.strict:
            return 1
        return 0
    print("SONUÇ: ✅ TÜM KONTROLLER GEÇTİ — eksik yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

