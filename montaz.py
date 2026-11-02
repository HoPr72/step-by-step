#!/usr/bin/env python
"""Zadní pohled s roztečemi děr pro uchycení na zeď (skříně B3).

Na zádech jsou dvě podélné lišty. Každá má nahoře řadu průchozích děr pro
vrut a pod nimi řadu navařených matic. Na zeď se skříň chytá za ty díry,
takže se kótuje jejich rozteč vodorovně a odstup obou lišt svisle.

Díry se nehledají v modelu, ale rovnou v průmětu — díra v rovné stěně se
promítne zase jako kružnice, takže střed vyjde přesně tam, kam se kótuje.

    python montaz.py "Skrin varianta 4 sloupce.stp" zada.png --meritko 0.9519
"""

from __future__ import annotations

import argparse
import math
import sys

import vykres

#: Poloměr průchozí díry pro vrut. Matice v dolní řadě mají 4.35 a nekótují se.
DIRA_R = 4.5

#: O kolik kótovací čára přesahuje obrys tělesa.
ODSTUP = 30.0


def kotovani(polys, circles):
    """Kóty pro uchycení na zeď: rozteče děr v horní liště a odstup obou lišt.

    Vrací seznam pro `vykres.draw`, nebo vyhodí ValueError, když záda nevypadají,
    jak mají — to je lepší než tiše okótovat něco jiného.
    """
    rady = vykres.circle_rows(circles, DIRA_R)
    if len(rady) != 2:
        raise ValueError(f"čekám dvě řady děr ⌀{DIRA_R * 2:.0f}, našel jsem {len(rady)}")
    (_y_h, horni), (_y_d, dolni) = rady
    if len(horni) != len(dolni):
        raise ValueError(f"lišty mají jiný počet děr: {len(horni)} a {len(dolni)}")

    _px0, px1, _py0, py1 = vykres.extent(polys)

    # Vodorovný řetězec nad obrysem: mezi sousedními dírami horní lišty.
    nad = (py1 - horni[0][1]) + ODSTUP
    dims = [(horni[i], horni[i + 1], nad) for i in range(len(horni) - 1)]

    # Svisle u pravého kraje: od pravé díry horní lišty k pravé díře dolní.
    a, b = horni[-1], dolni[-1]
    if abs(a[0] - b[0]) > 0.01:
        raise ValueError(f"pravé díry nejsou nad sebou ({a[0]:.2f} a {b[0]:.2f})")
    dims.append((a, b, (px1 - a[0]) + ODSTUP))
    return dims


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--sirka", type=int, default=1600)
    ap.add_argument("--meritko", type=float, help="px na milimetr")
    ap.add_argument("--pruhledne", action="store_true")
    opts = ap.parse_args()

    polys, bbox, circles = vykres.project(opts.src, "zezadu")
    try:
        dims = kotovani(polys, circles)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    info = vykres.draw(polys, bbox, opts.out, view="zezadu", width=opts.sirka,
                       transparent=opts.pruhledne, scale=opts.meritko, dims=dims)

    print(f"{opts.out}  {info['px'][0]}×{info['px'][1]} px"
          f"  (měřítko {info['meritko']:.4f} px/mm)")
    for a, b, _off in dims:
        smer = "vodorovně" if abs(a[1] - b[1]) < 1e-6 else "svisle  "
        print(f"  {smer} {math.dist(a, b):8.2f} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
