"""Scéna a render — běží uvnitř Blenderu, ne ve venv.

    blender --background --python blender_scena.py -- scena.json

Dostane hotové sítě už otočené a posunuté tak, jak mají ve scéně stát;
tenhle skript řeší jen vzhled: materiály, světla, kameru a vlastní render.
Dělicí čára je schválně tady — Blender nemá OCCT a venv nemá bpy.
"""

import json
import math
import sys

import bmesh
import bpy
import numpy as np

#: Vstupy Principled BSDF se mezi verzemi přejmenovaly; bereme první, co sedí.
VSTUPY = {
    "barva": ("Base Color",),
    "drsnost": ("Roughness",),
    "kov": ("Metallic",),
    "odlesk": ("Specular IOR Level", "Specular"),
    "svit": ("Emission Strength",),
    "svit_barva": ("Emission Color", "Emission"),
}


def _nastav(bsdf, klic, hodnota):
    for jmeno in VSTUPY[klic]:
        if jmeno in bsdf.inputs:
            bsdf.inputs[jmeno].default_value = hodnota
            return True
    return False


def material(jmeno, spec):
    """Principled BSDF podle popisu ze scény."""
    mat = bpy.data.materials.new(jmeno)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    barva = spec.get("barva", [0.5, 0.5, 0.5])
    _nastav(bsdf, "barva", (*barva, 1.0))
    _nastav(bsdf, "drsnost", spec.get("drsnost", 0.5))
    _nastav(bsdf, "kov", spec.get("kov", 0.0))
    _nastav(bsdf, "odlesk", spec.get("odlesk", 0.5))

    if spec.get("textura"):
        obr = bpy.data.images.load(spec["textura"])
        obr.colorspace_settings.name = "sRGB"
        uzel = mat.node_tree.nodes.new("ShaderNodeTexImage")
        uzel.image = obr
        uzel.interpolation = "Cubic"
        uzel.location = (-400, 200)
        # Obrázek jde do svitu, ne do barvy: displej si svítí sám a jeho jas
        # tak drží jediné číslo místo toho, aby ho hýbalo světlo scény.
        for vstup in VSTUPY["svit_barva"]:
            if vstup in bsdf.inputs:
                mat.node_tree.links.new(bsdf.inputs[vstup], uzel.outputs["Color"])
                break
        _nastav(bsdf, "svit", spec.get("svit", 1.0))
    return mat


def teleso(jmeno, verts, tris, mat):
    """Síť do scény. Přes foreach_set, protože from_pydata je na statisíce pomalé."""
    mesh = bpy.data.meshes.new(jmeno)
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    pocet = len(tris)
    mesh.loops.add(pocet * 3)
    mesh.polygons.add(pocet)
    mesh.loops.foreach_set("vertex_index", tris.ravel())
    mesh.polygons.foreach_set("loop_start", np.arange(pocet) * 3)
    mesh.polygons.foreach_set("loop_total", np.full(pocet, 3))
    mesh.update()
    mesh.validate()

    # Trojúhelníky chodí z OCCT po plochách, takže na švech leží vrcholy přes
    # sebe. Bez sešití by se hladké stínování nemělo kudy přelít přes hranu.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(mesh)
    bm.free()

    mesh.polygons.foreach_set("use_smooth", np.ones(len(mesh.polygons), dtype=bool))
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = math.radians(30)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(jmeno, mesh)
    bpy.context.collection.objects.link(ob)
    return ob


def obdelnik(jmeno, rohy, mat):
    """Plochý čtyřúhelník s obrázkem — displej se nelepí na síť tělesa."""
    mesh = bpy.data.meshes.new(jmeno)
    mesh.from_pydata(rohy, [], [[0, 1, 2, 3]])
    mesh.update()
    uv = mesh.uv_layers.new(name="UV")
    for i, souradnice in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[i].uv = souradnice
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(jmeno, mesh)
    bpy.context.collection.objects.link(ob)
    return ob


def svetlo(spec):
    light = bpy.data.lights.new(spec.get("jmeno", "svetlo"), type="AREA")
    light.shape = "RECTANGLE"
    light.size, light.size_y = spec["rozmer"]
    light.energy = spec["vykon"]
    light.color = spec.get("barva", (1, 1, 1))
    ob = bpy.data.objects.new(light.name, light)
    ob.location = spec["kde"]
    smer = np.array(spec["kam"]) - np.array(spec["kde"])
    ob.rotation_euler = _natoc(smer)
    bpy.context.collection.objects.link(ob)
    return ob


def _natoc(smer):
    """Eulerovy úhly tak, aby -Z objektu mířilo podél směru."""
    from mathutils import Vector
    return Vector(smer).to_track_quat("-Z", "Y").to_euler()


def kamera(spec, cil):
    cam = bpy.data.cameras.new("kamera")
    cam.lens = spec["objektiv"]
    cam.sensor_width = spec["senzor"]
    ob = bpy.data.objects.new("kamera", cam)
    ob.location = spec["kde"]
    ob.rotation_euler = _natoc(np.array(cil) - np.array(spec["kde"]))
    bpy.context.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def zed(spec):
    """Rovina za modelem. Stín na ni dělá polovinu dojmu."""
    y = spec["kde"]
    r = spec["rozmer"]
    rohy = [(-r, y, -r), (r, y, -r), (r, y, r), (-r, y, r)]
    mesh = bpy.data.meshes.new("zed")
    mesh.from_pydata(rohy, [], [[0, 1, 2, 3]])
    mesh.update()
    mesh.materials.append(material("zed", spec))
    ob = bpy.data.objects.new("zed", mesh)
    bpy.context.collection.objects.link(ob)
    return ob


def main():
    scena = json.load(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8"))
    site = np.load(scena["sit"])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    materialy = {k: material(k, v) for k, v in scena["materialy"].items()}

    for dil in scena["dily"]:
        teleso(dil["jmeno"], site[dil["klic"] + "v"], site[dil["klic"] + "t"],
               materialy[dil["material"]])

    if scena.get("obrazovka"):
        obdelnik("obrazovka", scena["obrazovka"]["rohy"], materialy["obrazovka"])

    zed(scena["zed"])
    for s in scena["svetla"]:
        svetlo(s)
    kamera(scena["kamera"], scena["kamera"]["cil"])

    svet = bpy.data.worlds.new("svet")
    svet.use_nodes = True
    pozadi = svet.node_tree.nodes["Background"]
    pozadi.inputs["Color"].default_value = (*scena["svet"]["barva"], 1.0)
    pozadi.inputs["Strength"].default_value = scena["svet"]["sila"]
    bpy.context.scene.world = svet

    r = scena["render"]
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = r["vzorky"]
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = r["sirka"], r["vyska"]
    sc.render.resolution_percentage = 100
    sc.render.filepath = r["out"]
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = r["transform"]
    sc.view_settings.exposure = r["expozice"]
    sc.view_settings.look = r.get("look", "None")

    try:                                   # Metal když je, jinak procesor
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
        sc.cycles.device = "GPU"
    except Exception as exc:
        print(f"GPU nevyšlo ({exc}), počítá procesor")

    bpy.ops.render.render(write_still=True)
    print(f"HOTOVO {r['out']}")


main()
