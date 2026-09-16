"""KAPANIS/SLOT MUHUR OLCUMU (2026-09-11 plani; C1 denetimiyle sertlestirildi 2026-09-15).

Salt-okuma: origin'den (git) ve Actions API'den okur; repo dosyasina yazmaz, push etmez.
`python scripts/kapanis_muhur_olc.py [--tarih 2026-09-14] [--slot acilis|gunici|kapanis]`

Dokuz alan, hepsi HAM kaynak (ozet degil):
  1 precise/bist-alpha kosumu adim duzeyi        (Actions API, hedef tarihe kadar SAYFALI;
                                                  gun = created_at TR = ICRA gunu, niyet degil)
  2 state commit MESAJI etiketi                  (git log; committer saati %cI -> TR, sinirlar +03:00)
  3 docs/state/run_trace.json                    (git show; P0.5 oncesi yoksa YOK = olculdu)
  4 portfolios/*.json bugunku stop olayi + load  (git show + pf.load gecici dizinde)
  5 CAPRAZ: SLOT-ONCESI gozlemci breach == daemon stop satislari (slot claim'inden onceki son
                                                  snapshot; hesap semasi: F-sinifi history, G1 trades[])
  6 dashboard shadow_cycle.accounts current_source / stop_unchecked / value_unpriced
  7 report_runs :slot sent_at
  8 liveness run_trace uyesi
  9 panel: raw run_trace.json HTTP durumu

DENETIM KILITLERI (C1 incelemesi):
  * git HATASI != YOKLUK: `show_required` yoklukta da hatada da RAISE; `show_optional`
    yalniz gercek yoklukta None (`git ls-tree` gecerli ref + bos cikti), hatada RAISE.
  * `sh()` check=True: donus kodu/stderr YUTULMAZ.
  * fetch basarisiz -> olcum DURUR (eski origin'le devam edilmez).
  * local HEAD != origin/main -> olcum DURUR (pf.load yerel koddan gelir; ayrisma = yanlis kod).
  * kosum listesi per_page ile SAYFALANIR, hedef tarihten eski kosum gorunene kadar;
    sayfa siniri/bos liste ile hedefe ULASILAMAZSA RAISE (bos liste != 'kosum yok').
  * --tarih gecmis gunse [2][3][4][5][6][7][8] o gunun SON origin commit'inden okunur
    (`hedef_ref`, nokta-zamanli); bugun ise origin/main. Gelecek tarih RAISE.
Cikti: her alan icin OLCUM satiri; hukum KURMAZ.
"""
import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = ZoneInfo("Europe/Istanbul")
REPO = "ssimseksuleyman-coder/bistalpha"
REF = "origin/main"


class OlcumHatasi(RuntimeError):
    """git/API arizasi: yokluk DEGIL, olcum yapilamadi."""


def sh(*a, check=True):
    r = subprocess.run(a, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    if check and r.returncode != 0:
        raise OlcumHatasi(f"{' '.join(a)} -> rc={r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def _var_mi(path, ref=REF):
    """True/False = olculdu; ref gecersizse RAISE (hata != yokluk)."""
    out = sh("git", "ls-tree", ref, "--", path)     # gecersiz ref -> rc 128 -> raise
    return bool(out.strip())


def show_optional(path, ref=REF):
    if not _var_mi(path, ref):
        return None
    raw = sh("git", "show", f"{ref}:{path}")
    return json.loads(raw)                            # bozuk JSON -> raise (olculdu-bozuk != yok)


def show_required(path, ref=REF):
    if not _var_mi(path, ref):
        raise OlcumHatasi(f"{ref}:{path} YOK — bu artefakt zorunlu, olcum duruyor")
    return json.loads(sh("git", "show", f"{ref}:{path}"))


def api(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "kapanis-olc"})
    return json.load(urllib.request.urlopen(req, timeout=45))


def tr(iso):
    return _dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TR)


def _uyum_kontrol(head, origin):
    if head != origin:
        raise OlcumHatasi(f"local HEAD {head[:12]} != {REF} {origin[:12]} -> olcum DURDU (once rebase/checkout)")


def hedef_ref(tarih, bugun=None, sh=sh):
    """NOKTA-ZAMANLI REF (C1 incelemesi #2): hedef gun bugunse origin/main; gecmisse o gunun
    SON origin commit'i (TR gun sonu). Boylece run_trace/dashboard/gozlemci/liveness hepsi
    ayni andan okunur; 'Actions 09-14, artefakt 09-15' karisimi olmaz. Bulunamazsa RAISE."""
    bugun = bugun or _dt.datetime.now(TR).strftime("%Y-%m-%d")
    if tarih == bugun:
        return REF
    if tarih > bugun:
        raise OlcumHatasi(f"hedef tarih gelecekte: {tarih}")
    sha = sh("git", "rev-list", "-1", f"--before={tarih}T23:59:59+03:00", REF).strip()
    if not sha:
        raise OlcumHatasi(f"{tarih} gun sonuna kadar origin commit'i yok — gecmis muhur olculemez")
    return sha


def gun_commitleri(ref, gun, sh=sh):
    """Hedef TR gununun commit'leri: [(HH:MM TR, kisa sha, mesaj)]. ZAMAN EKSENI (inceleme #3):
    %cI (committer ISO, kendi ofsetiyle) okunur ve tr() ile TR'ye cevrilir — `--date=format`
    commit'in kendi ofsetinde basar (Actions commit'leri UTC: 379da56 '15:47' yazardi, TR 18:47).
    since/until sinirlari da ACIK +03:00 ile verilir (makine saat dilimine bagli degil)."""
    out = sh("git", "log", ref, "--format=%h|%cI|%s",
             f"--since={gun}T00:00:00+03:00", f"--until={gun}T23:59:59+03:00")
    rows = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        sha, ciso, msg = ln.split("|", 2)
        rows.append((tr(ciso).strftime("%H:%M"), sha, msg))
    return rows


def hesap_satislari(st, gun):
    """Hedef gunun olaylari ve STOP satislari, HESAP SEMASINA gore (C1-ek, 2026-09-16 canli kaniti):
      F/A/B/O : history[date==gun] -> event=='stop' ya da trades[reason=='stop']
      G1      : `trades[]` duz liste (history'de yalniz cold_start) -> date==gun, SELL, reason=='stop'
    Eski surum yalniz history okuyordu -> G1 IEYHO satisi 'olay=0 stop=0' gorunmustu.
    Donus: {'olay': n, 'stop': [ticker...], 'detay': [str...]}"""
    olay, stop, detay = 0, [], []
    for h in st.get("history") or []:
        if str(h.get("date", ""))[:10] != gun:
            continue
        olay += 1
        for t in h.get("trades") or []:
            # reason=='stop' ya da event=='stop' girisinde reason YAZILMAMIS SELL; acik baska reason (rebalance) stop degil
            if t.get("reason") == "stop" or (h.get("event") == "stop" and t.get("type") == "SELL" and not t.get("reason")):
                stop.append(t.get("ticker")); detay.append(f"{h.get('event')} {json.dumps(t, ensure_ascii=False)[:120]}")
    for t in st.get("trades") or []:                       # G1 semasi
        if str(t.get("date", ""))[:10] != gun:
            continue
        olay += 1
        if t.get("type") == "SELL" and t.get("reason") == "stop":
            stop.append(t.get("ticker")); detay.append(f"trades[] {json.dumps(t, ensure_ascii=False)[:120]}")
    return {"olay": olay, "stop": sorted(set(stop)), "detay": detay}


def slot_baslangici(ref, gun, slot, sh=sh):
    """Hedef gun+slot'un DAEMON BASLANGIC ANI = o slotun `report claim <slot> run <id>` commit'inin
    committer zamani (claim daemon'dan hemen once, kalici). Yoksa None (uydurulmaz)."""
    out = sh("git", "log", ref, "--format=%H|%cI|%s", f"--grep=^report claim {slot} run",
             f"--since={gun}T00:00:00+03:00", f"--until={gun}T23:59:59+03:00")
    for ln in out.splitlines():
        if ln.strip():
            return ln.split("|", 2)[1]                        # en yeni claim (git log sirasi)
    return None


def _state_yukle(sha, acc):
    """origin'deki portfoy dosyasini gecici dizine alip pf.load ile yukler; dizin silinir.
    Karantina = olculemedi (OlcumHatasi), sessiz traceback degil."""
    sys.path.insert(0, ROOT)
    from bist_alpha import portfolio as pf
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, f"portfolio_{acc}.json"), "w", encoding="utf-8").write(
            sh("git", "show", f"{sha}:portfolios/portfolio_{acc}.json"))
        try:
            return pf.load(acc, state_dir=tmp)
        except pf.StateQuarantined as e:
            raise OlcumHatasi(f"{acc}@{sha[:12]} KARANTINA status={e.status} -> slot satisi olculemedi")


def sonraki_claim(ref, gun, t0, sh=sh):
    """t0'dan sonraki ILK claim commit'inin (herhangi bir slot) committer zamani; yoksa None."""
    out = sh("git", "log", ref, "--reverse", "--format=%cI", "--grep=^report claim ",
             f"--since={t0}", f"--until={gun}T23:59:59+03:00")
    for ln in out.splitlines():
        if ln.strip() and ln.strip() != t0:
            return ln.strip()
    return None


def slot_satislari(ref, gun, t0, sh=sh, yukle=_state_yukle, hesaplar=("F", "A", "B", "O", "G1")):
    """BU SLOTUN daemon'unun kitapladigi stop satislari = (slot state commit'indeki gunun satislari)
    − (claim'den onceki son portfoy commit'indekiler). Gun-bazli sayim slotlar arasi sizdirir:
    2026-09-16 acilis muhru kapanistaki IEYHO satisini 'acilis satisi' saymisti (FARKLI).
    'sonra' penceresi SONRAKI CLAIM ile sinirlidir (oz-okuma bulgusu): bu slotun daemon'u portfoy
    commit'i yazmadiysa ayni gunun sonraki slotunun commit'i bu slota atfedilmez -> None.
    Donus: {acc: [ticker...]} ya da None (bu slot penceresinde portfoy commit'i yok = OLCULEMEDI)."""
    once = sh("git", "log", ref, "-1", "--format=%H", f"--before={t0}", "--", "portfolios/").strip()
    ust = sonraki_claim(ref, gun, t0, sh=sh) or f"{gun}T23:59:59+03:00"
    sonra = sh("git", "log", ref, "--reverse", "--format=%H", f"--since={t0}",
               f"--until={ust}", "--", "portfolios/").split()
    if not sonra:
        return None
    out = {}
    for acc in hesaplar:
        s_sonra = set(hesap_satislari(yukle(sonra[0], acc), gun)["stop"])
        s_once = set(hesap_satislari(yukle(once, acc), gun)["stop"]) if once else set()
        out[acc] = sorted(s_sonra - s_once)
    return out


def satis_oncesi_gozlemci(ref, before_iso, sh=sh):
    """Slot baslangicindan ONCE commit edilmis SON gozlemci snapshot'inin SHA'si. 'Sondan ikinci'
    DEGIL: sonraki ek kosumlar ([NO_RUN], gunici) snapshot'i ilerletir — 2026-09-16'da 12:08Z
    G1 breach'i boyle ucuncuye dusup sahte ESIT uretmisti."""
    out = sh("git", "log", ref, f"--before={before_iso}", "-1", "--format=%H", "--", "docs/state/stop_observer.json")
    return out.strip() or None


# [1] icin gun secimi: Actions `created_at` (icra ani) TR'ye cevrilip hedef gunle karsilastirilir.
# Kosumun NIYET ettigi slot/gun API'den okunmaz (cron ifadesi vs gecikme) -> etiket acik.
KOSUM_GUN_ETIKETI = "created_at_TR / niyet(slot) bilinmiyor"


def kosumlar_sayfali(wf, tarih, api=api, per_page=100, max_page=10):
    """Hedef tarihten (YYYY-MM-DD, created_at TR gunu — icra gunu, niyet degil) ESKI bir kosum
    gorunene kadar sayfalar; o gunun tum kosumlarini dondurur. Hedefe ulasilamazsa (sayfa
    siniri / bos liste) RAISE — bos liste 'kosum yok' demek DEGILDIR (C1 incelemesi #5)."""
    out = []
    eski_var = False
    for page in range(1, max_page + 1):
        d = api(f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/runs?per_page={per_page}&page={page}")
        runs = d.get("workflow_runs") or []
        if not runs:
            break
        for x in runs:
            g = tr(x["created_at"]).strftime("%Y-%m-%d")
            if g == tarih:
                out.append(x)
            elif g < tarih:
                eski_var = True
        if eski_var:
            break
    if not eski_var:
        raise OlcumHatasi(f"{wf}: {tarih} gununden eski kosum {max_page} sayfada gorunmedi — liste TAMAMLANMADI, 'yok' denemez")
    return sorted(out, key=lambda z: z["created_at"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tarih", default=_dt.datetime.now(TR).strftime("%Y-%m-%d"))
    ap.add_argument("--slot", default="kapanis")
    a = ap.parse_args()
    gun = a.tarih
    print(f"OLCUM SAATI {_dt.datetime.now(TR):%Y-%m-%d %H:%M} TR | hedef {gun}:{a.slot}")
    sh("git", "fetch", "-q", "origin", "main")        # basarisiz -> raise, eski origin'le devam YOK
    head = sh("git", "rev-parse", "HEAD").strip(); origin = sh("git", "rev-parse", REF).strip()
    print(f"origin/main {origin[:12]} | local HEAD {head[:12]}")
    _uyum_kontrol(head, origin)
    ref = hedef_ref(gun)
    print("artefakt ref: " + (ref if ref == REF else ref[:12] + " (" + gun + " gun sonu, nokta-zamanli)"))

    print(f"\n[1] SCHEDULE KOSUMLARI — gun secimi {KOSUM_GUN_ETIKETI} (sayfali; adim duzeyi yalniz is yapanlar icin)")
    for wf in ("precise.yml", "bist-alpha.yml"):
        for x in kosumlar_sayfali(wf, gun):
            if x.get("event") != "schedule":
                continue
            c, u = tr(x["created_at"]), tr(x["updated_at"])
            print(f"  {wf:15s} {c:%H:%M}->{u:%H:%M} TR {x['status']:<11} {x['conclusion'] or '-':<9} trigger_sha={x['head_sha'][:7]} run={x['id']}")
            if (u - c).total_seconds() > 120 and x["status"] == "completed":
                for j in api(x["jobs_url"])["jobs"]:
                    adimlar = [s for s in j["steps"] if s["conclusion"] != "skipped" and not s["name"].startswith(("Set up", "Post ", "Complete", "Run actions"))]
                    print("     " + " | ".join(f"{s['name'][:28]}={s['conclusion']}" for s in adimlar))

    print("\n[2] STATE COMMIT MESAJLARI (hedef gun TR, committer saati TR'ye cevrilmis, origin) — P0.5 etiketi")
    for saat, sha, msg in gun_commitleri(ref, gun):
        if msg.startswith("state ") or msg.startswith("precise state ") or msg.startswith("report claim "):
            if msg.startswith("report claim "):
                etiket = "(claim commit — etiket beklenmez; daemon'dan ONCE, kalici sahiplik)"
            else:
                etiket = msg[msg.rfind("["):] if "[" in msg else "(ETIKET YOK — P0.5 oncesi kod)"
            ln = f"{sha} {saat} TR {msg}"
            print(f"  {ln[:66]:<66} -> {etiket}")

    print("\n[3] docs/state/run_trace.json (" + ("origin/main" if ref == REF else ref[:12]) + ")")
    rt = show_optional("docs/state/run_trace.json", ref=ref)
    if rt is None:
        print("  YOK (olculdu: dosya origin'de yok — P0.5 kodu henuz bir uretici kosum bitirmedi)")
    else:
        for k in ("slot", "status", "phase", "sha", "sha_source", "run_id", "workflow", "started_at", "ended_at", "error", "phases"):
            print(f"  {k:12s} {rt.get(k)!r}")

    print("\n[4] PORTFOYLER: hedef gunun olaylari + pf.load (origin kopyasi, gecici dizin)")
    sys.path.insert(0, ROOT)
    from bist_alpha import portfolio as pf
    tmp = tempfile.mkdtemp()
    satislar = {}
    for acc in ("F", "A", "B", "O", "G1"):
        raw = sh("git", "show", f"{ref}:portfolios/portfolio_{acc}.json")
        open(os.path.join(tmp, f"portfolio_{acc}.json"), "w", encoding="utf-8").write(raw)
        try:
            st = pf.load(acc, state_dir=tmp)
            hs = hesap_satislari(st, gun)                    # sema-farkindalikli (G1 trades[] dahil)
            satislar[acc] = hs["stop"]
            print(f"  {acc:2s} load OK poz={len(st.get('positions') or {})} olay={hs['olay']} stop={len(hs['stop'])}"
                  + (" -> " + "; ".join(hs["detay"]) if hs["stop"] else ""))
        except pf.StateQuarantined as e:
            print(f"  {acc:2s} KARANTINA status={e.status} detail={e.detail}")
    agac = sh("git", "ls-tree", "--name-only", ref, "portfolios/")
    print("  .quarantine.json origin'de:", [l for l in agac.splitlines() if "quarantine" in l] or "YOK")

    print("\n[5] CAPRAZ: SLOT-ONCESI gozlemci breach == daemon stop satislari")
    so = show_required("docs/state/stop_observer.json", ref=ref)
    print(f"  son gozlemci {so.get('generated_at')} gate={(so.get('gate') or {}).get('verdict')} breach={so.get('breach')}")
    t0 = slot_baslangici(ref, gun, a.slot)
    prev_sha = satis_oncesi_gozlemci(ref, t0) if t0 else None
    if t0 is None:
        print(f"  {gun}:{a.slot} claim commit'i yok -> slot baslangici OLCULEMEDI, capraz kurulmadi (P0.5 oncesi ya da slot kosmadi)")
    elif prev_sha is None:
        print(f"  claim {t0} oncesinde gozlemci snapshot'i yok — capraz OLCULEMEDI")
    else:
        prev = show_required("docs/state/stop_observer.json", ref=prev_sha)
        br = sorted((acc, r.get("ticker")) for acc, rows in (prev.get("accounts") or {}).items() for r in (rows if isinstance(rows, list) else []) if r.get("breached"))
        ss = slot_satislari(ref, gun, t0)                  # yalniz BU slotun kitapladigi satislar
        print(f"  slot claim {t0} | ONCEKI gozlemci {prev.get('generated_at')} @{prev_sha[:12]} breach: {br or 'bos'}")
        if ss is None:
            print("  claim sonrasi portfoy commit'i yok -> bu slotun satisi OLCULEMEDI (daemon state yazmadi?)")
        else:
            sat = sorted((acc, tk) for acc, tks in ss.items() for tk in tks)
            if a.slot == "kapanis":
                print(f"  bu slotun stop satisi: {sat or 'bos'} -> {'ESIT' if br == sat else 'FARKLI'} (P1.6 canli on-kaniti, n kucuk)")
            else:
                print(f"  bu slotun stop satisi: {sat or 'bos'} | beklenen: bos (stop degerlendirmesi yalniz kapanis, #0l)"
                      f" -> {'BEKLENEN' if not sat else 'BEKLENMEYEN SATIS'}; breach listesi bilgi amacli, kiyas kapanista")

    print("\n[6] dashboard.json shadow_cycle.accounts + positions.current_source")
    d = show_required("docs/state/dashboard.json", ref=ref)
    print(f"  timestamp={d.get('timestamp')} source={d.get('source')} price_count={d.get('price_count')}")
    sc = ((d.get("shadow_cycle") or {}).get("accounts") or {})
    for acc, v in (d.get("accounts") or {}).items():
        pos = v.get("positions") or []
        pos = pos if isinstance(pos, list) else list(pos.values())
        srcs = {}
        for p in pos:
            srcs[str(p.get("current_source"))] = srcs.get(str(p.get("current_source")), 0) + 1
        r = sc.get(acc) or {}
        print(f"  {acc:2s} current_source={srcs} | stop_trades={r.get('stop_trades')!r} stop_unchecked={r.get('stop_unchecked')!r} value_unpriced={r.get('value_unpriced')!r}")

    print("\n[7] report_runs.json")
    rr = show_required("docs/state/report_runs.json", ref=ref)
    sent = rr.get("sent") or {}
    k = f"{gun}:{a.slot}"
    print(f"  {k}: {sent.get(k) or 'YOK (olculdu: gonderilmedi/isaretlenmedi)'}")

    print("\n[8] liveness.json run_trace + report_coverage")
    lv = show_required("docs/state/liveness.json", ref=ref)
    print(f"  verdict={lv.get('verdict')}")
    for r in lv.get("checks") or []:
        if r.get("name") in ("run_trace", "report_coverage"):
            print(f"  {r['name']:16s} {r.get('status')} | {(r.get('reason') or '')[:110]}")

    print("\n[9] panelin okudugu ham kaynak")
    try:
        code = urllib.request.urlopen(f"https://raw.githubusercontent.com/{REPO}/main/docs/state/run_trace.json", timeout=30).status
    except urllib.error.HTTPError as e:
        code = e.code
    print(f"  raw run_trace.json HTTP {code}")
    print("\nHUKUM YOK — alanlar plan (1)-(9) ile karsilastirilir.")


if __name__ == "__main__":
    try:
        main()
    except OlcumHatasi as e:
        print(f"\nOLCUM DURDU: {e}", file=sys.stderr)
        sys.exit(2)
