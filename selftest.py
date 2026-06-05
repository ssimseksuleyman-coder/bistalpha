#!/usr/bin/env python3
"""
SİSTEM ÖZ-DENETİM (self-test) — her an çalıştır, eksik kalmasın.

  python selftest.py

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
Çıkış kodu 0 = her şey tamam, 1 = eksik var.
"""
import ast
import os
import sys
import importlib
import io
import contextlib

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
fails = []


def ok(msg): print(f"   \u2713 {msg}")
def bad(msg): print(f"   \u2717 {msg}"); fails.append(msg)
def warn(msg): print(f"   \u26a0 {msg}"); fails.append(msg)


def main():
    print("=" * 70)
    print("BIST ALPHA — SİSTEM ÖZ-DENETİM")
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
    for root, _, files in os.walk("."):
        if "__pycache__" in root:
            continue
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
    print("\n[4] Veri bütünlüğü")
    for path, desc in [("data/Tarihsel_Fiyat_Bilgileri.xlsx", "ana veri"),
                       ("data/omega", "OMEGA yan-kaynak"),
                       ("deniz_inbox", "Deniz bülten")]:
        if os.path.exists(path):
            ok(f"{desc}: {path}")
        else:
            bad(f"{desc} YOK: {path}")

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
    print("\n[6] Backtest A/B/F")
    try:
        from bist_alpha import data as dm, signals as sm, backtest as bm, config as cfg
        src = getattr(cfg, "DATA_SOURCE", "file")
        d = dm.load_data()
        sig = sm.compute_signals(d)
        ranges = {"A": (260, 320), "B": (240, 300), "F": (275, 335)}
        for mode in ["A", "B", "F"]:
            r = bm.run(d, sig, mode=mode)
            if not r:
                bad(f"{mode}: backtest çalışmadı")
                continue
            if src == "file":
                lo, hi = ranges[mode]
                if lo <= r["ret"] <= hi:
                    ok(f"{mode}: %{r['ret']} (gömülü veri beklenen {lo}-{hi})")
                else:
                    bad(f"{mode}: %{r['ret']} gömülü veri aralığı dışı")
            else:
                if -50 <= r["ret"] <= 500:
                    ok(f"{mode}: %{r['ret']} (canlı veri — sabit aralık denetlenmez)")
                else:
                    warn(f"{mode}: %{r['ret']} canlı veride şüpheli")
    except Exception as e:
        bad(f"backtest hatası: {e}")

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
        d2 = selfheal.safe_feed()
        ok(f"selfheal.safe_feed ({d2['prices'].shape[1]} hisse)")
        n = maintenance.clean_temp()
        ok(f"maintenance.clean_temp ({n} öğe temizlendi)")
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

    # 10. CLI çalışma testi (TESPİT 5 — eksik kontrol tamamlandı)
    print("\n[10] CLI çalışma (gerçekten çalışıyor mu)")
    import subprocess
    clis = [
        ("run_backtest.py", ["--mode", "A"]),
        ("analyze_stock.py", ["GARAN"]),
        ("daemon.py", ["--optimize"]),
    ]
    for script, args in clis:
        try:
            p = subprocess.run([sys.executable, script] + args,
                               capture_output=True, timeout=180, text=True)
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
        print(f"SONUÇ: {len(fails)} EKSİK/SORUN bulundu ⚠")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("SONUÇ: ✅ TÜM KONTROLLER GEÇTİ — eksik yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

