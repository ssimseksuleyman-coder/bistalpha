"""
EKSİK #5 — Deniz Yatırım bülteni OTOMATİK çekme (manuel değil).

Adapter deseni — kullanıcı kaynağına göre seçer:
  - FolderFetcher : bir klasörü izler, en yeni bülteni otomatik bulur (çalışır)
  - EmailFetcher  : Deniz e-postalarını IMAP ile çeker (kullanıcı kimlik girer)
  - PortalFetcher : Deniz portal/URL'den indirir (kullanıcı URL+oturum girer)

Çekilen bülten parse edilip (deniz.parse_bulletin) günlük snapshot'a yazılır.
"""
import os
import glob
import json
import re
import unicodedata
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from abc import ABC, abstractmethod
from . import config
from . import deniz


def _normalized_name(value):
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).lower()


def _is_bulletin_file(filename):
    normalized = _normalized_name(filename)
    if not normalized.endswith((".xlsx", ".xls", ".pdf")):
        return False
    return (
        ("teknik" in normalized and "takip" in normalized)
        or ("bist" in normalized and "bulten" in normalized)
        or ("bist" in normalized and "teknik" in normalized)
    )


def _filename_date(filename):
    match = re.search(r'(\d{2})[_.\-\s](\d{2})[_.\-\s](\d{4})', filename)
    return (match.group(3), match.group(2), match.group(1)) if match else ("0", "0", "0")


class DenizFetcher(ABC):
    @abstractmethod
    def fetch_latest(self):
        """En yeni bülten dosya yolunu döner (yoksa None)."""
        ...


class FolderFetcher(DenizFetcher):
    """
    Bir klasörü izler — Deniz bültenleri oraya düşürülür (örn e-posta eki,
    indirme klasörü senkronu). En yeni 'Teknik_Takip' xlsx'i otomatik bulur.
    """
    def __init__(self, folder=None):
        self.folder = folder or getattr(config, "DENIZ_FOLDER", "deniz_inbox")

    def fetch_latest(self):
        if not os.path.isdir(self.folder):
            print(f"[deniz_fetcher] Klasör yok: {self.folder}")
            return None
        files = [
            path for path in glob.glob(os.path.join(self.folder, "*"))
            if os.path.isfile(path) and _is_bulletin_file(os.path.basename(path))
        ]
        if not files:
            return None
        # Dosya adındaki tarihe göre en yeni
        def file_date(f):
            return _filename_date(os.path.basename(f))
        return sorted(files, key=file_date)[-1]


class EmailFetcher(DenizFetcher):
    """
    Deniz bülten e-postalarını IMAP ile çeker (Gmail vb.) — ÇALIŞIR.
    config (ENV): IMAP_HOST, IMAP_USER, IMAP_PASS, DENIZ_SENDER
    Gmail için: IMAP_HOST=imap.gmail.com, IMAP_PASS=uygulama_şifresi

    Deniz e-postalarını Gmail'e yönlendir (filtre) -> bu fetcher eki indirir.
    Ücretsiz 7/24 (GitHub Actions) için ideal.
    """
    def __init__(self, save_dir="deniz_inbox"):
        self.save_dir = save_dir

    @staticmethod
    def _decode_filename(value):
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return str(value)

    @staticmethod
    def _normalized(value):
        return _normalized_name(value)

    @classmethod
    def _is_bulletin_attachment(cls, filename):
        return _is_bulletin_file(filename)

    @staticmethod
    def _search_ids(mailbox, sender):
        since = (datetime.now() - timedelta(days=21)).strftime("%d-%b-%Y")
        criteria = ["SINCE", since]
        if sender:
            criteria.extend(["FROM", f'"{sender}"'])
        typ, ids = mailbox.search(None, *criteria)
        if typ == "OK" and ids and ids[0]:
            return ids[0].split()
        return []

    def fetch_latest(self):
        host = getattr(config, "IMAP_HOST", None)
        user = getattr(config, "IMAP_USER", None)
        pw = getattr(config, "IMAP_PASS", None)
        if not (host and user and pw):
            print("[deniz_fetcher] IMAP yapılandırılmamış (IMAP_HOST/USER/PASS)")
            return None
        import imaplib
        import email
        import os
        sender = getattr(config, "DENIZ_SENDER", "")
        os.makedirs(self.save_dir, exist_ok=True)
        try:
            M = imaplib.IMAP4_SSL(host, timeout=15)
            M.login(user, pw)
            M.select("INBOX")
            # Deniz göndericiden, ekli, son e-postalar
            id_list = self._search_ids(M, sender)
            if not id_list and sender:
                print("[deniz_fetcher] Gönderici eşleşmedi; ek adına göre aranıyor")
                id_list = self._search_ids(M, "")
            if not id_list:
                M.logout()
                return None
            # En yeni e-postadan başla
            saved_path = None
            for eid in reversed(id_list[-100:]):
                typ, msg_data = M.fetch(eid, "(RFC822)")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                for part in msg.walk():
                    fn = self._decode_filename(part.get_filename())
                    if self._is_bulletin_attachment(fn):
                        safe_name = os.path.basename(fn).replace("\x00", "").strip()
                        path = os.path.join(self.save_dir, safe_name)
                        with open(path, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        saved_path = path
                        break
                if saved_path:
                    break
            M.logout()
            return saved_path
        except Exception as e:
            print(f"[deniz_fetcher] IMAP hatası: {e}")
            return None



class UrlFetcher(DenizFetcher):
    """DENIZ_URL veya DENIZ_URL_TEMPLATE ile bulteni web/portal URL'sinden indirir."""
    def __init__(self, save_dir="deniz_inbox"):
        self.save_dir = save_dir

    @staticmethod
    def _candidate_urls():
        urls = []
        direct = getattr(config, "DENIZ_URL", None)
        if direct:
            urls.append(direct)
        template = getattr(config, "DENIZ_URL_TEMPLATE", None)
        if template:
            for days_back in range(0, 7):
                dt = datetime.now() - timedelta(days=days_back)
                try:
                    urls.append(template.format(date=dt, yyyy=dt.strftime("%Y"),
                                                mm=dt.strftime("%m"), dd=dt.strftime("%d")))
                except Exception:
                    continue
        return list(dict.fromkeys(urls))

    def fetch_latest(self):
        urls = self._candidate_urls()
        if not urls:
            return None
        import requests
        os.makedirs(self.save_dir, exist_ok=True)
        for url in urls:
            try:
                r = requests.get(url, timeout=25)
                if r.status_code != 200 or not r.content:
                    continue
                name = os.path.basename(url.split("?")[0]) or "deniz_bulten.xlsx"
                if not name.lower().endswith((".xlsx", ".xls")):
                    cd = r.headers.get("content-disposition", "")
                    m = re.search(r'filename="?([^";]+)"?', cd)
                    name = m.group(1) if m else "deniz_bulten.xlsx"
                if not _is_bulletin_file(name):
                    ext = ".pdf" if url.lower().endswith(".pdf") else ".xlsx"
                    name = "Deniz_Yatirim_BIST_Teknik_Takip_Bulteni_" + datetime.now().strftime("%d_%m_%Y") + ext
                path = os.path.join(self.save_dir, os.path.basename(name))
                with open(path, "wb") as f:
                    f.write(r.content)
                return path
            except Exception as e:
                print(f"[deniz_fetcher] URL indirme hatasi: {e}")
        return None

class DenizWebScanner(DenizFetcher):
    """
    Deniz Yatırım /Uploads/ klasörünü paralel HEAD istekleriyle tarar.
    Son bilinen dosya ID'sinden itibaren yeni BIST Teknik Takip Bülteni arar.

    Neden işe yarar:
      Bültenler https://www.denizyatirim.com/Uploads/..._DD.MM.YYYY_NNNNN.pdf
      formatında ardışık ID ile yayınlanır. ID'ler tahmin edilemez ama her gün
      ~5-30 adet artar. 150 ID × son 5 iş günü tarihi = 750 HEAD isteği.
      10 paralel worker ile ~15-30 saniyede tamamlanır.
    """
    _BASE = "https://www.denizyatirim.com/Uploads/"
    _NAME = ("Deniz_Yat_r_m_Strateji_ve_Ara_t_rma_BIST_Teknik_Takip_"
             "B_lteni_{date}_{fid}.pdf")
    _STATE_FILE = os.path.join("deniz_snapshots", "scanner_state.json")

    def __init__(self, save_dir="deniz_inbox", max_scan=150, workers=10):
        self.save_dir = save_dir
        self.max_scan = max_scan
        self.workers = workers

    def _load_state(self):
        if os.path.exists(self._STATE_FILE):
            try:
                with open(self._STATE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_id": 14173}

    def _save_state(self, state):
        import json as _json
        os.makedirs(os.path.dirname(self._STATE_FILE) or ".", exist_ok=True)
        with open(self._STATE_FILE, "w", encoding="utf-8") as f:
            _json.dump(state, f)

    def _workdays(self, n=5):
        """Son n iş gününün DD.MM.YYYY listesi (bugün dahil)."""
        dates, d = [], datetime.now()
        while len(dates) < n:
            if d.weekday() < 5:
                dates.append(d.strftime("%d.%m.%Y"))
            d -= timedelta(days=1)
        return dates

    @staticmethod
    def _head(session, url):
        try:
            r = session.head(url, timeout=4, allow_redirects=True)
            return r.status_code == 200
        except Exception:
            return False

    def fetch_latest(self):
        import requests
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        state = self._load_state()
        last_id = state.get("last_id", 14173)
        dates = self._workdays(5)
        os.makedirs(self.save_dir, exist_ok=True)

        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (compatible; bistalpha)"

        # Tüm (fid, date) kombinasyonlarını paralel dene
        candidates = []
        for fid in range(last_id + 1, last_id + self.max_scan + 1):
            for date_str in dates:
                name = self._NAME.format(date=date_str, fid=fid)
                candidates.append((fid, date_str, self._BASE + name, name))

        found = []
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            fut_map = {ex.submit(self._head, session, url): (fid, name, url)
                       for fid, _, url, name in candidates}
            for fut in as_completed(fut_map):
                fid, name, url = fut_map[fut]
                if fut.result():
                    found.append((fid, name, url))

        if not found:
            print("[deniz_scanner] Yeni bülten bulunamadı")
            return None

        # En küçük ID = en eski (muhtemelen en son bülten günü)
        found.sort(key=lambda x: x[0])
        best_fid, best_name, best_url = found[0]

        try:
            r = session.get(best_url, timeout=30)
            r.raise_for_status()
            path = os.path.join(self.save_dir, best_name)
            with open(path, "wb") as f:
                f.write(r.content)
            state["last_id"] = best_fid
            self._save_state(state)
            print(f"[deniz_scanner] Bülten indirildi: {best_name} (ID {best_fid})")
            return path
        except Exception as e:
            print(f"[deniz_scanner] İndirme hatası: {e}")
            return None


class FallbackFetcher(DenizFetcher):
    def __init__(self, fetchers):
        self.fetchers = fetchers

    def fetch_latest(self):
        for fetcher in self.fetchers:
            path = fetcher.fetch_latest()
            if path:
                return path
        return None


def get_fetcher():
    src = getattr(config, "DENIZ_SOURCE", "folder")
    if src == "email":
        return FallbackFetcher([EmailFetcher(), DenizWebScanner(), FolderFetcher()])
    if src in ("url", "web", "portal"):
        return FallbackFetcher([UrlFetcher(), DenizWebScanner(), FolderFetcher()])
    if src == "scanner":
        return DenizWebScanner()
    # Varsayılan: scanner önce, sonra klasör ve e-posta
    return FallbackFetcher([DenizWebScanner(), FolderFetcher(), EmailFetcher()])


def auto_update(snapshot_dir="deniz_snapshots"):
    """
    En yeni Deniz bültenini otomatik çek, parse et, snapshot kaydet.
    daemon tarafından günlük çağrılır.
    Returns: parse edilmiş bülten dict veya None.
    """
    fetcher = get_fetcher()
    path = fetcher.fetch_latest()
    if not path:
        print("[deniz_fetcher] Yeni bülten bulunamadı")
        return None
    bulletin = deniz.parse_bulletin(path)
    status = deniz.bulletin_status(bulletin)
    if not status.get("fresh"):
        print(
            f"[deniz_fetcher] Bülten eski; snapshot güncellenmedi: "
            f"{bulletin.get('date')} ({status.get('age_days')} gün)"
        )
        return None
    bulletin["source_file"] = os.path.basename(path)
    bulletin["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    deniz.save_snapshot(bulletin, out_dir=snapshot_dir)
    print(f"[deniz_fetcher] Bülten güncellendi: {bulletin['date']} "
          f"({len(bulletin['sector_scores'])} sektör)")
    return bulletin
