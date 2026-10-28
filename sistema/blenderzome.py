"""blenderzome.py - pannello "Zome" per Blender 5.2 (versione 2.0, 2026-10-19).

Disegna l'INTERNO di una zome con la geometria di zome_core.py (stessa cartella).
Uso: nel Text editor di Blender aprire carica_zome.py e premere "Esegui script",
oppure (da codice) aggiungere la cartella a sys.path e chiamare blenderzome.register().
Il pannello compare nella barra laterale della vista 3D (tasto N), scheda "Zome".
"""
VERSIONE = "1.0.1"   # tag pubblicato su github.com/nefaristo/zome. Il pannello, come programma, resta la serie 2.0.
_REPO = "nefaristo/zome"   # solo il codice. Le istanze non stanno in quel repository.

bl_info = {"name": "Zome", "author": "Stefano", "version": (2, 0, 0), "blender": (5, 2, 0),
           "location": "Vista 3D > barra laterale > Zome", "description": "Interno di una zome (N, M, theta, ZH)",
           "category": "Mesh"}

import colorsys
import importlib
import io
import json
import math
import os
import random
import shutil
import sys
import threading
import urllib.request
import zipfile

import bpy
import mathutils
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

try:
    _CODICE = os.path.dirname(os.path.abspath(__file__))
except NameError:                                  # eseguito da un blocco di testo
    _CODICE = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else ""
# Il codice sta in sistema/. Texture, prezzi e istanze stanno nella cartella del progetto.
_ROOT = os.path.dirname(_CODICE) if os.path.basename(_CODICE).lower() == "sistema" else _CODICE
_HERE = _ROOT
if _CODICE and _CODICE not in sys.path:
    sys.path.append(_CODICE)
import zome_core
importlib.reload(zome_core)
import zome_pavimento
importlib.reload(zome_pavimento)
from zome_core import (Params, build, shell, beams, CATALOGO, APERTO, cutlist, beams_summary, BEAM_FACES,
                        isolante_guscio,
                       porta_dist_max, porta_telaio, porta_anta, porta_cerniera, chiave_taglio, parse_traverse, toggle_traverse)
import zome_viste
importlib.reload(zome_viste)
import zome_statica
importlib.reload(zome_statica)
import zome_foglio
import zome_scena
importlib.reload(zome_foglio)
importlib.reload(zome_scena)

_REBUILDING = False


def _catalogo(z):
    cat = {k: dict(v) for k, v in CATALOGO.items()}
    cat["roof_external"]["spessore"] = z.t_tetto / 100.0
    cat["wood_external"]["spessore"] = z.t_legno / 100.0
    cat["glass_external"]["spessore"] = z.t_vetro / 100.0
    cat["wood_internal"]["spessore"] = z.t_int_legno / 100.0
    cat["wood_internal"]["materiale"] = "perline_01"
    return cat


def _uv_orizzontali(me, scala, scale_per_materiale=None):
    """UV per faccia, in metri/scala: u lungo l'orizzontale della faccia, v verso l'alto lungo la falda,
    cosi' tegole e assi corrono parallele al terreno."""
    from mathutils import Vector
    uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    up = Vector((0, 0, 1))
    for poly in me.polygons:
        n = poly.normal
        u = up.cross(n)
        u = Vector((1, 0, 0)) if u.length < 1e-6 else u.normalized()
        v = n.cross(u)
        if v.z < 0:
            v = -v
        sc = (scale_per_materiale or {}).get(poly.material_index, scala)
        for li in poly.loop_indices:
            p = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = (p.dot(u) / sc, p.dot(v) / sc)


N_ASSI_ATLANTE = 7          # assi diverse in textures/assi_singole.jpg (una sopra l'altra, stessa altezza)


def _uv_legno(me, z, chiavi, cat):
    """UV delle facce di legno: ogni faccia ha le sue assi, intere, sempre orizzontali, con larghezza e sfasamento casuali
    (ma sempre uguali a parita' di seme_legno). u = lungo l'asse (1 = larghezza dell'immagine), v = tra le assi
    (un'unita' = un'asse); la parte intera di v, diversa per faccia, da' a ogni asse il suo numero casuale."""
    from mathutils import Vector
    legno = {i for i, k in enumerate(chiavi) if cat[k]["uso"] == "legno"}
    if not legno:
        return
    uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    st, fa = me.attributes["strato"].data, me.attributes["faccia"].data
    up = Vector((0, 0, 1))
    for poly in me.polygons:
        if poly.material_index not in legno:
            continue
        W = max(z.larghezza_perline if chiavi[poly.material_index] == "wood_internal" else z.larghezza_assi, 1.0) / 100.0
        rnd = random.Random(z.seme_legno * 1000003 + st[poly.index].value * 1009 + fa[poly.index].value * 7919)
        n = poly.normal.normalized()
        pts = [me.vertices[me.loops[li].vertex_index].co for li in poly.loop_indices]
        orizz = up.cross(n)                          # le assi sono sempre orizzontali
        d = Vector((1, 0, 0)) if orizz.length < 1e-6 else orizz.normalized()
        w = n.cross(d).normalized()
        larg = W * rnd.uniform(0.8, 1.25)
        lungh = larg * 21.7                          # 900 px dell'immagine lungo l'asse, 41 px = una larghezza
        fase = rnd.randrange(0, 3000) + rnd.random()
        for li, q in zip(poly.loop_indices, pts):
            uvl.data[li].uv = (q.dot(d) / lungh, q.dot(w) / larg + fase)


def _uv_pareti(me, z):
    """UV delle pareti del corridoio: assi orizzontali come sul legno esterno."""
    from mathutils import Vector
    uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    up = Vector((0, 0, 1))
    larg = max(z.larghezza_assi, 1.0) / 100.0
    lungh = larg * 21.7
    for poly in me.polygons:
        rnd = random.Random(z.seme_legno * 1000003 + poly.index * 7919)
        n = poly.normal.normalized()
        orizz = up.cross(n)
        d = Vector((1, 0, 0)) if orizz.length < 1e-6 else orizz.normalized()
        w = n.cross(d).normalized()
        fase = rnd.randrange(0, 3000) + rnd.random()
        for li in poly.loop_indices:
            q = me.vertices[me.loops[li].vertex_index].co
            uvl.data[li].uv = (q.dot(d) / lungh, q.dot(w) / larg + fase)


def _materiale_tinta(nome, rgb, rough=0.6, metal=0.0):
    """Materiale di tinta unita (non esiste ancora: si crea)."""
    mat = bpy.data.materials.get(nome)
    if mat is None:
        mat = bpy.data.materials.new(nome)
        for nodo in mat.node_tree.nodes:
            if nodo.bl_idname == "ShaderNodeBsdfPrincipled":
                nodo.inputs["Base Color"].default_value = (*rgb, 1.0)
                nodo.inputs["Roughness"].default_value = rough
                nodo.inputs["Metallic"].default_value = metal
        mat.diffuse_color = (*rgb, 1.0)
    return mat


def _materiale_pietra(nome="pietra_01"):
    """Pietra grigia procedurale: rumore in coordinate dell'oggetto (non si allunga sul muro) piu' una tinta diversa per ogni pietra
    (attributo "tinta" delle facce), poi rampa -> colore base."""
    mat = bpy.data.materials.get(nome)
    if mat is None:
        mat = bpy.data.materials.new(nome)
    nt = mat.node_tree
    if any(n.bl_idname == "ShaderNodeAttribute" and n.attribute_name == "tinta" for n in nt.nodes):
        return mat
    bsdf = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    for n in list(nt.nodes):                                    # toglie la versione precedente (rumore in coordinate generate)
        if n.bl_idname in ("ShaderNodeTexNoise", "ShaderNodeValToRGB"):
            nt.nodes.remove(n)
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 14.0
    noise.inputs["Detail"].default_value = 8.0
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    m1 = nt.nodes.new("ShaderNodeMath")
    m1.operation = "MULTIPLY"
    m1.inputs[1].default_value = 0.6
    nt.links.new(noise.outputs["Fac"], m1.inputs[0])
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "tinta"
    m2 = nt.nodes.new("ShaderNodeMath")
    m2.operation = "MULTIPLY_ADD"
    m2.inputs[1].default_value = 0.4
    nt.links.new(attr.outputs["Fac"], m2.inputs[0])
    nt.links.new(m1.outputs["Value"], m2.inputs[2])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.25
    ramp.color_ramp.elements[0].color = (0.10, 0.10, 0.095, 1.0)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.40, 0.38, 0.34, 1.0)
    nt.links.new(m2.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.92
    mat.diffuse_color = (0.35, 0.34, 0.31, 1.0)
    return mat


def _nome_isolante(ident):
    """Dal codice del menu al nome della riga nel foglio materiali."""
    for cod, nome, _d in _voci_isolanti(None, None):
        if cod == ident:
            return nome
    return ident


def _segna(ob, chiave):
    """La proprietà che fa entrare il solido nel conto. `chiave` è un nome breve o il nome della riga materiali."""
    if ob is None:
        return None
    ob["materiale"] = zome_foglio.NOMI.get(chiave, chiave)
    return ob
    """Un oggetto con piu' poliedri {"v": vertici, "f": facce}: le facce guardano verso fuori."""
    from mathutils import Vector
    vs, fs = [], []
    for P in poliedri:
        base = len(vs)
        vs.extend(P["v"])
        cen = Vector(tuple(sum(q[j] for q in P["v"]) / len(P["v"]) for j in range(3)))
        for f in P["f"]:
            pts = [Vector(P["v"][i]) for i in f]
            n = Vector((0, 0, 0))
            for i in range(len(pts)):
                a_, b_ = pts[i], pts[(i + 1) % len(pts)]
                n += Vector(((a_.y - b_.y) * (a_.z + b_.z), (a_.z - b_.z) * (a_.x + b_.x), (a_.x - b_.x) * (a_.y + b_.y)))
            fuori = n.dot(pts[0] - cen) > 0
            fs.append([base + i for i in (f if fuori else f[::-1])])
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vs, [], fs)
    me.update()
    if any(P.get("tinta") is not None for P in poliedri):          # una tinta per ogni pietra (attributo delle facce)
        vals = []
        for P in poliedri:
            vals += [float(P.get("tinta", 0.5))] * len(P["f"])
        at = me.attributes.new(name="tinta", type="FLOAT", domain="FACE")
        at.data.foreach_set("value", vals)
    me.materials.append(mat)
    ob = bpy.data.objects.new(nome, me)
    L(ob, ruolo)
    return ob


def _mesh_prismi(nome, prismi, mat, L, ruolo):
    """Prismi come liste di 2n vertici (anello basso + anello alto) -> poliedri."""
    poli = []
    for pr_ in prismi:
        n = len(pr_) // 2
        f = [list(range(n)), list(range(2 * n - 1, n - 1, -1))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
        poli.append({"v": pr_, "f": f})
    return _mesh_poliedri(nome, poli, mat, L, ruolo)


def _costruisci_pavimento(pav, name, z, L):
    """Fondazione, dormienti, travetti, tavolato e gradino nella collection «Pavimento»."""
    ruolo = "Pavimento"
    if pav["pietre"]:
        _mesh_poliedri(name + "_pav_pietre", pav["pietre"], _materiale_pietra(), L, ruolo)
    if pav["dormienti"]:
        _segna(_mesh_poliedri(name + "_pav_dormienti", pav["dormienti"], _materiale_tinta("dormiente_01", (0.30, 0.19, 0.10), 0.8), L, ruolo), "c24")
    if pav["travetti"]:
        ob_t = _mesh_poliedri(name + "_pav_travetti", pav["travetti"], _materiale_tinta("travetto_01", (0.62, 0.45, 0.27), 0.7), L, ruolo)
        _segna(ob_t, "c24")
        if ob_t is not None and pav.get("summary"):
            ob_t["travetti_formula"] = json.dumps(pav["summary"].get("formula") or {})
    if pav["tavolato"]:
        ob = _mesh_poliedri(name + "_pav_tavolato", [pav["tavolato"]], _materiale(_catalogo(z)["wood_external"]["materiale"], "legno"), L, ruolo)
        _uv_pareti(ob.data, z)
        _segna(ob, "perline")
    if pav.get("fondo"):
        ob = _mesh_poliedri(name + "_pav_fondo", pav["fondo"], _materiale(_catalogo(z)["wood_internal"]["materiale"], "legno"), L, ruolo)
        _segna(ob, "perline")
    if pav.get("isolante"):
        ob = _mesh_poliedri(name + "_pav_isolante", pav["isolante"], _materiale_tinta("isolante_01", (0.86, 0.78, 0.45), 0.85), L, "Isolante")
        _segna(ob, _nome_isolante(z.isolante))
    if pav["gradino"]:
        _mesh_poliedri(name + "_pav_gradino", [pav["gradino"]], _materiale_pietra(), L, ruolo)


def _materiale_legno(nome):
    perline = nome.startswith("perline")
    """Materiale legno a assi intere: ogni asse (parte intera di v) sceglie a caso una delle assi di
    textures/assi_singole.jpg, un punto di partenza, il verso, una variazione di tono e di ruvidezza."""
    mat = bpy.data.materials.get(nome) or bpy.data.materials.new(nome)
    if mat.get("zome_legno") == 2 and mat.node_tree:
        return mat
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    L = nt.links
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (1500, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (1250, 0)
    L.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def math(op, a, b=None, x=0, y=0, clamp=False):
        m = nt.nodes.new("ShaderNodeMath"); m.operation = op; m.use_clamp = clamp; m.location = (x, y)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                L.new(v, m.inputs[i])
        return m.outputs[0]

    def caso(w, x, y):
        t = nt.nodes.new("ShaderNodeTexWhiteNoise"); t.noise_dimensions = '1D'; t.location = (x, y)
        L.new(w, t.inputs["W"])
        return t.outputs["Value"]

    def mappa(v, a, b, c, d, x, y):
        m = nt.nodes.new("ShaderNodeMapRange"); m.clamp = True; m.location = (x, y)
        L.new(v, m.inputs["Value"])
        for nm, val in (("From Min", a), ("From Max", b), ("To Min", c), ("To Max", d)):
            m.inputs[nm].default_value = val
        return m.outputs["Result"]

    tc = nt.nodes.new("ShaderNodeTexCoord"); tc.location = (-1400, 0)
    sep = nt.nodes.new("ShaderNodeSeparateXYZ"); sep.location = (-1200, 0)
    L.new(tc.outputs["UV"], sep.inputs["Vector"])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    idx = math('FLOOR', v, None, -1000, -200)                 # numero dell'asse
    fr = math('FRACT', v, None, -1000, -350)                  # posizione dentro l'asse (0..1)
    r1 = caso(idx, -800, 300)
    r2 = caso(math('ADD', idx, 31.7, -950, 150), -800, 150)
    r3 = caso(math('ADD', idx, 77.3, -950, 0), -800, 0)
    r4 = caso(math('ADD', idx, 123.1, -950, -150), -800, -150)
    k = math('FLOOR', math('MULTIPLY', r1, float(N_ASSI_ATLANTE) - 1e-3, -600, 300), None, -450, 300)
    verso = math('SUBTRACT', math('MULTIPLY', math('FLOOR', math('MULTIPLY', r3, 2.0 - 1e-3, -600, 100), None, -450, 100), 2.0, -300, 100), 1.0, -150, 100)
    u_img = math('ADD', math('MULTIPLY', u, verso, -100, 0), math('MULTIPLY', r2, 10.0, -300, 0), 50, 0)
    v_img = math('DIVIDE', math('ADD', k, math('ADD', 0.05, math('MULTIPLY', fr, 0.9, -300, -350), -150, -350), -20, -300), float(N_ASSI_ATLANTE), 150, -300)
    comb = nt.nodes.new("ShaderNodeCombineXYZ"); comb.location = (300, -100)
    L.new(u_img, comb.inputs["X"]); L.new(v_img, comb.inputs["Y"])
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.location = (500, -100)
    tex.interpolation = 'Linear'; tex.extension = 'REPEAT'
    perc = os.path.join(_HERE, "textures", "assi_singole.jpg") if _HERE else ""
    img = bpy.data.images.get("assi_singole.jpg")
    if img is None and perc and os.path.exists(perc):
        img = bpy.data.images.load(perc)
    if img is not None:
        tex.image = img
    L.new(comb.outputs["Vector"], tex.inputs["Vector"])
    # fessura scura tra un'asse e l'altra
    bordo = math('MINIMUM', fr, math('SUBTRACT', 1.0, fr, 300, -450), 500, -450)
    # perline: giunto a V piu' marcato e legno piu' chiaro e uniforme
    fess = mappa(bordo, 0.0, 0.06 if perline else 0.035, 0.12 if perline else 0.2, 1.0, 700, -450)
    tono = mappa(r4, 0.0, 1.0, *((0.72, 0.92) if perline else (0.52, 0.78)), 500, -250)
    hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.location = (950, -50)
    L.new(tex.outputs["Color"], hs.inputs["Color"])
    L.new(math('MULTIPLY', fess, tono, 850, -300), hs.inputs["Value"])
    L.new(mappa(r2, 0.0, 1.0, 0.485, 0.515, 700, -600), hs.inputs["Hue"])
    L.new(mappa(r4, 0.0, 1.0, 1.0, 1.3, 700, -750), hs.inputs["Saturation"])
    L.new(hs.outputs["Color"], bsdf.inputs["Base Color"])
    L.new(mappa(r1, 0.0, 1.0, 0.55, 0.85, 950, -450), bsdf.inputs["Roughness"])
    mat["zome_legno"] = 2
    return mat


def _materiale(nome, uso):
    if uso == "legno":
        return _materiale_legno(nome)
    mat = bpy.data.materials.get(nome)
    if mat is None:
        mat = bpy.data.materials.new(nome)
        if uso == "vetro" and mat.node_tree:
            for nodo in mat.node_tree.nodes:
                if nodo.bl_idname == "ShaderNodeBsdfPrincipled":
                    nodo.inputs["Base Color"].default_value = (0.6, 0.8, 0.9, 1.0)
                    nodo.inputs["Alpha"].default_value = 0.3
                    nodo.inputs["Roughness"].default_value = 0.05
            mat.surface_render_method = 'BLENDED'
            mat.diffuse_color = (0.6, 0.8, 0.9, 0.3)
    elif mat.node_tree:                      # le texture usano le UV (tegole parallele al terreno), non le coordinate generate
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        tc = next((n for n in nodes if n.bl_idname == "ShaderNodeTexCoord"), None)
        mp = next((n for n in nodes if n.bl_idname == "ShaderNodeMapping"), None)
        if tc and mp:
            for l in list(links):
                if l.to_node == mp and l.to_socket.name == "Vector":
                    links.remove(l)
            links.new(tc.outputs["UV"], mp.inputs["Vector"])
    return mat


def _usi_manuali(z):
    import json
    try:
        return json.loads(z.usi_manuali) if z.usi_manuali else {}
    except ValueError:
        return {}


def _params(z):
    return Params(N=z.N, M=z.M, theta=z.theta, ZH=z.ZH,
                  cut=z.cut if z.secondario else 0, M2=z.M2, theta2=z.theta2,
                  tilt=(90.0 if z.posa == "CORICATA" else 0.0), orient=z.orient, px=z.px, py=z.py, pz=z.pz,
                  radial=0.0, pav_taglio=(z.pav_taglio if z.posa == "CORICATA" else -1.0), floor=z.floor, zfloor=z.zfloor, pav_tipo=z.pav_tipo, pav_carico=z.pav_carico, pav_interasse=z.pav_interasse / 100.0, pav_seme=z.pav_seme,
                  ztop=0.0, caps=z.caps,
                  porta=z.porta, porta_dir=z.porta_dir, porta_modo=z.porta_modo, porta_dist=z.porta_dist, porta_w=z.porta_w / 100.0, porta_h=z.porta_h / 100.0, porta_falda=z.porta_falda / 100.0,
                  TW=z.TW / 100.0, pendenza_tetto=z.pendenza_tetto, usi_manuali=z.usi_manuali, catalogo=_catalogo(z),
                  stella_vetri=z.stella_vetri, finestre=z.finestre, strato_finestre=z.strato_finestre,
                  sporgenza_tetto=z.sporgenza / 100.0, traverse=z.traverse)


def costruisci(context, z):
    """(Ri)crea la collection e la mesh dell'interno."""
    global _REBUILDING
    z.errore = ""
    try:
        pr = _params(z)
        model = build(pr)
        if z.esterno:
            shell(model, model["params"])
            model["isolante"] = isolante_guscio(model, z.TT / 100.0)
    except ValueError as e:
        z.errore = str(e)
        return None
    name = z.nome or "zome"
    # pulizia: stessa collection, stesso oggetto, stessa mesh.
    # L'arredo resta: non lo ha generato questa ricostruzione.
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        context.scene.collection.children.link(coll)
    conservare = (f"{name} · Arredo",)

    def _conserva(ob):
        return any(c.name in conservare for c in ob.users_collection)

    for ob in list(coll.all_objects):
        if _conserva(ob):
            continue
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me and me.users == 0:
            bpy.data.meshes.remove(me)
    def L(ob, ruolo):
        """collega l'oggetto alla sotto-collection del suo ruolo (esterno, tetto, interno, struttura...)"""
        nome_s = f"{name} · {ruolo}"
        sub = bpy.data.collections.get(nome_s)
        if sub is None:
            sub = bpy.data.collections.new(nome_s)
        if sub.name not in coll.children:
            coll.children.link(sub)
        sub.objects.link(ob)

    # mesh unica con vertici condivisi
    index, verts, polys, strato_of, faccia_of = {}, [], [], [], []
    for st in model["strata"]:
        for fi, (kind, pts) in enumerate(st["facce"]):
            ids = []
            for q in pts:
                key = (round(q[0], 6), round(q[1], 6), round(q[2], 6))
                if key not in index:
                    index[key] = len(verts)
                    verts.append(q)
                ids.append(index[key])
            polys.append(ids)
            strato_of.append(st["strato"])
            faccia_of.append(fi)
    me = bpy.data.meshes.new(name + "_interno")
    me.from_pydata(verts, [], polys)
    me.update()
    attr = me.attributes.new("strato", 'INT', 'FACE')
    attr.data.foreach_set("value", strato_of)
    af = me.attributes.new("faccia", 'INT', 'FACE')
    af.data.foreach_set("value", faccia_of)
    ns = len(model["strata"])
    for i in range(1, ns + 1):
        mname = f"{name}_strato_{i:02d}"
        mat = bpy.data.materials.get(mname) or bpy.data.materials.new(mname)
        r, g, b = colorsys.hsv_to_rgb((i - 1) / max(ns, 1) * 0.8, 0.55, 0.95)
        mat.diffuse_color = (r, g, b, z.trasparenza)
        mat.surface_render_method = 'BLENDED' if z.trasparenza < 1.0 else 'DITHERED'
        if mat.node_tree:                                   # i nodi hanno nomi tradotti: si cercano per tipo
            for nodo in mat.node_tree.nodes:
                if nodo.bl_idname == "ShaderNodeBsdfPrincipled":
                    nodo.inputs["Base Color"].default_value = (r, g, b, 1.0)
                    nodo.inputs["Alpha"].default_value = z.trasparenza
        me.materials.append(mat)
    for poly, s in zip(me.polygons, strato_of):
        poly.material_index = s - 1
    ob = bpy.data.objects.new(name + "_interno", me)
    ob.show_wire = True
    ob["zome_params"] = json.dumps(model["params"].__dict__)
    ob["zome_summary"] = json.dumps({k: (round(v, 6) if isinstance(v, float) else v)
                                     for k, v in model["summary"].items()})
    L(ob, "Riferimento")
    if z.esterno:                      # con l'esterno acceso l'interno colorato si vedrebbe attraverso i vetri
        ob.hide_viewport = True
    tutti = model.get("caps") or {}
    pareti = {k: v for k, v in tutti.items() if k.startswith("corridoio:")}
    caps = {k: v for k, v in tutti.items() if k not in pareti and k != "pavimento" and z.caps}
    if pareti:
        pv, pp = [], []
        for poly in pareti.values():
            base = len(pv)
            pv.extend(poly)
            pp.append([base + k for k in range(len(poly))])
        mpw = bpy.data.meshes.new(name + "_pareti_porta")
        mpw.from_pydata(pv, [], pp)
        mpw.update()
        cat_w = _catalogo(z)["wood_external"]
        mpw.materials.append(_materiale(cat_w["materiale"], "legno"))
        _uv_pareti(mpw, z)
        opw = bpy.data.objects.new(name + "_pareti_porta", mpw)
        L(opw, "Esterno · legno")
    if caps:
        cv, cp = [], []
        for poly in caps.values():
            base = len(cv)
            cv.extend(poly)
            cp.append([base + k for k in range(len(poly))])
        mc = bpy.data.meshes.new(name + "_tappi")
        mc.from_pydata(cv, [], cp)
        mc.update()
        mm = bpy.data.materials.get(name + "_tappo") or bpy.data.materials.new(name + "_tappo")
        mm.diffuse_color = (0.8, 0.8, 0.75, 1.0)
        mc.materials.append(mm)
        oc = bpy.data.objects.new(name + "_tappi", mc)
        L(oc, "Struttura")
    if z.porta:                                    # telaio sul piano della porta (in entrambi i modi)
        tel = porta_telaio(model["params"], z.TT / 100.0, z.TW / 100.0)
        tv, tp = [], []
        for t_ in tel:
            base = len(tv)
            tv.extend(t_["vertici"])
            cen = tuple(sum(q[j] for q in t_["vertici"]) / 8 for j in range(3))
            for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                v0, v1, v2 = (Vector(t_["vertici"][i]) for i in f[:3])
                nrm = (v1 - v0).cross(v2 - v1)
                fuori = nrm.dot(Vector(t_["vertici"][f[0]]) - Vector(cen)) > 0
                tp.append([base + i for i in (f if fuori else f[::-1])])
        mp = bpy.data.meshes.new(name + "_porta")
        mp.from_pydata(tv, [], tp)
        mp.update()
        mw = bpy.data.materials.get(name + "_legno") or bpy.data.materials.new(name + "_legno")
        mp.materials.append(mw)
        op = bpy.data.objects.new(name + "_porta", mp)
        op["porta_telaio"] = json.dumps([{"nome": t_["nome"], "volume": t_["volume"]} for t_ in tel])
        L(op, "Struttura")
        if z.porta_anta:
            an = porta_anta(model["params"], z.TT / 100.0, apertura=0.0)          # modellata chiusa: l'apertura e' la rotazione della cerniera
            catp = _catalogo(z)
            oa = _mesh_prismi(name + "_anta", an["legno"], _materiale(catp["wood_external"]["materiale"], "legno"), L, "Porta")
            _uv_pareti(oa.data, z)
            gv = [q for poly in an["vetro"] for q in poly]
            mg_ = bpy.data.meshes.new(name + "_anta_vetro")
            mg_.from_pydata(gv, [], [list(range(len(gv)))])
            mg_.update()
            mg_.materials.append(_materiale(catp["glass_external"]["materiale"], "vetro"))
            og_ = bpy.data.objects.new(name + "_anta_vetro", mg_)
            L(og_, "Porta")
            om_ = _mesh_prismi(name + "_anta_maniglia", an["maniglia"], _materiale_tinta("ferro_01", (0.08, 0.08, 0.09), 0.35, 0.8), L, "Porta")
            ce = porta_cerniera(model["params"])
            oce = _mesh_prismi(name + "_anta_cerniere", ce["cerniere"], _materiale_tinta("ferro_01", (0.08, 0.08, 0.09), 0.35, 0.8), L, "Porta")
            emp = bpy.data.objects.new(name + "_cerniera", None)           # asse di rotazione dell'anta (anche per l'animazione)
            emp.empty_display_type = 'ARROWS'
            emp.empty_display_size = 0.08
            emp.location = ce["punto"]
            emp.rotation_mode = 'AXIS_ANGLE'
            emp.rotation_axis_angle = (0.0, *ce["asse"])
            L(emp, "Porta")
            inv = mathutils.Matrix.Translation(Vector(ce["punto"])).inverted()
            for fo_ in (oa, og_, om_, oce):
                fo_.parent = emp
                fo_.matrix_parent_inverse = inv
            emp.rotation_axis_angle = (math.radians(z.porta_apertura), *ce["asse"])
    if model.get("pavimento"):
        _costruisci_pavimento(model["pavimento"], name, z, L)
    if z.esterno and model.get("esterno"):
        cat = _catalogo(z)
        est = [d for d in model["esterno"] if d["copertura_est"]]
        gruppi = (("_legno", "Esterno · legno", [d for d in est if d["uso"] == "legno"]),
                  ("_vetro", "Esterno · vetro", [d for d in est if d["uso"] == "vetro"]),
                  ("_tetto", "Tetto", [d for d in est if d["uso"] == "tetto"]),
                  ("_perline", "Interno · perline", [dict(d, chiave="wood_internal", uso="legno", copertura_est=d["rivestimento_int_alto"],
                                                           copertura_int=d["rivestimento_int"])
                                                     for d in model["esterno"] if d.get("rivestimento_int")]))
        for suffisso, ruolo, voci in gruppi:
            if not voci:
                continue
            chiavi = sorted({d["chiave"] for d in voci})
            ev, ep, ei, es, ef = [], [], [], [], []
            for d in voci:
                top, bot = d["copertura_est"], d["copertura_int"]
                n_ = len(top)
                base = len(ev)
                ev.extend(top); ev.extend(bot)
                lati = [list(range(base, base + n_)),                                  # faccia esterna
                        list(range(base + 2 * n_ - 1, base + n_ - 1, -1))]            # faccia interna (rovesciata)
                for i in range(n_):
                    j = (i + 1) % n_
                    lati.append([base + i, base + n_ + i, base + n_ + j, base + j])   # fianchi
                for pl in lati:
                    ep.append(pl)
                    ei.append(chiavi.index(d["chiave"]))
                    es.append(d["strato"]); ef.append(d["faccia"])
            me = bpy.data.meshes.new(name + suffisso)
            me.from_pydata(ev, [], ep)
            me.update()
            for nome_a, vals in (("strato", es), ("faccia", ef), ("voce", ei)):
                a_ = me.attributes.new(nome_a, 'INT', 'FACE')
                a_.data.foreach_set("value", vals)
            for k in chiavi:
                me.materials.append(_materiale(cat[k]["materiale"], cat[k]["uso"]))
            for poly, i in zip(me.polygons, ei):
                poly.material_index = i
            _uv_orizzontali(me, z.scala_texture, {i: (z.scala_legno if cat[k]["uso"] == "legno" else z.scala_texture) for i, k in enumerate(chiavi)})
            _uv_legno(me, z, chiavi, cat)
            oe = bpy.data.objects.new(name + suffisso, me)
            if suffisso == "_legno":
                oe["esterno_totali"] = json.dumps(model["esterno_totali"])
            else:
                oe.hide_viewport = oe.hide_render = not z.tetto_visibile
            L(oe, ruolo)
            _segna(oe, {"_legno": "tavole", "_vetro": "vetro", "_tetto": "tegole", "_perline": "perline"}.get(suffisso, "perline"))
        if model.get("gronda"):
            gv, gp = [], []
            for g_ in model["gronda"]:
                base = len(gv)
                top, bot = g_["pts"], g_["bot"]
                n_ = len(top)
                gv.extend(top); gv.extend(bot)
                gp.append(list(range(base, base + n_)))                                   # faccia esterna
                gp.append(list(range(base + 2 * n_ - 1, base + n_ - 1, -1)))              # faccia interna
                for i in range(1, n_):                                                    # fianchi (il lato sul rombo resta aperto: la lastra continua)
                    j = (i + 1) % n_
                    gp.append([base + i, base + n_ + i, base + n_ + j, base + j])
            mg = bpy.data.meshes.new(name + "_gronda")
            mg.from_pydata(gv, [], gp)
            mg.update()
            mg.materials.append(_materiale(cat["roof_external"]["materiale"], "tetto"))
            _uv_orizzontali(mg, z.scala_texture)
            og = bpy.data.objects.new(name + "_gronda", mg)
            og.hide_viewport = og.hide_render = not z.tetto_visibile
            L(og, "Tetto")
    if model.get("isolante"):
        prismi = [sl["in"] + sl["out"] for sl in model["isolante"]]
        ob_i = _mesh_prismi(name + "_isolante", prismi, _materiale_tinta("isolante_01", (0.86, 0.78, 0.45), 0.85), L, "Isolante")
        _segna(ob_i, _nome_isolante(z.isolante))
    model["scheletro"] = None
    if z.scheletro:
        try:
            bl = beams(model, z.TT / 100.0, z.TW / 100.0, z.giunto, True, z.densita)
        except ValueError as e:
            z.errore = str(e)
            bl = []
        if bl:
            cl = cutlist(bl)
            classe = {}
            for i, g in enumerate(cl):
                classe[chiave_taglio(g)] = i
            tv, tp, f_strato, f_classe = [], [], [], []
            for b in bl:
                base = len(tv)
                tv.extend(b["vertici"])
                for f in BEAM_FACES:
                    tp.append([base + k for k in f])
                    f_strato.append(b["strato"])
                    f_classe.append(classe[chiave_taglio(b)])
            mt = bpy.data.meshes.new(name + "_scheletro")
            mt.from_pydata(tv, [], tp)
            mt.update()
            for nome_attr, vals in (("strato", f_strato), ("classe", f_classe)):
                a = mt.attributes.new(nome_attr, 'INT', 'FACE')
                a.data.foreach_set("value", vals)
            mw = bpy.data.materials.get(name + "_legno") or bpy.data.materials.new(name + "_legno")
            mw.diffuse_color = (0.72, 0.5, 0.28, 1.0)
            for nodo in (mw.node_tree.nodes if mw.node_tree else []):
                if nodo.bl_idname == "ShaderNodeBsdfPrincipled":
                    nodo.inputs["Base Color"].default_value = (0.72, 0.5, 0.28, 1.0)
            mt.materials.append(mw)
            ot = bpy.data.objects.new(name + "_scheletro", mt)
            ot["scheletro_summary"] = json.dumps(beams_summary(bl, z.TT / 100.0, z.TW / 100.0))
            ot["scheletro_cutlist"] = json.dumps(cl)
            L(ot, "Struttura")
            _segna(ot, "c24")
            model["scheletro"] = {"lista": bl, "cutlist": cl, "summary": beams_summary(bl, z.TT / 100.0, z.TW / 100.0)}
    try:                                           # arredo e animazione seguono la zome ricostruita
        zome_viste.aggiorna_arredo(context.scene, z, model)
        if zome_viste.animazione_esiste(z):
            zome_viste.crea_animazione(context.scene, z, model, z.anim_secondi, z.anim_sole)
        zome_viste.aggiorna_spaccato(context.scene, z)          # per ultimo: taglia anche il nuovo arredo
    except Exception as e:                         # sono solo resa: un errore qui non deve fermare la zome
        print("zome_viste:", e)
    return model


_STATICA_CACHE = {"esito": None}


def _update(self, context):
    if _REBUILDING or not self.live:
        return
    _STATICA_CACHE["esito"] = None
    if self.statica_testo:
        self.statica_testo = ""
    costruisci(context, self)


def _update_statica_momento(self, context):
    """Cambia solo il disegno del momento. Non ricalcola il telaio e non ricostruisce la zome."""
    esito = _STATICA_CACHE.get("esito")
    if not esito or not esito.get("ok"):
        return
    try:
        _statica_disegna(context, self.nome or "zome", esito, fuori_m=self.TW / 100.0 + 0.04)
    except Exception as e:
        print("statica momento:", e)


def _update_sole(self, context):
    zome_viste.aggiorna_sole(self)


def _update_arredo(self, context):
    zome_viste.aggiorna_arredo(context.scene, self, _model_for(self))
    zome_viste.aggiorna_spaccato(context.scene, self)


def _update_spaccato(self, context):
    zome_viste.aggiorna_spaccato(context.scene, self)


# ---------------------------------------------------------------------------------------------------------------- preset
_PRESET_ESCLUSI = {"nome", "live", "errore", "preset_nome", "preset_scelta", "rna_type", "name", "statica_testo"}
_PRESET_PREFISSI = ("sole_", "arredo_", "anim_", "spaccato")          # solo resa: non fanno parte del modello
_preset_voci = []


def _nome_file(nome):
    pulito = "".join(c for c in nome.strip() if c not in '\\/:*?"<>|').strip(" .")
    return pulito


def _cartella_istanze():
    return os.path.join(_ROOT or bpy.utils.user_resource('CONFIG'), "Istanze")


def _cartella_istanza(nome):
    return os.path.join(_cartella_istanze(), nome)


def _elenco_preset():
    """Un preset per istanza: Istanze/<nome>/preset.json. Il nome in elenco è la cartella."""
    d = _cartella_istanze()
    try:
        return sorted(
            voce for voce in os.listdir(d)
            if os.path.isfile(os.path.join(d, voce, "preset.json")))
    except OSError:
        return []


_PARAMETRI_GRUPPI = (
    ("Forma", ("N", "M", "theta", "ZH", "secondario", "cut", "M2", "theta2")),
    ("Posa e tagli", ("posa", "tilt", "pav_taglio", "orient", "px", "py", "pz", "caps", "radial", "parete_alta", "ztop")),
    ("Pavimento", ("floor", "zfloor", "pav_tipo", "pav_carico", "pav_interasse", "pav_seme")),
    ("Porta", ("porta", "porta_modo", "porta_dir", "porta_dist", "porta_w", "porta_h", "porta_anta", "porta_apertura", "porta_falda")),
    ("Esterno", ("esterno", "tetto_visibile", "stella_vetri", "finestre", "strato_finestre", "pendenza_tetto", "isolante",
                 "t_tetto", "t_legno", "t_vetro", "t_int_legno", "sporgenza", "larghezza_assi", "larghezza_perline",
                 "scala_legno", "scala_texture", "seme_legno", "usi_manuali", "trasparenza")),
    ("Scheletro", ("scheletro", "TT", "TW", "giunto", "densita", "traverse", "statica_neve", "statica_momento")),
    ("Report", ("foglio_esterno", "foglio_perline", "foglio_vetro", "foglio_travi")),
)
_NOMI_PARAMETRI = {
    "theta": "θ (°)", "ZH": "ZH (m)", "secondario": "Riduzione punta", "cut": "Anello di taglio",
    "M2": "M secondario", "theta2": "θ secondario (°)", "posa": "Posa", "tilt": "Inclinazione nel file vecchio (°)",
    "pav_taglio": "Pavimento nella zome (%)", "orient": "Orientamento (°)", "caps": "Chiudi i tagli",
    "floor": "Pavimento", "zfloor": "Quota pavimento (m)", "pav_tipo": "Fondazione",
    "pav_carico": "Carico (kN/m²)", "pav_interasse": "Interasse (cm)", "pav_seme": "Seme pietre",
    "porta_modo": "Modo", "porta_dir": "Direzione porta (°)", "porta_dist": "Distanza porta (m)",
    "porta_w": "Larghezza porta (cm)", "porta_h": "Altezza porta (cm)", "porta_anta": "Anta",
    "porta_apertura": "Apertura anta (°)", "porta_falda": "Falda (cm)", "tetto_visibile": "Tetto visibile",
    "stella_vetri": "Stella di vetri", "strato_finestre": "Strato finestre", "pendenza_tetto": "Pendenza max tetto (°)",
    "t_tetto": "Tetto (cm)", "t_legno": "Legno est. (cm)", "t_vetro": "Vetro est. (cm)",
    "t_int_legno": "Perline int. (cm)", "sporgenza": "Gronda (cm)", "larghezza_assi": "Larghezza assi (cm)",
    "larghezza_perline": "Larghezza perline (cm)", "scala_legno": "Scala legno (m)",
    "scala_texture": "Scala texture (m)", "seme_legno": "Seme legno", "usi_manuali": "Scelte a mano",
    "TT": "TT (cm)", "TW": "TW (cm)", "giunto": "Giunto", "densita": "Densità (kg/m³)",
    "statica_neve": "Neve (kN/m²)", "statica_momento": "Momento",
    "foglio_esterno": "Nel report: esterno", "foglio_perline": "Nel report: perline",
    "foglio_vetro": "Nel report: vetrocamera", "foglio_travi": "Nel report: travi e travetti",
}
_INIZIO_PARAMETRI = "<!-- parametri -->"
_FINE_PARAMETRI = "<!-- /parametri -->"


def _fmt_parametro(v):
    if isinstance(v, bool):
        return "sì" if v else "no"
    if isinstance(v, float):
        t = f"{v:.3f}".rstrip("0").rstrip(".")
        return t if t not in ("", "-") else "0"
    if v == "" or v is None:
        return "—"
    return str(v)


def _testo_parametri(dati):
    usati = set()
    righe = []
    for titolo, chiavi in _PARAMETRI_GRUPPI:
        presenti = [k for k in chiavi if k in dati]
        if not presenti:
            continue
        righe.append(f"### {titolo}")
        righe.append("")
        for k in presenti:
            usati.add(k)
            righe.append(f"- {_NOMI_PARAMETRI.get(k, k)}: {_fmt_parametro(dati[k])}")
        righe.append("")
    altri = [k for k in dati if k not in usati]
    if altri:
        righe.append("### Altro")
        righe.append("")
        for k in altri:
            righe.append(f"- {k}: {_fmt_parametro(dati[k])}")
        righe.append("")
    return "\n".join(righe).rstrip() + "\n"


def _blocco_parametri(dati):
    return _INIZIO_PARAMETRI + "\n" + _testo_parametri(dati) + _FINE_PARAMETRI + "\n"


def _assicura_istanza(nome):
    """Crea la cartella e, se manca, README.md: è il file che si trova aprendo la cartella."""
    d = _cartella_istanza(nome)
    os.makedirs(d, exist_ok=True)
    note = os.path.join(d, "README.md")
    if not os.path.isfile(note):
        with open(note, "w", encoding="utf-8") as f:
            f.write(
                f"# {nome}\n\n"
                "Requisiti di questa istanza. È il file da leggere insieme al blend.\n\n"
                "## Requisiti\n\n"
                "(da scrivere)\n\n"
                "## Parametri del pannello\n\n"
                "Copia leggibile di `preset.json`. Salva nel pannello aggiorna solo il blocco qui sotto; "
                "i requisiti restano. Strati, pezzi e preventivo stanno in `report.html`.\n\n"
                + _blocco_parametri({}))
    return d


def _aggiorna_readme(nome, dati):
    """Sostituisce solo il blocco dei parametri. I requisiti scritti a mano restano."""
    d = _assicura_istanza(nome)
    path = os.path.join(d, "README.md")
    with open(path, encoding="utf-8") as f:
        testo = f.read()
    blocco = _blocco_parametri(dati).rstrip("\n")
    if _INIZIO_PARAMETRI in testo and _FINE_PARAMETRI in testo:
        pre, resto = testo.split(_INIZIO_PARAMETRI, 1)
        _, post = resto.split(_FINE_PARAMETRI, 1)
        testo = pre + blocco + post
    else:
        testo = testo.rstrip() + "\n\n## Parametri del pannello\n\n" + blocco + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(testo)


def _items_preset(self, context):
    global _preset_voci
    nomi = _elenco_preset()
    _preset_voci = [(n, n, "") for n in nomi] or [("_nessuno_", "(nessun preset)", "")]
    return _preset_voci


def _update_preset_scelta(self, context):
    if self.preset_scelta and self.preset_scelta != "_nessuno_":
        self.preset_nome = self.preset_scelta


def _dati_modello(z):
    d = {}
    for p in z.bl_rna.properties:
        k = p.identifier
        if k in _PRESET_ESCLUSI or k.startswith(_PRESET_PREFISSI):
            continue
        v = getattr(z, k)
        if p.type in ('FLOAT', 'INT', 'BOOLEAN') and getattr(p, "array_length", 0):
            v = list(v)
        d[k] = v
    return d


class ZOME_OT_preset_salva(bpy.types.Operator):
    bl_idname = "zome.preset_salva"
    bl_label = "Salva preset"
    bl_description = "Salva i parametri in Istanze/<nome>/preset.json e aggiorna la copia nel README. I requisiti scritti a mano restano"

    def execute(self, context):
        z = context.scene.zome
        nome = _nome_file(z.preset_nome)
        if not nome:
            self.report({'ERROR'}, "Scrivi un nome per l'istanza")
            return {'CANCELLED'}
        d = _assicura_istanza(nome)
        dati = _dati_modello(z)
        with open(os.path.join(d, "preset.json"), "w", encoding="utf-8") as f:
            json.dump({"zome_preset": 1, "dati": dati}, f, ensure_ascii=False, indent=1)
        _aggiorna_readme(nome, dati)
        z.preset_nome = nome
        try:
            z.preset_scelta = nome
        except TypeError:
            pass
        self.report({'INFO'}, f"Istanza «{nome}» salvata")
        return {'FINISHED'}


class ZOME_OT_preset_carica(bpy.types.Operator):
    bl_idname = "zome.preset_carica"
    bl_label = "Carica preset"
    bl_description = "Applica il preset scelto e ricostruisce la zome (i parametri non presenti nel preset restano come sono)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        global _REBUILDING
        z = context.scene.zome
        nome = z.preset_scelta
        if not nome or nome == "_nessuno_":
            self.report({'ERROR'}, "Nessuna istanza scelta")
            return {'CANCELLED'}
        try:
            with open(os.path.join(_cartella_istanza(nome), "preset.json"), encoding="utf-8") as f:
                dati = json.load(f)["dati"]
        except (OSError, ValueError, KeyError) as e:
            self.report({'ERROR'}, f"Preset illeggibile: {e}")
            return {'CANCELLED'}
        if "posa" not in dati and abs(float(dati.get("tilt", 0.0))) > 45.0:        # preset vecchi: inclinazione -> zome coricata
            dati = {**dati, "posa": "CORICATA"}
        _REBUILDING = True                                 # un solo ricalcolo alla fine, non uno per parametro
        saltati = []
        try:
            for k, v in dati.items():
                if k in _PRESET_ESCLUSI or k not in z.bl_rna.properties:
                    saltati.append(k)
                    continue
                try:
                    setattr(z, k, v)
                except (TypeError, ValueError, AttributeError):
                    saltati.append(k)
        finally:
            _REBUILDING = False
        costruisci(context, z)
        self.report({'INFO'}, f"Istanza «{nome}» caricata" + (f" (ignorati: {', '.join(saltati)})" if saltati else ""))
        return {'FINISHED'}


class ZOME_OT_preset_elimina(bpy.types.Operator):
    bl_idname = "zome.preset_elimina"
    bl_label = "Elimina preset"
    bl_description = "Toglie preset.json dell'istanza scelta. Appunti e blend restano (chiede conferma)"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        nome = context.scene.zome.preset_scelta
        if not nome or nome == "_nessuno_":
            return {'CANCELLED'}
        try:
            os.remove(os.path.join(_cartella_istanza(nome), "preset.json"))
        except OSError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        context.scene.zome.preset_nome = ""
        return {'FINISHED'}



_ISOLANTI_VOCI = {"elenco": None}


def _voci_isolanti(self, context):
    """Nomi del foglio materiali, categoria isolanti. Il valore salvato è il nome della riga."""
    if _ISOLANTI_VOCI["elenco"] is None:
        try:
            prezzi = zome_foglio.carica_prezzi(os.path.join(_HERE, "Riferimenti", "proprieta_materiali.xlsx"))
            _ISOLANTI_VOCI["elenco"] = zome_foglio.elenco_isolanti(prezzi)
        except (OSError, KeyError, ValueError):
            _ISOLANTI_VOCI["elenco"] = [("Canapa", "Canapa", "")]
    return _ISOLANTI_VOCI["elenco"]


class ZomeProps(bpy.types.PropertyGroup):
    nome: StringProperty(name="Nome", default="zome", description="Nome della collection che contiene la zome")
    N: IntProperty(name="N", default=8, min=3, max=40, update=_update,
                   description="Lati del poligono di base (= rombi per strato)")
    M: IntProperty(name="M", default=7, min=2, max=40, update=_update,
                   description="Livelli (anelli di vertici, apice e terra compresi); gli strati sono M-1")
    theta: FloatProperty(name="θ", default=55.0, min=1.0, max=89.0, update=_update,
                         description="Angolo degli elementi del primo strato con la verticale (gradi)")
    ZH: FloatProperty(name="ZH", default=2.9, min=0.05, max=30.0, unit='LENGTH', update=_update,
                      description="Altezza della zome primaria (m)")
    secondario: BoolProperty(name="Riduzione punta", default=True, update=_update,
                             description="Abbassa la punta: sopra l'anello di taglio si appoggia un secondo zome (zome secondario) con lo stesso N")
    cut: IntProperty(name="Anello di taglio", default=2, min=1, max=40, update=_update,
                     description="Anello (contato dall'apice) su cui poggia il secondario")
    M2: IntProperty(name="M secondario", default=3, min=2, max=40, update=_update, description="Livelli del secondario")
    theta2: FloatProperty(name="θ secondario", default=60.0, min=1.0, max=89.0, update=_update,
                          description="Angolo del primo strato del secondario (gradi)")
    posa: EnumProperty(name="Posa", default="DRITTA", update=_update,
                       items=[("DRITTA", "Zome dritta", "Asse verticale: la base poggia sul pavimento"),
                              ("CORICATA", "Zome coricata", "Asse orizzontale (90°), a mezzo sigaro: il pavimento taglia la zome a triangoli interi")])
    pav_taglio: FloatProperty(name="Pavimento nella zome", default=50.0, min=0.0, max=100.0, subtype='PERCENTAGE', update=_update,
                              description="Zome coricata: dove il pavimento taglia. 0 = niente taglio (il pavimento tocca solo il fondo), 100 = resta solo la cima. Il taglio segue i triangoli: i rombi si spezzano e il pavimento passa per la base dei triangoli rimasti")
    orient: FloatProperty(name="Orientamento °", default=0.0, min=-180.0, max=180.0, update=_update,
                          description="Rotazione attorno a Z, dopo l'inclinazione")
    px: FloatProperty(name="X", default=0.0, unit='LENGTH', update=_update)
    py: FloatProperty(name="Y", default=0.0, unit='LENGTH', update=_update)
    pz: FloatProperty(name="Z", default=0.0, unit='LENGTH', update=_update)
    floor: BoolProperty(name="Pavimento", default=True, update=_update,
                        description="La zome poggia sul piano z = quota: si tiene la parte sopra (anche se coricata o inclinata) e si costruiscono fondazione, dormienti, travetti e tavolato")
    zfloor: FloatProperty(name="Quota", default=0.40, unit='LENGTH', update=_update,
                          description="Quota del piano di appoggio dei triangoli (sopra dormienti o pali) dal terreno")
    pav_tipo: EnumProperty(name="Fondazione", update=_update, default="muretto",
                           items=[("muretto", "Muretto a secco", "Muretto di pietre irregolari (~40 cm) con un dormiente sopra e due varchi opposti per aerare e ispezionare"),
                                  ("pietroni", "Pietroni e pali", "Un pietrone per ogni vertice e un palo squadrato di sopra, da un pietrone al successivo")])
    pav_carico: FloatProperty(name="Carico (kN/m²)", default=0.5, min=0.5, max=6.0, update=_update, description="Carico di riferimento del solaio. 0,5 kN/m² sono circa 50 kg/m²: con la sezione data si calcola l'interasse")
    pav_interasse: FloatProperty(name="Interasse (cm)", default=40.0, min=20.0, max=80.0, update=_update, description="Distanza tra i travetti")
    pav_seme: IntProperty(name="Seme pietre", default=1, min=0, max=9999, update=_update, description="Cambia l'irregolarita' delle pietre")
    caps: BoolProperty(name="Chiudi i tagli", default=True, update=_update,
                       description="Disegna le pareti di chiusura (tappi) sui piani di taglio")
    porta: BoolProperty(name="Porta", default=False, update=_update,
                        description="Taglia la zome con un piano verticale e lascia nella parete un vano di porta con le misure minime indicate")
    porta_modo: EnumProperty(name="Modo", update=_update, default="parete",
                             items=[("parete", "Parete", "Taglia la zome con una parete verticale e un vano di porta"),
                                    ("corridoio", "Corridoio", "Zome intera con un passaggio a casetta: le pareti collegano il telaio al profilo d'incontro col guscio. Piano della porta dentro la zome: il passaggio va verso fuori; piano fuori dalla zome: va verso la zome")])
    porta_dir: FloatProperty(name="Direzione °", default=0.0, min=-180.0, max=180.0, update=_update,
                             description="Direzione verso la porta, nel sistema della zome: 0 = sud (-Y), 90 = est (+X), -90 = ovest, 180 = nord")
    porta_dist: FloatProperty(name="Distanza", default=1.0, min=0.05, max=30.0, unit='LENGTH', update=_update,
                              description="Distanza del piano di taglio dall'asse; si tiene la parte verso l'asse")
    porta_w: FloatProperty(name="Larghezza (cm)", default=80.0, min=10.0, max=500.0, update=_update, description="Larghezza minima del vano")
    porta_h: FloatProperty(name="Altezza (cm)", default=200.0, min=10.0, max=500.0, update=_update, description="Altezza minima del vano, dal piano della base (in corridoio: al colmo)")
    porta_anta: BoolProperty(name="Anta", default=True, update=_update, description="Disegna l'anta: legno con una finestra a rombo di vetro, socchiusa verso l'interno")
    porta_apertura: FloatProperty(name="Apertura (°)", default=0.0, min=0.0, max=100.0, update=_update, description="Di quanto e' socchiusa l'anta")
    porta_falda: FloatProperty(name="Falda (cm)", default=15.0, min=0.0, max=100.0, update=_update, description="Corridoio: i lati del soffitto sono piu' bassi del colmo di questa quota (soffitto a due falde, scola la pioggia); 0 = piano")
    esterno: BoolProperty(name="Esterno", default=False, update=_update,
                          description="Disegna la superficie esterna (copertura): tetto, legno, vetro")
    tetto_visibile: BoolProperty(name="Tetto visibile", default=True, update=_update,
                                 description="Mostra o nasconde il tetto (e la gronda); il legno sotto resta sempre e i conteggi non cambiano")
    stella_vetri: BoolProperty(name="Stella di vetri", default=True, update=_update, description="Lo strato 1 (cima) tutto a vetro")
    finestre: IntProperty(name="Finestre", default=3, min=0, max=20, update=_update, description="Numero di finestre a vetro distribuite sullo strato indicato")
    strato_finestre: IntProperty(name="Strato finestre", default=4, min=1, max=40, update=_update)
    sporgenza: FloatProperty(name="Gronda (cm)", default=10.0, min=0.0, max=60.0, update=_update, description="Quanto il tetto sporge oltre il bordo basso")
    scala_legno: FloatProperty(name="Scala legno (m)", default=1.0, min=0.02, max=5.0, update=_update, description="Lato in metri di una ripetizione della grana del legno")
    larghezza_assi: FloatProperty(name="Larghezza assi (cm)", default=12.0, min=2.0, max=40.0, update=_update,
                                  description="Larghezza media delle assi del legno esterno; ogni faccia la varia a caso (da 0,8 a 1,25 volte)")
    seme_legno: IntProperty(name="Seme legno", default=1, min=0, max=100000, update=_update,
                            description="Cambia il numero per rimescolare direzione, larghezza e tono delle assi di ogni faccia")
    pendenza_tetto: FloatProperty(name="Pendenza max tetto °", default=65.0, min=0.0, max=90.0, update=_update,
                                  description="Per regola una faccia e' tetto se guarda in su e la sua inclinazione sull'orizzontale e' al massimo questa; il resto e' legno")
    usi_manuali: StringProperty(default="", description="Scelte fatte a mano per faccia (JSON); vuoto = solo regola")
    scala_texture: FloatProperty(name="Scala texture (m)", default=1.0, min=0.05, max=10.0, update=_update,
                                 description="Lato in metri di una ripetizione della texture")
    t_tetto: FloatProperty(name="Tetto (cm)", default=0.3, min=0.0, max=50.0, update=_update, description="Spessore della bituminosa, in cm. 0,3 = 3 mm, lo spessore del prodotto nel foglio materiali")
    t_legno: FloatProperty(name="Legno est. (cm)", default=2.0, min=0.0, max=50.0, update=_update, description="Spessore del rivestimento esterno in legno (wood_external)")
    t_vetro: FloatProperty(name="Vetro est. (cm)", default=1.0, min=0.0, max=50.0, update=_update, description="Spessore del vetro, sempre esterno (glass_external)")
    t_int_legno: FloatProperty(name="Perline int. (cm)", default=1.5, min=0.0, max=50.0, update=_update, description="Rivestimento interno in legno (wood_internal); 0 = nessuno")
    isolante: EnumProperty(name="Isolante", items=_voci_isolanti, update=_update,
                           description="Materiale che riempie i rombi opachi e lo spazio fra i travetti. L'elenco è la categoria Isolanti del foglio materiali")
    larghezza_perline: FloatProperty(name="Larg. perline (cm)", default=9.0, min=2.0, max=30.0, update=_update, description="Larghezza delle perline interne")
    foglio_esterno: BoolProperty(name="Esterno", default=True, description="Nel report: tavole esterne, tetto, pareti della porta")
    foglio_perline: BoolProperty(name="Perline", default=True, description="Nel report: rivestimento interno")
    foglio_vetro: BoolProperty(name="Vetrocamera", default=True, description="Nel report: vetri delle facce e dell'anta")
    foglio_travi: BoolProperty(name="Travi e travetti", default=True, description="Nel report: scheletro, telaio, anta, dormienti e travetti")
    scheletro: BoolProperty(name="Scheletro", default=True, update=_update,
                         description="Disegna lo scheletro: le tavole di struttura sul bordo di ogni rombo (parallelepipedi perpendicolari al piano del rombo)")
    TT: FloatProperty(name="Spessore (cm)", default=2.0, min=0.1, max=30.0, update=_update,
                      description="Spessore del pezzo di scheletro, nel piano del rombo")
    TW: FloatProperty(name="Altezza (cm)", default=5.0, min=0.1, max=60.0, update=_update,
                      description="Altezza del pezzo di scheletro, perpendicolare al rombo, verso l'esterno")
    giunto: EnumProperty(name="Giunto", default="butt_ccw", update=_update,
                         items=[("butt_ccw", "Testa-testa (antiorario)", ""), ("butt_cw", "Testa-testa (orario)", ""),
                                ("miter", "A 45° (bisettrice)", "")])
    densita: FloatProperty(name="Densità (kg/m³)", default=700.0, min=100.0, max=1500.0, update=_update)
    traverse: StringProperty(name="Traverse", default="", update=_update,
                             description="Per strato: t = tra anelli, a = sull'anello. Esempio 1:ta,4:t. Lo compila la tabella nello Scheletro")
    statica_neve: FloatProperty(name="Neve (kN/m²)", default=1.0, min=0.0, max=10.0,
                                description="Neve sulla proiezione orizzontale delle facce che guardano in su. Non ricostruisce la zome")
    statica_momento: EnumProperty(
        name="Momento", default="CIRCOLARE", update=_update_statica_momento,
        items=[("CIRCOLARE", "Circolare", "Freccia circolare nel piano in cui l'asta tende a ruotare"),
               ("VETTORE", "Vettore", "Asse di rotazione, perpendicolare a quel piano")],
        description="Come disegnare il momento. Non ricalcola e non ricostruisce la zome")
    statica_testo: StringProperty(name="Risultato statica", default="",
                                  description="Ultimo rapporto del telaio. Si azzera quando cambi la forma")
    trasparenza: FloatProperty(name="Trasparenza", default=1.0, min=0.0, max=1.0, update=_update,
                               description="1 = opaco")
    live: BoolProperty(name="Aggiorna subito", default=True, description="Ricostruisce a ogni modifica")
    sole_mese: IntProperty(name="Mese", default=6, min=1, max=12, update=_update_sole, description="Mese per la posizione del sole")
    sole_giorno: IntProperty(name="Giorno", default=21, min=1, max=31, update=_update_sole)
    sole_ora: FloatProperty(name="Ora", default=12.0, min=0.0, max=24.0, update=_update_sole,
                            description="Ora civile italiana (legale o solare secondo la data); Neirone, 44,4° N 9,2° E")
    arredo_mobili: BoolProperty(name="Mobili", default=False, update=_update_arredo,
                                description="Il letto 160 x 190 cm, senza testiera, contro la parete opposta alla porta (cucina e scrivania tolte il 21/10/2026)")
    arredo_persone: BoolProperty(name="Persone", default=False, update=_update_arredo, description="Un uomo e una donna in piedi")
    spaccato: FloatProperty(name="Spaccato", default=0.0, min=0.0, max=100.0, subtype='PERCENTAGE', update=_update_spaccato,
                            description="0 = zome intera, 50 = tagliata a meta' con un piano verticale, 100 = sparita")
    spaccato_dir: FloatProperty(name="Lato (°)", default=0.0, min=-180.0, max=180.0, update=_update_spaccato,
                                description="Lato che si toglie: 0 = sud (si guarda da sud dentro la zome), 90 = est, 180 = nord, -90 = ovest")
    anim_secondi: FloatProperty(name="Durata (s)", default=40.0, min=8.0, max=120.0, description="Durata della visita animata")
    anim_distanza: FloatProperty(name="Distanza giro", default=1.3, min=0.9, max=5.0,
                                 description="Distanza della camera nel giro aereo, in multipli dell'ingombro della zome: piu' basso = piu' vicina")
    anim_sole: BoolProperty(name="Il sole fa il giro", default=True, description="Durante la visita il sole va dall'alba al tramonto")
    errore: StringProperty(default="")
    preset_nome: StringProperty(name="Nome", default="", description="Nome dell'istanza: cartella in Istanze/")
    preset_scelta: EnumProperty(name="Istanza", items=_items_preset, update=_update_preset_scelta,
                                description="Istanze con preset.json in Istanze/<nome>/")


class ZOME_OT_crea(bpy.types.Operator):
    bl_idname = "zome.crea"
    bl_label = "Crea / ricrea zome"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        m = costruisci(context, context.scene.zome)
        if m is None:
            self.report({'ERROR'}, context.scene.zome.errore)
            return {'CANCELLED'}
        return {'FINISHED'}


class ZOME_OT_reimposta(bpy.types.Operator):
    bl_idname = "zome.reimposta"
    bl_label = "Reimposta tutto"
    bl_description = "Riporta tutti i parametri ai valori iniziali (il nome si conserva); chiede conferma"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        z = context.scene.zome
        nome = z.nome
        for p in z.bl_rna.properties:
            if p.identifier != "rna_type":
                z.property_unset(p.identifier)
        z.nome = nome
        costruisci(context, z)
        return {'FINISHED'}


_cache = {}


def _model_for(z):
    key = (z.N, z.M, round(z.theta, 6), round(z.ZH, 6), z.secondario, z.cut, z.M2, round(z.theta2, 6),
           z.posa, z.pav_taglio, z.orient, z.px, z.py, z.pz, z.floor, z.zfloor, z.pav_tipo, z.pav_carico, z.pav_interasse, z.pav_seme, z.caps,
           z.esterno, z.pendenza_tetto, z.usi_manuali, z.scala_texture, z.scala_legno, z.larghezza_assi, z.seme_legno, z.stella_vetri, z.finestre, z.strato_finestre, z.sporgenza, z.t_tetto, z.t_legno, z.t_vetro, z.t_int_legno, z.larghezza_perline,
           z.porta, z.porta_modo, z.porta_dir, round(z.porta_dist, 6), z.porta_w, z.porta_h, z.porta_falda, z.porta_anta, z.porta_apertura,
           z.scheletro, round(z.TT, 4), round(z.TW, 4), z.giunto, round(z.densita, 2), z.traverse)
    if key not in _cache:
        if len(_cache) > 20:
            _cache.clear()
        try:
            pr = _params(z)
            mod = build(pr)
            if z.esterno:
                shell(mod, mod["params"])
                mod["isolante"] = isolante_guscio(mod, z.TT / 100.0)
            mod["scheletro"] = None
            if z.scheletro:
                bl = beams(mod, z.TT / 100.0, z.TW / 100.0, z.giunto, True, z.densita)
                mod["scheletro"] = {"cutlist": cutlist(bl), "summary": beams_summary(bl, z.TT / 100.0, z.TW / 100.0)}
            _cache[key] = mod
        except ValueError:
            _cache[key] = None
    return _cache[key]


class ZOME_OT_zh_altezza(bpy.types.Operator):
    bl_idname = "zome.zh_altezza"
    bl_label = "ZH per l'altezza totale"
    bl_description = ("Cambia ZH finche' l'altezza ESTERNA da terra (con la copertura del tetto, i vetri e il pavimento sollevato) "
                      "e' quella scelta; con la riduzione punta attiva e' il secondario a adeguarsi")
    bl_options = {'REGISTER', 'UNDO'}
    altezza: FloatProperty(name="Altezza totale (m)", default=3.0, min=1.0, max=30.0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        z = context.scene.zome
        try:
            zh = zome_core.solve_secondary_total_height(_params(z), self.altezza, esterna=z.esterno)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        z.ZH = zh
        self.report({'INFO'}, f"ZH = {zh:.3f} m per {self.altezza:.2f} m totali")
        return {'FINISHED'}


_aggiornamento = {"stato": "", "remota": "", "tag": ""}


def _versione_tupla(testo):
    testo = (testo or "").strip().lstrip("vV")
    numeri = []
    for pezzo in testo.split("."):
        cifre = ""
        for c in pezzo:
            if c.isdigit():
                cifre += c
            else:
                break
        if not cifre:
            return None
        numeri.append(int(cifre))
    return tuple(numeri) if numeri else None


def _chiedi_json(url):
    richiesta = urllib.request.Request(url, headers={
        "User-Agent": "BlenderZome",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(richiesta, timeout=15) as risposta:
        return json.loads(risposta.read().decode("utf-8"))


def _controlla_versione():
    try:
        tag = ""
        try:
            dati = _chiedi_json(f"https://api.github.com/repos/{_REPO}/releases/latest")
            tag = dati.get("tag_name") or ""
        except Exception:
            dati = _chiedi_json(f"https://api.github.com/repos/{_REPO}/tags")
            migliore = None
            for voce in dati:
                nome = voce.get("name") or ""
                t = _versione_tupla(nome)
                if t is not None and (migliore is None or t > migliore[0]):
                    migliore = (t, nome)
            tag = migliore[1] if migliore else ""
        locale = _versione_tupla(VERSIONE)
        remota = _versione_tupla(tag)
        _aggiornamento["tag"] = tag
        _aggiornamento["remota"] = tag.lstrip("vV")
        if remota and locale and remota > locale:
            _aggiornamento["stato"] = "nuova"
        elif tag:
            _aggiornamento["stato"] = "attuale"
        else:
            _aggiornamento["stato"] = "errore"
            print("Zome: nessuna release da confrontare")
    except Exception as exc:
        _aggiornamento["stato"] = "errore"
        print("Zome: controllo versione non riuscito:", exc)


def _ridisegna_pannello():
    if _aggiornamento["stato"] == "":
        return 0.5
    try:
        for finestra in bpy.context.window_manager.windows:
            for area in finestra.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass
    return None


def _avvia_controllo():
    if _aggiornamento["stato"] == "":
        threading.Thread(target=_controlla_versione, daemon=True).start()
        if not bpy.app.timers.is_registered(_ridisegna_pannello):
            bpy.app.timers.register(_ridisegna_pannello, first_interval=0.5)
    return None


def _estrai_sistema(dati, destinazione):
    """Copia dal ZIP solo i file sotto sistema/. Un percorso che esce dalla cartella si scarta."""
    destinazione = os.path.normpath(destinazione)
    scritti = 0
    with zipfile.ZipFile(io.BytesIO(dati)) as archivio:
        for info in archivio.infolist():
            nome = info.filename.replace("\\", "/")
            marca = "/sistema/"
            indice = ("/" + nome).find(marca)
            if indice < 0:
                continue
            relativo = ("/" + nome)[indice + len(marca):]
            if not relativo or relativo.endswith("/"):
                continue
            parti = relativo.split("/")
            if ".." in parti or any(p.startswith(".") for p in parti):
                continue
            if relativo.endswith(".pyc") or "/__pycache__/" in relativo:
                continue
            arrivo = os.path.normpath(os.path.join(destinazione, *parti))
            try:
                if os.path.commonpath([destinazione, arrivo]) != destinazione:
                    continue
            except ValueError:
                continue
            os.makedirs(os.path.dirname(arrivo), exist_ok=True)
            with archivio.open(info) as sorgente, open(arrivo, "wb") as uscita:
                uscita.write(sorgente.read())
            scritti += 1
    if scritti == 0:
        raise RuntimeError("nello ZIP non c'è sistema/")
    return scritti


def _copia_loader():
    sorgente = os.path.join(_ROOT, "sistema", "zome_loader.py")
    appdata = os.environ.get("APPDATA", "")
    if not appdata or not os.path.isfile(sorgente):
        return
    arrivo = os.path.join(appdata, "Blender Foundation", "Blender", "5.2", "scripts", "addons", "zome_loader.py")
    if os.path.isdir(os.path.dirname(arrivo)):
        shutil.copyfile(sorgente, arrivo)


def _ricarica_pannello():
    unregister()
    for nome in list(sys.modules):
        if nome in ("blenderzome", "zome_core", "zome_pavimento", "zome_viste", "zome_statica", "zome_foglio", "zome_scena"):
            del sys.modules[nome]
    import blenderzome as nuovo
    importlib.reload(nuovo)
    nuovo.register()
    loader = sys.modules.get("zome_loader")
    if loader is not None:
        loader._mod = nuovo


class ZOME_OT_aggiorna(bpy.types.Operator):
    """Scarica la release più nuova e sostituisce solo sistema/. Le istanze restano dov'erano."""
    bl_idname = "zome.aggiorna"
    bl_label = "Aggiorna"

    def execute(self, context):
        tag = _aggiornamento.get("tag") or ""
        if _aggiornamento.get("stato") != "nuova" or not tag:
            self.report({"WARNING"}, "Non c'è una versione più nuova")
            return {"CANCELLED"}
        try:
            url = f"https://github.com/{_REPO}/archive/refs/tags/{tag}.zip"
            richiesta = urllib.request.Request(url, headers={"User-Agent": "BlenderZome"})
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                dati = risposta.read()
            n = _estrai_sistema(dati, os.path.join(_ROOT, "sistema"))
            _copia_loader()
        except Exception as exc:
            self.report({"ERROR"}, "Aggiornamento non riuscito: %s" % exc)
            return {"CANCELLED"}

        def _dopo():
            _ricarica_pannello()
            return None

        bpy.app.timers.register(_dopo, first_interval=0.2)
        self.report({"INFO"}, "Sistema aggiornato, %s file. Le istanze non sono state toccate." % n)
        return {"FINISHED"}


class ZOME_PT_panel(bpy.types.Panel):
    bl_label = "Zome " + VERSIONE
    bl_idname = "ZOME_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Zome"

    def draw(self, context):
        z = context.scene.zome
        lay = self.layout
        if _aggiornamento.get("stato") == "nuova":
            avviso = lay.box()
            avviso.alert = True
            avviso.label(text="C'è una versione nuova: " + _aggiornamento.get("remota", ""), icon="FILE_REFRESH")
            avviso.operator("zome.aggiorna", icon="IMPORT")
        box = lay.box()
        box.label(text="Istanza", icon='BOOKMARKS')
        row = box.row(align=True)
        row.prop(z, "preset_scelta", text="")
        row.operator("zome.preset_carica", text="Carica", icon='IMPORT')
        row.operator("zome.preset_elimina", text="", icon='TRASH')
        row = box.row(align=True)
        row.prop(z, "preset_nome", text="")
        row.operator("zome.preset_salva", text="Salva", icon='EXPORT')
        m = _model_for(z)
        if z.errore:
            lay.label(text=z.errore, icon='ERROR')
        # 1. risultati: le cose da guardare sempre
        box = lay.box()
        box.label(text="Risultati", icon='SOLO_ON')
        if m:
            s = m["summary"]
            col = box.column(align=True)
            col.scale_y = 1.2
            h_terra = s.get("altezza_esterna", s["quota_max"])
            h_tot = s.get("altezza_esterna_su_pavimento", h_terra)      # il limite dei 3 m e' dal pavimento finito (tavolato) al punto piu' alto
            r = col.row(); r.alert = h_tot > 3.0
            r.label(text=f"Altezza dal pavimento, con tetto: {h_tot:.2f} m" + ("  oltre 3 m!" if h_tot > 3.0 else ""), icon='EMPTY_SINGLE_ARROW')
            col.label(text=f"(da terra: {h_terra:.2f} m)")
            ix, iy = s.get("ingombro_x_esterno", s["ingombro_x"]), s.get("ingombro_y_esterno", s["ingombro_y"])
            col.label(text=f"Ingombro, con tetto: {ix:.2f} (E-O) × {iy:.2f} (N-S) m", icon='ARROW_LEFTRIGHT')
            col.label(text=f"Pavimento: {s['area_pavimento']:.2f} m²  (a {s['quota_pavimento']:.2f} m)", icon='MESH_GRID')
            col.label(text=f"A 1,80 m dal pavimento: {s['area_180']:.2f} m²", icon='FIXED_SIZE')
        # 2. forma (richiudibile)
        head, body = lay.panel("zome_forma", default_closed=False)
        head.label(text="Forma", icon='MESH_ICOSPHERE')
        if body is not None:
            body.prop(z, "nome")
            row = body.row(align=True); row.prop(z, "N"); row.prop(z, "M")
            row = body.row(align=True); row.prop(z, "theta"); row.prop(z, "ZH")
            body.operator("zome.zh_altezza", icon='EMPTY_SINGLE_ARROW')
            sub = body.box()
            sub.prop(z, "secondario")
            if z.secondario:
                sub.prop(z, "cut")
                row = sub.row(align=True); row.prop(z, "M2"); row.prop(z, "theta2")


class ZOME_PT_comandi(bpy.types.Panel):
    """Ricostruisci / Automatico / reimposta: in fondo al pannello (ultimo figlio, senza intestazione)."""
    bl_label = "Comandi"
    bl_idname = "ZOME_PT_comandi"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Zome"
    bl_parent_id = "ZOME_PT_panel"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        z = context.scene.zome
        row = self.layout.row(align=True)
        row.operator("zome.crea", text="Ricostruisci", icon='FILE_REFRESH')
        row.prop(z, "live", text="Automatico", toggle=True)
        row.operator("zome.reimposta", text="", icon='LOOP_BACK')


class _SottoPannello(bpy.types.Panel):
    """Sezione richiudibile, chiusa di partenza, figlia del pannello Zome."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Zome"
    bl_parent_id = "ZOME_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}
    bl_icon = 'DOT'

    def draw_header(self, context):
        self.layout.label(icon=self.bl_icon)


class ZOME_OT_vista(bpy.types.Operator):
    """Vista predefinita del 3D: esterno da sud, o interno (da nord verso sud, altezza occhi 1,5 m, grandangolo)"""
    bl_idname = "zome.vista"
    bl_label = "Vista predefinita"
    modo: StringProperty(default="esterno")

    def execute(self, context):
        sp = context.space_data
        if sp is None or sp.type != 'VIEW_3D':
            return {'CANCELLED'}
        r3 = sp.region_3d
        m = _model_for(context.scene.zome)
        z = context.scene.zome
        R = m["summary"]["diametro_base"] / 2 if m else 2.0
        H = m["summary"].get("altezza_esterna", m["summary"]["altezza_totale"]) if m else 3.0
        cx, cy = z.px, z.py
        r3.view_perspective = 'PERSP'
        if self.modo == 'interno':
            r3.view_location = (cx, cy + 0.6 * R, (m["summary"].get("quota_pavimento", 0.0) if (m and z.floor) else 0.0) + 1.5)      # occhi a nord, guardando verso sud (dove c'e' l'entrata)
            r3.view_rotation = mathutils.Euler((math.radians(88), 0, math.radians(180))).to_quaternion()
            r3.view_distance = 0.01
            sp.lens, sp.clip_start = 18.0, 0.02
        else:
            r3.view_location = (cx, cy, H / 2)
            r3.view_rotation = mathutils.Euler((math.radians(75), 0, 0)).to_quaternion()   # da sud, un po' dall'alto
            r3.view_distance = max(2.5 * R, 1.5 * H) * 1.6
            sp.lens, sp.clip_start = 35.0, 0.1
        return {'FINISHED'}


class ZOME_OT_anim_crea(bpy.types.Operator):
    bl_idname = "zome.anim_crea"
    bl_label = "Crea animazione"
    bl_description = "Una visita: dalla porta si entra, si attraversa la zome e ci si gira guardando in alto (la porta si apre sulle cerniere)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        z = context.scene.zome
        m = _model_for(z)
        if m is None:
            self.report({'ERROR'}, "La zome non e' valida")
            return {'CANCELLED'}
        F = zome_viste.crea_animazione(context.scene, z, m, z.anim_secondi, z.anim_sole)
        sp = context.space_data
        if sp is not None and sp.type == 'VIEW_3D':
            sp.region_3d.view_perspective = 'CAMERA'
        self.report({'INFO'}, f"Animazione di {F} fotogrammi: Alt+A per vederla")
        return {'FINISHED'}


class ZOME_OT_anteprima(bpy.types.Operator):
    bl_idname = "zome.anteprima"
    bl_label = "Guarda e avvia"
    bl_description = ("Mette il 3D nella vista della camera (il riquadro tratteggiato e' l'inquadratura del render) e fa partire/ferma "
                      "l'anteprima dell'animazione (come Alt+A); per tornare alla vista libera: Numpad 0")

    def execute(self, context):
        sp = context.space_data
        if sp is None or sp.type != 'VIEW_3D':
            self.report({'ERROR'}, "Usalo dalla vista 3D")
            return {'CANCELLED'}
        sp.region_3d.view_perspective = 'CAMERA'
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


class ZOME_OT_render(bpy.types.Operator):
    bl_idname = "zome.render"
    bl_label = "Render"
    bl_description = ("Render vero con la camera della scena (EEVEE). Fotogramma: finestra di render, poi Immagine > Salva. "
                      "Animazione: video MP4 1920x1080 in BlenderZome/Render (puo' richiedere molti minuti)")
    animazione: BoolProperty(default=False)

    def execute(self, context):
        sc = context.scene
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
        if self.animazione:
            if not zome_viste.animazione_esiste(sc.zome):
                self.report({'ERROR'}, "Crea prima l'animazione")
                return {'CANCELLED'}
            d = os.path.join(_HERE or os.path.dirname(bpy.data.filepath) or bpy.app.tempdir, "Render")
            os.makedirs(d, exist_ok=True)
            if hasattr(sc.render.image_settings, "media_type"):          # Blender 5: il video e' un tipo di supporto a parte
                sc.render.image_settings.media_type = 'VIDEO'
            sc.render.image_settings.file_format = 'FFMPEG'
            sc.render.ffmpeg.format = 'MPEG4'
            sc.render.ffmpeg.codec = 'H264'
            sc.render.filepath = os.path.join(d, (sc.zome.nome or "zome") + "_visita")
            bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
            self.report({'INFO'}, f"Render in corso: il video finisce in {d}")
        else:
            bpy.ops.render.render('INVOKE_DEFAULT')
        return {'FINISHED'}


class ZOME_OT_anim_rimuovi(bpy.types.Operator):
    bl_idname = "zome.anim_rimuovi"
    bl_label = "Togli animazione"
    bl_description = "Toglie camera, sguardo e movimenti del sole e della porta; rimette la camera di prima"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        zome_viste.rimuovi_animazione(context.scene, context.scene.zome)
        return {'FINISHED'}


class ZOME_PT_vista(_SottoPannello):
    bl_label = "Vista"
    bl_idname = "ZOME_PT_vista"
    bl_icon = 'CAMERA_DATA'

    def draw(self, context):
        row = self.layout.row(align=True)
        row.operator("zome.vista", text="Esterno (da sud)", icon='HIDE_OFF').modo = 'esterno'
        row.operator("zome.vista", text="Interno", icon='CAMERA_DATA').modo = 'interno'


class ZOME_PT_viste(_SottoPannello):
    bl_label = "Visualizzazioni"
    bl_idname = "ZOME_PT_viste"
    bl_icon = 'LIGHT_SUN'

    def draw(self, context):
        z = context.scene.zome
        lay = self.layout
        box = lay.box()
        box.label(text="Spaccato verticale", icon='MOD_BOOLEAN')
        box.prop(z, "spaccato", slider=True, text="Fetta tolta")
        box.prop(z, "spaccato_dir", slider=True)
        box.label(text="Solo vista: non toglie pezzi e non cambia pesi né il calcolo")
        box.label(text="0% = intera · 50% = a metà · 100% = sparita")
        box = lay.box()
        box.label(text="Sole (Neirone)", icon='LIGHT_SUN')
        row = box.row(align=True); row.prop(z, "sole_giorno", text="Giorno"); row.prop(z, "sole_mese", text="Mese")
        box.prop(z, "sole_ora", slider=True)
        az, el = zome_viste.posizione_sole(z.sole_mese, z.sole_giorno, z.sole_ora)
        al, tr = zome_viste.alba_tramonto(z.sole_mese, z.sole_giorno)
        def hm(o):
            return "-" if o is None else f"{int(o):02d}:{int(round((o - int(o)) * 60)) % 60:02d}"
        box.label(text=f"Altezza {math.degrees(el):.0f}°  azimut {math.degrees(az):.0f}°   alba {hm(al)}  tramonto {hm(tr)}")
        if zome_viste.animazione_esiste(z):
            box.label(text="C'e' un'animazione: il sole segue i suoi tasti", icon='INFO')
        box = lay.box()
        box.label(text="Arredo", icon='OUTLINER_OB_GROUP_INSTANCE')
        row = box.row(align=True); row.prop(z, "arredo_mobili", toggle=True); row.prop(z, "arredo_persone", toggle=True)
        m = _model_for(z)
        if m and (z.arredo_mobili or z.arredo_persone):
            a = m["summary"].get("area_pavimento", 0.0)
            r = box.row()
            r.alert = a < 15.0
            r.label(text=f"Pavimento {a:.1f} m²" + ("  (l'arredo e' pensato per 15 m² o piu')" if a < 15.0 else ""))
        box = lay.box()
        box.label(text="Animazione", icon='RENDER_ANIMATION')
        row = box.row(align=True); row.prop(z, "anim_secondi"); row.prop(z, "anim_sole", text="Sole")
        box.prop(z, "anim_distanza", slider=True)
        row = box.row(align=True)
        row.operator("zome.anim_crea", icon='PLAY')
        row.operator("zome.anim_rimuovi", icon='X')
        row = box.row(align=True)
        row.operator("zome.anteprima", icon='CAMERA_DATA')
        row = box.row(align=True)
        row.operator("zome.render", text="Render fotogramma", icon='RENDER_STILL').animazione = False
        row.operator("zome.render", text="Render animazione", icon='RENDER_ANIMATION').animazione = True
        box.label(text="Riquadro tratteggiato = inquadratura del render")


# Solo queste sotto-collection entrano nel foglio. La porta, l'arredo, i sanitari e la statica non ci sono.
_RUOLI_CONTO = (
    "Struttura", "Pavimento",
    "Esterno · legno", "Esterno · vetro", "Interno · perline",
    "Tetto", "Isolante",
)


def _oggetti_foglio(z):
    """Solidi delle mesh nelle collection dei materiali della zome."""
    nome = z.nome or "zome"
    coll = bpy.data.collections.get(nome)
    oggetti, visti = [], set()
    ferramenta = 0

    def ruolo_di(coll_name):
        pref = nome + " · "
        return coll_name[len(pref):] if coll_name.startswith(pref) else ""

    def leggi_attr(me, attr):
        a = me.attributes.get(attr) if hasattr(me, "attributes") else None
        if a is None:
            return None
        try:
            return [a.data[i].value for i in range(len(me.polygons))]
        except (AttributeError, RuntimeError):
            return None

    def visita(coll, ruolo):
        nonlocal ferramenta
        for ob in list(coll.objects):
            chiave = ob.as_pointer()
            if chiave in visti:
                continue
            materiale = ob.get("materiale") if hasattr(ob, "get") else None
            if not materiale and ruolo not in _RUOLI_CONTO:
                continue
            visti.add(chiave)
            basso = ob.name.lower()
            if "maniglia" in basso or "cernier" in basso:
                ferramenta += 1
                continue
            if ob.type != "MESH" or ob.data is None or not ob.data.polygons:
                continue
            me, mw = ob.data, ob.matrix_world
            verts = [tuple((mw @ v.co)[i] for i in range(3)) for v in me.vertices]
            faces = [list(p.vertices) for p in me.polygons]
            cut = None
            if "scheletro_cutlist" in ob.keys():
                try:
                    cut = json.loads(ob["scheletro_cutlist"])
                except (TypeError, json.JSONDecodeError, ValueError):
                    cut = None
            oggetti.append({"nome": ob.name, "ruolo": ruolo, "materiale": materiale or "",
                            "verts": verts, "faces": faces,
                            "strati": leggi_attr(me, "strato"), "classi": leggi_attr(me, "classe"),
                            "cutlist": cut})
        for ch in coll.children:
            visita(ch, ruolo_di(ch.name))

    if coll is not None:
        visita(coll, "")
    porta = bpy.data.collections.get(f"{nome} · Porta")
    if porta is not None:
        for ob in porta.objects:
            basso = ob.name.lower()
            if "maniglia" in basso or "cernier" in basso:
                ferramenta += 1
    summary, params = {}, {}
    rif = bpy.data.objects.get(nome + "_interno")
    if rif is not None:
        try:
            if "zome_summary" in rif.keys():
                summary = json.loads(rif["zome_summary"])
            if "zome_params" in rif.keys():
                tutto = json.loads(rif["zome_params"])
                params = {k: tutto.get(k) for k in ("N", "M", "theta", "ZH", "cut", "M2", "theta2")}
        except (TypeError, json.JSONDecodeError, ValueError):
            summary, params = {}, {}
    formula = None
    trav = bpy.data.objects.get(nome + "_pav_travetti")
    if trav is not None and "travetti_formula" in trav.keys():
        try:
            formula = json.loads(trav["travetti_formula"])
        except (TypeError, json.JSONDecodeError, ValueError):
            formula = None
    porta_esclusa = porta is not None and any(
        ob.type == "MESH" and ob.data and ob.data.polygons for ob in porta.objects)
    meta = {"nome": nome, "summary": summary, "params": params, "ferramenta": ferramenta,
            "porta_esclusa": porta_esclusa,
            "pav_tipo": z.pav_tipo, "pav_carico": z.pav_carico, "pav_interasse": z.pav_interasse,
            "travetti_formula": formula,
            "t_legno_mm": z.t_legno * 10.0, "t_tetto_mm": z.t_tetto * 10.0,
            "t_int_mm": z.t_int_legno * 10.0, "t_isolante_mm": z.TW * 10.0,
            "isolante_nome": _nome_isolante(z.isolante), "t_tavolato_mm": 25.0}
    return oggetti, meta


class ZOME_OT_foglio(bpy.types.Operator):
    """Scrive il report dai solidi della collection e lo apre"""
    bl_idname = "zome.foglio"
    bl_label = "Crea report"
    bl_options = {'REGISTER'}

    def execute(self, context):
        import webbrowser
        z = context.scene.zome
        nome = z.nome or "zome"
        if bpy.data.collections.get(nome) is None:
            self.report({'ERROR'}, f"Non trovo la collection {nome}.")
            return {'CANCELLED'}
        context.view_layer.update()
        opz = {"nome": nome, "esterno": z.foglio_esterno, "perline": z.foglio_perline,
               "vetro": z.foglio_vetro, "travi": z.foglio_travi}
        istanza = z.preset_scelta if z.preset_scelta and z.preset_scelta != "_nessuno_" else ""
        cartella_ist = _cartella_istanza(istanza) if istanza else ""
        if cartella_ist and os.path.isdir(cartella_ist):
            percorso = os.path.join(cartella_ist, "report.html")
        else:
            sicuro = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in nome)
            percorso = os.path.join(_ROOT, "reports", sicuro + ".html")
        try:
            importlib.reload(zome_foglio)
            importlib.reload(zome_scena)
            oggetti, meta = _oggetti_foglio(z)
            prezzi = zome_foglio.carica_prezzi(os.path.join(_HERE, "Riferimenti", "proprieta_materiali.xlsx"))
            dati = zome_scena.scrivi_scena(percorso, oggetti, meta, opz, prezzi)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        webbrowser.open(percorso)
        self.report({'INFO'}, f"Report: {dati['totale']:.2f} €  ({percorso})")
        return {'FINISHED'}


class ZOME_PT_dati(_SottoPannello):
    bl_label = "Dati e elenchi"
    bl_idname = "ZOME_PT_dati"
    bl_icon = 'SPREADSHEET'

    def draw(self, context):
        z = context.scene.zome
        lay = self.layout
        lay.label(text="Strati, pezzi, pesi e preventivo stanno nel report")
        box = lay.box()
        box.label(text="Report")
        row = box.row(align=True)
        row.prop(z, "foglio_esterno", toggle=True)
        row.prop(z, "foglio_perline", toggle=True)
        row = box.row(align=True)
        row.prop(z, "foglio_vetro", toggle=True)
        row.prop(z, "foglio_travi", toggle=True)
        box.operator("zome.foglio", icon='FILE')


class ZOME_PT_posa(_SottoPannello):
    bl_label = "Posa e tagli"
    bl_idname = "ZOME_PT_posa"
    bl_icon = 'EMPTY_ARROWS'

    def draw(self, context):
        z = context.scene.zome
        col = self.layout.column(align=True)
        col.prop(z, "posa", expand=True)
        r = col.row(); r.enabled = z.posa == "CORICATA"
        r.prop(z, "pav_taglio", slider=True)
        if z.posa == "CORICATA" and not z.floor:
            col.label(text="Accendi il pavimento: il taglio lo usa", icon='INFO')
        col.prop(z, "orient")
        row = col.row(align=True); row.prop(z, "px"); row.prop(z, "py"); row.prop(z, "pz")
        col.separator()
        col.prop(z, "caps")


class ZOME_OT_uso(bpy.types.Operator):
    """Assegna un rivestimento alle facce selezionate (in Modifica, sull'oggetto _interno, _legno, _vetro o _tetto)"""
    bl_idname = "zome.uso"
    bl_label = "Imposta rivestimento"
    bl_options = {'REGISTER', 'UNDO'}
    voce: StringProperty(default="glass_external")     # chiave del catalogo, "aperto", "regola" (torna alla regola) o "tutte" (azzera)

    def execute(self, context):
        import bmesh
        import json
        z = context.scene.zome
        man = _usi_manuali(z)
        if self.voce == "tutte":
            z.usi_manuali = ""
            costruisci(context, z)
            return {'FINISHED'}
        ob = context.active_object
        if ob is None or ob.type != 'MESH' or context.mode != 'EDIT_MESH':
            self.report({'ERROR'}, "Entra in Modifica sull'oggetto _interno, _legno, _vetro o _tetto e seleziona le facce")
            return {'CANCELLED'}
        bm = bmesh.from_edit_mesh(ob.data)
        ls, lf = bm.faces.layers.int.get("strato"), bm.faces.layers.int.get("faccia")
        if ls is None or lf is None:
            self.report({'ERROR'}, "L'oggetto non e' una zome (mancano gli attributi strato/faccia)")
            return {'CANCELLED'}
        scelte = [(f[ls], f[lf]) for f in bm.faces if f.select]
        bpy.ops.object.mode_set(mode='OBJECT')
        for st, fa in scelte:
            key = f"{st}.{fa}"
            if self.voce == "regola":
                man.pop(key, None)
            else:
                man[key] = self.voce
        z.usi_manuali = json.dumps(man) if man else ""
        costruisci(context, z)
        self.report({'INFO'}, f"{len(scelte)} facce: {self.voce}")
        return {'FINISHED'}


class ZOME_OT_porta_max(bpy.types.Operator):
    """Porta il piano alla distanza massima dall'asse che lascia ancora entrare il vano di porta"""
    bl_idname = "zome.porta_max"
    bl_label = "Massima"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        z = context.scene.zome
        m_ = _model_for(z)
        from dataclasses import replace as _repl
        d = porta_dist_max(_repl(_params(z), porta_z0=m_["params"].porta_z0 if m_ else 0.0))
        if d <= 0:
            self.report({'ERROR'}, "Il vano non entra neppure con il piano per l'asse: riduci le misure")
            return {'CANCELLED'}
        z.porta_dist = int(d * 1000) / 1000.0          # al millimetro verso il basso, cosi' il vano entra
        self.report({'INFO'}, f"Distanza massima {z.porta_dist:.3f} m")
        return {'FINISHED'}


class ZOME_PT_pavimento(_SottoPannello):
    bl_label = "Pavimento e fondazione"
    bl_idname = "ZOME_PT_pavimento"
    bl_icon = 'MESH_GRID'

    def draw(self, context):
        z = context.scene.zome
        col = self.layout.column(align=True)
        col.prop(z, "floor")
        sub = col.column(align=True)
        sub.active = z.floor
        sub.prop(z, "zfloor")
        sub.prop(z, "pav_tipo", text="")
        sub.prop(z, "pav_carico")
        sub.prop(z, "pav_seme")
        m = _model_for(z) if z.floor else None
        pv = m["summary"].get("pavimento") if m else None
        if pv:
            box = col.box()
            box.label(text=f"Travetti: {pv['travetti']} di {pv['travetto_b']*100:.0f}×{pv['travetto_h']*100:.0f} cm, "
                           f"luce {pv['luce']:.2f} m, interasse {pv['interasse']*100:.0f} cm")
            box.label(text=f"Volume {pv['volume_travetti']*1000:.0f} dm³   massa {pv['massa_travetti']:.0f} kg")
            box.label(text=f"Dormienti/pali: {pv['volume_dormienti']*1000:.0f} dm³   massa {pv['massa_dormienti']:.0f} kg")
            box.label(text=f"Tavolato 2,5 cm: {pv['area_tavolato']:.2f} m²   {pv['volume_tavolato']*1000:.0f} dm³")
            box.label(text=f"Pietre: {pv['pietre']}   Pavimento finito a {pv['z_finito']:.2f} m")
            box.label(text=f"Altezza libera sotto i travetti: {pv['altezza_libera']*100:.0f} cm", icon='INFO')
            box.label(text=f"Interasse dalla freccia L/300, C24, carico {pv['carico']*100:.0f} kg/m²", icon='INFO')


class ZOME_PT_porta(_SottoPannello):
    bl_label = "Porta"
    bl_idname = "ZOME_PT_porta"
    bl_icon = 'MOD_BUILD'

    def draw(self, context):
        z = context.scene.zome
        col = self.layout.column(align=True)
        col.prop(z, "porta")
        sub = col.column(align=True)
        sub.active = z.porta
        sub.prop(z, "porta_modo", expand=True)
        row = sub.row(align=True); row.prop(z, "porta_dir"); row.prop(z, "porta_dist")
        sub.operator("zome.porta_max")
        row = sub.row(align=True); row.prop(z, "porta_w"); row.prop(z, "porta_h")
        row = sub.row(align=True); row.prop(z, "porta_anta"); row.prop(z, "porta_apertura")
        if z.porta_modo != "parete":
            sub.prop(z, "porta_falda")
        m = _model_for(z) if z.porta else None
        if m and m["summary"].get("porta"):
            info = m["summary"]["porta"]
            if info.get("fuori"):
                col.label(text="Piano fuori dalla zome: il passaggio va verso la zome", icon='CHECKMARK')
            elif info["entra"]:
                col.label(text="Il vano entra nella sezione", icon='CHECKMARK')
            else:
                col.label(text="Il vano NON entra: avvicina il piano o riduci le misure", icon='ERROR')
            ar = sum(a for k, a in m["summary"]["tappi"].items() if k.startswith(("porta", "corridoio")))
            col.label(text=f"Parete con il vano tolto: {ar:.2f} m²")


class ZOME_PT_esterno(_SottoPannello):
    bl_label = "Esterno e rivestimenti"
    bl_idname = "ZOME_PT_esterno"
    bl_icon = 'MATERIAL'

    def draw(self, context):
        z = context.scene.zome
        lay = self.layout
        lay.prop(z, "esterno", toggle=True, icon='MATERIAL')
        col = lay.column()
        col.active = z.esterno
        box = col.box()
        box.label(text="Tetto", icon='HOME')
        box.prop(z, "tetto_visibile")
        row = box.row(align=True); row.prop(z, "t_tetto"); row.prop(z, "sporgenza")
        box.prop(z, "pendenza_tetto")
        box.prop(z, "scala_texture")
        box = col.box()
        box.label(text="Pareti in legno", icon='MOD_BUILD')
        row = box.row(align=True); row.prop(z, "t_legno"); row.prop(z, "larghezza_assi")
        row = box.row(align=True); row.prop(z, "scala_legno"); row.prop(z, "seme_legno")
        box = col.box()
        box.label(text="Vetri", icon='MOD_WIREFRAME')
        row = box.row(align=True); row.prop(z, "t_vetro"); row.prop(z, "stella_vetri")
        row = box.row(align=True); row.prop(z, "finestre"); row.prop(z, "strato_finestre")
        box = col.box()
        box.label(text="Interno a perline", icon='SNAP_EDGE')
        row = box.row(align=True); row.prop(z, "t_int_legno"); row.prop(z, "larghezza_perline")
        box.prop(z, "isolante")
        box = col.box()
        box.label(text="Scelta a mano (in Modifica, facce selezionate)", icon='RESTRICT_SELECT_OFF')
        row = box.row(align=True)
        for etichetta, voce in (("Tetto", "roof_external"), ("Legno", "wood_external"), ("Vetro", "glass_external"), ("Buco", APERTO)):
            row.operator("zome.uso", text=etichetta).voce = voce
        row = box.row(align=True)
        row.operator("zome.uso", text="Torna alla regola").voce = "regola"
        row.operator("zome.uso", text="Azzera tutto").voce = "tutte"
        n = len(_usi_manuali(z))
        if n:
            box.label(text=f"{n} facce scelte a mano")


def _statica_materiale():
    """Un materiale solo: il colore lo dà l'oggetto, così ogni asta ha il suo."""
    mat = bpy.data.materials.get("zome_statica")
    if mat is None:
        mat = bpy.data.materials.new("zome_statica")
        mat.use_nodes = True
    nt = mat.node_tree
    if nt and "zome_statica_ok" not in mat:
        bsdf = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
        info = nt.nodes.new("ShaderNodeObjectInfo")
        info.location = (-300, 0)
        if bsdf:
            nt.links.new(info.outputs["Color"], bsdf.inputs["Base Color"])
        mat["zome_statica_ok"] = 1
    return mat


def _statica_segmento(p0, p1, raggio, nome, colore, coll, mat, lati=6):
    from mathutils import Vector
    a, b = Vector(p0), Vector(p1)
    d = b - a
    if d.length < 1e-4:
        return None
    d.normalize()
    aus = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
    lato = d.cross(aus).normalized()
    alto = d.cross(lato).normalized()
    vertici = []
    for centro in (a, b):
        for i in range(lati):
            ang = 2 * math.pi * i / lati
            vertici.append(tuple(centro + (lato * math.cos(ang) + alto * math.sin(ang)) * raggio))
    facce = []
    for i in range(lati):
        j = (i + 1) % lati
        facce.append((i, j, lati + j, lati + i))
    facce.append(tuple(range(lati)))
    facce.append(tuple(range(2 * lati - 1, lati - 1, -1)))
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vertici, [], facce)
    me.update()
    ob = bpy.data.objects.new(nome, me)
    ob.color = (colore[0], colore[1], colore[2], 1.0)
    ob.show_in_front = True
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _statica_cono(punta, verso, lunghezza, raggio, nome, colore, coll, mat):
    """Cono con la punta in `punta` e l'asse lungo `verso`."""
    from mathutils import Vector
    v = Vector(verso)
    if v.length < 1e-8:
        return None
    v.normalize()
    base = Vector(punta) - v * lunghezza
    aus = Vector((0, 0, 1)) if abs(v.z) < 0.9 else Vector((1, 0, 0))
    lato = v.cross(aus).normalized()
    alto = v.cross(lato).normalized()
    lati = 6
    vertici = [tuple(punta)]
    for i in range(lati):
        ang = 2 * math.pi * i / lati
        vertici.append(tuple(base + (lato * math.cos(ang) + alto * math.sin(ang)) * raggio))
    facce = [(0, i, i % lati + 1) for i in range(1, lati)]
    facce.append((0, lati, 1))
    facce.append(tuple(range(lati, 0, -1)))
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vertici, [], facce)
    me.update()
    ob = bpy.data.objects.new(nome, me)
    ob.color = (colore[0], colore[1], colore[2], 1.0)
    ob.show_in_front = True
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _statica_forza(a, b, d, span, compressione, colore, nome, coll, mat):
    """Un oggetto solo. La lunghezza è la frazione dell'asta: 1 = da nodo a nodo."""
    from mathutils import Vector
    lati = 6
    aus = Vector((0.0, 0.0, 1.0)) if abs(d.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    lato = d.cross(aus).normalized()
    alto = d.cross(lato).normalized()
    meta = (Vector(a) + Vector(b)) / 2
    half = max(float(span), 0.05) / 2.0
    a2, b2 = meta - d * half, meta + d * half
    # spessore fisso: cambia solo la lunghezza
    r_asta, r_testa = 0.008, 0.022
    freccia = min(0.06, half * 0.4)
    vertici = []
    facce = []

    def anello(centro, raggio):
        base = len(vertici)
        for i in range(lati):
            ang = 2 * math.pi * i / lati
            vertici.append(centro + (lato * math.cos(ang) + alto * math.sin(ang)) * raggio)
        return base

    sa, sb = a2 + d * freccia, b2 - d * freccia
    ia, ib = anello(sa, r_asta), anello(sb, r_asta)
    for i in range(lati):
        j = (i + 1) % lati
        facce.append((ia + i, ia + j, ib + j, ib + i))
    coni = ((sa, d), (sb, -d)) if compressione else ((a2, -d), (b2, d))
    for punta, verso in coni:
        iv = len(vertici)
        vertici.append(Vector(punta))
        ic = anello(Vector(punta) - Vector(verso) * freccia, r_testa)
        for i in range(lati):
            facce.append((iv, ic + i, ic + (i + 1) % lati))
        facce.append(tuple(ic + i for i in range(lati - 1, -1, -1)))
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vertici, [], facce)
    me.update()
    ob = bpy.data.objects.new(nome, me)
    ob.color = (colore[0], colore[1], colore[2], 1.0)
    ob.show_in_front = True
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _statica_vettore(centro, asse, lunghezza, colore, nome, coll, mat):
    """Una punta sola, sull'asse di rotazione. La lunghezza piena equivale all'asta intera."""
    from mathutils import Vector
    asse = Vector(asse)
    if asse.length < 1e-8 or lunghezza < 1e-4:
        return None
    asse.normalize()
    meta = Vector(centro)
    coda = meta - asse * (lunghezza * 0.5)
    punta = meta + asse * (lunghezza * 0.5)
    lati = 6
    aus = Vector((0.0, 0.0, 1.0)) if abs(asse.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    lato = asse.cross(aus).normalized()
    alto = asse.cross(lato).normalized()
    testa = min(max(lunghezza * 0.22, 0.03), 0.12)
    raggio = 0.008
    vertici = []
    facce = []

    def anello(centro_anello, raggio_anello):
        base = len(vertici)
        for i in range(lati):
            ang = 2 * math.pi * i / lati
            vertici.append(centro_anello + (lato * math.cos(ang) + alto * math.sin(ang)) * raggio_anello)
        return base

    ia, ib = anello(coda, raggio), anello(punta - asse * testa, raggio)
    for i in range(lati):
        j = (i + 1) % lati
        facce.append((ia + i, ia + j, ib + j, ib + i))
    iv = len(vertici)
    vertici.append(punta)
    ic = anello(punta - asse * testa, 0.02)
    for i in range(lati):
        facce.append((iv, ic + i, ic + (i + 1) % lati))
    facce.append(tuple(ic + i for i in range(lati - 1, -1, -1)))
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vertici, [], facce)
    me.update()
    ob = bpy.data.objects.new(nome, me)
    ob.color = (colore[0], colore[1], colore[2], 1.0)
    ob.show_in_front = True
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _statica_cerchio(centro, asse, raggio, colore, nome, coll, mat):
    """Arco nel piano perpendicolare all'asse: è il piano in cui l'asta tende a ruotare."""
    from mathutils import Vector
    asse = Vector(asse)
    if asse.length < 1e-8 or raggio < 1e-4:
        return None
    asse.normalize()
    aus = Vector((0.0, 0.0, 1.0)) if abs(asse.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    u = asse.cross(aus).normalized()
    v = asse.cross(u).normalized()
    n = 12
    giro = 2 * math.pi * 0.34
    larg = max(raggio * 0.14, 0.008)
    sp = 0.004
    vertici = []
    facce = []
    for i in range(n + 1):
        ang = giro * i / n
        rad = u * math.cos(ang) + v * math.sin(ang)
        p = Vector(centro) + rad * raggio
        interno, esterno = p - rad * larg, p + rad * larg
        vertici.append(interno - asse * sp)
        vertici.append(interno + asse * sp)
        vertici.append(esterno + asse * sp)
        vertici.append(esterno - asse * sp)
    for i in range(n):
        a0, a1 = 4 * i, 4 * (i + 1)
        facce.append((a0, a0 + 1, a1 + 1, a1))
        facce.append((a0 + 1, a0 + 2, a1 + 2, a1 + 1))
        facce.append((a0 + 2, a0 + 3, a1 + 3, a1 + 2))
        facce.append((a0 + 3, a0, a1, a1 + 3))
    ang = giro
    tang = (-u * math.sin(ang) + v * math.cos(ang)).normalized()
    fine = Vector(centro) + (u * math.cos(ang) + v * math.sin(ang)) * raggio
    iv = len(vertici)
    vertici.append(fine + tang * (larg * 2.2))
    base = fine - tang * larg
    lato = tang.cross(asse).normalized()
    for i, segno in enumerate((-1.0, 1.0)):
        vertici.append(base + lato * (larg * 1.3 * segno))
        facce.append((iv, iv + 1 + i, iv + 1 + (i + 1) % 2))
    me = bpy.data.meshes.new(nome)
    me.from_pydata(vertici, [], facce)
    me.update()
    ob = bpy.data.objects.new(nome, me)
    ob.color = (colore[0], colore[1], colore[2], 1.0)
    ob.show_in_front = True
    if mat:
        me.materials.append(mat)
    coll.objects.link(ob)
    return ob


def _statica_fuori(p, n, d):
    return (p[0] + n[0] * d, p[1] + n[1] * d, p[2] + n[2] * d)


def _statica_svuota(coll):
    for child in list(coll.children):
        _statica_svuota(child)
        bpy.data.collections.remove(child)
    for ob in list(coll.objects):
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me and getattr(me, "users", 1) == 0:
            bpy.data.meshes.remove(me)


def _statica_collection(nome, padre):
    vecchia = bpy.data.collections.get(nome)
    if vecchia:
        _statica_svuota(vecchia)
        bpy.data.collections.remove(vecchia)
    coll = bpy.data.collections.new(nome)
    padre.children.link(coll)
    return coll


def _statica_calore(u):
    """0 verde, 0.5 giallo, 1 rosso. È il posto in questa prova, non un limite di rottura."""
    u = max(0.0, min(1.0, u))
    if u < 0.5:
        k = u / 0.5
        return (0.15 + 0.80 * k, 0.62 + 0.28 * k, 0.18 - 0.08 * k)
    k = (u - 0.5) / 0.5
    return (0.95, 0.90 - 0.75 * k, 0.10 * (1.0 - k))


def _statica_occhio(coll, visibile):
    """L'occhio dell'outliner. Il monitor (hide_viewport della collection) resta acceso, altrimenti l'occhio non basta."""
    def cerca(layer):
        if layer.collection == coll:
            layer.hide_viewport = not visibile
            return True
        return any(cerca(ch) for ch in layer.children)
    bpy.context.view_layer.update()
    cerca(bpy.context.view_layer.layer_collection)


def _statica_annota(ob, nome, scheda, dati=None):
    if ob is None:
        return
    ob.name = nome
    ob["scheda"] = scheda
    for chiave, valore in (dati or {}).items():
        ob[chiave] = valore


def _statica_disegna(context, nome, esito, fuori_m=0.08):
    """Aste corte, frecce intere alle estremità. Colore = carico di questa prova."""
    aste = esito.get("aste_viste") or []
    if not aste:
        return
    padre = bpy.data.collections.get(nome) or context.scene.collection
    vecchia_mom = bpy.data.collections.get(f"{nome} · Statica momento")
    if vecchia_mom:
        _statica_svuota(vecchia_mom)
        bpy.data.collections.remove(vecchia_mom)
    mat = _statica_materiale()
    radice = _statica_collection(f"{nome} · Statica", padre)
    coll = bpy.data.collections.new("Sforzo")
    mom_coll = bpy.data.collections.new("Momento")
    app_coll = bpy.data.collections.new("Appoggi")
    radice.children.link(coll)
    radice.children.link(mom_coll)
    radice.children.link(app_coll)
    nmax = max(abs(t["N"]) for t in aste) or 1.0
    mmax = max(t["mom"] for t in aste) or 1.0
    modo = "CIRCOLARE"
    if getattr(context.scene, "zome", None) is not None:
        modo = context.scene.zome.statica_momento
    from mathutils import Vector
    for t in aste:
        colore = _statica_calore(abs(t["N"]) / nmax)
        nrm = Vector(t.get("normale") or (0.0, 0.0, 1.0))
        if nrm.length < 1e-8:
            nrm = Vector((0.0, 0.0, 1.0))
        nrm.normalize()
        a = Vector(_statica_fuori(t["a"], nrm, fuori_m))
        b = Vector(_statica_fuori(t["b"], nrm, fuori_m))
        d = b - a
        if d.length < 1e-4:
            continue
        d.normalize()
        lunga_asta = (b - a).length
        if (a.z, a.y, a.x) <= (b.z, b.y, b.x):
            salita = d
        else:
            salita = -d
        sinistra = nrm.cross(salita)
        if sinistra.length < 1e-6:
            sinistra = Vector((0.0, 0.0, 1.0)).cross(salita)
        if sinistra.length < 1e-6:
            sinistra = Vector((1.0, 0.0, 0.0))
        sinistra.normalize()
        # forze a sinistra della salita, momento a destra: non si coprono
        a_f, b_f = a + sinistra * 0.08, b + sinistra * 0.08
        centro = (a + b) / 2 - sinistra * 0.08
        posto = abs(t["N"]) / nmax
        if t["N"] >= 0:
            sforzo = f"Compressione {t['compr']/1000:.2f} kN"
        else:
            sforzo = f"Trazione {t['traz']/1000:.2f} kN"
        scheda = "|".join((
            f"n°{t['n']}  strato {t['strato']}  {t['lung']*100:.0f} cm",
            sforzo,
            f"Momento {t['mom']/1000:.3f} kN·m, {t['piega']}, {t['sigma_m']:.0f} MPa",
            "Il picco del momento è al giunto",
        ))
        dati = {
            "n": int(t["n"]),
            "strato": int(t["strato"]),
            "lunghezza_cm": round(t["lung"] * 100.0, 1),
            "sforzo": "compressione" if t["N"] >= 0 else "trazione",
            "sforzo_kN": round(abs(t["N"]) / 1000.0, 3),
            "momento_kNm": round(t["mom"] / 1000.0, 3),
            "piega": t["piega"],
            "sigma_MPa": round(float(t["sigma_m"]), 1),
        }
        _statica_annota(
            _statica_forza(a_f, b_f, d, max(posto, 0.12) * lunga_asta, t["N"] >= 0, colore, f"n°{t['n']} · {sforzo}", coll, mat),
            f"n°{t['n']} · {sforzo}", scheda, dati)
        caldo = t["mom"] / mmax
        asse = Vector(t.get("asse") or (0.0, 0.0, 1.0))
        if asse.length < 1e-8:
            asse = nrm
        asse.normalize()
        mscheda = "|".join((
            f"n°{t['n']}  piegamento {t['piega']}",
            f"Momento {t['mom']/1000:.3f} kN·m, circa {t['sigma_m']:.0f} MPa",
            "Circolare: piano di rotazione" if modo == "CIRCOLARE" else "Vettore: asse di rotazione",
        ))
        mdati = {
            "n": int(t["n"]),
            "strato": int(t["strato"]),
            "momento_kNm": round(t["mom"] / 1000.0, 3),
            "piega": t["piega"],
            "sigma_MPa": round(float(t["sigma_m"]), 1),
        }
        quota = max(caldo, 0.12)
        if modo == "VETTORE":
            ob_m = _statica_vettore(centro, asse, quota * lunga_asta, _statica_calore(caldo), f"n°{t['n']} momento", mom_coll, mat)
        else:
            ob_m = _statica_cerchio(centro, asse, 0.18 * quota * lunga_asta, _statica_calore(caldo), f"n°{t['n']} momento", mom_coll, mat)
        _statica_annota(ob_m, f"n°{t['n']} · {t['mom']/1000:.3f} kN·m", mscheda, mdati)
    rmax = max((sum(c * c for c in r["R"]) ** 0.5 for r in esito.get("reazioni") or []), default=1.0) or 1.0
    for i, r in enumerate(esito.get("reazioni") or []):
        R = Vector(r["R"])
        if R.length < 1e-6:
            continue
        lunga = 0.12 + 0.35 * (R.length / rmax)
        lato = math.hypot(r["R"][0], r["R"][1])
        verso_z = "in su" if r["R"][2] >= 0 else "in giù"
        scheda = "|".join((
            f"Appoggio {i}, cerniera",
            f"Verticale {r['R'][2]/1000:.2f} kN, il terreno spinge {verso_z}",
            f"Di lato {lato/1000:.2f} kN",
        ))
        dati = {
            "appoggio": i,
            "verticale_kN": round(r["R"][2] / 1000.0, 3),
            "lato_kN": round(lato / 1000.0, 3),
        }
        _statica_annota(
            _statica_cono(Vector(r["p"]) + R.normalized() * lunga, R, lunga, 0.028, f"appoggio {i}", (1.0, 0.85, 0.1), app_coll, mat),
            f"appoggio {i}", scheda, dati)


def _pelli_statica(z):
    """Densità dal foglio materiali. Il vetro è il pacco, non il volume della lastra disegnata."""
    prezzi = zome_foglio.carica_prezzi(os.path.join(_HERE, "Riferimenti", "proprieta_materiali.xlsx"))

    def dens(chiave):
        riga = prezzi.get(zome_foglio.NOMI[chiave]) or {}
        return float(riga["densita"]) if riga.get("densita") else None

    nome = _nome_isolante(z.isolante)
    riga = prezzi.get(nome) or {}
    tegole = prezzi.get(zome_foglio.NOMI["tegole"]) or {}
    return {
        "esterno": dens("tavole") or dens("perline"),
        "interno": dens("perline"),
        "tetto": dens("tegole"),
        "tetto_mm": float(tegole["spessore_mm"]) if tegole.get("spessore_mm") else 3.0,
        "vetro_kg_m2": 35.0,
        "vetro_grande_kg_m2": 45.0,
        "luce_grande": 0.90,
        "tilt_neve": 55.0,
        "isolante": float(riga["densita"]) if riga.get("densita") else None,
    }


class ZOME_OT_statica(bpy.types.Operator):
    """Telaio dello scheletro: peso del legno, dei rivestimenti, dell'isolante e neve"""
    bl_idname = "zome.statica"
    bl_label = "Calcola sollecitazioni"
    bl_options = {'REGISTER'}

    def execute(self, context):
        z = context.scene.zome
        m = _model_for(z)
        if m is None:
            self.report({'ERROR'}, z.errore or "Modello non disponibile")
            return {'CANCELLED'}
        esito = zome_statica.analizza(m, TT=z.TT / 100.0, TW=z.TW / 100.0, density=z.densita,
                                      snow_kN_m2=z.statica_neve, pelli=_pelli_statica(z))
        if esito.get("ok"):
            _STATICA_CACHE["esito"] = esito
            try:
                _statica_disegna(context, z.nome or "zome", esito, fuori_m=z.TW / 100.0 + 0.04)
            except Exception as e:
                esito["testo"] += "\nVista 3D non disegnata: " + str(e)
            try:
                context.window_manager.clipboard = esito["testo"]
            except Exception as e:
                esito["testo"] += "\nAppunti non copiati: " + str(e)
        z.statica_testo = esito["testo"]
        self.report({'INFO'} if esito["ok"] else {'WARNING'}, esito["testo"].split("\n", 1)[0])
        return {'FINISHED'}


class ZOME_OT_statica_copia(bpy.types.Operator):
    """Copia l'ultimo rapporto negli appunti, senza ricalcolare"""
    bl_idname = "zome.statica_copia"
    bl_label = "Copia negli appunti"

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.scene, "zome", None) and context.scene.zome.statica_testo)

    def execute(self, context):
        righe = []
        for riga in context.scene.zome.statica_testo.splitlines():
            if riga.startswith("Copiato negli appunti") or riga.startswith("Appunti non copiati"):
                continue
            righe.append(riga)
        context.window_manager.clipboard = "\n".join(righe).strip()
        self.report({'INFO'}, "Rapporto copiato negli appunti")
        return {'FINISHED'}


class ZOME_OT_traversa(bpy.types.Operator):
    """Accende o spegne la traversa su questo strato"""
    bl_idname = "zome.traversa"
    bl_label = "Traversa"
    bl_description = "Tra anelli: da un anello all'altro (nello zome dritto è verticale). Sull'anello: i due vertici dello stesso anello (nello zome dritto è orizzontale)"
    bl_options = {'REGISTER', 'UNDO'}

    strato: IntProperty(default=1)
    quale: StringProperty(default="t")

    def execute(self, context):
        z = context.scene.zome
        z.traverse = toggle_traverse(z.traverse, self.strato, self.quale)
        return {'FINISHED'}


class ZOME_PT_scheletro(_SottoPannello):
    bl_label = "Scheletro (struttura)"
    bl_idname = "ZOME_PT_scheletro"
    bl_icon = 'MOD_WIREFRAME'

    def draw(self, context):
        z = context.scene.zome
        col = self.layout.column(align=True)
        col.prop(z, "scheletro", toggle=True)
        sub = col.column(align=True)
        sub.active = z.scheletro
        row = sub.row(align=True); row.prop(z, "TT"); row.prop(z, "TW")
        sub.prop(z, "giunto", text="Giunto")
        sub.prop(z, "densita", text="Densità (kg/m³)")
        box = sub.box()
        box.label(text="Traverse, una riga per strato")
        box.label(text="Tra anelli: fra due anelli (dritta = verticale)")
        box.label(text="Sull'anello: stesso anello (dritta = orizzontale)")
        box.label(text="Sui triangoli «sull'anello» non si mette")
        mtab = _model_for(z)
        flags = parse_traverse(z.traverse)
        if mtab:
            for st in mtab["strata"]:
                rombi = any(k == "rombo" and len(pt) == 4 for k, pt in st["facce"])
                tri = any(str(k).startswith("triangolo") and len(pt) == 3 for k, pt in st["facce"])
                nome = "misto" if rombi and tri else ("triangoli" if tri else "rombi")
                row = box.row(align=True)
                row.label(text=f"{st['strato']} {nome}")
                acc = flags.get(st["strato"], ())
                op = row.operator("zome.traversa", text="Tra anelli", depress=("t" in acc))
                op.strato = st["strato"]
                op.quale = "t"
                if rombi:
                    op = row.operator("zome.traversa", text="Sull'anello", depress=("a" in acc))
                    op.strato = st["strato"]
                    op.quale = "a"
                else:
                    row.label(text="—")
        box.label(text="Stessa sezione. Il calcolo del telaio le include.")
        sub.separator()
        sub.prop(z, "statica_neve")
        sub.prop(z, "statica_momento", text="Momento")
        sub.operator("zome.statica", icon='FORCE_FORCE')
        sub.operator("zome.statica_copia", icon='COPYDOWN', text="Copia negli appunti")
        sub.label(text="Numeri nell'outliner: Statica → Sforzo, oppure Momento")
        ob = context.active_object
        scheda = ob.get("scheda") if ob else ""
        if scheda:
            scheda_box = self.layout.box()
            for riga in scheda.split("|"):
                scheda_box.label(text=riga)
        if z.statica_testo:
            box = self.layout.box()
            prime = [r for r in z.statica_testo.split("\n") if r][:4]
            for riga in prime:
                box.label(text=riga)
            box.label(text="Il resto: «Copia negli appunti». Per asta, i numeri sono nell'outliner.")


_classes = (ZomeProps, ZOME_OT_crea, ZOME_OT_reimposta, ZOME_OT_zh_altezza, ZOME_OT_preset_salva, ZOME_OT_preset_carica, ZOME_OT_preset_elimina, ZOME_OT_aggiorna, ZOME_PT_panel, ZOME_OT_uso, ZOME_OT_porta_max, ZOME_OT_statica, ZOME_OT_statica_copia, ZOME_OT_traversa, ZOME_OT_vista, ZOME_OT_anim_crea, ZOME_OT_anim_rimuovi, ZOME_OT_anteprima, ZOME_OT_render, ZOME_OT_foglio,
            ZOME_PT_posa, ZOME_PT_pavimento, ZOME_PT_porta, ZOME_PT_esterno, ZOME_PT_scheletro, ZOME_PT_vista, ZOME_PT_viste,
            ZOME_PT_dati, ZOME_PT_comandi)


_CATALOGO_MATERIALI = (
    {"nome": "Zome · Scheletro", "ruolo": "scheletro", "colore": (0.62, 0.45, 0.27), "props": {
        "densita": 700.0, "E_MPa": 11000.0, "fm_MPa": 24.0, "fc_MPa": 21.0, "ft_MPa": 14.0,
        "lambda": 0.13, "costo": 0.0, "costo_unita": "€/m³",
        "note": "C24 di partenza. Il costo è da compilare. Il calcolo del telaio userà questi numeri."}},
    {"nome": "Zome · Copertura esterna", "ruolo": "copertura_esterna", "colore": (0.45, 0.32, 0.18), "props": {
        "densita": 500.0, "E_MPa": 11000.0, "fm_MPa": 24.0, "fc_MPa": 21.0, "ft_MPa": 14.0,
        "lambda": 0.13, "costo": 0.0, "costo_unita": "€/m²",
        "note": "Rivestimento esterno, valori di partenza. Non entra ancora nel calcolo."}},
    {"nome": "Zome · Copertura interna", "ruolo": "copertura_interna", "colore": (0.72, 0.58, 0.40), "props": {
        "densita": 500.0, "E_MPa": 11000.0, "fm_MPa": 24.0, "fc_MPa": 21.0, "ft_MPa": 14.0,
        "lambda": 0.13, "costo": 0.0, "costo_unita": "€/m²",
        "note": "Rivestimento interno, valori di partenza. Non entra ancora nel calcolo."}},
    {"nome": "Zome · Tetto", "ruolo": "tetto", "colore": (0.25, 0.28, 0.30), "props": {
        "densita": 0.0, "E_MPa": 0.0, "fm_MPa": 0.0, "fc_MPa": 0.0, "ft_MPa": 0.0,
        "lambda": 0.0, "costo": 0.0, "costo_unita": "€/m²",
        "note": "Un solo materiale di copertura. Previsto: tegole bituminose. I numeri arrivano dalla scheda prodotto."}},
    {"nome": "Zome · Travi", "ruolo": "travi", "colore": (0.40, 0.26, 0.14), "props": {
        "densita": 700.0, "E_MPa": 11000.0, "fm_MPa": 24.0, "fc_MPa": 21.0, "ft_MPa": 14.0,
        "lambda": 0.13, "costo": 0.0, "costo_unita": "€/m³",
        "note": "Travi di base, C24 di partenza. Non entrano ancora nel calcolo."}},
    {"nome": "Zome · Vetro", "ruolo": "vetro", "colore": (0.60, 0.75, 0.80), "props": {
        "densita": 2500.0, "E_MPa": 70000.0, "fm_MPa": 0.0, "fc_MPa": 0.0, "ft_MPa": 0.0,
        "lambda": 1.0, "costo": 0.0, "costo_unita": "€/m²",
        "note": "Vetro di partenza. Le resistenze restano a zero finché non si sceglie il tipo."}},
)

_DESC_MATERIALI = {
    "ruolo": "A cosa serve nel modello",
    "densita": "kg/m³",
    "E_MPa": "Modulo elastico, MPa",
    "fm_MPa": "Resistenza a flessione, MPa",
    "fc_MPa": "Resistenza a compressione, MPa",
    "ft_MPa": "Resistenza a trazione, MPa",
    "lambda": "Conducibilità termica, W/mK. Valore tipico di partenza",
    "costo": "Costo, nell'unità di costo_unita. 0 = da compilare",
    "costo_unita": "€/m³ oppure €/m²",
    "note": "Promemoria",
}


def _assicura_materiali():
    """Crea le schede materiale se mancano. Non sovrascrive un numero già compilato."""
    for spec in _CATALOGO_MATERIALI:
        nuovo = bpy.data.materials.get(spec["nome"]) is None
        mat = bpy.data.materials.get(spec["nome"]) or bpy.data.materials.new(spec["nome"])
        if nuovo:
            mat.diffuse_color = (*spec["colore"], 1.0)
        if "ruolo" not in mat.keys():
            mat["ruolo"] = spec["ruolo"]
        for chiave, valore in spec["props"].items():
            if chiave not in mat.keys():
                mat[chiave] = valore
        for chiave, testo in _DESC_MATERIALI.items():
            if chiave not in mat.keys():
                continue
            try:
                mat.id_properties_ui(chiave).update(description=testo)
            except Exception:
                pass


def register():
    unregister()
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.zome = PointerProperty(type=ZomeProps)
    _assicura_materiali()
    if not bpy.app.timers.is_registered(_avvia_controllo):
        bpy.app.timers.register(_avvia_controllo, first_interval=1.5)


def unregister():
    for fn in (_avvia_controllo, _ridisegna_pannello):
        try:
            if bpy.app.timers.is_registered(fn):
                bpy.app.timers.unregister(fn)
        except Exception:
            pass
    if hasattr(bpy.types.Scene, "zome"):
        del bpy.types.Scene.zome
    for c in reversed(_classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
