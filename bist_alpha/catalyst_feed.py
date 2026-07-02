"""
catalyst_feed.py — Fiyat-disi veri katmani (katalizor + temel). event_study motorunu besler.

IKI FEED:
  CatalystFeed     — KAP bildirimleri: bedelli/bedelsiz, endeks-giris/cikis, geri-alim,
                     ortaklik/satin-alma, temettu, bilanco tarihleri (OLAY TARIHLERI)
  FundamentalsFeed — F/K, PD/DD, buyume, net borc (DONEMSEL TEMEL VERI)

ONEMLI — DURUST SINIR:
  Fetch metotlari KAP/veri-saglayici ENDPOINT'ine baglanmali; bu kurulusa gore
  ayarlanir ve SENIN ORTAMINDA calisir (sandbox kap.org.tr'ye cikamaz). Sema, parse
  iskeleti ve motor arayuzu hazir; gercek cekme sende baglanir. Uydurma veri YOK.
"""
from __future__ import annotations
import os
import re
import json
import time
from datetime import date, datetime, timedelta

try:
    import requests
except Exception:
    requests = None

# --- Katalizor tur taksonomisi ---
CATALYST_TYPES = (
    "bedelsiz",       # bonus issue (sermaye artirimi, bedelsiz)
    "bedelli",        # rights issue
    "endeks_giris",   # BIST endeks kompozisyonuna giris
    "endeks_cikis",   # endeksten cikis
    "geri_alim",      # pay geri alim programi
    "ortaklik",       # ortaklik / satin alma / birlesme
    "temettu",        # temettu
    "bilanco",        # finansal tablo aciklama
    "yatirim_tesvik", # yatirim / tesvik / yeni proje
)


class CatalystFeed:
    """KAP bildirim akisindan katalizor OLAY TARIHLERI. event_study'ye [(ticker,date)] verir."""

    def __init__(self, state_dir: str = "docs/state"):
        self.state_dir = state_dir

    # ---- fetch (PLAYWRIGHT — gercek tarayici, WAF/RSC gecer) ----
    # KESIF (2026-07): KAP requests-API'si (POST /tr/api/disclosures) headless'e
    # WAF-timeout veriyor; site Next.js RSC (client XHR yok, veri DOM'da render).
    # COZUM: Playwright headless Chromium -> ana sayfa render -> tr-satirlarindan
    # yapilandirilmis cek. fetch_today() 3x tutarli test edildi (49/49/49).
    _KAP_URL = "https://www.kap.org.tr/tr/"
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120 Safari/537.36")
    _ROW_JS = r"""() => {
        const out = [];
        document.querySelectorAll('tr').forEach(tr => {
            const c = [...tr.children].map(td => (td.innerText||'').replace(/\s+/g,' ').trim());
            if (c.length >= 9 && /^[A-Z0-9]{3,6}$/.test(c[3] || '')) {
                const a = tr.querySelector('a[href*="/Bildirim/"]');
                out.push({tarih:c[2], kod:c[3], sirket:c[4], tip:c[5], konu:c[6],
                          ilgili:c[8]||'', url:a ? a.href : ''});
            }
        });
        return out;
    }"""

    def fetch_kap(self, ticker: str = None, headless: bool = True,
                  retries: int = 2, timeout: int = 45000) -> list:
        """KAP BUGUNKU bildirimlerini Playwright ile cek -> [{date,ticker,type,title,url}].
        classify_title ile turlenir (rutin=None ELENIR). Gunluk cagirilir (accumulate).
        Tarihsel backfill KAP formu kapali-panelde (kirilgan) -> forward-birikim tercih."""
        rows = self._scrape_kap_rows(headless, retries, timeout)
        return self._map_rows(rows, ticker)

    def _scrape_kap_rows(self, headless=True, retries=2, timeout=45000) -> list:
        """Playwright headless: ana sayfa -> ticker'li tr satirlari render olana kadar
        bekle (wait_for_function, 0-satir yarisini cozer) -> hucreleri cek."""
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise RuntimeError("playwright yok: pip install playwright && python -m playwright install chromium")
        today_iso = date.today().isoformat()
        yday_iso = (date.today() - timedelta(days=1)).isoformat()
        wait_js = ("()=>[...document.querySelectorAll('tr')].some(tr=>{"
                   "const c=[...tr.children].map(td=>(td.innerText||'').trim());"
                   "return c.length>=9&&/^[A-Z0-9]{3,6}$/.test(c[3]||'');})")
        last = None
        for _ in range(retries + 1):
            try:
                with sync_playwright() as p:
                    br = p.chromium.launch(headless=headless)
                    page = br.new_context(user_agent=self._UA, locale="tr-TR").new_page()
                    page.goto(self._KAP_URL, wait_until="domcontentloaded", timeout=timeout)
                    page.wait_for_function(wait_js, timeout=timeout)
                    raw = page.evaluate(self._ROW_JS)
                    br.close()
                if raw:
                    out = []
                    for r in raw:
                        d = self._norm_date(r.get("tarih", ""), today_iso, yday_iso)
                        codes = self._split_codes(r.get("kod", "")) + self._split_codes(r.get("ilgili", ""))
                        out.append({"date": d, "title": r.get("konu", ""),
                                    "stockCodes": codes, "url": r.get("url", ""), "raw": r})
                    return out
            except Exception as e:
                last = e
        if last:
            print(f"[catalyst_feed] KAP scrape uyari: {type(last).__name__}: {str(last)[:80]}")
        return []

    @staticmethod
    def _norm_date(s, today_iso, yday_iso):
        """KAP tarih hucresi -> ISO. 'Bugun HH:MM'->bugun, 'Dun'->dun, 'DD.MM.YYYY'->parse."""
        s = (s or "").strip()
        low = s.lower()
        if low.startswith("bug"):
            return today_iso
        if low.startswith("dün") or low.startswith("dun"):
            return yday_iso
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None

    def accumulate(self, filename: str = "catalysts.json") -> int:
        """Bugunku bildirimleri cek + catalysts.json'a DEDUP-MERGE. Daemon gunluk cagirir;
        haftalar icinde event_study'ye yetecek katalizor gecmisi birikir. Doner: eklenen sayi."""
        new = self.fetch_kap()
        existing = self._load(filename).get("events", [])
        seen = {(e.get("ticker"), e.get("date"), e.get("type"), (e.get("title") or "")[:40])
                for e in existing}
        added = 0
        for e in new:
            k = (e.get("ticker"), e.get("date"), e.get("type"), (e.get("title") or "")[:40])
            if e.get("date") and k not in seen:
                existing.append({"date": e["date"], "ticker": e["ticker"],
                                 "type": e["type"], "title": e.get("title", ""),
                                 "url": e.get("raw", {}).get("url", "") if isinstance(e.get("raw"), dict) else ""})
                seen.add(k); added += 1
        # IDEMPOTENT: yeni olay yoksa dosyaya DOKUNMA (generated_at degisip
        # gereksiz git-commit uretmesin). Ayni-gun re-run -> byte-identical.
        if added > 0:
            self.save(existing, filename)
        return added

    def _map_rows(self, rows: list, ticker: str = None) -> list:
        """KAP ham satirlari -> [{"date","ticker","type","title","raw"}]. SAF/AGSIZ.
        _pick fallback anahtarlari ilk gercek yanitta dogrulanmali."""
        want = ticker.split(".")[0].upper() if ticker else None
        out, seen = [], set()
        for r in rows:
            d = self._to_iso(self._pick(r, "publishDate", "disclosureDate",
                                        "kapPublishDate", "publishTime", "date"))
            title = self._pick(r, "title", "kapTitle", "summary",
                               "disclosureCategory", "subject") or ""
            codes = self._pick(r, "stockCodes", "relatedStocks", "memberName",
                               "companyCode", "stockCode", "ticker")
            if not d:
                continue
            typ = self.classify_title(title)
            if typ is None:
                continue
            for tic in self._split_codes(codes):
                if want and tic != want:
                    continue
                key = (tic, d, typ, title[:40])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"date": d, "ticker": tic, "type": typ,
                            "title": title, "raw": r})
        return out

    @staticmethod
    def _pick(obj, *keys):
        if not isinstance(obj, dict):
            return None
        for k in keys:
            v = obj.get(k)
            if v not in (None, ""):
                return v
        return None

    @staticmethod
    def _split_codes(codes):
        """Ticker listesi -> gecerli BIST kodlari (3-6 harf/rakam). '-', bos, cop ELENIR."""
        if codes is None:
            return []
        toks = codes if isinstance(codes, list) else str(codes).replace(";", ",").replace("/", ",").split(",")
        out = []
        for c in toks:
            c = str(c).upper().strip()
            if re.fullmatch(r"[A-Z0-9]{3,6}", c):
                out.append(c)
        return out

    @staticmethod
    def _to_iso(d):
        """KAP tarih -> 'YYYY-MM-DD'. ISO veya 'DD.MM.YYYY[ HH:MM]' kabul eder."""
        if not d:
            return None
        s = str(d).strip()
        try:
            if len(s) >= 10 and s[2] == "." and s[5] == ".":
                return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
            return s[:10]
        except Exception:
            return None

    @staticmethod
    def classify_title(title: str) -> str | None:
        """KAP bildirim basligini katalizor turune esle (Turkce anahtar kelimeler)."""
        # Circumflex normalizasyonu: KAP "Kâr Payı" (â) yazar; anahtar kelimeler
        # "kar payı" (a). â/î/û -> a/i/u (uzatma sapkasi, opsiyonel harf).
        # DIKKAT: ı/i/ş/ç/ğ/ö/ü GERCEK Turkce harfler, DOKUNULMAZ.
        t = (title or "").lower().replace("â", "a").replace("î", "i").replace("û", "u")
        rules = [
            ("bedelsiz", ["bedelsiz"]),
            ("bedelli", ["bedelli", "rüçhan", "ruchan"]),
            # NOT: endeks giris/cikis rules'ta DEGIL — asagidaki erken-return
            # yon-kelimesiyle birlikte kontrol eder. Rules'a "endeks" koymak
            # yon kelimesi olmayan basliklari (ör. "endeks duzeltme katsayisi")
            # yanlislikla endeks_giris etiketler.
            ("geri_alim", ["geri alım", "geri alim", "pay geri"]),
            ("ortaklik", ["devralma", "satın alma", "satin alma", "birleşme", "birlesme", "ortaklık"]),
            ("temettu", ["temettü", "temettu", "kar payı", "kar payi"]),
            ("yatirim_tesvik", ["teşvik", "tesvik", "yatırım tamamlama", "yeni yatırım"]),
            ("bilanco", ["finansal rapor", "finansal tablo", "bilanço", "bilanco", "faaliyet raporu"]),
        ]
        # endeks giris/cikis: "endeks" + yon kelimesi BIRLIKTE (yalniz "endeks" yetmez)
        if "endeks" in t and any(k in t for k in ["dahil", "giriş", "giris", "eklen"]):
            return "endeks_giris"
        if "endeks" in t and any(k in t for k in ["çıkar", "cikar", "çıkarıl", "cikaril"]):
            return "endeks_cikis"
        for typ, keys in rules:
            if any(k in t for k in keys):
                return typ
        return None

    def get_events(self, catalyst_type: str = None, filename: str = "catalysts.json") -> list:
        """Kaydedilmis olaylardan event_study formatinda [(ticker, date)] uret."""
        data = self._load(filename)
        out = []
        for e in data.get("events", []):
            if catalyst_type and e.get("type") != catalyst_type:
                continue
            try:
                out.append((e["ticker"], datetime.fromisoformat(e["date"]).date()))
            except Exception:
                continue
        return out

    def save(self, events: list, filename: str = "catalysts.json") -> str:
        os.makedirs(self.state_dir, exist_ok=True)
        path = os.path.join(self.state_dir, filename)
        payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "events": events}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def _load(self, filename):
        path = os.path.join(self.state_dir, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return {"events": []}


class FundamentalsFeed:
    """Donemsel temel veri (F/K, PD/DD, buyume, net borc). Momentum'a HARMAN filtre icin."""

    def __init__(self, state_dir: str = "docs/state"):
        self.state_dir = state_dir

    def fetch(self, tickers, pause: float = 0.8, retries: int = 1) -> dict:
        """Temel veriyi yfinance'ten cek -> {ticker: {pe,pb,growth_yoy,net_debt_ebitda,period,...}}.

        KAYNAK: yfinance (ilk pass, sifir ek altyapi; datafeed zaten Yahoo cekiyor).
        KAPSAM (Analiz olctu, buyuk-cap BIST 6/6): trailingPE/forwardPE/priceToBook/
        revenueGrowth/totalDebt/totalCash/ebitda dolu. Kucuk/iliksiz isimlerde kapsam
        DUSER -> yetmezse Is Yatirim scrape (not: KATALIZOR Asama-2). Momentum LIDERLERI
        (blend'in uygulandigi yer) genelde likit -> kapsam orada yeterli.

        BIRIM: yfinance revenueGrowth kesir (0.15) -> quality_filter yuzde (15) bekler,
        x100 cevrilir. pe = trailingPE HAM (sihirli swap YOK — Analiz test etti: pe>1000
        esigi tutarsizdi + kavramsal yanlisti). trailing dusuk-kar'da yuksek olabilir
        (or. EREGL 577, ROE %0.2) ama bu GERCEK zayifligi yansitir, maskeleme; forward
        projeksiyonu ayri `forward_pe` alaninda, filtre hangisini isterse. NAZIK: ticker
        basina pause + gecici hatada retry."""
        try:
            import yfinance as yf
        except Exception:
            raise RuntimeError("yfinance yok: pip install yfinance")
        if isinstance(tickers, str):
            tickers = [tickers]
        scores = {}
        for t in tickers:
            sym = t if str(t).upper().endswith(".IS") else f"{t}.IS"
            info = None
            for attempt in range(retries + 1):
                try:
                    info = yf.Ticker(sym).info
                    break
                except Exception:
                    if attempt < retries:
                        time.sleep(1.0 * (attempt + 1))
            if not info:
                continue
            pe = info.get("trailingPE")   # HAM trailing; forward ayri alanda (sihirli swap yok)
            pb = info.get("priceToBook")
            rg = info.get("revenueGrowth")
            growth = rg * 100 if isinstance(rg, (int, float)) else None
            td, tc, eb = info.get("totalDebt"), info.get("totalCash"), info.get("ebitda")
            nde = None
            if isinstance(eb, (int, float)) and eb > 0 and isinstance(td, (int, float)):
                nde = round((td - (tc or 0)) / eb, 2)
            key = str(t).split(".")[0].upper()
            scores[key] = {
                "pe": round(pe, 2) if isinstance(pe, (int, float)) else None,
                "pb": round(pb, 2) if isinstance(pb, (int, float)) else None,
                "growth_yoy": round(growth, 1) if growth is not None else None,
                "net_debt_ebitda": nde,
                "period": "yfinance-live",
                # ek (harmansiz ama faydali): forward PE + ROE + kar marji
                "forward_pe": round(info["forwardPE"], 2) if isinstance(info.get("forwardPE"), (int, float)) else None,
                "roe": round(info["returnOnEquity"] * 100, 1) if isinstance(info.get("returnOnEquity"), (int, float)) else None,
            }
            time.sleep(pause)
        return scores

    def save(self, scores: dict, filename: str = "fundamentals.json") -> str:
        os.makedirs(self.state_dir, exist_ok=True)
        path = os.path.join(self.state_dir, filename)
        payload = {"generated_at": datetime.now().isoformat(timespec="seconds"), "scores": scores}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    def get_scores(self, filename: str = "fundamentals.json") -> dict:
        path = os.path.join(self.state_dir, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("scores", {})
        return {}

    @staticmethod
    def quality_filter(scores: dict, max_pe=None, min_growth=None, max_net_debt_ebitda=None) -> set:
        """Temel-saglam isimler kumesi (momentum liderleri ARASINDAN sececek harman filtre)."""
        ok = set()
        for tic, f in scores.items():
            if max_pe is not None and (f.get("pe") is None or f["pe"] > max_pe):
                continue
            if min_growth is not None and (f.get("growth_yoy") is None or f["growth_yoy"] < min_growth):
                continue
            if max_net_debt_ebitda is not None and (f.get("net_debt_ebitda") is None or f["net_debt_ebitda"] > max_net_debt_ebitda):
                continue
            ok.add(tic)
        return ok
