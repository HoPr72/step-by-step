#!/usr/bin/env python
"""Výměna krajního modulu přihrádek za brain — modul s elektronikou.

    python brain.py "…/Skrin varianta 3 sloupce.stp" "…/s-brainem/STEP"
    python brain.py "…/Vykresy PDF revize 3/STEP"    "…/s-brainem/STEP"

Ze skříně vypadne nejpravější modul přihrádek a plech sloupce, který si brain
nese po svém, a místo nich se vloží brain zarovnaný podle dvou navařovacích
matic nahoře. Nakonec se doplní záslepka do otvoru pro fabku vpravo nahoře;
její polohu určí fabka, která je v obou modelech.

Výsledkem je STEP se zachovanou strukturou i názvy, takže se dá otevřít
v CADu. Když se místo souboru zadá adresář, projede se celá řada velikostí.
Kreslí se až potom, `nacrtky.py` nad výstupním adresářem.
"""

from __future__ import annotations

import argparse
import glob
import os

import stepkit
from OCP.collections import Sequence_TDF_Label
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Trsf, gp_Vec

#: Názvy dílů, podle kterých se skládá. Hledá se začátek jména, protože
#: SolidWorks k instancím dopisuje `:1`, `:2` a podobně.
MODUL = "Navrh sloupce skladaci varianty"
PLECH = "Plech sloupce"
MATICE = "Matice M4 navarovaci"
ZASLEPKA = "Kryt_Fabky"
FABKA = "fabka"

#: Jak daleko od sebe smí ležet matice, aby to byl ještě stejný plech.
TOLERANCE = 1.0

#: Díly menší než tolik milimetrů, schované uvnitř největšího tělesa, se do
#: skříně nepřenášejí. Nula nechá brain celý. Výchozích 120 mm vezme celý
#: vnitřek displeje včetně osazené desky (110 mm) a nechá displej (161 mm);
#: mezi těmi dvěma čísly je pohodlná mezera, takže na přesné hodnotě nesejde.
DROBNE = 120.0


# --------------------------------------------------------------------------
# čtení sestavy
# --------------------------------------------------------------------------

def prochazej(st, label, loc=None, parent=None, depth=0):
    """Všechny uzly sestavy, každý už ve světových souřadnicích.

    Poloha se skládá cestou dolů: `GetShape` vrací tvar v soustavě toho,
    kdo ho odkazuje, ne celé sestavy.
    """
    loc = loc or TopLoc_Location()
    target = TDF_Label()
    if st.IsReference_s(label):
        st.GetReferredShape_s(label, target)
        world = loc.Multiplied(st.GetLocation_s(label))
    else:
        target = label
        world = loc
    base = st.GetShape_s(target)
    uzel = {"name": stepkit._name_of(label), "label": label, "base": base,
            "loc": world, "shape": base.Moved(world),
            "parent": parent, "depth": depth}
    yield uzel
    if st.IsAssembly_s(target):
        kids = Sequence_TDF_Label()
        st.GetComponents_s(target, kids)
        for i in range(1, kids.Length() + 1):
            yield from prochazej(st, kids.Value(i), world, uzel, depth + 1)


def nacti(path):
    """(dokument, nástroj, kořeny, uzly). Dokument musí volající držet.

    Kořenů bývá víc: skříň je jedna sestava, ale brain přijde jako plochý
    seznam dílů bez obalu. Hloubka 0 jsou tedy kořeny, 1 jejich komponenty.
    """
    doc, st = stepkit._read_document(path)
    labels = Sequence_TDF_Label()
    st.GetFreeShapes(labels)
    roots = [labels.Value(i) for i in range(1, labels.Length() + 1)]
    if not roots:
        raise SystemExit(f"{os.path.basename(path)}: žádná tělesa")
    uzly = [u for r in roots for u in prochazej(st, r)]
    return doc, st, roots, uzly


def stred(shape):
    lo, hi = stepkit._bbox(shape)
    return [(lo[i] + hi[i]) / 2 for i in range(3)]


def obal(shapes):
    """Obalový kvádr přes víc těles."""
    kvadry = [stepkit._bbox(s) for s in shapes]
    return ([min(k[0][i] for k in kvadry) for i in range(3)],
            [max(k[1][i] for k in kvadry) for i in range(3)])


def jmenem(uzly, zacatek, depth=None):
    out = [u for u in uzly if u["name"].startswith(zacatek)]
    return [u for u in out if depth is None or u["depth"] == depth]


# --------------------------------------------------------------------------
# zarovnání podle matic
# --------------------------------------------------------------------------

def dvojice_matic(uzly, rodic=None):
    """Středy dvou navařovacích matic, seřazené odpředu dozadu."""
    matice = [u for u in jmenem(uzly, MATICE)
              if rodic is None or u["parent"] is rodic]
    stredy = sorted((stred(u["shape"]) for u in matice), key=lambda c: c[1])
    if len(stredy) != 2:
        raise ValueError(f"čekám dvě matice {MATICE!r}, je jich {len(stredy)}")
    return stredy


def posun(odkud, kam):
    """Posun, který přenese jednu dvojici matic na druhou.

    Dvojice matic určuje polohu i natočení, ale tady je obojí stejné —
    ověří se to a počítá se jen rozdíl středů.
    """
    for i in range(2):
        a = [odkud[i][k] - odkud[1 - i][k] for k in range(3)]
        b = [kam[i][k] - kam[1 - i][k] for k in range(3)]
        if max(abs(a[k] - b[k]) for k in range(3)) > TOLERANCE:
            raise ValueError("matice nejsou rozmístěné stejně, samotný posun nestačí")
    return [(kam[0][k] - odkud[0][k] + kam[1][k] - odkud[1][k]) / 2 for k in range(3)]


def drobne(dily, mez):
    """Díly menší než `mez`, schované uvnitř největšího tělesa.

    Vnitřek displeje přišel s jeho modelem a v sestavě skříně nemá co dělat:
    nic z něj není vidět a nese většinu velikosti souboru. Co z krabice
    čouhá ven, zůstává — tam patří i matice, podle kterých se zarovnává,
    takže je žádná mez neodnese.
    """
    kvadry = {id(u): stepkit._bbox(u["shape"]) for u in dily}

    def objem(u):
        lo, hi = kvadry[id(u)]
        return (hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])

    klo, khi = kvadry[id(max(dily, key=objem))]
    out = []
    for u in dily:
        lo, hi = kvadry[id(u)]
        uvnitr = all(lo[i] >= klo[i] - 0.01 and hi[i] <= khi[i] + 0.01 for i in range(3))
        if uvnitr and max(hi[i] - lo[i] for i in range(3)) < mez:
            out.append(u)
    return out


def _overu_misto(buzly, modul, delta, podil=0.9):
    """Brain musí po zarovnání padnout do místa po modulu, ne vedle něj.

    Sloupce vypadají jeden jako druhý, takže špatně vybraný plech by posunul
    brain o celou rozteč a nikde by to nezaskřípalo.
    """
    blo, bhi = obal([u["shape"] for u in buzly if u["depth"] == 0])
    mlo, mhi = stepkit._bbox(modul["shape"])
    prekryv = (min(bhi[0] + delta[0], mhi[0]) - max(blo[0] + delta[0], mlo[0]))
    if prekryv < podil * (mhi[0] - mlo[0]):
        raise SystemExit(f"brain by místo po modulu kryl jen z "
                         f"{max(prekryv, 0) / (mhi[0] - mlo[0]):.0%}, zarovnání nesedí")


def _loc(delta):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*delta))
    return TopLoc_Location(t)


# --------------------------------------------------------------------------
# skládání
# --------------------------------------------------------------------------

def vloz(st, root, uzel, delta, jmeno=None):
    """Díl z jiného dokumentu jako další komponentu kořene."""
    lbl = st.AddShape(uzel["base"], False)
    jmeno = jmeno or uzel["name"]
    TDataStd_Name.Set_s(lbl, TCollection_ExtendedString(jmeno))
    comp = st.AddComponent(root, lbl, _loc(delta).Multiplied(uzel["loc"]))
    TDataStd_Name.Set_s(comp, TCollection_ExtendedString(jmeno))
    return comp


def vymen(skrin, brain, zaslepka, out, mez=DROBNE):
    """Skříň s brainem místo nejpravějšího modulu. Vrací popis toho, co se stalo."""
    doc, st, roots, uzly = nacti(skrin)
    if len(roots) != 1:
        raise SystemExit(f"skříň čekám jako jednu sestavu, kořenů je {len(roots)}")
    root = roots[0]
    bdoc, _bst, _broots, buzly = nacti(brain)
    zdoc, _zst, _zroots, zuzly = nacti(zaslepka)

    moduly = jmenem(uzly, MODUL, depth=1)
    if not moduly:
        raise SystemExit(f"ve skříni není žádný {MODUL!r}")
    modul = max(moduly, key=lambda u: stred(u["shape"])[0])

    # Brain se veze s vlastní verzí plechu sloupce; ten ze skříně musí pryč,
    # jinak by tam stály dva přes sebe. Je to ten u levého kraje vyjímaného
    # modulu — brain si nese jeho kopii na témž místě vůči sobě. Podle matic
    # ho hledat nejde, ve všech sloupcích vypadají stejně.
    plechy = jmenem(uzly, PLECH, depth=1)
    if not plechy:
        raise SystemExit(f"ve skříni není žádný {PLECH!r}")
    kraj = stepkit._bbox(modul["shape"])[0][0]
    plech = min(plechy, key=lambda p: abs(stred(p["shape"])[0] - kraj))

    delta = posun(dvojice_matic(buzly), dvojice_matic(uzly, plech))
    _overu_misto(buzly, modul, delta)

    dily = [u for u in buzly if u["depth"] == 0]
    pryc = {id(u) for u in drobne(dily, mez)} if mez else set()

    # Záslepku umístí fabka, která je v obou modelech.
    fabky = [jmenem(u, FABKA) for u in (zuzly, uzly)]
    if not all(len(f) == 1 for f in fabky):
        raise SystemExit("fabku čekám v obou modelech právě jednou")
    dzaslepka = [round(a - b, 6) for a, b in
                 zip(stred(fabky[1][0]["shape"]), stred(fabky[0][0]["shape"]))]
    kryty = jmenem(zuzly, ZASLEPKA)
    if len(kryty) != 1:
        raise SystemExit(f"{ZASLEPKA!r} čekám jednou, je {len(kryty)}×")

    st.RemoveComponent(modul["label"])
    st.RemoveComponent(plech["label"])
    for u in dily:
        if id(u) not in pryc:
            vloz(st, root, u, delta)
    vloz(st, root, kryty[0], dzaslepka)
    st.UpdateAssemblies()

    writer = STEPCAFControl_Writer()
    writer.SetNameMode(True)
    if not writer.Transfer(doc):
        raise SystemExit("přenos do STEPu selhal")
    writer.Write(out)
    del bdoc, zdoc, doc

    return {"out": out, "modul": stred(modul["shape"]), "plech": stred(plech["shape"]),
            "posun": [round(v, 3) for v in delta], "dilu": len(dily) - len(pryc),
            "drobnych": len(pryc), "zaslepka": dzaslepka}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skrin", help="STEP skříně, nebo adresář s celou řadou")
    ap.add_argument("outdir")
    ap.add_argument("--brain", help="brain.step; bez něj se hledá vedle skříně")
    ap.add_argument("--zaslepka", help="zaslepka_Fab_kryt.step")
    ap.add_argument("--drobne", type=float, default=DROBNE,
                    help=f"pod kolik mm vyhazovat díly schované uvnitř (výchozí {DROBNE:.0f});"
                         " 0 nechá brain celý")
    opts = ap.parse_args()

    if os.path.isdir(opts.skrin):
        files = sorted(glob.glob(os.path.join(opts.skrin, "*.stp"))
                       + glob.glob(os.path.join(opts.skrin, "*.step")))
        if not files:
            raise SystemExit(f"v {opts.skrin} nejsou žádné STEP soubory")
    else:
        files = [opts.skrin]

    def vedle(cesta, jmeno):
        if cesta:
            return cesta
        here = os.path.dirname(os.path.abspath(files[0]))
        for _ in range(4):
            kandidat = os.path.join(here, jmeno)
            if os.path.exists(kandidat):
                return kandidat
            here = os.path.dirname(here)
        raise SystemExit(f"nenašel jsem {jmeno}, zadej cestu přepínačem")

    brain = vedle(opts.brain, "brain.step")
    zaslepka = vedle(opts.zaslepka, "zaslepka_Fab_kryt.step")
    os.makedirs(opts.outdir, exist_ok=True)

    for src in files:
        jmeno = os.path.basename(src).rsplit(".", 1)[0] + " s brainem.step"
        info = vymen(src, brain, zaslepka, os.path.join(opts.outdir, jmeno),
                     mez=opts.drobne)
        print(f"{jmeno}  ({os.path.getsize(info['out']) / 1e6:.1f} MB)")
        print(f"  pryč: modul na x {info['modul'][0]:.1f}"
              f" a plech sloupce na x {info['plech'][0]:.1f}")
        print(f"  brain: {info['dilu']} dílů, posun podle matic {info['posun']} mm"
              f"  (drobných uvnitř vynecháno {info['drobnych']})")
        print(f"  záslepka: posun podle fabky {info['zaslepka']} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
