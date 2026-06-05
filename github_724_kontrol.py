#!/usr/bin/env python3
import configparser
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED_SECRETS = [
    "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO",
    "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID",
    "IMAP_HOST", "IMAP_USER", "IMAP_PASS", "DENIZ_SENDER",
]


def ok(msg):
    print(f"OK  - {msg}")


def warn(msg):
    print(f"YOK - {msg}")


def main():
    missing = []
    wf = ROOT / ".github" / "workflows" / "bist-alpha.yml"
    if wf.exists():
        text = wf.read_text(encoding="utf-8", errors="ignore")
        ok("workflow dosyasi var: .github/workflows/bist-alpha.yml")
        if "schedule:" in text and "cron:" in text:
            ok("cron zamanlari var: 09:45 / 14:30 / 18:30 TR")
        else:
            warn("workflow cron schedule eksik")
            missing.append("workflow cron")
        if "DATA_SOURCE: yahoo" in text:
            ok("GitHub Actions canli veri icin DATA_SOURCE=yahoo kullanacak")
        else:
            warn("workflow DATA_SOURCE=yahoo icermiyor")
            missing.append("DATA_SOURCE=yahoo")
        if "permissions:" in text and "contents: write" in text and "git push" in text:
            ok("state kaliciligi icin contents:write + git push var")
        else:
            warn("state commit/push ayari eksik")
            missing.append("state commit/push")
    else:
        warn("workflow dosyasi yok")
        missing.append("workflow")

    git_config = ROOT / ".git" / "config"
    if git_config.exists():
        cfg = configparser.ConfigParser()
        cfg.read(git_config, encoding="utf-8")
        remotes = [s for s in cfg.sections() if s.startswith('remote ')]
        github_remotes = []
        for section in remotes:
            url = cfg.get(section, "url", fallback="")
            if "github.com" in url:
                github_remotes.append(url)
        if github_remotes:
            ok("GitHub remote tanimli: " + github_remotes[0])
        else:
            warn("GitHub remote yok; bilgisayar kapaliyken 7/24 henuz aktif degil")
            missing.append("GitHub remote/push")
    else:
        warn(".git klasoru yok; repo GitHub'a yuklenmemis")
        missing.append("GitHub repo")

    print("\nGitHub Actions secrets kontrolu:")
    print("Not: GitHub secrets uzaktan okunamaz; burada sadece bu bilgisayardaki ENV var/yok kontrol edilir.")
    local_missing = [key for key in REQUIRED_SECRETS if not os.environ.get(key)]
    for key in REQUIRED_SECRETS:
        if key in local_missing:
            warn(f"{key} ENV yok / GitHub secret olarak eklenmeli")
        else:
            ok(f"{key} ENV mevcut")
    if local_missing:
        missing.append("GitHub Actions secrets")

    print("\nSONUC:")
    if missing:
        print("7/24 dosya altyapisi hazir, fakat bulutta aktif olmak icin eksik var:")
        for item in missing:
            print(f" - {item}")
        print("\nGitHub'da repo olusturup bu klasoru push et; sonra Settings > Secrets and variables > Actions altina secrets ekle.")
        return 1
    print("7/24 GitHub Actions kurulumu aktif gorunuyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
