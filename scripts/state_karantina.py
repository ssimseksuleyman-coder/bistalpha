"""P0.4 karantina operator araci — INSAN cagirir, daemon/shadow ASLA.

NEDEN VAR (2026-09-11 bagimsiz okuma): `reset_state` ve `release_quarantine`
yazildi, "bir insan cagirir" dendi, ama cagiracak arac verilmedi. Bir ariza
aninda operatorun Python acip fonksiyon cagirmasi gerekiyordu — bekcisiz
kurtarma yolu. Bu betik o yolun operasyonel yarisidir.

KULLANIM
  python scripts/state_karantina.py status                    # bes hesabin durumu
  python scripts/state_karantina.py release F                 # dosya ELLE onarildi, marker'i kaldir
  python scripts/state_karantina.py reset F --reason "..."    # eskiyi arsivle, sifirla (GEREKCE ZORUNLU)

GUVENLIK
  - reset gerekce olmadan CALISMAZ (portfolio.reset_state ValueError atar).
  - reset once mevcut dosyayi committable adla ARSIVLER; kanit kaybolmaz.
  - Her iki eylem de yalniz portfolios/ altina yazar; F motoruna dokunmaz.
  - Sonrasinda `git add -f portfolios/ && git commit && git push` INSANIN isidir:
    arsiv + yeni state + marker degisikligi origin'e insan eliyle gider.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bist_alpha import portfolio as pf  # noqa: E402

HESAPLAR = ["F", "A", "B", "O", "G1"]


def cmd_status(args):
    sd = args.state_dir
    print(f"  state_dir: {sd}")
    for acc in HESAPLAR:
        q = pf.quarantine_status(acc, sd)
        p = pf._path(acc, sd)
        if not q and not os.path.exists(p):
            print(f"  {acc:3s} YOK        dosya da marker da yok (yeni hesap? -> init_state)")
            continue
        if q:
            print(f"  {acc:3s} KARANTINA  {q.get('status'):10s} {str(q.get('at'))[:19]}  {str(q.get('detail'))[:60]}")
            continue
        try:
            s = pf.load(acc, sd)
            print(f"  {acc:3s} ok         cash={s['cash']:.4f} pozisyon={len(s['positions'])} "
                  f"history={len(s.get('history', []))}")
        except pf.StateQuarantined as e:
            print(f"  {acc:3s} KARANTINA  {e.status:10s} (marker simdi yazildi)  {e.detail[:60]}")
        except Exception as e:
            print(f"  {acc:3s} HATA       {type(e).__name__}: {str(e)[:60]}")
    return 0


def cmd_release(args):
    vardi = pf.release_quarantine(args.account, args.state_dir)
    print(f"  {args.account}: marker {'kaldirildi' if vardi else 'zaten yoktu'}")
    try:
        s = pf.load(args.account, args.state_dir)
        print(f"  dogrulama: yuklendi, cash={s['cash']:.4f} pozisyon={len(s['positions'])}")
        print("  SONRAKI ADIM: git add -f portfolios/ && git commit -m '...' && git push")
        return 0
    except pf.StateQuarantined as e:
        print(f"  !! dosya HALA bozuk ({e.status}: {e.detail[:60]}) — marker yeniden yazildi.")
        print("     Ya dosyayi onar, ya `reset` kullan.")
        return 1


def cmd_reset(args):
    print(f"  {args.account}: mevcut dosya arsivlenecek, YENI default yazilacak.")
    print(f"  gerekce: {args.reason}")
    if not args.yes:
        cevap = input("  Devam? (evet yazin): ").strip().lower()
        if cevap != "evet":
            print("  iptal"); return 2
    state, arsiv = pf.reset_state(args.account, args.reason, args.state_dir)
    print(f"  arsiv : {arsiv}")
    print(f"  yeni  : cash={state['cash']} pozisyon=0 history[0].event={state['history'][0]['event']}")
    print("  SONRAKI ADIM: git add -f portfolios/ && git commit -m 'reset: ...' && git push")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state-dir", default=os.path.join(ROOT, "portfolios"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    r = sub.add_parser("release"); r.add_argument("account", choices=HESAPLAR)
    s = sub.add_parser("reset"); s.add_argument("account", choices=HESAPLAR)
    s.add_argument("--reason", required=True)
    s.add_argument("--yes", action="store_true", help="onay sorma (script kullanimi)")
    a = ap.parse_args(argv)
    return {"status": cmd_status, "release": cmd_release, "reset": cmd_reset}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
