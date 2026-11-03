#!/usr/bin/env python
"""Render modelu přes Blender: materiály, měkké světlo, stín na zeď.

    python render.py "GK3_v5.step" render.png --celo=-Z --nahoru=+X

Model se promění v síť trojúhelníků, postaví se k zdi podle toho, jak leží,
dostane materiály podle názvů těles a vyrenderuje se v Cycles. Blender běží
na pozadí, nic se neotevírá na obrazovce.

Kamera se zadává úhly, ne souřadnicemi: `--azimut` je odklon od čelního
pohledu doprava, `--elevace` výška nad vodorovnou. Kosoúhlý pohled jako
v perokresbách je 45° a 35°.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

import stepkit
import vykres

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
SCENA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_scena.py")

#: Jemnost sítě pro render. Pro prohlížeč stačí 0,3 mm, tady by byla
#: zaoblení vidět jako fasety.
ODCHYLKA = 0.05
UHLOVA = 0.2

#: Název tělesa → materiál. Hledá se podřetězec, první trefa platí.
#: Co se netrefí, je plech.
PODLE_JMENA = (("body", "lak"), ("display", "sklo"))
VYCHOZI = "nerez"


def materialy(cerna: float, drsnost: float, svit: float, textura: str | None) -> dict:
    """Popis materiálů pro scénu. Černá se zadává jako lineární odrazivost.

    Matný lak není nula — úplná čerň se na obrázku chová jako díra, protože
    nemá co odrážet. Skutečný černý lak odráží kolem čtyř procent světla
    a právě ta troška dělá tvar.
    """
    return {
        "lak": {"barva": [cerna, cerna, cerna * 1.06], "drsnost": drsnost,
                "kov": 0.0, "odlesk": 0.5},
        "sklo": {"barva": [cerna * 0.35, cerna * 0.35, cerna * 0.4],
                 "drsnost": 0.07, "kov": 0.0, "odlesk": 0.6},
        "nerez": {"barva": [0.55, 0.56, 0.57], "drsnost": 0.28, "kov": 1.0},
        "obrazovka": {"barva": [0.01, 0.01, 0.012], "drsnost": 0.12, "kov": 0.0,
                      "textura": textura, "svit": svit},
    }


def material_pro(jmeno: str) -> str:
    cil = jmeno.lower()
    for kus, mat in PODLE_JMENA:
        if kus in cil:
            return mat
    return VYCHOZI


# --------------------------------------------------------------------------
# jak model leží → soustava scény
# --------------------------------------------------------------------------

def zaklad(celo, nahoru):
    """Osy scény v souřadnicích modelu: doprava, do hloubky, nahoru.

    Kamera stojí v -Y a dívá se na čelo, takže čelo míří do -Y a zeď je
    vzadu v +Y.
    """
    vpravo = np.cross(nahoru, celo)
    dozadu = -np.asarray(celo, dtype=float)
    return np.array([vpravo, dozadu, nahoru], dtype=float)


def preved(body, baze, posun=None, meritko=0.001):
    """Body modelu do scény: otočit, zmenšit na metry, posunout."""
    out = np.asarray(body, dtype=float).reshape(-1, 3) @ baze.T * meritko
    return out if posun is None else out + posun


# --------------------------------------------------------------------------
# plocha displeje
# --------------------------------------------------------------------------

def plocha_displeje(shape, celo, tolerance=0.05):
    """Největší rovná plocha koukající dopředu — tam přijde obrázek.

    Vrací obalový kvádr plochy v souřadnicích modelu. Hledá se geometricky,
    aby to nestálo na tom, jak kdo pojmenoval plochy v CADu.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    nejlepsi = None
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face(ex.Current())
        ad = BRepAdaptor_Surface(face)
        if ad.GetType() == GeomAbs_Plane:
            d = ad.Plane().Axis().Direction()
            n = np.array([d.X(), d.Y(), d.Z()])
            if face.Orientation() == TopAbs_REVERSED:
                n = -n
            if float(n @ np.array(celo, dtype=float)) > 1 - tolerance:
                p = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, p)
                if nejlepsi is None or p.Mass() > nejlepsi[0]:
                    nejlepsi = (p.Mass(), stepkit._bbox(face))
        ex.Next()
    return None if nejlepsi is None else nejlepsi[1]


def rohy_obrazovky(kvadr, baze, posun, odsazeni=2e-5):
    """Čtyři rohy obdélníku ve scéně, od levého dolního proti směru hodin."""
    lo, hi = kvadr
    body = np.array([[x, y, z] for x in (lo[0], hi[0])
                     for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    p = preved(body, baze, posun)
    x0, x1 = p[:, 0].min(), p[:, 0].max()
    z0, z1 = p[:, 2].min(), p[:, 2].max()
    y = p[:, 1].min() - odsazeni            # kousek před plochu, ať se nehádají
    return [[x0, y, z0], [x1, y, z0], [x1, y, z1], [x0, y, z1]]


# --------------------------------------------------------------------------
# scéna
# --------------------------------------------------------------------------

def kamera(rozmer, opts):
    """Kam kameru postavit, aby model padl do záběru.

    Vzdálenost plyne z obalové koule a zorného úhlu objektivu — s delším
    sklem se couvá dál a perspektiva je mírnější, přesně jako ve skutečnosti.
    """
    polomer = float(np.linalg.norm(rozmer) / 2)
    uhly = [2 * math.atan(opts.senzor / (2 * opts.objektiv))]
    uhly.append(2 * math.atan(math.tan(uhly[0] / 2) * opts.vyska / opts.sirka))
    vzdalenost = polomer / math.tan(min(uhly) / 2) * opts.zaber

    az, el = math.radians(opts.azimut), math.radians(opts.elevace)
    smer = np.array([math.sin(az) * math.cos(el),
                     -math.cos(az) * math.cos(el),
                     math.sin(el)])
    cil = np.array([0.0, -rozmer[1] / 2, opts.cil * rozmer[2]])
    return {"kde": list(cil + smer * vzdalenost), "cil": list(cil),
            "objektiv": opts.objektiv, "senzor": opts.senzor}


def svetla(rozmer, opts):
    """Velká měkká světla. Velikost zdroje dělá měkkost stínu, ne jeho síla."""
    r = float(max(rozmer))
    cil = [0, -rozmer[1] / 2, 0]
    return [
        {"jmeno": "klic", "kde": [-2.2 * r, -3.0 * r, 2.4 * r], "kam": cil,
         "rozmer": [4 * r, 4 * r], "vykon": opts.klic},
        {"jmeno": "vypln", "kde": [3.0 * r, -2.6 * r, 0.2 * r], "kam": cil,
         "rozmer": [5 * r, 5 * r], "vykon": opts.vypln},
        {"jmeno": "strop", "kde": [0.0, -1.2 * r, 4.5 * r], "kam": cil,
         "rozmer": [6 * r, 6 * r], "vykon": opts.strop},
    ]


def scena(src, out, opts):
    """Celý popis scény i se sítěmi. Vrací (cesta k json, cesta k npz)."""
    celo, nahoru = vykres.osa(opts.celo), vykres.osa(opts.nahoru)
    baze = zaklad(celo, nahoru)

    doc, solids = stepkit._collect(src)
    site, dily, displej = {}, [], None
    for i, solid in enumerate(solids):
        verts, tris = stepkit._triangulate(solid["shape"], opts.odchylka, UHLOVA)
        klic = f"d{i}"
        site[klic + "v"] = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
        site[klic + "t"] = np.asarray(tris, dtype=np.int32).reshape(-1, 3)
        mat = material_pro(solid["name"])
        dily.append({"klic": klic, "jmeno": solid["name"] or klic, "material": mat})
        if displej is None and opts.displej.lower() in solid["name"].lower():
            displej = solid["shape"]

    # Model se postaví zády ke zdi a vystředí se na šířku i na výšku.
    vse = np.vstack([site[d["klic"] + "v"] for d in dily])
    p = preved(vse, baze)
    lo, hi = p.min(axis=0), p.max(axis=0)
    posun = np.array([-(lo[0] + hi[0]) / 2, -hi[1], -(lo[2] + hi[2]) / 2])
    for d in dily:
        site[d["klic"] + "v"] = (preved(site[d["klic"] + "v"], baze, posun)
                                 .astype(np.float32))
    rozmer = hi - lo

    obrazovka = None
    if displej is not None and opts.obrazek:
        kvadr = plocha_displeje(displej, celo)
        if kvadr is not None:
            obrazovka = {"rohy": rohy_obrazovky(kvadr, baze, posun)}
    del doc

    popis = {
        "dily": dily,
        "materialy": materialy(opts.cerna, opts.drsnost, opts.svit,
                               os.path.abspath(opts.obrazek) if opts.obrazek else None),
        "obrazovka": obrazovka,
        "zed": {"kde": 5e-4, "rozmer": float(max(rozmer)) * 12,
                "barva": [opts.zed, opts.zed, opts.zed * 1.02], "drsnost": 0.85},
        "kamera": kamera(rozmer, opts),
        "svetla": svetla(rozmer, opts),
        "svet": {"barva": [0.55, 0.57, 0.6], "sila": opts.obloha},
        "render": {"sirka": opts.sirka, "vyska": opts.vyska, "vzorky": opts.vzorky,
                   "expozice": opts.expozice, "transform": opts.transform,
                   "out": os.path.abspath(out)},
    }
    return popis, site, rozmer


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--celo", default="-Y")
    ap.add_argument("--nahoru", default="+Z")
    ap.add_argument("--azimut", type=float, default=30.0,
                    help="odklon kamery od čela doprava ve stupních")
    ap.add_argument("--elevace", type=float, default=23.5,
                    help="výška kamery nad vodorovnou ve stupních")
    ap.add_argument("--objektiv", type=float, default=85.0, help="ohnisko v mm")
    ap.add_argument("--senzor", type=float, default=36.0, help="šířka snímače v mm")
    ap.add_argument("--zaber", type=float, default=1.08, help="rezerva kolem modelu")
    ap.add_argument("--cil", type=float, default=0.0,
                    help="o kolik výšky modelu zvednout bod, kam se kamera dívá")
    ap.add_argument("--sirka", type=int, default=1400)
    ap.add_argument("--vyska", type=int, default=1750)
    ap.add_argument("--vzorky", type=int, default=160)
    ap.add_argument("--odchylka", type=float, default=ODCHYLKA)
    ap.add_argument("--cerna", type=float, default=0.007,
                    help="lineární odrazivost černého laku; nula je díra")
    ap.add_argument("--drsnost", type=float, default=0.42, help="matnost laku")
    ap.add_argument("--zed", type=float, default=0.8)
    ap.add_argument("--obloha", type=float, default=0.40)
    ap.add_argument("--klic", type=float, default=14.0)
    ap.add_argument("--vypln", type=float, default=5.0)
    ap.add_argument("--strop", type=float, default=8.0)
    ap.add_argument("--svit", type=float, default=1.6, help="jas displeje")
    ap.add_argument("--obrazek", help="co ukazuje displej")
    ap.add_argument("--displej", default="display", help="název tělesa s obrazovkou")
    ap.add_argument("--expozice", type=float, default=-0.4)
    ap.add_argument("--transform", default="AgX", choices=("AgX", "Standard", "Filmic"))
    opts = ap.parse_args()

    if not os.path.exists(BLENDER):
        raise SystemExit(f"Blender nenalezen: {BLENDER}")

    popis, site, rozmer = scena(opts.src, opts.out, opts)
    tri = sum(len(site[k]) for k in site if k.endswith("t"))
    print(f"{os.path.basename(opts.src)}: {len(popis['dily'])} těles, "
          f"{tri} trojúhelníků, "
          f"{rozmer[0] * 1000:.0f} × {rozmer[2] * 1000:.0f} × {rozmer[1] * 1000:.0f} mm")
    print(f"  kamera: azimut {opts.azimut:.0f}°, elevace {opts.elevace:.0f}°, "
          f"{opts.objektiv:.0f} mm, odstup "
          f"{np.linalg.norm(np.array(popis['kamera']['kde'])) * 1000:.0f} mm")
    if popis["obrazovka"]:
        r = np.array(popis["obrazovka"]["rohy"])
        print(f"  obrazovka: {(r[1][0] - r[0][0]) * 1000:.1f} × "
              f"{(r[2][2] - r[1][2]) * 1000:.1f} mm")

    with tempfile.TemporaryDirectory(prefix="render-") as tmp:
        npz, js = os.path.join(tmp, "sit.npz"), os.path.join(tmp, "scena.json")
        np.savez(npz, **site)
        popis["sit"] = npz
        with open(js, "w", encoding="utf-8") as fh:
            json.dump(popis, fh)
        hotovo = subprocess.run(
            [BLENDER, "--background", "--python", SCENA, "--", js],
            capture_output=True, text=True)
    for radek in hotovo.stdout.splitlines():
        if radek.startswith(("HOTOVO", "GPU nevyšlo", "Fra:")) or "Error" in radek:
            print(f"  {radek}")
    if hotovo.returncode:
        print(hotovo.stderr[-2000:], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
