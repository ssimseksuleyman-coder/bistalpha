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
from abc import ABC, abstractmethod
from . import config
from . import deniz


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
        files = glob.glob(os.path.join(self.folder, "*Teknik_Takip*.xlsx"))
        if not files:
            return None
        # Dosya adındaki tarihe göre en yeni
        def file_date(f):
            m = re.search(r'(\d{2})_(\d{2})_(\d{4})', os.path.basename(f))
            return (m.group(3), m.group(2), m.group(1)) if m else ("0", "0", "0")
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
            M = imaplib.IMAP4_SSL(host)
            M.login(user, pw)
            M.select("INBOX")
            # Deniz göndericiden, ekli, son e-postalar
            crit = f'(FROM "{sender}")' if sender else '(ALL)'
            typ, ids = M.search(None, crit)
            id_list = ids[0].split()
            if not id_list:
                M.logout()
                return None
            # En yeni e-postadan başla
            saved_path = None
            for eid in reversed(id_list[-10:]):
                typ, msg_data = M.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                for part in msg.walk():
                    fn = part.get_filename()
                    if fn and "Teknik_Takip" in fn and fn.endswith(".xlsx"):
                        path = os.path.join(self.save_dir, fn)
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


def get_fetcher():
    src = getattr(config, "DENIZ_SOURCE", "folder")
    if src == "email":
        return EmailFetcher()
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
    deniz.save_snapshot(bulletin, out_dir=snapshot_dir)
    print(f"[deniz_fetcher] Bülten güncellendi: {bulletin['date']} "
          f"({len(bulletin['sector_scores'])} sektör)")
    return bulletin
