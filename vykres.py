"""Perokresba ze STEPu: pravoúhlý průmět s kótami do PNG.

Projekce je rovnoběžná, bez perspektivy — okraje tělesa tedy odpovídají
skutečným rozměrům a dají se přímo okótovat. Kreslí se jen viditelné hrany,
schované se zahazují.

Kreslí se do několikanásobně většího plátna, které se na konci zmenší;
PIL totiž čáry nevyhlazuje a bez toho jsou šikmé hrany zubaté.

Průmět je to pomalé, samotná kresba skoro nic. Proto jsou oddělené: celá řada
velikostí se dá promítnout napřed a nakreslit až ve společném měřítku, které
je známé teprve ze všech kusů najednou.
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

#: Kolikrát větší plátno se kreslí, než je výsledek.
SUPERSAMPLE = 4

#: Pohled → (odkud se kouká, co je nahoře, osy modelu ve vodorovném a svislém
#: směru). Bez os se nedá automaticky kótovat — u kosoúhlého pohledu žádná
#: hrana obrázku neodpovídá rozměru tělesa.
VIEWS = {
    "zepredu": ((0, -1, 0), (0, 0, 1), ("X", "Z")),
    "zezadu": ((0, 1, 0), (0, 0, 1), ("X", "Z")),
    "zboku": ((1, 0, 0), (0, 0, 1), ("Y", "Z")),
    "shora": ((0, 0, 1), (0, 1, 0), ("X", "Y")),
    "iso": ((1, -1, 1), (0, 0, 1), None),
}

FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

INK = (20, 24, 33)          # hrany tělesa
DIM_INK = (20, 24, 33)      # kóty — tenčí čárou, jak je ve výkresu zvykem


def _font(px: int):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def _mm(value: float) -> str:
    """Kóta na celé milimetry nahoru, ať rozměr nikdy nepodstřelíme.

    Tolerance pohlídá případ, kdy je rozměr celé číslo a vyjde jako
    1500.0000000001 — bez ní by z toho byla kóta o milimetr větší.
    """
    return str(math.ceil(value - 1e-6))


def _round_up(value: float, step: int) -> int:
    """Nahoru na násobek `step`, s tolerancí na zbytky z plovoucí čárky."""
    return int(math.ceil(value / step - 1e-9)) * step


def _view(name: str):
    try:
        return VIEWS[name]
    except KeyError:
        raise ValueError(f"neznámý pohled {name!r}, čekám {'/'.join(VIEWS)}") from None


# --------------------------------------------------------------------------
# měřítko a rozvržení
# --------------------------------------------------------------------------

def _metrics(width: int) -> dict:
    """Rozměry prvků kresby v pixelech zvětšeného plátna.

    Drží poměr k nominální šířce obrázku, ať to sedí v každé velikosti.
    V sadě se počítají ze stejné šířky pro všechny kusy, takže čáry i popisky
    mají napříč řadou stejnou tloušťku — i když je každá kresba jinak široká.
    """
    u = width * SUPERSAMPLE / 1600.0
    font_px = max(10, int(27 * u))
    g = {
        "u": u,
        "margin": 40 * u,
        "gap": 11 * u,          # mezera mezi měřeným místem a vynášecí čárou
        "offset": 56 * u,       # odstup kótovací čáry od tělesa
        "over": 13 * u,         # přesah vynášecí čáry za kótovací
        "arrow": 15 * u,
        "arrow_half": 5 * u,
        "font_px": font_px,
        "text_gap": 8 * u,
        "edge": max(1, int(2.4 * u)),
        "thin": max(1, int(1.2 * u)),
    }
    return g


def fit_scale(width: int, span_mm: float) -> float:
    """Měřítko v px/mm, při kterém kresba široká `span_mm` vyplní `width` pixelů.

    Počítá s tím, že kóta výšky ukousne vlevo pruh na kótovací čáru i popisek.
    """
    g = _metrics(width)
    band = g["offset"] + g["text_gap"] + g["font_px"]
    return (width * SUPERSAMPLE - 2 * g["margin"] - band) / SUPERSAMPLE / span_mm


# --------------------------------------------------------------------------
# průmět
# --------------------------------------------------------------------------

def project(src: str, view: str):
    """Průmět tělesa: lomené čáry, obalový kvádr a kružnice.

    Kružnice se vracejí zvlášť i se středem a poloměrem — v rovině průmětu,
    takže se na ně dá rovnou kótovat, aniž by se cokoli přepočítávalo zpátky
    do modelu. Díra v rovné stěně se promítne zase jako kružnice.
    """
    from build123d import Vector, import_step

    direction, up, _axes = _view(view)
    shape = import_step(src)
    bbox = shape.bounding_box()
    shape = shape.translate(-bbox.center())

    span = max(bbox.size.X, bbox.size.Y, bbox.size.Z)
    origin = Vector(*direction).normalized() * (span * 8)
    visible, _hidden = shape.project_to_viewport(
        viewport_origin=origin, viewport_up=up, look_at=(0, 0, 0))

    polys, circles = [], []
    for edge in visible:
        kind = str(edge.geom_type).upper()
        try:
            n = 2 if kind.endswith("LINE") else 48
            polys.append([(p.X, p.Y) for p in (edge @ (i / (n - 1)) for i in range(n))])
            if kind.endswith("CIRCLE"):
                c, r = edge.arc_center, edge.radius
                # Jen celé kružnice: oblouček na hraně zaoblení není díra.
                if abs(edge.length - 2 * math.pi * r) < 0.01:
                    circles.append({"c": (c.X, c.Y), "r": r})
        except Exception:
            continue
    return polys, bbox, circles


def circle_rows(circles, radius: float, tol: float = 0.05):
    """Kružnice daného poloměru po vodorovných řadách, v řadě zleva doprava.

    Vrací [(y, [(x, y), ...]), ...] odshora dolů. Stejné středy se slučují —
    průmět vrátí soustřednou kružnici za každou plochu, kterou díra protne.
    """
    picked = [c for c in circles if abs(c["r"] - radius) <= tol]
    rows: dict[float, dict] = {}
    for c in picked:
        x, y = c["c"]
        key = next((k for k in rows if abs(k - y) <= tol), y)
        rows.setdefault(key, {})[round(x, 3)] = (x, y)
    return [(y, sorted(pts.values())) for y, pts in sorted(rows.items(), reverse=True)]


def extent(polys):
    """Obdélník, do kterého se průmět vejde: (x0, x1, y0, y1)."""
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), max(xs), min(ys), max(ys)


# --------------------------------------------------------------------------
# kóty
# --------------------------------------------------------------------------

def _arrow(dr, tip, vec, length, half, fill):
    """Plná šipka hrotem v `tip`, tělem ve směru `vec` (jednotkový)."""
    bx, by = tip[0] + vec[0] * length, tip[1] + vec[1] * length
    nx, ny = -vec[1], vec[0]
    dr.polygon([tip, (bx + nx * half, by + ny * half), (bx - nx * half, by - ny * half)],
               fill=fill)


def _rotated_text(img, center, text, font, fill):
    """Svislý popisek, čitelný zprava — tedy otočený o 90° proti směru hodin."""
    left, top, right, bottom = font.getbbox(text)
    tile = Image.new("RGBA", (right - left + 4, bottom - top + 4), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((2 - left, 2 - top), text, font=font, fill=fill)
    tile = tile.rotate(90, expand=True, resample=Image.BICUBIC)
    img.paste(tile, (int(center[0] - tile.width / 2), int(center[1] - tile.height / 2)), tile)


def _dim(a, b, off, to_px, k, g, font, dr=None, img=None):
    """Jedna kóta mezi body `a` a `b`, zadanými v milimetrech průmětu.

    `off` je odstup kótovací čáry od měřené, taky v milimetrech; znaménko volí
    stranu — u vodorovné kóty nahoru, u svislé doprava. Popisek sedí podle
    normy vždy nad vodorovnou čárou a vlevo od svislé, ať je kóta kdekoli.

    Vrací obdélník, který kóta na plátně zabere. Bez `dr` jen počítá: rozvržení
    plátna musí znát obrys dřív, než je kam kreslit.
    """
    vodorovna = abs(a[1] - b[1]) <= 1e-6
    if not vodorovna and abs(a[0] - b[0]) > 1e-6:
        raise ValueError("kóta musí být vodorovná nebo svislá")

    ax, ay = to_px(a)
    bx, by = to_px(b)
    text = _mm(math.dist(a, b))
    tl, tt, tr, tb = font.getbbox(text)
    tw, th = tr - tl, tb - tt
    gap, over, text_gap = g["gap"], g["over"], g["text_gap"]

    if vodorovna:
        yd = ay - off * k                      # v pixelech roste y dolů
        d = 1 if yd > ay else -1               # směr od měřeného místa ke kótovací čáře
        x0, x1 = min(ax, bx), max(ax, bx)
        cx = (ax + bx) / 2
        if dr is not None:
            for x in (ax, bx):
                dr.line([(x, ay + d * gap), (x, yd + d * over)], fill=DIM_INK, width=g["thin"])
            dr.line([(x0, yd), (x1, yd)], fill=DIM_INK, width=g["thin"])
            _arrow(dr, (x0, yd), (1, 0), g["arrow"], g["arrow_half"], DIM_INK)
            _arrow(dr, (x1, yd), (-1, 0), g["arrow"], g["arrow_half"], DIM_INK)
            dr.text((cx, yd - text_gap), text, font=font, fill=DIM_INK, anchor="ms")
        return (min(x0, cx - tw / 2), min(ay, yd + d * over, yd - text_gap - g["font_px"]),
                max(x1, cx + tw / 2), max(ay, yd + d * over))

    xd = ax + off * k
    d = 1 if xd > ax else -1
    y0, y1 = min(ay, by), max(ay, by)
    cx, cy = xd - text_gap - g["font_px"] / 2, (ay + by) / 2
    if dr is not None:
        for y in (ay, by):
            dr.line([(ax + d * gap, y), (xd + d * over, y)], fill=DIM_INK, width=g["thin"])
        dr.line([(xd, y0), (xd, y1)], fill=DIM_INK, width=g["thin"])
        _arrow(dr, (xd, y0), (0, 1), g["arrow"], g["arrow_half"], DIM_INK)
        _arrow(dr, (xd, y1), (0, -1), g["arrow"], g["arrow_half"], DIM_INK)
        _rotated_text(img, (cx, cy), text, font, DIM_INK)
    # po otočení má popisek šířku `th` a výšku `tw`
    return (min(ax, xd + d * over, cx - th / 2), min(y0, cy - tw / 2),
            max(ax, xd + d * over), max(y1, cy + tw / 2))


# --------------------------------------------------------------------------
# kresba
# --------------------------------------------------------------------------

def draw(polys, bbox, out: str, view: str = "zepredu", width: int = 1600,
         transparent: bool = False, scale: float | None = None,
         dims=None) -> dict:
    """Hotový průmět na papír.

    `scale` je v px na milimetr. Bez něj se kresba roztáhne na `width` pixelů —
    s ním `width` určuje už jen tloušťku čar a velikost písma a plátno se
    přizpůsobí kresbě.

    `dims` je seznam kót `(a, b, odstup)` v milimetrech průmětu. Výchozí `None`
    okótuje šířku dole a výšku vlevo, prázdný seznam nekreslí kóty žádné.
    """
    if not polys:
        raise ValueError("průmět nevrátil žádné hrany")

    axes = _view(view)[2]
    sizes = {"X": bbox.size.X, "Y": bbox.size.Y, "Z": bbox.size.Z}

    px0, px1, py0, py1 = extent(polys)
    pw, ph = (px1 - px0) or 1.0, (py1 - py0) or 1.0

    S = SUPERSAMPLE
    g = _metrics(width)
    font = _font(g["font_px"])
    if scale is None:
        scale = fit_scale(width, pw)
    k = scale * S                             # pixelů zvětšeného plátna na milimetr
    draw_w, draw_h = pw * k, ph * k

    if dims is None:
        if axes is None:                      # kosoúhlý pohled nemá co kótovat
            dims = []
        else:
            d = g["offset"] / k
            dims = [((px0, py0), (px1, py0), -d),     # šířka dole
                    ((px0, py0), (px0, py1), -d)]     # výška vlevo

    # Plátno se vede podle toho, co se na něm octne — kóta může být i mimo těleso.
    local = lambda p: ((p[0] - px0) * k, (py1 - p[1]) * k)
    boxes = [_dim(a, b, off, local, k, g, font) for a, b, off in dims]
    fx0 = min([0.0] + [bx[0] for bx in boxes])
    fy0 = min([0.0] + [bx[1] for bx in boxes])
    fx1 = max([draw_w] + [bx[2] for bx in boxes])
    fy1 = max([draw_h] + [bx[3] for bx in boxes])

    margin = g["margin"]
    canvas_w = _round_up(2 * margin + (fx1 - fx0), S)
    canvas_h = _round_up(2 * margin + (fy1 - fy0), S)
    ox, oy = margin - fx0, margin - fy0
    to_px = lambda p: (ox + (p[0] - px0) * k, oy + (py1 - p[1]) * k)

    mode = "RGBA" if transparent else "RGB"
    bg = (255, 255, 255, 0) if transparent else "white"
    img = Image.new(mode, (canvas_w, canvas_h), bg)
    dr = ImageDraw.Draw(img)

    for poly in polys:
        pts = [to_px(p) for p in poly]
        if len(pts) > 1:
            dr.line(pts, fill=INK, width=g["edge"], joint="curve")

    for a, b, off in dims:
        _dim(a, b, off, to_px, k, g, font, dr=dr, img=img)

    img = img.resize((canvas_w // S, canvas_h // S), Image.LANCZOS)
    img.save(out)
    info = {"hran": len(polys), "px": img.size, "meritko": scale, "out": out,
            "kot": len(dims)}
    if axes:
        info.update(sirka=sizes[axes[0]], vyska=sizes[axes[1]],
                    hloubka=sizes[({"X", "Y", "Z"} - set(axes)).pop()])
    else:
        info.update(sirka=sizes["X"], vyska=sizes["Z"], hloubka=sizes["Y"])
    return info


def render(src: str, out: str, view: str = "zepredu", width: int = 1600,
           transparent: bool = False, scale: float | None = None, dims=None) -> dict:
    """Jeden STEP na jednu perokresbu. Vrací rozměry v mm a použité měřítko."""
    polys, bbox, _circles = project(src, view)
    return draw(polys, bbox, out, view=view, width=width,
                transparent=transparent, scale=scale, dims=dims)


def render_set(sources, outdir: str, view: str = "zepredu", width: int = 1600,
               transparent: bool = False) -> list[dict]:
    """Celá řada v jednom měřítku: nejširší kus vyjde na `width`, ostatní poměrně menší.

    Teprve tak jdou obrázky postavit vedle sebe — každý zvlášť roztažený na
    stejnou šířku by malou skříň ukázal větší než velkou.
    """
    import stepkit

    _view(view)
    os.makedirs(outdir, exist_ok=True)

    jobs = []
    for src in sources:
        polys, bbox, _circles = project(src, view)
        if not polys:
            raise ValueError(f"{os.path.basename(src)}: průmět nevrátil žádné hrany")
        jobs.append((src, polys, bbox, extent(polys)))

    scale = fit_scale(width, max(e[1] - e[0] for _s, _p, _b, e in jobs))

    out = []
    for src, polys, bbox, _e in jobs:
        target = os.path.join(outdir, stepkit.slugify(src) + ".png")
        info = draw(polys, bbox, target, view=view, width=width,
                    transparent=transparent, scale=scale)
        info["src"] = src
        out.append(info)
    return out
