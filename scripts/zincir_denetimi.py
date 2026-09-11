"""Zincir denetimi — bir degisikligin SONUC ZINCIRINI koddan cikarir.

NEDEN VAR (2026-09-11): iki gunde alti bagimsiz okuma yapildi, altisi bir sey
buldu, altisinin tetigi de KULLANICIYDI. Denetim yetenegi vardi, denetim ADIMI
yoktu. En pahali iki bulgu ayni sinifti: fırlatilan istisnayi bir ust katman
`except Exception` ile yutuyordu (once shadow.py, sonra daemon.py) — ve bu,
KODDAN OTOMATIK bulunabilir bir seydi. Bu betik onu otomatik bulur.

KULLANIM
  python scripts/zincir_denetimi.py <sembol> [<sembol> ...]
  python scripts/zincir_denetimi.py --degisen        # git diff'teki fonksiyonlar

HER SEMBOL ICIN
  1. cagiran yerler (dosya:satir)
  2. cagri BROAD EXCEPT icinde mi  (`except Exception` / `except:`)
     -> istisna orada YUTULUR; "firlattim" != "ulasti"
  3. o broad except ne yapiyor: yeniden firlatiyor mu (raise) yoksa devam mi

CIKIS KODU: broad-except icinde yutulan cagri varsa 1 (commit ritueli C10 bunu
gormeden gecemez), yoksa 0. Bu bir OLCUM aracidir; hukmu insan verir — ama
hukum verilmeden once olcum GORULMUS olur.
"""
import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATLA = {".git", ".venv", "__pycache__", "local", "node_modules", "deniz_snapshots"}


def _py_dosyalar():
    for kok, dizinler, dosyalar in os.walk(ROOT):
        dizinler[:] = [d for d in dizinler if d not in ATLA]
        for f in dosyalar:
            if f.endswith(".py"):
                yield os.path.join(kok, f)


def _broad_except(handler):
    if handler.type is None:
        return True
    n = handler.type
    return isinstance(n, ast.Name) and n.id in ("Exception", "BaseException")


def _yeniden_firlatir(handler):
    return any(isinstance(x, ast.Raise) for x in ast.walk(handler))


def _cagri_adlari(node):
    """Bir Call icin eslesebilecek adlar: 'load' ve 'pf.load' gibi."""
    f = node.func
    if isinstance(f, ast.Name):
        return {f.id}
    if isinstance(f, ast.Attribute):
        adlar = {f.attr}
        if isinstance(f.value, ast.Name):
            adlar.add(f"{f.value.id}.{f.attr}")
        return adlar
    return set()


def _handler_ozeti(h):
    if h.type is None:
        tip = "bare"
    elif isinstance(h.type, ast.Name):
        tip = h.type.id
    elif isinstance(h.type, ast.Attribute):
        tip = h.type.attr
    elif isinstance(h.type, ast.Tuple):
        tip = "(" + ",".join(getattr(e, "id", getattr(e, "attr", "?")) for e in h.type.elts) + ")"
    else:
        tip = "?"
    return f"{tip}->{'raise' if _yeniden_firlatir(h) else 'yutar'}@{h.lineno}"


def _try_kapsayan(tree):
    """Her Call node'u icin onu kapsayan en ic try'in handler ozetini ver."""
    sonuc = {}

    def gez(node, try_stack):
        if isinstance(node, ast.Try):
            broad = [h for h in node.handlers if _broad_except(h)]
            yeni = try_stack + [(node, broad)]
            for b in node.body:
                gez(b, yeni)
            for h in node.handlers:
                for b in h.body:
                    gez(b, try_stack)
            for b in node.orelse + node.finalbody:
                gez(b, try_stack)
            return
        if isinstance(node, ast.Call):
            sonuc[id(node)] = try_stack[-1] if try_stack else None
        for c in ast.iter_child_nodes(node):
            gez(c, try_stack)

    gez(tree, [])
    return sonuc


def denetle(semboller):
    bulgular = []
    for yol in _py_dosyalar():
        try:
            src = open(yol, encoding="utf-8").read()
            tree = ast.parse(src)
        except Exception:
            continue
        kapsam = _try_kapsayan(tree)
        rel = os.path.relpath(yol, ROOT).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            adlar = _cagri_adlari(node)
            eslesen = adlar & semboller
            if not eslesen:
                continue
            ad = sorted(eslesen, key=len)[-1]          # en nitelikli adi goster
            try_bilgi = kapsam.get(id(node))
            if try_bilgi is None:
                bulgular.append((ad, rel, node.lineno, "acik", ""))
                continue
            _try, broad = try_bilgi
            ozet = " ".join(_handler_ozeti(h) for h in _try.handlers)
            if not broad:
                bulgular.append((ad, rel, node.lineno, "dar-except", ozet))
                continue
            # Herhangi bir handler yeniden firlatiyorsa yutma KESIN degil:
            # hangi tip icin firlattigi ozette gorunur, hukmu insan verir.
            if any(_yeniden_firlatir(h) for h in _try.handlers):
                bulgular.append((ad, rel, node.lineno, "kismi-raise", ozet))
            else:
                bulgular.append((ad, rel, node.lineno, "YUTULUR", ozet))
    return bulgular


def _degisen_semboller():
    """git diff'te dokunulan fonksiyon adlarini cikar (HEAD'e gore calisma agaci + staged)."""
    out = subprocess.run(["git", "diff", "HEAD", "--unified=0", "--", "*.py"],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout
    dosya, semboller = None, set()
    for satir in out.splitlines():
        if satir.startswith("+++ b/"):
            dosya = os.path.join(ROOT, satir[6:])
        elif satir.startswith("@@") and dosya and os.path.exists(dosya):
            # @@ -a,b +c,d @@ -> c'den itibaren hangi fonksiyon
            try:
                hedef = int(satir.split("+")[1].split(",")[0].split()[0])
            except Exception:
                continue
            try:
                tree = ast.parse(open(dosya, encoding="utf-8").read())
            except Exception:
                continue
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        n.lineno <= hedef <= (n.end_lineno or n.lineno):
                    semboller.add(n.name)
    return sorted(semboller)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv == ["--degisen"]:
        semboller = _degisen_semboller()
        if not semboller:
            print("  degisen fonksiyon yok (git diff HEAD bos)")
            return 0
        print("  degisen fonksiyonlar:", ", ".join(semboller))
    else:
        semboller = set(argv)
    b = denetle(set(semboller))
    if not b:
        print("  cagiran bulunamadi:", ", ".join(sorted(semboller)))
        return 0
    yutulan = 0
    print()
    print("  %-22s %-38s %-6s %-20s %s" % ("sembol", "cagiran", "satir", "durum", "not"))
    for ad, rel, ln, durum, notu in sorted(b):
        isaret = "!!" if durum == "YUTULUR" else "  "
        print("%s%-22s %-38s %-6s %-20s %s" % (isaret, ad, rel, ln, durum, notu))
        yutulan += durum == "YUTULUR"
    print()
    if yutulan:
        print(f"  !! {yutulan} cagri BROAD EXCEPT icinde YUTULUYOR — 'firlattim' != 'ulasti'.")
        print("     Her biri icin karar: yeniden firlat, ozel except ekle, ya da bilerek yut (yaz).")
        return 1
    print("  yutulan cagri yok.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
