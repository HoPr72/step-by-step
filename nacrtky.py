#!/usr/bin/env python
"""Všechny náčrtky pro produktové listy B3 najednou, v jednom měřítku.

    python nacrtky.py "…/STEP" "…/nacrtky"

Nárys každé velikosti, k tomu jeden bokorys (hloubka i výška jsou u všech
stejné), iso nejmenší skříně bez kót a zadní pohled s roztečemi pro uchycení
na zeď. Měřítko se spočítá z nejširší skříně a použije se na všechno, takže
se obrázky dají postavit vedle sebe a porovnávat.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import montaz
import stepkit
import vykres


def vyber(files, maska):
    """Soubory podle masky: `vse` všechny, `nic` žádný, jinak právě jeden.

    Bez trefy nebo při dvou končíme — radši chyba než náčrtek z jiné velikosti.
    """
    if maska == "nic":
        return []
    if maska == "vse":
        return files
    hit = [f for f in files if maska.lower() in os.path.basename(f).lower()]
    if len(hit) != 1:
        raise SystemExit(f"maska {maska!r} sedí na {len(hit)} souborů, čekám jeden")
    return hit


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stepdir")
    ap.add_argument("outdir")
    ap.add_argument("--sirka", type=int, default=1600,
                    help="šířka PNG nejširšího nárysu v pixelech")
    ap.add_argument("--meritko", type=float,
                    help="px na milimetr; bez něj se nejširší nárys roztáhne na --sirka")
    ap.add_argument("--iso", default="2 sloupce",
                    help="ze které velikosti udělat iso; také `vse` nebo `nic`")
    ap.add_argument("--bokorys", default="8 sloupce")
    ap.add_argument("--zada", default="4 sloupce")
    opts = ap.parse_args()

    files = sorted(glob.glob(os.path.join(opts.stepdir, "*.stp"))
                   + glob.glob(os.path.join(opts.stepdir, "*.step")))
    if not files:
        raise SystemExit(f"v {opts.stepdir} nejsou žádné STEP soubory")

    print(f"nárysy ({len(files)})")
    infos = vykres.render_set(files, opts.outdir, view="zepredu",
                              width=opts.sirka, scale=opts.meritko)
    scale = infos[0]["meritko"]
    for i in infos:
        print(f"  {os.path.basename(i['out']):<40}{i['px'][0]:>5} ×{i['px'][1]:>5} px"
              f"{i['sirka']:>10.2f} ×{i['vyska']:>8.2f} mm")

    def kresli(src, nazev, view, **kw):
        out = os.path.join(opts.outdir, nazev)
        polys, bbox, _circles = vykres.project(src, view)
        info = vykres.draw(polys, bbox, out, view=view,
                           width=opts.sirka, scale=scale, **kw)
        print(f"  {nazev:<40}{info['px'][0]:>5} ×{info['px'][1]:>5} px")
        return info

    boky = vyber(files, opts.bokorys)
    if boky:
        print("bokorys — u všech velikostí stejný")
    for src in boky:
        nazev = ("skrin-bokorys.png" if len(boky) == 1
                 else stepkit.slugify(src) + "-bokorys.png")
        kresli(src, nazev, "zboku")

    isa = vyber(files, opts.iso)
    if isa:
        print("iso bez kót")
    for src in isa:
        kresli(src, stepkit.slugify(src) + "-iso.png", "iso", dims=[])

    zada = vyber(files, opts.zada)
    if zada:
        print("záda s roztečemi na zeď")
    for src in zada:
        polys, bbox, circles = vykres.project(src, "zezadu")
        out = os.path.join(opts.outdir, stepkit.slugify(src) + "-zada.png")
        try:
            dims = montaz.kotovani(polys, circles)
        except ValueError as exc:
            print(f"  záda nekótuji: {exc}", file=sys.stderr)
            dims = []
        info = vykres.draw(polys, bbox, out, view="zezadu", width=opts.sirka,
                           scale=scale, dims=dims)
        print(f"  {os.path.basename(out):<40}{info['px'][0]:>5} ×{info['px'][1]:>5} px"
              f"   {len(dims)} kót")

    print(f"\nvšechno v měřítku {scale:.4f} px/mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
