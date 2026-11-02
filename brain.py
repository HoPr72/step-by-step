#!/usr/bin/env python
"""Výměna krajního modulu přihrádek za brain — modul s elektronikou.

    python brain.py "…/Skrin varianta 3 sloupce.stp" "…/s-brainem"

Ze skříně vypadne nejpravější modul přihrádek a plech sloupce, který si brain
nese po svém, a místo nich se vloží brain zarovnaný podle dvou navařovacích
matic nahoře. Nakonec se doplní záslepka do otvoru pro fabku vpravo nahoře;
její polohu určí fabka, která je v obou modelech.

Výsledkem je STEP se zachovanou strukturou i názvy, takže se dá otevřít
v CADu, a k němu nárys a iso.
"""

from __future__ import annotations

import argparse
import os
import sys

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


def vymen(skrin, brain, zaslepka, out):
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
    # jinak by tam stály dva přes sebe. Pozná se podle matic — zarovnává se
    # na ně a zároveň jsou to ty, které brain duplikuje.
    bmatice = dvojice_matic(buzly)
    plechy = jmenem(uzly, PLECH, depth=1)
    sedi = [(p, dvojice_matic(uzly, p)) for p in plechy]
    sedi = [(p, m) for p, m in sedi
            if abs(m[0][0] - bmatice[0][0]) < TOLERANCE
            and abs(m[0][1] - bmatice[0][1]) < TOLERANCE]
    if len(sedi) != 1:
        raise SystemExit(f"matice brainu sedí na {len(sedi)} plechů, čekám jeden")
    plech, smatice = sedi[0]

    delta = posun(bmatice, smatice)

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
    for u in buzly:
        if u["depth"] == 0:
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
            "posun": [round(v, 3) for v in delta], "dilu": sum(u["depth"] == 0 for u in buzly),
            "zaslepka": dzaslepka}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skrin")
    ap.add_argument("outdir")
    ap.add_argument("--brain", help="brain.step; bez něj se hledá vedle skříně")
    ap.add_argument("--zaslepka", help="zaslepka_Fab_kryt.step")
    ap.add_argument("--sirka", type=int, default=1600)
    ap.add_argument("--meritko", type=float, help="px na milimetr, kvůli společné řadě")
    ap.add_argument("--bez-kreseb", action="store_true")
    opts = ap.parse_args()

    def vedle(cesta, jmeno):
        if cesta:
            return cesta
        here = os.path.dirname(os.path.abspath(opts.skrin))
        for _ in range(4):
            kandidat = os.path.join(here, jmeno)
            if os.path.exists(kandidat):
                return kandidat
            here = os.path.dirname(here)
        raise SystemExit(f"nenašel jsem {jmeno}, zadej cestu přepínačem")

    os.makedirs(opts.outdir, exist_ok=True)
    jmeno = os.path.basename(opts.skrin).rsplit(".", 1)[0] + " s brainem.step"
    info = vymen(opts.skrin, vedle(opts.brain, "brain.step"),
                 vedle(opts.zaslepka, "zaslepka_Fab_kryt.step"),
                 os.path.join(opts.outdir, jmeno))

    print(f"{jmeno}  ({os.path.getsize(info['out']) / 1e6:.1f} MB)")
    print(f"  pryč: modul na x {info['modul'][0]:.1f} a plech sloupce na x {info['plech'][0]:.1f}")
    print(f"  brain: {info['dilu']} dílů, posun podle matic {info['posun']} mm")
    print(f"  záslepka: posun podle fabky {info['zaslepka']} mm")
    if opts.bez_kreseb:
        return 0

    import vykres
    for view, pripona in (("zepredu", ""), ("iso", "-iso")):
        png = os.path.join(opts.outdir, stepkit.slugify(info["out"]) + pripona + ".png")
        k = vykres.render(info["out"], png, view=view, width=opts.sirka,
                          scale=opts.meritko, dims=[] if view == "iso" else None)
        print(f"  {os.path.basename(png):<46}{k['px'][0]:>5} ×{k['px'][1]:>5} px"
              f"  (měřítko {k['meritko']:.4f} px/mm)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
