#!/usr/bin/env python
"""Příkazová řádka nad stepkit.

    python cli.py rozmery "dil.step"                 tabulka těles do terminálu
    python cli.py png     "dil.step" nahled.png      technický render, 4 pohledy
    python cli.py vykres  "dil.step" list.png        perokresba s kótami
    python cli.py sada    vystup/ "a.step" "b.step"  perokresby v jednom měřítku
    python cli.py json    vystup/ "a.step" "b.step"  data pro webový prohlížeč
"""

from __future__ import annotations

import json
import os
import sys

import stepkit


def cmd_rozmery(args: list[str]) -> int:
    if not args:
        print("chybí soubor", file=sys.stderr)
        return 1
    for path in args:
        solids = stepkit.read_solids(path)
        gmin = [min(s["min"][i] for s in solids) for i in range(3)]
        gmax = [max(s["max"][i] for s in solids) for i in range(3)]
        print("=" * 78)
        print(f"{os.path.basename(path)}  —  {len(solids)} těles")
        print("  celek: " + " × ".join(f"{gmax[i] - gmin[i]:.2f}" for i in range(3)) + " mm")
        print(f"  objem: {sum(s['volume'] for s in solids):.1f} cm³")
        print(f"  {'název':<30}{'X':>9}{'Y':>9}{'Z':>9}{'cm³':>10}")
        for s in solids:
            x, y, z = s["size"]
            print(f"  {s['name'][:29]:<30}{x:>9.2f}{y:>9.2f}{z:>9.2f}{s['volume']:>10.2f}")
    return 0


def cmd_png(args: list[str]) -> int:
    if len(args) < 2:
        print("použití: png <soubor.step> <vystup.png>", file=sys.stderr)
        return 1
    from build123d import Vector, import_step
    from PIL import Image, ImageDraw

    src, out = args[0], args[1]
    views = [("ISO", (1, -1, 1)), ("ZEPŘEDU", (0, -1, 0)),
             ("ZBOKU", (1, 0, 0)), ("SHORA", (0, 0, 1))]
    W, H, PAD = 520, 420, 26

    shape = import_step(src)
    bb = shape.bounding_box()
    span = max(bb.size.X, bb.size.Y, bb.size.Z)
    shape = shape.translate(-bb.center())

    def polyline(edge, n=28):
        try:
            return [(p.X, p.Y) for p in (edge @ (i / n) for i in range(n + 1))]
        except Exception:
            return []

    def draw(visible, hidden):
        pts = [p for poly in visible + hidden for p in poly]
        img = Image.new("RGB", (W, H), "white")
        if not pts:
            return img
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sx = (max(xs) - min(xs)) or 1
        sy = (max(ys) - min(ys)) or 1
        k = min((W - 2 * PAD) / sx, (H - 2 * PAD) / sy)
        ox = (W - sx * k) / 2 - min(xs) * k
        oy = (H - sy * k) / 2 + max(ys) * k
        dr = ImageDraw.Draw(img)
        for poly in hidden:
            xy = [(x * k + ox, oy - y * k) for x, y in poly]
            for i in range(0, len(xy) - 1, 2):
                dr.line([xy[i], xy[i + 1]], fill=(190, 195, 205), width=1)
        for poly in visible:
            dr.line([(x * k + ox, oy - y * k) for x, y in poly],
                    fill=(20, 24, 33), width=2, joint="curve")
        return img

    sheet = Image.new("RGB", (W * 2, H * 2), "white")
    pen = ImageDraw.Draw(sheet)
    for i, (label, direction) in enumerate(views):
        origin = Vector(*direction).normalized() * (span * 6)
        up = (0, 0, 1) if abs(direction[2]) < 0.99 else (0, 1, 0)
        vis, hid = shape.project_to_viewport(viewport_origin=origin,
                                             viewport_up=up, look_at=(0, 0, 0))
        tile = draw([polyline(e) for e in vis], [polyline(e) for e in hid])
        px, py = (i % 2) * W, (i // 2) * H
        sheet.paste(tile, (px, py))
        pen.text((px + 12, py + 10), label, fill=(120, 128, 140))
        pen.rectangle([px, py, px + W - 1, py + H - 1], outline=(222, 226, 232))
    sheet.save(out)
    print(f"{out}  ({bb.size.X:.1f} × {bb.size.Y:.1f} × {bb.size.Z:.1f} mm)")
    return 0


def cmd_vykres(args: list[str]) -> int:
    import argparse

    import vykres

    ap = argparse.ArgumentParser(prog="cli.py vykres", description="perokresba s kótami")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--pohled", default="zepredu", choices=sorted(vykres.VIEWS))
    ap.add_argument("--sirka", type=int, default=1600, help="šířka PNG v pixelech")
    ap.add_argument("--meritko", type=float,
                    help="px na milimetr; bez něj se kresba roztáhne na --sirka")
    ap.add_argument("--pruhledne", action="store_true", help="průhledné pozadí")
    opts = ap.parse_args(args)

    info = vykres.render(opts.src, opts.out, view=opts.pohled, width=opts.sirka,
                         transparent=opts.pruhledne, scale=opts.meritko)
    print(f"{opts.out}  {info['px'][0]}×{info['px'][1]} px"
          f"  (měřítko {info['meritko']:.4f} px/mm)")
    print(f"  kóty: šířka {info['sirka']:.2f} mm, výška {info['vyska']:.2f} mm"
          f"  (hloubka {info['hloubka']:.2f} mm nekótovaná)")
    print(f"  viditelných hran: {info['hran']}")
    return 0


def cmd_sada(args: list[str]) -> int:
    import argparse

    import vykres

    ap = argparse.ArgumentParser(prog="cli.py sada",
                                 description="perokresby celé řady v jednom měřítku")
    ap.add_argument("outdir")
    ap.add_argument("src", nargs="+")
    ap.add_argument("--pohled", default="zepredu", choices=sorted(vykres.VIEWS))
    ap.add_argument("--sirka", type=int, default=1600,
                    help="šířka PNG nejširšího kusu v pixelech")
    ap.add_argument("--pruhledne", action="store_true", help="průhledné pozadí")
    opts = ap.parse_args(args)

    infos = vykres.render_set(opts.src, opts.outdir, view=opts.pohled,
                              width=opts.sirka, transparent=opts.pruhledne)
    for info in infos:
        print(f"  {os.path.basename(info['out'])[:40]:<42}"
              f"{info['px'][0]:>5} ×{info['px'][1]:>5} px"
              f"{info['sirka']:>10.2f} ×{info['vyska']:>8.2f} mm")
    print(f"\n{len(infos)} kreseb v měřítku {infos[0]['meritko']:.4f} px/mm")
    return 0


def cmd_json(args: list[str]) -> int:
    if len(args) < 2:
        print("použití: json <vystupni_adresar> <soubor.step> ...", file=sys.stderr)
        return 1
    outdir, sources = args[0], args[1:]
    os.makedirs(outdir, exist_ok=True)
    index = []
    for path in sources:
        try:
            data = stepkit.to_viewer_json(path)
        except Exception as exc:
            print(f"  CHYBA {os.path.basename(path)}: {exc}", file=sys.stderr)
            continue
        key = stepkit.slugify(path)
        target = os.path.join(outdir, key + ".json")
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        kb = os.path.getsize(target) / 1024
        index.append({"key": key, "file": data["file"],
                      "n": len(data["solids"]), "size": data["size"], "kb": round(kb)})
        print(f"  {data['file'][:44]:<46}{len(data['solids']):>4} těles{kb:>8.0f} kB")
    with open(os.path.join(outdir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False)
    print(f"\ncelkem {len(index)} modelů, {sum(i['kb'] for i in index)} kB")
    return 0


COMMANDS = {"rozmery": cmd_rozmery, "png": cmd_png,
            "vykres": cmd_vykres, "sada": cmd_sada, "json": cmd_json}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        return 1
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
