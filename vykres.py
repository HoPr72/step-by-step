"""Perokresba ze STEPu: pravoúhlý průmět s kótami do PNG.

Projekce je rovnoběžná, bez perspektivy — okraje tělesa tedy odpovídají
skutečným rozměrům a dají se přímo okótovat. Kreslí se jen viditelné hrany,
schované se zahazují.

Kreslí se do několikanásobně většího plátna, které se na konci zmenší;
PIL totiž čáry nevyhlazuje a bez toho jsou šikmé hrany zubaté.
"""

from __future__ import annotations

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
    """Rozměr do popisku kóty, s desetinnou čárkou a bez zbytečných nul."""
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


# --------------------------------------------------------------------------
# průmět
# --------------------------------------------------------------------------

def project(src: str, view: str):
    """Viditelné hrany jako lomené čáry v rovině průmětu, plus obalový kvádr."""
    from build123d import Vector, import_step

    direction, up, _axes = VIEWS[view]
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

def render(src: str, out: str, view: str = "zepredu", width: int = 1600,
           transparent: bool = False) -> dict:
    """Vykreslí perokresbu s kótou šířky dole a výšky vlevo. Vrací rozměry v mm."""
    if view not in VIEWS:
        raise ValueError(f"neznámý pohled {view!r}, čekám {'/'.join(VIEWS)}")

    polys, bbox = project(src, view)
    if not polys:
        raise ValueError("průmět nevrátil žádné hrany")

    _d, _u, (ha, va) = VIEWS[view]
    sizes = {"X": bbox.size.X, "Y": bbox.size.Y, "Z": bbox.size.Z}
    w_mm, h_mm = sizes[ha], sizes[va]

    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    px0, px1, py0, py1 = min(xs), max(xs), min(ys), max(ys)
    pw, ph = (px1 - px0) or 1.0, (py1 - py0) or 1.0

    # Rozměry prvků kresby drží poměr k šířce obrázku, ať to sedí v každé velikosti.
    S = SUPERSAMPLE
    canvas_w = width * S
    u = canvas_w / 1600.0
    margin = 40 * u
    gap = 11 * u            # mezera mezi tělesem a začátkem vynášecí čáry
    offset = 56 * u         # odstup kótovací čáry od tělesa
    over = 13 * u           # přesah vynášecí čáry za kótovací
    arrow, arrow_half = 15 * u, 5 * u
    font_px = max(10, int(27 * u))
    font = _font(font_px)
    text_gap = 8 * u

    band = offset + font_px + text_gap        # místo, které si kóta ukousne
    left = margin + band
    draw_w = canvas_w - left - margin
    k = draw_w / pw                           # pixelů na jednotku průmětu
    draw_h = ph * k
    canvas_h = int(round((margin + draw_h + band + margin) / S)) * S

    ix0, iy1 = left, margin + draw_h
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

    img = img.resize((width, canvas_h // S), Image.LANCZOS)
    img.save(out)
    return {"sirka": w_mm, "vyska": h_mm, "hloubka": sizes[({"X", "Y", "Z"} - {ha, va}).pop()],
            "hran": len(polys), "px": img.size}
