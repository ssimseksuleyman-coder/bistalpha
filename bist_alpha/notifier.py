"""
EKSİK #2 — Otomatik bildirim: e-posta + Telegram.

Çalışan kod. Kullanıcı sadece config'e kimlik bilgilerini girer:
  - E-posta: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_TO
  - Telegram: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from . import config


def send_email(subject, body, to=None):
    """SMTP ile e-posta gönderir. config'de SMTP_* tanımlı olmalı."""
    host = getattr(config, "SMTP_HOST", None)
    if not host:
        print("[notifier] SMTP yapılandırılmamış — e-posta atlandı")
        return False
    msg = MIMEMultipart()
    msg["From"] = config.SMTP_USER
    msg["To"] = to or config.MAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP(host, getattr(config, "SMTP_PORT", 587)) as srv:
            srv.starttls()
            srv.login(config.SMTP_USER, config.SMTP_PASS)
            srv.send_message(msg)
        print(f"[notifier] E-posta gönderildi: {subject}")
        return True
    except Exception as e:
        print(f"[notifier] E-posta hatası: {e}")
        return False


def send_telegram(text):
    """Telegram bot ile mesaj gönderir. config'de TELEGRAM_* tanımlı olmalı."""
    token = getattr(config, "TELEGRAM_TOKEN", None)
    chat_id = getattr(config, "TELEGRAM_CHAT_ID", None)
    if not token or not chat_id:
        print("[notifier] Telegram yapılandırılmamış — atlandı")
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Telegram mesaj limiti 4096 karakter
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=10)
        print("[notifier] Telegram gönderildi")
        return True
    except Exception as e:
        print(f"[notifier] Telegram hatası: {e}")
        return False


def notify_all(subject, body):
    """Hem e-posta hem Telegram'a gönderir (yapılandırılmış olanlar)."""
    e = send_email(subject, body)
    t = send_telegram(f"{subject}\n\n{body}")
    return {"email": e, "telegram": t}
