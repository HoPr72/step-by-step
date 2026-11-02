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

#: Pohled → (odkud se kouká, co je nahoře, osy modelu ve vodorovném a svislém směru).
VIEWS = {
    "zepredu": ((0, -1, 0), (0, 0, 1), ("X", "Z")),
    "zezadu": ((0, 1, 0), (0, 0, 1), ("X", "Z")),
    "zboku": ((1, 0, 0), (0, 0, 1), ("Y", "Z")),
    "shora": ((0, 0, 1), (0, 1, 0), ("X", "Y")),
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
        "gap": 11 * u,          # mezera mezi tělesem a začátkem vynášecí čáry
        "offset": 56 * u,       # odstup kótovací čáry od tělesa
        "over": 13 * u,         # přesah vynášecí čáry za kótovací
        "arrow": 15 * u,
        "arrow_half": 5 * u,
        "font_px": font_px,
        "text_gap": 8 * u,
    }
    g["band"] = g["offset"] + font_px + g["text_gap"]   # místo, které si kóta ukousne
    g["left"] = g["margin"] + g["band"]
    return g


def fit_scale(width: int, span_mm: float) -> float:
    """Měřítko v px/mm, při kterém kresba široká `span_mm` vyplní `width` pixelů."""
    g = _metrics(width)
    return (width * SUPERSAMPLE - g["left"] - g["margin"]) / SUPERSAMPLE / span_mm


# --------------------------------------------------------------------------
# průmět
# --------------------------------------------------------------------------

def project(src: str, view: str):
    """Viditelné hrany jako lomené čáry v rovině průmětu, plus obalový kvádr."""
    from build123d import Vector, import_step

    direction, up, _axes = _view(view)
    shape = import_step(src)
    bbox = shape.bounding_box()
    shape = shape.translate(-bbox.center())

    span = max(bbox.size.X, bbox.size.Y, bbox.size.Z)
    origin = Vector(*direction).normalized() * (span * 8)
    visible, _hidden = shape.project_to_viewport(
        viewport_origin=origin, viewport_up=up, look_at=(0, 0, 0))

    polys = []
    for edge in visible:
        try:
            n = 2 if str(edge.geom_type).upper().endswith("LINE") else 48
            polys.append([(p.X, p.Y) for p in (edge @ (i / (n - 1)) for i in range(n))])
        except Exception:
            continue
    return polys, bbox


def _extent(polys):
    """Obdélník, do kterého se průmět vejde: (x0, x1, y0, y1)."""
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), max(xs), min(ys), max(ys)


# --------------------------------------------------------------------------
# prvky kóty
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


# --------------------------------------------------------------------------
# kresba
# --------------------------------------------------------------------------

def draw(polys, bbox, out: str, view: str = "zepredu", width: int = 1600,
         transparent: bool = False, scale: float | None = None) -> dict:
    """Hotový průmět na papír: kóta šířky dole, výšky vlevo.

    `scale` je v px na milimetr. Bez něj se kresba roztáhne na `width` pixelů —
    s ním `width` určuje už jen tloušťku čar a velikost písma a plátno se
    přizpůsobí kresbě.
    """
    if not polys:
        raise ValueError("průmět nevrátil žádné hrany")

    _d, _u, (ha, va) = _view(view)
    sizes = {"X": bbox.size.X, "Y": bbox.size.Y, "Z": bbox.size.Z}
    w_mm, h_mm = sizes[ha], sizes[va]

    px0, px1, py0, py1 = _extent(polys)
    pw, ph = (px1 - px0) or 1.0, (py1 - py0) or 1.0

    S = SUPERSAMPLE
    g = _metrics(width)
    margin, gap, offset, over = g["margin"], g["gap"], g["offset"], g["over"]
    arrow, arrow_half, text_gap = g["arrow"], g["arrow_half"], g["text_gap"]
    font_px = g["font_px"]
    font = _font(font_px)
    u = g["u"]

    if scale is None:
        scale = fit_scale(width, pw)
    k = scale * S                             # pixelů zvětšeného plátna na milimetr
    draw_w, draw_h = pw * k, ph * k
    canvas_w = _round_up(g["left"] + draw_w + margin, S)
    canvas_h = _round_up(margin + draw_h + g["band"] + margin, S)

    ix0, iy1 = g["left"], margin + draw_h
    to_px = lambda p: (ix0 + (p[0] - px0) * k, iy1 - (p[1] - py0) * k)

    mode = "RGBA" if transparent else "RGB"
    bg = (255, 255, 255, 0) if transparent else "white"
    img = Image.new(mode, (canvas_w, canvas_h), bg)
    dr = ImageDraw.Draw(img)

    for poly in polys:
        pts = [to_px(p) for p in poly]
        if len(pts) > 1:
            dr.line(pts, fill=INK, width=max(1, int(2.4 * u)), joint="curve")

    thin = max(1, int(1.2 * u))
    ix1, iy0 = ix0 + draw_w, margin

    # Šířka: kótovací čára pod tělesem.
    y = iy1 + offset
    for x in (ix0, ix1):
        dr.line([(x, iy1 + gap), (x, y + over)], fill=DIM_INK, width=thin)
    dr.line([(ix0, y), (ix1, y)], fill=DIM_INK, width=thin)
    _arrow(dr, (ix0, y), (1, 0), arrow, arrow_half, DIM_INK)
    _arrow(dr, (ix1, y), (-1, 0), arrow, arrow_half, DIM_INK)
    dr.text(((ix0 + ix1) / 2, y - text_gap), _mm(w_mm), font=font, fill=DIM_INK, anchor="ms")

    # Výška: kótovací čára vlevo od tělesa.
    x = ix0 - offset
    for yy in (iy0, iy1):
        dr.line([(ix0 - gap, yy), (x - over, yy)], fill=DIM_INK, width=thin)
    dr.line([(x, iy0), (x, iy1)], fill=DIM_INK, width=thin)
    _arrow(dr, (x, iy0), (0, 1), arrow, arrow_half, DIM_INK)
    _arrow(dr, (x, iy1), (0, -1), arrow, arrow_half, DIM_INK)
    _rotated_text(img, (x - text_gap - font_px / 2, (iy0 + iy1) / 2), _mm(h_mm), font, DIM_INK)

    img = img.resize((canvas_w // S, canvas_h // S), Image.LANCZOS)
    img.save(out)
    return {"sirka": w_mm, "vyska": h_mm, "hloubka": sizes[({"X", "Y", "Z"} - {ha, va}).pop()],
            "hran": len(polys), "px": img.size, "meritko": scale, "out": out}


def render(src: str, out: str, view: str = "zepredu", width: int = 1600,
           transparent: bool = False, scale: float | None = None) -> dict:
    """Jeden STEP na jednu perokresbu. Vrací rozměry v mm a použité měřítko."""
    polys, bbox = project(src, view)
    return draw(polys, bbox, out, view=view, width=width,
                transparent=transparent, scale=scale)


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
        polys, bbox = project(src, view)
        if not polys:
            raise ValueError(f"{os.path.basename(src)}: průmět nevrátil žádné hrany")
        jobs.append((src, polys, bbox, _extent(polys)))

    scale = fit_scale(width, max(e[1] - e[0] for _s, _p, _b, e in jobs))

    out = []
    for src, polys, bbox, _e in jobs:
        target = os.path.join(outdir, stepkit.slugify(src) + ".png")
        info = draw(polys, bbox, target, view=view, width=width,
                    transparent=transparent, scale=scale)
        info["src"] = src
        out.append(info)
    return out
