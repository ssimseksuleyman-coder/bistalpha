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
    if not normalized.endswith((".xlsx", ".xls")):
        return False
    return (
        ("teknik" in normalized and "takip" in normalized)
        or ("bist" in normalized and "bulten" in normalized)
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
        return FallbackFetcher([EmailFetcher(), FolderFetcher()])
    return FolderFetcher()


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
