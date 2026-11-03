"""Čtení STEP souborů přes OCCT: názvy těles, rozměry, objemy a mesh.

Jádro je Open CASCADE (OCCT 8.0) přes vazbu OCP, kterou s sebou veze
balík cadquery-ocp. Žádné GUI, žádný parametrický model — jen načíst,
odměřit a vrátit data.
"""

from __future__ import annotations

import os
import re

from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.collections import Sequence_TDF_Label

#: Jemnost triangulace. Lineární odchylka v mm, úhlová v radiánech.
LINEAR_DEFLECTION = 0.3
ANGULAR_DEFLECTION = 0.4

#: Kódová stránka pro escape sekvence v názvech (SolidWorks CZ píše CP1250).
STEP_CODEPAGE = "cp1250"

STEP_SUFFIXES = (".step", ".stp", ".STEP", ".STP")


# --------------------------------------------------------------------------
# názvy: STEP je escapuje a OCCT 8.0 je nerozkóduje
# --------------------------------------------------------------------------

def _decode_byte(value: int) -> str:
    try:
        return bytes([value]).decode(STEP_CODEPAGE)
    except Exception:
        return bytes([value]).decode("latin-1")


def step_unescape(text: str) -> str:
    """Rozloží escape sekvence podle ISO 10303-21.

    ``\\X\\E1`` je jeden znak kódu 0xE1, ``\\X2\\....\\X0\\`` je UTF-16BE
    a ``\\S\\x`` je znak s nastaveným osmým bitem.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("\\X2\\", i):
            end = text.find("\\X0\\", i)
            if end < 0:
                end = len(text)
            try:
                out.append(bytes.fromhex(text[i + 4:end]).decode("utf-16-be"))
            except Exception:
                out.append(text[i + 4:end])
            i = end + 4
        elif text.startswith("\\X\\", i) and i + 5 <= len(text):
            try:
                out.append(_decode_byte(int(text[i + 3:i + 5], 16)))
            except ValueError:
                out.append(text[i:i + 5])
            i += 5
        elif text.startswith("\\S\\", i) and i + 4 <= len(text):
            out.append(_decode_byte(ord(text[i + 3]) + 128))
            i += 4
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _mask(text: str) -> str:
    """Nahradí znaky nad ASCII otazníkem, aby šly páry porovnat."""
    return "".join("?" if ord(c) > 127 else c for c in text)


def _repair_table(path: str) -> dict[str, str]:
    """Správné názvy ze zdrojového souboru, klíčované maskou."""
    with open(path, "r", encoding="latin-1", errors="replace") as fh:
        text = fh.read()
    table: dict[str, str] = {}
    for literal in re.findall(r"'((?:[^']|'')*)'", text):
        decoded = step_unescape(literal.replace("''", "'"))
        if any(ord(c) > 127 for c in decoded):
            table.setdefault(_mask(decoded), decoded)
    return table


def _name_of(label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return TCollection_AsciiString(attr.Get()).ToCString().strip()
    return ""


# --------------------------------------------------------------------------
# geometrie
# --------------------------------------------------------------------------

def _bbox(shape) -> tuple[list[float], list[float]]:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    lo, hi = box.CornerMin(), box.CornerMax()
    return [lo.X(), lo.Y(), lo.Z()], [hi.X(), hi.Y(), hi.Z()]


def _volume_mm3(shape) -> float:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _triangulate(shape, linear: float | None = None,
                 angular: float | None = None) -> tuple[list[float], list[int]]:
    linear = LINEAR_DEFLECTION if linear is None else linear
    angular = ANGULAR_DEFLECTION if angular is None else angular
    BRepMesh_IncrementalMesh(shape, linear, False, angular, True)
    verts: list[float] = []
    tris: list[int] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            base = len(verts) // 3
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts += [p.X(), p.Y(), p.Z()]
            reversed_face = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if reversed_face:
                    a, c = c, a
                tris += [base + a - 1, base + b - 1, base + c - 1]
        explorer.Next()
    return verts, tris


# --------------------------------------------------------------------------
# načtení dokumentu
# --------------------------------------------------------------------------

def _read_document(path: str):
    """Vrátí (doc, shape_tool). Dokument je nutné držet, jinak ShapeTool osiří."""
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("step"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.ReadFile(path)
    reader.Transfer(doc)
    return doc, XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())


def _collect(path: str):
    """Vrátí (doc, tělesa). Dokument musí volající držet, dokud s tělesy pracuje."""
    doc, shape_tool = _read_document(path)
    labels = Sequence_TDF_Label()
    shape_tool.GetFreeShapes(labels)
    repairs = _repair_table(path)

    out = []
    for index, label in enumerate(labels):
        shape = shape_tool.GetShape_s(label)
        name = _name_of(label)
        if "�" in name:
            # Některé exporty mají náhradní znaky zapsané rovnou ve zdroji;
            # tam už se zachránit nedá nic a zbytek nahradíme otazníkem.
            name = repairs.get(_mask(name), name).replace("�", "?")
        lo, hi = _bbox(shape)
        out.append({
            "name": name or f"Těleso {index + 1}",
            "shape": shape,
            "min": lo,
            "max": hi,
            "size": [hi[i] - lo[i] for i in range(3)],
            "volume": _volume_mm3(shape) / 1000.0,
        })
    return doc, out


def read_solids(path: str) -> list[dict]:
    """Tělesa souboru: název, tvar, obalový kvádr a objem v cm³."""
    doc, solids = _collect(path)
    for solid in solids:
        solid.pop("shape", None)
    del doc
    return solids


def to_viewer_json(path: str) -> dict:
    """Celý model ve tvaru, který čte webový prohlížeč. Souřadnice jsou vycentrované."""
    doc, solids = _collect(path)
    if not solids:
        return {"file": os.path.basename(path), "size": [0, 0, 0],
                "total_vol": 0.0, "solids": []}

    gmin = [min(s["min"][i] for s in solids) for i in range(3)]
    gmax = [max(s["max"][i] for s in solids) for i in range(3)]
    center = [(gmin[i] + gmax[i]) / 2 for i in range(3)]

    payload = []
    for solid in solids:
        verts, tris = _triangulate(solid["shape"])
        payload.append({
            "name": solid["name"],
            "size": [round(v, 2) for v in solid["size"]],
            "vol": round(solid["volume"], 2),
            "v": [round(verts[i] - center[i % 3], 2) for i in range(len(verts))],
            "f": tris,
        })

    result = {
        "file": os.path.basename(path),
        "size": [round(gmax[i] - gmin[i], 2) for i in range(3)],
        "total_vol": round(sum(p["vol"] for p in payload), 1),
        "solids": payload,
    }
    del doc
    return result


_DIACRITICS = str.maketrans({
    "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e", "í": "i", "ň": "n",
    "ó": "o", "ř": "r", "š": "s", "ť": "t", "ú": "u", "ů": "u", "ý": "y", "ž": "z",
})


def slugify(path: str) -> str:
    """Název souboru na bezpečný klíč pro JSON a URL."""
    stem = os.path.basename(path).rsplit(".", 1)[0].lower().translate(_DIACRITICS)
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:48] or "model"


def find_step_files(root: str, max_depth: int = 6) -> list[str]:
    """Všechny STEP soubory pod adresářem, relativní cesty, seřazené."""
    root = os.path.abspath(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith(STEP_SUFFIXES) and not name.startswith("."):
                found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return found
