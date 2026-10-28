"""Visualizzazioni della zome (solo Blender): sole, arredo e persone, animazione di una visita.

Le funzioni lavorano sul modello costruito da zome_core (quota del pavimento, sezioni orizzontali, riferimento della porta) e
sulle proprieta' del pannello (z).  Niente di qui entra nella geometria strutturale: sono oggetti di sola resa, in collection
proprie («<nome> · Arredo», «<nome> · Animazione»), che la ricostruzione della zome non cancella.
"""
import math
import random

import bpy
import bmesh
from mathutils import Matrix, Vector

from zome_core import _porta_frame
from zome_pavimento import sezione, _centro

LAT, LON = 44.4, 9.2           # Neirone (GE)


# --- sole --------------------------------------------------------------------------------------------------------------
def _fuso(mese, giorno):
    """Ore di scarto dall'UTC dell'ora civile italiana (ora legale da fine marzo a fine ottobre, approssimata)."""
    return 2.0 if (4 <= mese <= 9 or (mese == 3 and giorno >= 26) or (mese == 10 and giorno <= 25)) else 1.0


def _giorno_anno(mese, giorno):
    mesi = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return sum(mesi[:mese - 1]) + min(giorno, mesi[mese - 1])


def posizione_sole(mese, giorno, ora, lat=LAT, lon=LON):
    """(azimut dal nord in senso orario, altezza sull'orizzonte), in radianti, per l'ora civile `ora` (formule NOAA)."""
    doy = _giorno_anno(mese, giorno)
    g = 2 * math.pi / 365.0 * (doy - 1 + (ora - 12) / 24.0)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = ora * 60 + eqt + 4 * lon - 60 * _fuso(mese, giorno)
    ha = math.radians(tst / 4.0 - 180.0)
    la = math.radians(lat)
    cz = max(-1.0, min(1.0, math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))
    el = math.pi / 2 - math.acos(cz)
    az_sud = math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(dec) * math.cos(la))
    return (az_sud + math.pi) % (2 * math.pi), el


def alba_tramonto(mese, giorno):
    """(alba, tramonto) in ore civili, cercate a passi di 6 minuti (None se il sole non sorge o non tramonta)."""
    alba = tram = None
    prev = posizione_sole(mese, giorno, 0.0)[1]
    for k in range(1, 241):
        ora = k * 0.1
        el = posizione_sole(mese, giorno, ora)[1]
        if prev <= 0 < el and alba is None:
            alba = ora
        if prev > 0 >= el:
            tram = ora
        prev = el
    return alba, tram


def trova_sole():
    ob = bpy.data.objects.get("Sun")
    if ob is not None and ob.type == 'LIGHT' and ob.data.type == 'SUN':
        return ob
    return next((o for o in bpy.data.objects if o.type == 'LIGHT' and o.data.type == 'SUN'), None)


def _imposta_sole(sun, mese, giorno, ora, prev_euler=None):
    az, el = posizione_sole(mese, giorno, ora)
    if "zome_forza" not in sun:
        sun["zome_forza"] = sun.data.energy
        sun["zome_colore"] = list(sun.data.color)
    d = Vector((math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), math.sin(el)))      # x est, y nord (come la rosa dei venti)
    q = d.to_track_quat('Z', 'Y')
    sun.rotation_mode = 'XYZ'
    sun.rotation_euler = q.to_euler('XYZ', prev_euler) if prev_euler is not None else q.to_euler('XYZ')
    f = max(0.0, min(1.0, el / math.radians(8.0)))                 # si spegne all'orizzonte
    t = max(0.0, min(1.0, el / math.radians(25.0)))                # piu' caldo e arancio quando e' basso
    base = sun["zome_colore"]
    sun.data.energy = sun["zome_forza"] * f
    sun.data.color = (base[0], base[1] * (0.62 + 0.38 * t), base[2] * (0.35 + 0.65 * t))
    return el


def aggiorna_sole(z):
    sun = trova_sole()
    if sun is None:
        return None
    return _imposta_sole(sun, z.sole_mese, z.sole_giorno, z.sole_ora)


# --- arredo e persone ----------------------------------------------------------------------------------------------------
def _materiale(nome, rgb, rough=0.7):
    mat = bpy.data.materials.get(nome)
    if mat is None:
        mat = bpy.data.materials.new(nome)
        for n in mat.node_tree.nodes:
            if n.bl_idname == "ShaderNodeBsdfPrincipled":
                n.inputs["Base Color"].default_value = (*rgb, 1.0)
                n.inputs["Roughness"].default_value = rough
        mat.diffuse_color = (*rgb, 1.0)
    return mat


def _materiale_legno(nome, chiaro, scuro, scala=9.0, rough=0.55):
    """Legno procedurale: fibre (onda a bande disturbata dal rumore) tra due toni, in coordinate dell'oggetto."""
    mat = bpy.data.materials.get(nome)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(nome)
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    onda = nt.nodes.new("ShaderNodeTexWave")
    onda.wave_type = 'BANDS'
    onda.bands_direction = 'X'
    onda.inputs["Scale"].default_value = scala
    onda.inputs["Distortion"].default_value = 6.0
    onda.inputs["Detail"].default_value = 2.0
    nt.links.new(coord.outputs["Object"], onda.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*scuro, 1.0)
    ramp.color_ramp.elements[1].color = (*chiaro, 1.0)
    nt.links.new(onda.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    mat.diffuse_color = (*chiaro, 1.0)
    return mat


MATERIALI = {"legno": ("arredo_rovere", (0.62, 0.42, 0.22), 0.55), "legno_scuro": ("arredo_noce", (0.30, 0.17, 0.09), 0.5),
             "tela": ("arredo_tela", (0.90, 0.89, 0.85), 0.95), "cuscino": ("arredo_cuscino", (0.28, 0.40, 0.50), 0.95),
             "lino": ("arredo_lino", (0.72, 0.62, 0.50), 0.95), "acciaio": ("arredo_acciaio", (0.70, 0.72, 0.74), 0.3),
             "nero": ("arredo_nero", (0.04, 0.04, 0.045), 0.45), "piano": ("arredo_piano", (0.78, 0.60, 0.38), 0.45),
             "ceramica": ("arredo_ceramica", (0.92, 0.92, 0.90), 0.25), "verde": ("arredo_verde", (0.16, 0.38, 0.18), 0.8),
             "terracotta": ("arredo_terracotta", (0.65, 0.33, 0.20), 0.8),
             "pelle": ("persona_pelle", (0.82, 0.60, 0.48), 0.65), "pelle2": ("persona_pelle_2", (0.62, 0.42, 0.32), 0.65),
             "capelli": ("persona_capelli", (0.10, 0.07, 0.05), 0.7), "capelli2": ("persona_capelli_2", (0.45, 0.28, 0.12), 0.7),
             "camicia": ("persona_camicia", (0.30, 0.45, 0.65), 0.85), "pantaloni": ("persona_pantaloni", (0.18, 0.19, 0.24), 0.85),
             "maglia": ("persona_maglia", (0.72, 0.36, 0.26), 0.85), "jeans": ("persona_jeans", (0.20, 0.28, 0.42), 0.9),
             "scarpe": ("persona_scarpe", (0.22, 0.13, 0.08), 0.6)}
_LEGNI = {"legno": ((0.70, 0.50, 0.28), (0.52, 0.34, 0.16), 9.0), "legno_scuro": ((0.38, 0.22, 0.12), (0.22, 0.12, 0.06), 11.0),
          "piano": ((0.82, 0.64, 0.42), (0.68, 0.48, 0.28), 7.0)}


def _slot(me, chiavi):
    for k in chiavi:
        nome, rgb, rough = MATERIALI[k]
        if k in _LEGNI:
            ch, sc, scala = _LEGNI[k]
            me.materials.append(_materiale_legno(nome, ch, sc, scala))
        else:
            me.materials.append(_materiale(nome, rgb, rough))


class _Costruttore:
    """bmesh con parti (scatole, cilindri, sfere) ciascuna con il proprio materiale."""
    def __init__(self, chiavi):
        self.bm = bmesh.new()
        self.chiavi = list(chiavi)

    def _fine(self, ris, k):
        mi = self.chiavi.index(k)
        for v in ris["verts"]:
            for f in v.link_faces:
                f.material_index = mi

    def scatola(self, c, d, k, rz=0.0, r=0.0):
        """Scatola centrata in c di dimensioni d, ruotata di rz attorno a Z; r > 0 arrotonda gli spigoli."""
        m = Matrix.Translation(c) @ Matrix.Rotation(rz, 4, 'Z') @ Matrix.Diagonal((d[0], d[1], d[2], 1.0))
        ris = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        self._fine(ris, k)
        if r > 0:
            mi = self.chiavi.index(k)
            spigoli = list({e for v in ris["verts"] for e in v.link_edges})
            try:
                nuove = bmesh.ops.bevel(self.bm, geom=spigoli, offset=r, segments=2, affect='EDGES', profile=0.5)
                for f in nuove["faces"]:
                    f.material_index = mi
            except Exception:
                pass

    def cilindro(self, c, r, h, k, r2=None, seg=12):
        m = Matrix.Translation(c)
        self._fine(bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r if r2 is None else r2,
                                         depth=h, matrix=m), k)

    def tra(self, a, b, r1, r2, k, seg=12):
        """Cilindro (tronco di cono) dal punto a (raggio r1) al punto b (raggio r2)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        self._fine(bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r1, radius2=r2, depth=d.length,
                                         matrix=m), k)

    def tra_e(self, a, b, r1, r2, k, prof=0.65, seg=20):
        """Come tra, ma a sezione ellittica: profondita' = prof x larghezza (busto, bacino)."""
        a, b = Vector(a), Vector(b)
        d = b - a
        m = Matrix.Translation((a + b) / 2) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4()
        self._fine(bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r1, radius2=r2, depth=d.length,
                                         matrix=m @ Matrix.Diagonal((1.0, prof, 1.0, 1.0))), k)

    def sfera(self, c, r, k, scala=(1, 1, 1), fine=False):
        m = Matrix.Translation(c) @ Matrix.Diagonal((scala[0], scala[1], scala[2], 1.0))
        self._fine(bmesh.ops.create_uvsphere(self.bm, u_segments=24 if fine else 14, v_segments=16 if fine else 10, radius=r, matrix=m), k)

    def mesh(self, nome, matrix, liscio=False):
        me = bpy.data.meshes.new(nome)
        self.bm.transform(matrix)
        self.bm.to_mesh(me)
        self.bm.free()
        _slot(me, self.chiavi)
        for p in me.polygons:
            p.use_smooth = liscio
        return me


MOBILI = ["legno", "legno_scuro", "tela", "cuscino", "lino", "acciaio", "nero", "piano", "ceramica", "verde", "terracotta"]


def _letto(cb):
    """Letto 1,60 x 1,90 m (materasso), senza testiera: telaio di legno 1,64 x 1,94, materasso, piumone con risvolto, cuscini, plaid ai piedi.
    La testa e' sul lato -Y locale (quello che sta contro la parete)."""
    cb.scatola((0, 0, 0.14), (1.64, 1.94, 0.22), "legno_scuro", r=0.012)
    for x in (-0.76, 0.76):
        for y in (-0.89, 0.89):
            cb.scatola((x, y, 0.015), (0.08, 0.08, 0.03), "legno_scuro")           # piedini
    cb.scatola((0, 0, 0.33), (1.60, 1.90, 0.22), "tela", r=0.05)                   # materasso
    cb.scatola((0, 0.27, 0.45), (1.62, 1.36, 0.07), "cuscino", r=0.03)             # piumone
    cb.scatola((0, -0.41, 0.46), (1.63, 0.12, 0.08), "tela", r=0.035)              # risvolto
    cb.scatola((0, 0.78, 0.475), (1.64, 0.34, 0.03), "lino", r=0.012)              # plaid ai piedi
    for x, rz in ((-0.40, 0.04), (0.40, -0.05)):
        cb.scatola((x, -0.72, 0.51), (0.62, 0.38, 0.14), "tela", rz=rz, r=0.055)   # cuscini
    cb.scatola((0.0, -0.74, 0.58), (0.55, 0.22, 0.10), "lino", r=0.045)


def _cucina(cb):
    """Blocco cucina di legno, 1,8 m: basi con ante e maniglie, piano di legno, lavello con rubinetto, piano cottura, mensola con barattoli."""
    cb.scatola((0, 0, 0.04), (1.76, 0.54, 0.08), "nero")                                  # zoccolo rientrato
    cb.scatola((0, 0, 0.45), (1.80, 0.60, 0.74), "legno", r=0.006)                        # corpo
    for i, x in enumerate((-0.60, 0.0, 0.60)):
        cb.scatola((x, 0.305, 0.45), (0.585, 0.02, 0.70), "legno_scuro" if i == 1 else "legno", r=0.006)   # ante
        cb.scatola((x + 0.22, 0.322, 0.70), (0.012, 0.012, 0.14), "acciaio")              # maniglie verticali
    cb.scatola((0, 0.0, 0.855), (1.84, 0.64, 0.045), "piano", r=0.01)                     # piano di legno
    cb.scatola((-0.50, 0.0, 0.88), (0.52, 0.38, 0.012), "acciaio")                        # lavello
    cb.scatola((-0.50, 0.0, 0.885), (0.42, 0.28, 0.012), "nero")
    cb.cilindro((-0.50, -0.20, 0.99), 0.012, 0.22, "acciaio", seg=8)                      # rubinetto
    cb.tra((-0.50, -0.20, 1.10), (-0.50, -0.09, 1.10), 0.011, 0.011, "acciaio", seg=8)
    for x, y in ((0.45, -0.12), (0.72, -0.12), (0.45, 0.14), (0.72, 0.14)):               # piano cottura a induzione
        cb.cilindro((x, y, 0.882), 0.085, 0.006, "nero", seg=18)
    cb.scatola((0, -0.31, 1.15), (1.84, 0.015, 0.55), "legno_scuro")                      # schienale a muro
    cb.scatola((-0.20, -0.20, 1.50), (1.30, 0.26, 0.035), "legno", r=0.008)               # mensola
    for x in (-0.80, 0.40):
        cb.scatola((x, -0.28, 1.43), (0.03, 0.05, 0.12), "nero")
    for i, x in enumerate((-0.65, -0.45, -0.10, 0.10)):                                    # barattoli e tazze
        cb.cilindro((x, -0.20, 1.575), 0.045 if i < 2 else 0.04, 0.115, "ceramica" if i % 2 == 0 else "terracotta", seg=14)
    cb.cilindro((0.55, 0.15, 0.905), 0.035, 0.07, "ceramica", seg=12)                      # tazza sul piano


def _scrivania(cb):
    """Scrivania di rovere 1,3 m con cassettiera, sedia imbottita, lampada, portatile e pianta."""
    cb.scatola((0, 0, 0.755), (1.30, 0.65, 0.04), "legno", r=0.008)
    for x in (-0.60,):
        for y in (-0.27, 0.27):
            cb.tra((x, y, 0.735), (x - 0.02, y, 0.0), 0.030, 0.022, "legno_scuro", seg=8)
    cb.scatola((0.49, 0.0, 0.46), (0.40, 0.56, 0.56), "legno_scuro", r=0.008)             # cassettiera
    for z in (0.62, 0.45, 0.28):
        cb.scatola((0.49, 0.285, z), (0.36, 0.012, 0.15), "legno", r=0.004)
        cb.scatola((0.49, 0.296, z), (0.12, 0.012, 0.014), "acciaio")
    cb.scatola((-0.1, 0.0, 0.7775), (0.34, 0.24, 0.016), "nero", r=0.004)                  # portatile
    cb.scatola((-0.1, -0.11, 0.89), (0.34, 0.012, 0.22), "nero", rz=0.0)
    cb.tra((-0.55, -0.20, 0.775), (-0.50, -0.12, 1.00), 0.012, 0.006, "nero", seg=8)       # lampada
    cb.tra((-0.50, -0.12, 1.00), (-0.30, -0.02, 0.96), 0.006, 0.006, "nero", seg=8)
    cb.tra((-0.30, -0.02, 0.97), (-0.28, -0.01, 0.90), 0.055, 0.015, "nero", seg=12)
    cb.cilindro((0.30, -0.18, 0.80), 0.045, 0.07, "terracotta", r2=0.035, seg=12)           # vaso con pianta
    for dx, dy, dz in ((0, 0, 0.12), (0.03, 0.02, 0.07), (-0.03, 0.01, 0.08)):
        cb.sfera((0.30 + dx, -0.18 + dy, 0.87 + dz), 0.06, "verde", (1, 1, 0.9))
    # sedia: seduta imbottita, schienale, gambe di legno
    cb.scatola((0, 0.62, 0.47), (0.46, 0.44, 0.06), "cuscino", r=0.02)
    cb.scatola((0, 0.84, 0.74), (0.44, 0.04, 0.42), "cuscino", r=0.02)
    for x in (-0.19, 0.19):
        for y in (0.45, 0.79):
            cb.tra((x, y, 0.45), (x * 1.08, y + (0.03 if y > 0.6 else -0.03), 0.0), 0.017, 0.012, "legno_scuro", seg=8)
    for x in (-0.19, 0.19):
        cb.tra((x, 0.80, 0.45), (x, 0.84, 0.95), 0.016, 0.014, "legno_scuro", seg=8)


def _dentro(poly, q, margine=0.0):
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]) < margine * math.hypot(b[0] - a[0], b[1] - a[1]):
            return False
    return True


def _posa(poly, c, dwd, phi_deg, w, d, h_ogg, zf):
    """Centro e rotazione di un mobile contro la parete nella direzione phi (dalla porta, antiorario): il retro tocca la parete (alla
    quota del mobile) e i due angoli del retro stanno dentro la sezione."""
    a = math.atan2(dwd[1], dwd[0]) + math.radians(phi_deg)
    r = (math.cos(a), math.sin(a))                    # verso la parete
    t = (-r[1], r[0])
    rr = 0.0
    k = 3.0
    while k > 0.0:
        ok = all(_dentro(poly, (c[0] + r[0] * k + t[0] * s, c[1] + r[1] * k + t[1] * s), 0.02) for s in (-w / 2, 0.0, w / 2))
        if ok:
            rr = k
            break
        k -= 0.02
    cen = (c[0] + r[0] * (rr - d / 2), c[1] + r[1] * (rr - d / 2))
    rot = a - math.pi / 2 + math.pi                   # il fronte (+Y locale) guarda verso il centro
    return cen, rot


def _persona(cb, h, donna):
    """Figura stilizzata ma proporzionata (testa, collo, torso, braccia con gomito, mani, gambe con ginocchio, scarpe, capelli); le forme sono
    capsule e sfere: pochi poligoni, forme morbide.  Uomo con camicia, donna con maglia e jeans e capelli lunghi."""
    s = h / 1.78
    w = 0.86 if donna else 1.0
    def P(x, y, z):
        return (x * s, y * s, z * s)
    cam = "maglia" if donna else "camicia"
    pan = "jeans" if donna else "pantaloni"
    pelle = "pelle2" if donna else "pelle"
    capelli = "capelli2" if donna else "capelli"
    for sx in (-1, 1):
        anca, gin, cav = P(sx * 0.09 * w, 0.0, 0.93), P(sx * 0.095 * w, 0.015, 0.50), P(sx * 0.10 * w, 0.0, 0.085)
        cb.tra(anca, gin, 0.080 * s * w, 0.056 * s, pan, seg=20)
        cb.sfera(gin, 0.056 * s, pan, fine=True)
        cb.tra(gin, cav, 0.056 * s, 0.038 * s, pan, seg=20)
        cb.sfera(P(sx * 0.10 * w, 0.0, 0.08), 0.040 * s, pan, fine=True)
        cb.sfera(P(sx * 0.10 * w, 0.06, 0.04), 0.055 * s, "scarpe", (0.85, 2.4, 0.75), fine=True)      # scarpa: ovale, non scatola
    # bacino, vita stretta, petto, spalle
    cb.sfera(P(0, 0, 0.97), 0.16 * s * w, pan, (1.0, 0.72, 0.8), fine=True)
    cb.tra_e(P(0, 0, 0.97), P(0, 0, 1.12), 0.155 * s * w, 0.135 * s * w, cam, 0.68)
    cb.tra_e(P(0, 0, 1.12), P(0, 0, 1.38), 0.135 * s * w, 0.172 * s * w, cam, 0.66)
    cb.sfera(P(0, 0, 1.38), 0.172 * s * w, cam, (1.0, 0.66, 0.5), fine=True)
    cb.sfera(P(0, 0, 1.385), 0.24 * s * w, cam, (1.0, 0.34, 0.26), fine=True)                  # linea delle spalle
    if donna:
        cb.tra_e(P(0, 0, 0.82), P(0, 0, 1.0), 0.17 * s, 0.150 * s * w, cam, 0.70)               # maglia lunga sui fianchi
        cb.sfera(P(0, 0.03, 1.28), 0.075 * s, cam, (1.2, 0.9, 0.9), fine=True)
    for sx in (-1, 1):
        sp, go, po = P(sx * 0.225 * w, 0.0, 1.38), P(sx * 0.255 * w, 0.03, 1.13), P(sx * 0.235 * w, 0.10, 0.90)
        cb.sfera(sp, 0.055 * s, cam, fine=True)
        cb.tra(sp, go, 0.050 * s, 0.038 * s, cam, seg=20)
        cb.sfera(go, 0.038 * s, cam, fine=True)
        cb.tra(go, po, 0.038 * s, 0.028 * s, pelle, seg=20)
        cb.sfera(po, 0.036 * s, pelle, (0.9, 1.2, 1.4), fine=True)
    cb.tra(P(0, 0, 1.42), P(0, 0, 1.56), 0.050 * s, 0.044 * s, pelle, seg=20)
    cb.sfera(P(0, 0, 1.655), 0.100 * s, pelle, (0.88, 0.98, 1.14), fine=True)
    cb.sfera(P(0, 0.095, 1.645), 0.015 * s, pelle, fine=True)                                   # naso
    cb.sfera(P(0, -0.012, 1.695), 0.108 * s, capelli, (0.94, 1.0, 0.86), fine=True)
    if donna:
        cb.tra(P(0, -0.06, 1.68), P(0, -0.09, 1.34), 0.082 * s, 0.040 * s, capelli, seg=20)
        cb.sfera(P(0, -0.09, 1.34), 0.040 * s, capelli, fine=True)
    else:
        cb.sfera(P(0, 0.03, 1.72), 0.07 * s, capelli, (1.0, 0.8, 0.6), fine=True)


def _rimuovi(nome_ob):
    ob = bpy.data.objects.get(nome_ob)
    if ob is not None:
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def _coll(scene, nome):
    c = bpy.data.collections.get(nome)
    if c is None:
        c = bpy.data.collections.new(nome)
    if c.name not in scene.collection.children and c.name not in [x.name for x in bpy.data.collections if c.name in x.children]:
        scene.collection.children.link(c)
    return c


def _sotto_zome(nome_zome, nome):
    """Collection figlia della zome. Se era appesa alla scena, la sposta sotto."""
    padre = bpy.data.collections.get(nome_zome)
    c = bpy.data.collections.get(nome)
    if c is None:
        c = bpy.data.collections.new(nome)
    scena = bpy.context.scene.collection
    if c.name in scena.children:
        scena.children.unlink(c)
    for altro in list(bpy.data.collections):
        if altro != padre and c.name in altro.children:
            altro.children.unlink(c)
    if padre is not None and c.name not in padre.children:
        padre.children.link(c)
    elif padre is None and c.name not in scena.children:
        scena.children.link(c)
    return c


def aggiorna_arredo(scene, z, model):
    """Mobili (solo il letto; cucina e scrivania sono ancora definite sopra ma non usate) e persone (un uomo e una donna) sul pavimento finito.
    Il letto sta contro la parete opposta alla porta; le persone stanno ai lati, ognuna rivolta verso la parete e a ridosso di essa: il centro e' sul
    bordo della sezione all'altezza della testa, quindi dove la parete scende la testa la tocca (si vede se si batte la testa)."""
    nome = z.nome or "zome"
    for suff in ("_mobili", "_uomo", "_donna"):
        _rimuovi(nome + suff)
    coll = bpy.data.collections.get(f"{nome} · Arredo")
    if not (z.arredo_mobili or z.arredo_persone) or model is None:
        if coll is not None and not coll.objects and not coll.children:
            bpy.data.collections.remove(coll)
        return
    coll = _sotto_zome(nome, f"{nome} · Arredo")
    faces = [pts for s_ in model["strata"] for _, pts in s_["facce"]]
    zf = model["summary"].get("quota_pavimento", 0.0)
    pav = model.get("pavimento")
    dwd = pav["dir_porta"] if pav else (0.0, -1.0)
    sez = sezione(faces, zf + 0.30)
    if len(sez) < 3:
        return
    c = _centro(sez)
    z0 = zf
    if z.arredo_mobili:
        cb = _Costruttore(MOBILI)
        # tutti i mobili in un solo oggetto: ognuno costruito nel suo riferimento locale, poi spostato e ruotato
        parti = []
        for fn, phi, w, d, h in ((_letto, 180.0, 1.66, 1.96, 0.6),):
            polys = sezione(faces, z0 + h)
            if len(polys) < 3:
                continue
            cen, rot = _posa(polys, c, dwd, phi, w, d, h, z0)
            sub = _Costruttore(cb.chiavi)
            fn(sub)
            sub.bm.transform(Matrix.Translation((cen[0], cen[1], z0)) @ Matrix.Rotation(rot, 4, 'Z'))
            parti.append(sub)
        me = bpy.data.meshes.new(nome + "_mobili")
        for sub in parti:
            tmp = bpy.data.meshes.new("tmp")
            sub.bm.to_mesh(tmp)
            sub.bm.free()
            cb.bm.from_mesh(tmp)
            bpy.data.meshes.remove(tmp)
        cb.bm.to_mesh(me)
        cb.bm.free()
        _slot(me, cb.chiavi)
        ob = bpy.data.objects.new(nome + "_mobili", me)
        coll.objects.link(ob)
    if z.arredo_persone:
        a = math.atan2(dwd[1], dwd[0])
        for suff, h, donna, phi, (da, dt) in (("_uomo", 1.78, False, -90.0, (0.15, -0.55)), ("_donna", 1.66, True, 90.0, (-0.35, 0.45))):
            ang = a + math.radians(phi)                     # verso la parete laterale (0 = verso la porta, antiorario)
            r = (math.cos(ang), math.sin(ang))
            pol_testa = sezione(faces, z0 + h - 0.05)       # sezione all'altezza della testa
            pol_piedi = sezione(faces, z0 + 0.05)
            pos = None
            if len(pol_testa) >= 3 and len(pol_piedi) >= 3:
                k = 4.0
                while k > 0.0:                              # il piu' vicino alla parete: centro sul bordo della sezione della testa
                    q = (c[0] + r[0] * k, c[1] + r[1] * k)
                    if _dentro(pol_testa, q, 0.0) and _dentro(pol_piedi, q, 0.05):
                        pos = (q[0], q[1], z0)
                        break
                    k -= 0.01
            if pos is None:                                 # zome troppo bassa o stretta: posizione di prima, vicino al centro
                t = (-math.sin(a), math.cos(a))
                pos = (c[0] + math.cos(a) * da + t[0] * dt, c[1] + math.sin(a) * da + t[1] * dt, z0)
            cb = _Costruttore(["pantaloni", "jeans", "pelle", "pelle2", "maglia", "camicia", "capelli", "capelli2", "scarpe"])
            _persona(cb, h, donna)
            rot = ang                                       # guardano verso la parete che stanno per toccare
            me = cb.mesh(nome + suff, Matrix.Translation(pos) @ Matrix.Rotation(rot, 4, 'Z'), liscio=True)
            ob = bpy.data.objects.new(nome + suff, me)
            coll.objects.link(ob)


# --- animazione della visita -----------------------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------------------------------------- spaccato verticale
_SUFF_INTERO = " · intero"


def _oggetti_zome(z):
    """Mesh da tagliare nello spaccato: la zome con tutte le sue parti e il suo arredo.  Il riferimento `_interno` (rombi nudi, nascosto
    quando c'e' l'esterno) resta intero finche' l'esterno e' acceso: le scelte manuali di tetto/legno/vetro si fanno sulle sue facce."""
    nome = z.nome or "zome"
    obs, visti = [], set()
    for cn in (nome, f"{nome} · Arredo"):
        c = bpy.data.collections.get(cn)
        if c is None:
            continue
        for o in c.all_objects:
            if o.type != 'MESH' or o.as_pointer() in visti:
                continue
            visti.add(o.as_pointer())
            obs.append(o)
    if z.esterno:
        obs = [o for o in obs if o.name != nome + "_interno"]
    return obs


def _ripristina(o):
    """Rimette la mesh intera di un oggetto tagliato (se c'e')."""
    nm = o.get("spaccato_intero")
    if not nm:
        return
    orig = bpy.data.meshes.get(nm)
    if orig is not None:
        taglio = o.data
        o.data = orig
        orig.use_fake_user = False
        if taglio is not orig and taglio.users == 0:
            bpy.data.meshes.remove(taglio)
        if orig.name.endswith(_SUFF_INTERO):
            orig.name = orig.name[:-len(_SUFF_INTERO)]       # ritorna al nome di prima
    del o["spaccato_intero"]


def aggiorna_spaccato(scene, z):
    """Spaccato verticale a percentuale: 0 = zome intera, 50 = tagliata a meta', 100 = sparita.
    Un piano verticale, perpendicolare alla direzione `spaccato_dir` (0 = sud, 90 = est, 180 = nord, come la porta), scorre da una
    parte all'altra della zome; si toglie la parte dal lato della direzione (con 0 si guarda dal sud dentro la zome).
    Si taglia ogni mesh con il piano (bmesh, senza chiudere le sezioni); l'originale resta nella mesh `<nome> · intero` e si
    ripristina a 0.  La ricostruzione della zome ricrea tutto intero e ricalcola il taglio."""
    f = max(0.0, min(100.0, z.spaccato)) / 100.0
    obs = _oggetti_zome(z)
    # pulizia vecchie guide del Booleano (versione provvisoria) e mesh intere rimaste orfane
    for o in bpy.data.objects:
        for m in list(o.modifiers):
            if m.name == "Spaccato":
                o.modifiers.remove(m)
    _rimuovi((z.nome or "zome") + "_spaccato")
    for me in list(bpy.data.meshes):
        if me.name.endswith(_SUFF_INTERO) and me.use_fake_user and not any(o.get("spaccato_intero") == me.name for o in bpy.data.objects):
            me.use_fake_user = False
            if me.users == 0:
                bpy.data.meshes.remove(me)
    for o in obs:
        _ripristina(o)                                   # si parte sempre dall'intero
    if f <= 0.0 or not obs:
        return
    a = math.radians(z.spaccato_dir)
    d = (math.sin(a), -math.cos(a))
    smin, smax = 1e9, -1e9
    for o in obs:
        M_ = o.matrix_world
        for v in o.data.vertices:
            w = M_ @ v.co
            t = w.x * d[0] + w.y * d[1]
            smin, smax = min(smin, t), max(smax, t)
    c = smin - 0.05 if f >= 1.0 else smax - f * (smax - smin)
    for o in obs:
        orig = o.data
        taglio = orig.copy()
        orig.name = orig.name + _SUFF_INTERO if not orig.name.endswith(_SUFF_INTERO) else orig.name
        taglio.name = orig.name[:-len(_SUFF_INTERO)] if orig.name.endswith(_SUFF_INTERO) else orig.name + "_taglio"
        orig.use_fake_user = True
        o["spaccato_intero"] = orig.name
        o.data = taglio
        M_ = o.matrix_world
        bm = bmesh.new()
        bm.from_mesh(taglio)
        bm.transform(M_)
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-6, plane_co=(d[0] * c, d[1] * c, 0.0), plane_no=(d[0], d[1], 0.0),
                               clear_inner=False, clear_outer=True)
        bm.transform(M_.inverted())
        bm.to_mesh(taglio)
        bm.free()
        taglio.update()


def _frame(t, F):
    return 1 + int(round(t * (F - 1)))


def rimuovi_animazione(scene, z):
    nome = z.nome or "zome"
    for suff in ("_camera_visita", "_sguardo"):
        ob = bpy.data.objects.get(nome + suff)
        if ob is not None:
            dati = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if dati is not None and dati.users == 0:
                bpy.data.cameras.remove(dati)
    coll = bpy.data.collections.get(f"{nome} · Animazione")
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)
    sun = trova_sole()
    if sun is not None:
        sun.animation_data_clear()
        sun.data.animation_data_clear()
    emp = bpy.data.objects.get(nome + "_cerniera")
    if emp is not None:
        emp.animation_data_clear()
        emp.rotation_axis_angle = (math.radians(z.porta_apertura), *emp.rotation_axis_angle[1:])
    prima = scene.get("zome_camera_prima")
    if prima is not None:
        cam = bpy.data.objects.get(prima)
        if cam is not None:
            scene.camera = cam
        fs, fe = scene.get("zome_frame_prima", (scene.frame_start, scene.frame_end))
        scene.frame_start, scene.frame_end = int(fs), int(fe)
        del scene["zome_camera_prima"]
    aggiorna_sole(z)


def animazione_esiste(z):
    return bpy.data.objects.get((z.nome or "zome") + "_camera_visita") is not None


def _raggio_poligono(poly, c, d):
    """Distanza t >= 0 tale che c + t d esce dal poligono convesso (c dentro)."""
    best = None
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = d[0] * ey - d[1] * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - c[0]) * ey - (ay - c[1]) * ex) / den
        u = ((ax - c[0]) * d[1] - (ay - c[1]) * d[0]) / den
        if t > 1e-9 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
            best = t
    return best if best is not None else 0.0


def crea_animazione(scene, z, model, secondi=24.0, sole=True):
    """Visita: si parte fuori sulla linea della porta, ci si avvicina, la porta (sulle cerniere) si apre verso l'interno, si entra, si va
    dall'altra parte e ci si gira guardando in alto; il sole, se richiesto, fa il giro dall'alba al tramonto.  Senza porta si
    attraversano le pareti.  Ritorna il numero di fotogrammi."""
    nome = z.nome or "zome"
    p = model["params"]
    s = model["summary"]
    fps = scene.render.fps or 24
    F = max(48, int(secondi * fps))
    foot, tw, up, out = _porta_frame(p)
    oh = Vector((out[0], out[1], 0.0)).normalized()
    lat = Vector((-oh.y, oh.x, 0.0))
    c = Vector((p.px, p.py, 0.0))
    R = s["diametro_base"] / 2
    zf = s.get("quota_pavimento", 0.0)
    H = s.get("altezza_esterna", s["altezza_totale"])
    dist = p.porta_dist if z.porta else R
    Fd = c + oh * dist                                   # sul piano della porta

    def at(sx, zz, l=0.0):
        v = Fd + oh * sx + lat * l
        return Vector((v.x, v.y, zz))
    occhi_f, occhi_d = 1.65, zf + 1.65
    D = max(s.get("ingombro_x_esterno", 2 * R), s.get("ingombro_y_esterno", 2 * R), 2 * R)
    # 1) giro aereo: dalla porta (sud) attorno alla zome e di nuovo alla porta, ad altezza 1,5 volte quella della zome e a una
    #    distanza per cui la zome occupa circa un terzo della larghezza dell'inquadratura (obiettivo 22 mm: d = 1,83 x ingombro)
    ah = 1.5 * H
    d_orb = max(0.9, getattr(z, "anim_distanza", 1.3)) * D
    rh = math.sqrt(max(d_orb ** 2 - (ah - 0.45 * H) ** 2, (0.8 * D) ** 2))
    a0 = math.atan2(oh.y, oh.x)
    T_ORB = 0.30
    cam_pts, look_pts = [], []
    NO = 24
    for k in range(NO + 1):
        ang = a0 - 2 * math.pi * k / NO                      # senso orario visto dall'alto: da sud verso ovest, nord, est, sud
        cam_pts.append((T_ORB * k / NO, Vector((c.x + rh * math.cos(ang), c.y + rh * math.sin(ang), ah))))
        look_pts.append((T_ORB * k / NO, Vector((c.x, c.y, zf + 0.45 * H))))
    # 2) davanti alla porta ad altezza d'uomo, ci si avvicina, si entra
    cam_pts += [(0.37, at(6.0, occhi_f)), (0.47, at(1.8, occhi_f)), (0.54, at(0.5, occhi_f + 0.5 * zf)), (0.60, at(-0.7, occhi_d))]
    look_pts += [(0.37, at(0.0, zf + 1.4)), (0.54, at(0.0, zf + 1.4)), (0.60, at(-dist - R * 0.5, occhi_d))]
    # 3) fino al punto piu' lontano dalla porta (a nord), e da li' un lento giro da sinistra a destra: porta, mobilia, pareti
    # il punto piu' lontano deve stare DENTRO: sezione a quota testa (1,75 m) e camera al 65 % della distanza fino alla parete
    facce = [pts for s_ in model["strata"] for _, pts in s_["facce"]]
    dfar = 0.0
    for quota in (zf + 1.75, zf + 1.55, zf + 1.35):
        sez = sezione(facce, quota)
        if len(sez) >= 3:
            dfar = _raggio_poligono(sez, (c.x, c.y), (-oh.x, -oh.y))
            if dfar > 0.8:
                break
    nord = Vector((c.x - oh.x * 0.65 * dfar, c.y - oh.y * 0.65 * dfar, occhi_d))
    cam_pts += [(0.70, nord), (1.00, nord)]
    look_pts += [(0.70, at(-dist + 0.5 * R, occhi_d - 0.2, 0.0)), (0.76, at(-dist + 0.9 * R, occhi_d - 0.3, 0.9 * R)),
                 (1.00, at(-dist + 0.9 * R, occhi_d - 0.3, -0.9 * R))]
    if animazione_esiste(z):
        rimuovi_animazione(scene, z)
    if "zome_camera_prima" not in scene:
        scene["zome_camera_prima"] = scene.camera.name if scene.camera else ""
        scene["zome_frame_prima"] = (scene.frame_start, scene.frame_end)
    coll = _coll(scene, f"{nome} · Animazione")
    cd = bpy.data.cameras.new(nome + "_camera_visita")
    cd.lens = 22.0
    cd.clip_start = 0.05
    cam = bpy.data.objects.new(nome + "_camera_visita", cd)
    tgt = bpy.data.objects.new(nome + "_sguardo", None)
    tgt.empty_display_type = 'PLAIN_AXES'
    tgt.empty_display_size = 0.15
    coll.objects.link(cam)
    coll.objects.link(tgt)
    con = cam.constraints.new('TRACK_TO')
    con.target = tgt
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    for t, v in cam_pts:
        cam.location = v
        cam.keyframe_insert("location", frame=_frame(t, F))
    for t, v in look_pts:
        tgt.location = v
        tgt.keyframe_insert("location", frame=_frame(t, F))
    emp = bpy.data.objects.get(nome + "_cerniera")
    if emp is not None and z.porta and z.porta_anta:
        for t, ang in ((0.0, 0.0), (0.45, 0.0), (0.56, math.radians(88.0)), (1.0, math.radians(88.0))):
            emp.rotation_axis_angle = (ang, *emp.rotation_axis_angle[1:])
            emp.keyframe_insert("rotation_axis_angle", index=0, frame=_frame(t, F))
    sun = trova_sole()
    if sole and sun is not None:
        alba, tram = alba_tramonto(z.sole_mese, z.sole_giorno)
        a0, a1 = (alba or 6.0) + 0.3, (tram or 20.0) - 0.3
        prev = None
        n = 24
        # il sole sta fermo fino al punto piu' lontano dentro la zome; poi fa il giro, durante il lento giro di sguardo finale
        for k in range(n + 1):
            _imposta_sole(sun, z.sole_mese, z.sole_giorno, a0 + (a1 - a0) * k / n, prev)
            prev = sun.rotation_euler.copy()
            frs = [_frame(0.62 + 0.38 * k / n, F)] + ([_frame(0.0, F)] if k == 0 else [])
            for fr in frs:
                sun.keyframe_insert("rotation_euler", frame=fr)
                sun.data.keyframe_insert("energy", frame=fr)
                sun.data.keyframe_insert("color", frame=fr)
        for fc in (sun.animation_data.action.fcurves if hasattr(sun.animation_data.action, "fcurves") else []):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
    scene.camera = cam
    scene.frame_start, scene.frame_end, scene.frame_current = 1, F, 1
    return F
