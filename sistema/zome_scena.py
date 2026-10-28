"""Foglio tecnico dai solidi della collection, non da una ricostruzione dell'algoritmo.

Entrano i solidi che hanno la proprietà materiale. Stesso tipo, stesso colore.
Per ogni tipo: isometrica, pianta, laterale, sezione.
"""
import math
import os
from collections import Counter
from datetime import date

from zome_foglio import (NOMI, TILT_NEVE, LUCE_GRANDE, _altitudini, _croce, _esc, _euro,
                         _iva, _leggibile, _n, _scala, _unita, blocco_termico, peso_di,
                         prezzo_spessore, scegli_vetro, svg_torta)
from zome_core import _dist, _dot, _sub

_PAL = ("#c0392b", "#2471a3", "#1e8449", "#b7950b", "#6c3483", "#d35400", "#148f77",
        "#1a5276", "#a04000", "#196f3d", "#4a235a", "#7d6608", "#1abc9c", "#7b241c",
        "#5d6d7e", "#b9770e")
_LUCE = (0.35, 0.55, 0.76)
_CAM = (0.72, 0.48, 0.50)
_SUFFISSI = ("_scheletro", "_pareti_porta", "_anta_vetro", "_anta", "_porta", "_legno",
             "_vetro", "_tetto", "_gronda", "_perline", "_pav_travetti", "_pav_dormienti",
             "_pav_tavolato", "_pav_fondo", "_pav_isolante", "_isolante", "_pav_pietre", "_pav_gradino", "_tappi")
_ORDINE = (
    ("scheletro", "Scheletro", "c24", "m³", "travi"),
    ("dormienti", "Pali del pavimento", "c24", "m³", "travi"),
    ("travetti", "Travetti", "c24", "m³", "travi"),
    ("tavolato", "Pavimento", "perline", "m²", "travi"),
    ("fondo", "Tavolato sotto i travetti", "perline", "m²", "travi"),
    ("perline_est", "Esterno", "perline", "m²", "esterno"),
    ("pareti", "Pareti del corridoio", "perline", "m²", "esterno"),
    ("perline_int", "Interno", "perline", "m²", "perline"),
    ("isolante", "Isolante", "isolante", "m²", "esterno"),
    ("vetro", "Vetrocamera", "vetro", "m²", "vetro"),
    ("copertura", "Copertura", "tegole", "m²", "esterno"),
    ("aggiunto", "Solidi non assegnati", None, None, None),
)
_FETTA = {
    "scheletro": ("c24", "C24"), "porta": ("c24", "C24"),
    "dormienti": ("c24", "C24"), "travetti": ("c24", "C24"),
    "tavolato": ("pav", "Pavimento"), "fondo": ("pav", "Pavimento"),
    "isolante": ("iso", "Isolante"),
    "perline_est": ("est", "Esterno"), "pareti": ("est", "Esterno"),
    "perline_int": ("int", "Interno"),
    "vetro": ("vetro", "Vetrocamera"),
    "copertura": ("cop", "Copertura"),
}
_DESTRA = (0.8660254, -0.8660254, 0.0)
_SU = (0.5, 0.5, 1.0)
_COLORI_FETTA = {"c24": "#6b4f3a", "est": "#8d8474", "int": "#c4b49a", "pav": "#a07850",
                 "vetro": "#6d8a96", "cop": "#3e6b4f", "iso": "#c4a35a"}


def _moda(vals):
    vals = [v for v in vals if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else None


def _normale(verts, face):
    n = [0.0, 0.0, 0.0]
    m = len(face)
    for i in range(m):
        a, b = verts[face[i]], verts[face[(i + 1) % m]]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return tuple(n)


def _area_faccia(verts, face):
    n = _normale(verts, face)
    return 0.5 * math.sqrt(_dot(n, n))


def _volume(verts, faces):
    v = 0.0
    for f in faces:
        if len(f) < 3:
            continue
        p0 = verts[f[0]]
        for i in range(1, len(f) - 1):
            v += _dot(p0, _croce(verts[f[i]], verts[f[i + 1]]))
    return abs(v) / 6.0


def _isole(nvert, faces):
    parent = list(range(nvert))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    for f in faces:
        for k in f[1:]:
            union(f[0], k)
    gruppi = {}
    for i, f in enumerate(faces):
        gruppi.setdefault(find(f[0]), []).append(i)
    return list(gruppi.values())


def _pca(verts):
    """Centro e tre assi, dal più lungo. I primi due seguono la asimmetria, così un pezzo e il suo specchio restano diversi."""
    n = float(len(verts))
    c = tuple(sum(p[i] for p in verts) / n for i in range(3))
    a = [[0.0, 0.0, 0.0] for _ in range(3)]
    for p in verts:
        d = [p[i] - c[i] for i in range(3)]
        for i in range(3):
            for j in range(i, 3):
                a[i][j] += d[i] * d[j]
    for i in range(3):
        for j in range(i):
            a[i][j] = a[j][i]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(16):
        for p, q in ((0, 1), (0, 2), (1, 2)):
            apq = a[p][q]
            if abs(apq) < 1e-15:
                continue
            app, aqq = a[p][p], a[q][q]
            tau = (aqq - app) / (2.0 * apq)
            t = math.copysign(1.0, tau) / (abs(tau) + math.sqrt(1.0 + tau * tau)) if tau else 1.0
            cp = 1.0 / math.sqrt(1.0 + t * t)
            sp = t * cp
            a[p][p] = app - t * apq
            a[q][q] = aqq + t * apq
            a[p][q] = a[q][p] = 0.0
            for i in range(3):
                if i != p and i != q:
                    aip, aiq = a[i][p], a[i][q]
                    a[i][p] = a[p][i] = cp * aip - sp * aiq
                    a[i][q] = a[q][i] = sp * aip + cp * aiq
            for i in range(3):
                vip, viq = v[i][p], v[i][q]
                v[i][p] = cp * vip - sp * viq
                v[i][q] = sp * vip + cp * viq
    ordine = sorted(range(3), key=lambda i: -a[i][i])
    assi = [_unita(tuple(v[r][i] for r in range(3))) for i in ordine]
    if _dot(assi[2], _croce(assi[0], assi[1])) < 0:
        assi[2] = tuple(-x for x in assi[2])

    def skew(ax):
        s = 0.0
        for p_ in verts:
            t = _dot(_sub(p_, c), ax)
            s += t * t * t
        return s

    # Si ribaltano due assi insieme: è una rotazione, e un pezzo specchiato non coincide.
    for i in (0, 1):
        if skew(assi[i]) < -1e-8:
            assi[i] = tuple(-x for x in assi[i])
            assi[2] = tuple(-x for x in assi[2])
    return c, assi


def _locale(verts):
    c, assi = _pca(verts)
    return [(_dot(_sub(p, c), assi[0]), _dot(_sub(p, c), assi[1]), _dot(_sub(p, c), assi[2])) for p in verts], assi, c


def _estensioni(verts):
    loc, _, _ = _locale(verts)
    out = []
    for i in range(3):
        pr = [p[i] for p in loc]
        out.append(max(pr) - min(pr))
    return out


def _spessore(verts, faces):
    """Distanza fra le due facce più grandi: per una perlina è lo spessore vero, anche se il pannello è inclinato."""
    if len(faces) < 2:
        return 0.0
    ranked = sorted(faces, key=lambda f: -_area_faccia(verts, f))
    a, b = ranked[0], ranked[1]

    def centro(f):
        m = float(len(f))
        return tuple(sum(verts[i][k] for i in f) / m for k in range(3))

    return abs(_dot(_sub(centro(b), centro(a)), _unita(_normale(verts, a))))


def _tre_misure(verts, faces):
    """Lunghezza e le due quote della sezione, così il titolo coincide con laterale e sezione."""
    if not faces:
        return (0.0, 0.0, 0.0)
    lung = 0.0
    for f in faces:
        for i in range(len(f)):
            lung = max(lung, _dist(verts[f[i]], verts[f[(i + 1) % len(f)]]))
    fi = _faccia_pianta(verts, faces)
    pts = [verts[i] for i in faces[fi]]
    if len(pts) < 2:
        return (lung, 0.0, 0.0)
    i_lungo = max(range(len(pts)), key=lambda i: _dist(pts[i], pts[(i + 1) % len(pts)]))
    asse = _unita(_sub(pts[(i_lungo + 1) % len(pts)], pts[i_lungo]))
    nrm = _unita(_normale(verts, faces[fi]))
    lato = _unita(_croce(nrm, asse))
    o = pts[0]

    def span(ax):
        vals = [_dot(_sub(p, o), ax) for p in verts]
        return max(vals) - min(vals)

    return tuple(sorted((lung, span(lato), span(nrm)), reverse=True))


def _chiave_tipo(sol):
    if sol.get("classe") is not None and sol["gruppo"] == "scheletro":
        return ("classe", sol["nome"], sol.get("strato"), int(sol["classe"]))
    if sol["gruppo"] in ("perline_est", "perline_int", "vetro", "copertura", "pareti", "tavolato"):
        return ("forma", sol["gruppo"], _chiave_pannello(sol))
    return ("firma", firma(sol["verts"], sol.get("strato")))


def firma(verts, strato):
    loc, _, _ = _locale(verts)
    pts = tuple(sorted((round(p[0], 3), round(p[1], 3), round(p[2], 3)) for p in loc))
    return (strato, pts)


def _si_incrocia(pts):
    def ccw(p, q, r):
        return (r[1] - p[1]) * (q[0] - p[0]) > (q[1] - p[1]) * (r[0] - p[0])

    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            c, d = pts[j], pts[(j + 1) % n]
            if ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d):
                return True
    return False


def _inviluppo(pts):
    pts = sorted(set((round(x, 6), round(y, 6)) for x, y in pts))
    if len(pts) <= 2:
        return pts

    def croce(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    basso, alto = [], []
    for q in pts:
        while len(basso) >= 2 and croce(basso[-2], basso[-1], q) <= 0:
            basso.pop()
        basso.append(q)
    for q in reversed(pts):
        while len(alto) >= 2 and croce(alto[-2], alto[-1], q) <= 0:
            alto.pop()
        alto.append(q)
    return basso[:-1] + alto[:-1]


def _spezza(rec):
    verts, faces = rec["verts"], rec["faces"]
    if not faces:
        return []
    strati, classi = rec.get("strati"), rec.get("classi")
    out = []
    for facce_i in _isole(len(verts), faces):
        mappa, usati, nuove = {}, [], []
        for fi in facce_i:
            nf = []
            for vi in faces[fi]:
                if vi not in mappa:
                    mappa[vi] = len(usati)
                    usati.append(verts[vi])
                nf.append(mappa[vi])
            nuove.append(nf)
        if max(_area_faccia(usati, f) for f in nuove) < 1e-8 and _volume(usati, nuove) < 1e-10:
            continue
        st = _moda([strati[i] for i in facce_i]) if strati else None
        cl = _moda([classi[i] for i in facce_i]) if classi else None
        fi = max(range(len(nuove)), key=lambda i: _area_faccia(usati, nuove[i]))
        nrm = _unita(_normale(usati, nuove[fi]))
        out.append({"nome": rec["nome"], "ruolo": rec["ruolo"], "materiale": rec.get("materiale") or "",
                    "verts": usati, "faces": nuove,
                    "strato": st, "classe": cl, "cutlist": rec.get("cutlist"),
                    "tilt": math.degrees(math.acos(min(1.0, abs(nrm[2]))))})
    return out


def _gruppo(sol):
    nome, ruolo = sol["nome"].lower(), sol["ruolo"]
    if "pietre" in nome or "gradino" in nome:
        return "pietre"
    if "tappi" in nome:
        return "tappi"
    if ruolo == "Isolante":
        return "isolante"
    if ruolo == "Pavimento":
        if "fondo" in nome:
            return "fondo"
        if "travett" in nome:
            return "travetti"
        if "dormient" in nome:
            return "dormienti"
        if "tavolat" in nome:
            return "tavolato"
        return "aggiunto"
    if ruolo == "Struttura":
        return "porta" if "porta" in nome else "scheletro"
    if ruolo == "Porta":
        return "vetro" if "vetro" in nome else "porta"
    if ruolo == "Esterno · vetro":
        return "vetro"
    if ruolo == "Tetto":
        return "copertura"
    if ruolo == "Interno · perline":
        return "perline_int"
    if ruolo == "Esterno · legno":
        if "pareti" in nome:
            # Le falde del corridoio sono perlina esterna, come il resto del rivestimento, non bituminosa.
            return "perline_est" if sol["tilt"] <= 45.0 else "pareti"
        return "perline_est"
    basso = ruolo.lower()
    if "vetro" in basso:
        return "vetro"
    if "perlin" in basso or "interno" in basso:
        return "perline_int"
    if "tetto" in basso or "gronda" in basso:
        return "tetto"
    if "esterno" in basso:
        return "perline_est"
    if "struttura" in basso or "scheletro" in basso:
        return "scheletro"
    return "aggiunto"


def espandi(oggetti):
    solidi = []
    for rec in oggetti:
        for sol in _spezza(rec):
            sol["gruppo"] = _gruppo(sol)
            solidi.append(sol)
    return solidi


def _acceso(flag, opz):
    return flag is None or opz.get({"travi": "travi", "esterno": "esterno", "perline": "perline",
                                    "vetro": "vetro"}[flag], True)


def _tocca(a, b, tol=0.035):
    def box(s):
        xs, ys, zs = zip(*s["verts"])
        return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

    ax0, ax1, ay0, ay1, az0, az1 = box(a)
    bx0, bx1, by0, by1, bz0, bz1 = box(b)
    if ax1 + tol < bx0 or bx1 + tol < ax0 or ay1 + tol < by0 or by1 + tol < ay0 or az1 + tol < bz0 or bz1 + tol < az0:
        return False
    vb = b["verts"]
    passo_a = max(1, len(a["verts"]) // 16)
    passo_b = max(1, len(vb) // 16)
    t2 = tol * tol
    for p in a["verts"][::passo_a]:
        for q in vb[::passo_b]:
            d = _sub(p, q)
            if _dot(d, d) <= t2:
                return True
    return False


def _colora(tipi, membri):
    """Indice di tinta per tipo. Due tipi che si toccano non condividono la tinta, finché le tinte bastano."""
    vicini = {t: set() for t in tipi}
    ids = list(tipi)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if any(_tocca(p, q) for p in membri[a] for q in membri[b]):
                vicini[a].add(b)
                vicini[b].add(a)
    colore, stretto = {}, False
    for t in sorted(ids, key=lambda k: -len(vicini[k])):
        usati = {colore[v] for v in vicini[t] if v in colore}
        scelto = next((k for k in range(len(_PAL)) if k not in usati), None)
        if scelto is None:
            conteggio = Counter(colore[v] for v in vicini[t] if v in colore)
            scelto = min(range(len(_PAL)), key=lambda k: conteggio.get(k, 0))
            stretto = True
        colore[t] = scelto
    return colore, stretto


def _tonalita(col, k):
    r, g, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)

    def c(v):
        return max(0, min(255, int(v * k)))

    return f"#{c(r):02x}{c(g):02x}{c(b):02x}"


def _iso(p):
    x, y, z = p
    return ((x - y) * 0.8660254, (x + y) * 0.5 + z)


def _ruota_z(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (c * p[0] - s * p[1], s * p[0] + c * p[1], p[2])


def _vista():
    """Verso la camera dell'isometrica. Vale per una zome dritta e per una coricata: i vertici sono già nel mondo."""
    return _unita(_croce(_DESTRA, _SU))


def svg_schema(pezzi, colore_di, w, h, azimut=0.0, bordo=0.8):
    """Solo le facce verso la camera. azimut π è la stessa inquadratura dall'altra parte, ruotando attorno alla verticale."""
    vista = _vista()
    facce = []
    for pz in pezzi:
        col = colore_di[id(pz)] if id(pz) in colore_di else colore_di.get(pz.get("_tipo"), _PAL[0])
        for f in pz["faces"]:
            pts = [_ruota_z(pz["verts"][i], azimut) for i in f]
            if len(pts) < 3:
                continue
            nraw = _normale(pts, list(range(len(pts))))
            if _dot(nraw, nraw) < 1e-16:
                continue
            nrm = _unita(nraw)
            if _dot(nrm, vista) <= 0.02:
                continue
            k = 0.55 + 0.45 * abs(_dot(nrm, _unita(_LUCE)))
            profondita = sum(_dot(p, _CAM) for p in pts) / len(pts)
            facce.append((profondita, [_iso(p) for p in pts], _tonalita(col, k), _tonalita(col, 0.32)))
    if not facce:
        return ""
    facce.sort(key=lambda t: t[0])
    mappa, _s = _scala([p for _, q, _, _ in facce for p in q], w, h, 10)
    parti = []
    for _, q, col, filo in facce:
        punti = " ".join(f"{mappa(p)[0]:.1f},{mappa(p)[1]:.1f}" for p in q)
        parti.append(f'<polygon points="{punti}" fill="{col}" stroke="{filo}" stroke-width="{bordo}" stroke-linejoin="round"/>')
    return f'<svg class="solido" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{"".join(parti)}</svg>'


def svg_due_viste(pezzi, colore_di):
    a = svg_schema(pezzi, colore_di, 520, 340, 0.0, 0.7)
    b = svg_schema(pezzi, colore_di, 520, 340, math.pi, 0.7)
    return f'<div class="doppio"><figure>{a}<figcaption>Un lato</figcaption></figure><figure>{b}<figcaption>L\'altra parte</figcaption></figure></div>'


def _angoli_interni(pts):
    out = []
    n = len(pts)
    for i in range(n):
        b = pts[i]
        ua = _sub(pts[(i - 1) % n], b) if len(pts[0]) == 3 else (pts[(i - 1) % n][0] - b[0], pts[(i - 1) % n][1] - b[1], 0.0)
        uc = _sub(pts[(i + 1) % n], b) if len(pts[0]) == 3 else (pts[(i + 1) % n][0] - b[0], pts[(i + 1) % n][1] - b[1], 0.0)
        if len(pts[0]) == 2:
            ua, uc = (ua[0], ua[1], 0.0), (uc[0], uc[1], 0.0)
        lua, luc = math.sqrt(_dot(ua, ua)), math.sqrt(_dot(uc, uc))
        if lua < 1e-12 or luc < 1e-12:
            out.append(0.0)
            continue
        c = max(-1.0, min(1.0, _dot(ua, uc) / (lua * luc)))
        out.append(math.degrees(math.acos(c)))
    return out


def _faccia_pianta(verts, faces):
    """La faccia su cui si vedono i tagli obliqui; se è tutto a squadro, la più grande."""
    candidate, tutte = [], []
    for i, f in enumerate(faces):
        if len(f) < 3:
            continue
        area = _area_faccia(verts, f)
        tutte.append((area, i))
        pts = [verts[k] for k in f]
        if any(abs(a - 90.0) > 8.0 for a in _angoli_interni(pts)):
            candidate.append((area, i))
    pool = candidate or tutte
    return max(pool)[1] if pool else 0


def _proietta(verts, origine, asse, altro):
    return [(_dot(_sub(p, origine), asse), _dot(_sub(p, origine), altro)) for p in verts]


def _testo_angolo(a):
    """Grado interno e, tra parentesi, quanto manca a 90 sul più acuto."""
    if abs(a - 90.0) <= 2.0:
        return "90°"
    g = int(round(a))
    acuto = min(g, 180 - g)
    return f"{g}° ({90 - acuto}°)"


def _quote_poligono(pts, angoli=False):
    if len(pts) < 2:
        return [], []
    lati = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        lati.append((f"{_n(math.hypot(b[0] - a[0], b[1] - a[1]) * 100, 1)} cm", i))
    vertici = []
    if angoli:
        for i, ang in enumerate(_angoli_interni(pts)):
            if abs(ang - 90.0) > 2.0:
                vertici.append((_testo_angolo(ang), i))
    return lati, vertici


def _disegna(pts, etichette, w, h, stira, fill=None, vertici=None):
    if len(pts) < 2:
        return ""
    src = _leggibile(list(pts)) if stira else list(pts)
    mappa, _s = _scala(src, w, h, 26)
    q = [mappa(p) for p in src]
    n = len(q)
    punti = " ".join(f"{x:.1f},{y:.1f}" for x, y in q)
    riempi = f' fill="{fill}"' if fill else ' fill="none"'
    cx, cy = sum(p[0] for p in q) / n, sum(p[1] for p in q) / n
    testi = []
    for testo, lato in etichette:
        a, b = q[lato % n], q[(lato + 1) % n]
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        dx, dy = mx - cx, my - cy
        L = math.hypot(dx, dy) or 1.0
        testi.append(f'<text x="{mx + dx / L * 11:.1f}" y="{my + dy / L * 11:.1f}">{_esc(testo)}</text>')
    for testo, i in vertici or []:
        vx, vy = q[i % n]
        dx, dy = vx - cx, vy - cy
        L = math.hypot(dx, dy) or 1.0
        testi.append(f'<text class="ang" x="{vx + dx / L * 16:.1f}" y="{vy + dy / L * 14:.1f}">{_esc(testo)}</text>')
    tratto = ' stroke="#222" stroke-width="1.2"'
    if n == 2:
        corpo = f'<line x1="{q[0][0]:.1f}" y1="{q[0][1]:.1f}" x2="{q[1][0]:.1f}" y2="{q[1][1]:.1f}"{tratto}/>'
    else:
        corpo = f'<polygon points="{punti}"{riempi}{tratto}/>'
    return (f'<svg class="disegno" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'{corpo}{"".join(testi)}</svg>')


def _nome_cutlist(sol, lung_max):
    cut, cl = sol.get("cutlist"), sol.get("classe")
    if not cut or cl is None or not (0 <= int(cl) < len(cut)):
        return None
    g = cut[int(cl)]
    if abs(g.get("lung_max", lung_max) - lung_max) > 0.02:
        return None
    if g.get("ruolo") == "traversa":
        return "traversa tra anelli" if g.get("tipo") == "tra_anelli" else "traversa sull'anello"
    if g.get("tipo") == "rombo":
        return "bordo del rombo"
    if g.get("tipo") == "triangolo":
        return "bordo del triangolo"
    return None


def _viste_tipo(campione, colore):
    verts, faces = campione["verts"], campione["faces"]
    fi = _faccia_pianta(verts, faces)
    faccia = faces[fi]
    pts3 = [verts[i] for i in faccia]
    nrm = _unita(_normale(verts, faccia))
    lung, asse = 0.0, (1.0, 0.0, 0.0)
    for i in range(len(pts3)):
        d = _sub(pts3[(i + 1) % len(pts3)], pts3[i])
        L = math.sqrt(_dot(d, d))
        if L > lung:
            lung, asse = L, _unita(d)
    lato = _unita(_croce(nrm, asse))
    o = pts3[0]
    pianta = _proietta(pts3, o, asse, lato)
    incroci = _si_incrocia(pianta)
    if incroci:
        pianta = _inviluppo(pianta)
    et_p, vert_p = _quote_poligono(pianta, angoli=not incroci)
    laterale = _inviluppo(_proietta(verts, o, asse, nrm))
    sezione = _inviluppo(_proietta(verts, o, lato, nrm))
    et_l, vert_l = _quote_poligono(laterale, angoli=True)
    et_s, vert_s = _quote_poligono(sezione, angoli=True)

    loc = [(_dot(_sub(p, o), asse), _dot(_sub(p, o), lato), _dot(_sub(p, o), nrm)) for p in verts]
    pezzo = {"verts": loc, "faces": faces, "_tipo": 0}
    iso = svg_schema([pezzo], {0: colore}, 170, 120, bordo=1.6)
    return (iso, _disegna(pianta, et_p, 240, 130, False, vertici=vert_p),
            _disegna(laterale, et_l, 240, 100, False, vertici=vert_l),
            _disegna(sezione, et_s, 120, 100, False, vertici=vert_s), incroci)


def _chiave_pannello(sol, passo=0.01):
    """Forma della faccia grande. passo in metri: 1 cm per dire se due pezzi sono lo stesso, 5 cm per il colore."""
    verts, faces = sol["verts"], sol["faces"]
    fi = _faccia_pianta(verts, faces)
    f = faces[fi]
    pts = [verts[i] for i in f]
    lati = tuple(sorted(round(_dist(pts[i], pts[(i + 1) % len(pts)]) / passo) * passo for i in range(len(pts))))
    return (sol.get("strato"), len(pts), lati)


def _prezzo_isolante(riga, mm):
    """Euro al metro quadro del modello. Un pacco più sottile della cavità conta in proporzione."""
    if riga is None or riga.get("prezzo") is None:
        return None, "Manca il prezzo di questo isolante."
    unita = str(riga.get("unita") or "")
    if "m³" in unita or "m3" in unita:
        return riga["prezzo"], ""
    cella = riga.get("spessore_mm")
    if cella and mm:
        n = mm / float(cella)
        return riga["prezzo"] * n, (
            f"La cavità è {mm:.0f} mm, il pacco in listino è {float(cella):.0f} mm a {_euro(riga['prezzo'])} €. "
            f"Il conto usa {n:.2f} pacchi per metro quadro.")
    return riga["prezzo"], ""


def _prezzo_perline(prezzi, mm):
    riga = (prezzi or {}).get(NOMI["perline"])
    euro, avviso = prezzo_spessore(riga, mm)
    if euro is not None:
        return euro, avviso, "perline", "nota del foglio" in (avviso or "")
    riga_t = (prezzi or {}).get(NOMI["tavole"])
    if riga_t and riga_t.get("spessore_mm") is not None and mm is not None and abs(float(riga_t["spessore_mm"]) - mm) <= 2.0:
        return (riga_t["prezzo"],
                f"Per {mm:.0f} mm il foglio ha un prezzo sulla riga del listone da {float(riga_t['spessore_mm']):.0f} mm, "
                f"{_euro(riga_t['prezzo'])} €. Il pezzo è contato come perlina.",
                "tavole", False)
    return None, avviso, "perline", False


def _misure(sol):
    return (_tre_misure(sol["verts"], sol["faces"]),
            max(_area_faccia(sol["verts"], f) for f in sol["faces"]),
            _volume(sol["verts"], sol["faces"]))


def _mm_di(sol, meta, gruppo):
    mm = _spessore(sol["verts"], sol["faces"]) * 1000.0
    if mm >= 1.0:
        return mm, False
    chiave = {"pareti": "t_legno_mm", "perline_est": "t_legno_mm", "perline_int": "t_int_mm",
              "copertura": "t_tetto_mm", "tavolato": "t_tavolato_mm"}.get(gruppo)
    if chiave and meta.get(chiave):
        return float(meta[chiave]), True
    return None, False


def _aree_guscio(capitoli, meta):
    """Area del guscio opaco (isolante dello spessore del pannello) e della vetrocamera. Il pavimento no."""
    shell = float(meta.get("t_isolante_mm") or 0)
    opaca = vetro = 0.0
    for cap in capitoli:
        if cap["chiave"] == "vetro":
            vetro += sum(t["area"] for t in cap["tipi"])
        elif cap["chiave"] == "isolante" and shell:
            for t in cap["tipi"]:
                mm, _ = _mm_di(t["mm_sol"], meta, "isolante")
                if mm and abs(mm - shell) <= 5:
                    opaca += t["area"]
    return opaca, vetro


def _testo_formula(f):
    """La formula con cui l'interasse dei travetti esce dalla sezione e dal modulo."""
    if not f or "E" not in f:
        return ""
    q = float(f["q"])
    kg = "50" if abs(q - 0.5) < 0.02 else _n(q * 100, 0)
    libero = min(f["i_freccia"], f["i_flessione"])
    if f["interasse"] < libero - 0.01:
        chiusura = (f"Comanda la {f['comanda']}, a {_n(libero * 100, 0)} cm. "
                    f"Il tavolato ferma l'interasse a {_n(f['interasse'] * 100, 0)} cm.")
    else:
        chiusura = f"Comanda la {f['comanda']}. L'interasse è {_n(f['interasse'] * 100, 0)} cm."
    return (f"Sezione {_n(f['b'] * 100, 0)}×{_n(f['h'] * 100, 0)} cm, abete C24, E = {_n(f['E'], 0)} N/mm². "
            f"Carico di riferimento {_n(q, 2)} kN/m², {kg} kg/m². Luce {_n(f['L'], 2)} m. "
            f"i = 384 · E · I / (1500 · q · L³) = {_n(f['i_freccia'] * 100, 0)} cm, "
            f"con I = b·h³/12 e freccia L/300. "
            f"La flessione, i = 8 · f · W / (q · L²) con f = {_n(f['f'], 1)} N/mm², "
            f"darebbe {_n(f['i_flessione'] * 100, 0)} cm. {chiusura}")


def componi(oggetti, meta, opz, prezzi):
    meta = meta or {}
    solidi = espandi(oggetti)
    visibili = [s for s in solidi if s["gruppo"] not in ("pietre", "tappi")]
    note, righe = [], []
    n_porta = sum(1 for s in visibili if s["gruppo"] == "porta" or (s["gruppo"] == "vetro" and "anta" in s["nome"]))
    if n_porta or meta.get("porta_esclusa"):
        note.append("La porta non è in questo foglio. Un'anta di legno, quando si farà, va disegnata come cornice e pannello.")
    visibili = [s for s in visibili if s["gruppo"] != "porta" and not (s["gruppo"] == "vetro" and "anta" in s["nome"])]
    lamine = [s for s in visibili if s["gruppo"] == "scheletro" and _volume(s["verts"], s["faces"]) < 0.00015]
    if lamine:
        dove = ", ".join(sorted({f"strato {s.get('strato')}" for s in lamine if s.get("strato") is not None}))
        nota_dove = f" ({dove})" if dove else ""
        note.append(f"{len(lamine)} pezzi dello scheletro{nota_dove} sono lamine senza spessore: "
                    "il solido è collassato e la pianta non è una tavola. Non sono disegnati e non entrano nel conto.")
    visibili = [s for s in visibili if s not in lamine]
    note.append("Entra nel conto ogni solido con la proprietà materiale. L'algoritmo la compila da solo.")
    extra = [s for s in visibili if not any(s["nome"].endswith(suf) for suf in _SUFFISSI)]
    if extra:
        nomi = sorted({s["nome"] for s in extra})
        note.append("Pezzi aggiunti nella collection, contati con il ruolo in cui stanno: " + ", ".join(nomi) + ".")
    if meta.get("ferramenta"):
        note.append("Maniglia e cerniere sono nella collection della porta e restano fuori: sono ferramenta.")
    n_pietre = sum(1 for s in solidi if s["gruppo"] == "pietre")
    if n_pietre:
        note.append(f"Le pietre e il gradino, {n_pietre} solidi, non hanno un prezzo di listino in questo conto.")
    if any(s["gruppo"] == "tappi" for s in solidi):
        note.append("I tappi di chiusura non entrano nel conto.")
    s = meta.get("summary") or {}
    par = meta.get("params") or {}
    h_pav = s.get("altezza_esterna_su_pavimento", s.get("altezza_esterna"))
    if s.get("base_rientrante"):
        note.append("La base è più stretta della pancia: l'anello a terra è oltre la metà del poliedro.")
    porta = s.get("porta")
    if isinstance(porta, dict) and not porta.get("entra", True):
        note.append("Il vano della porta non entra nella sezione.")

    capitoli = []
    superfici_senza_spessore = False
    colori_pannello = {}
    incroci = 0
    for chiave, titolo, materiale, unita, flag in _ORDINE:
        if not _acceso(flag, opz):
            continue
        pezzi = [pz for pz in visibili if pz["gruppo"] == chiave]
        if not pezzi:
            continue
        if chiave == "dormienti" and meta.get("pav_tipo") != "pietroni":
            titolo = "Dormienti"
        gruppi = {}
        for pz in pezzi:
            gruppi.setdefault(_chiave_tipo(pz), []).append(pz)
        ordine_tipi = sorted(gruppi, key=lambda k: ((gruppi[k][0].get("strato") is None),
                                                    gruppi[k][0].get("strato") or 0,
                                                    -_tre_misure(gruppi[k][0]["verts"], gruppi[k][0]["faces"])[0]))
        colore_i, stretto = _colora(ordine_tipi, gruppi)
        if chiave == "perline_int":
            for t in ordine_tipi:
                voluto = colori_pannello.get(_chiave_pannello(gruppi[t][0], 0.05))
                if voluto is None:
                    continue
                if any(colore_i[altro] == voluto and any(_tocca(p, q) for p in gruppi[t] for q in gruppi[altro])
                       for altro in ordine_tipi if altro != t):
                    continue
                colore_i[t] = voluto
        if chiave == "perline_est":
            for t in ordine_tipi:
                colori_pannello.setdefault(_chiave_pannello(gruppi[t][0], 0.05), colore_i[t])
        nota = ""
        if chiave == "scheletro" and len(ordine_tipi) > 12:
            nota = (f"I tipi di taglio sono {len(ordine_tipi)} e le tinte distinguibili {len(_PAL)}: "
                    "due tipi che non si toccano possono averne una uguale, due che si toccano no.")
            if stretto:
                nota += " Qui un tipo tocca più forme diverse di quante tinte ci sono: in quel punto un colore si ripete."
        elif chiave == "dormienti" and meta.get("pav_tipo") == "pietroni":
            nota = ("Ogni palo va da un pietrone al successivo e supera il vertice di 10 cm, "
                    "perciò in pianta gli estremi si sovrappongono. La sezione non è un rettangolo: "
                    "il sotto è più stretto e il taglio è irregolare.")
        elif chiave == "travetti":
            nota = _testo_formula(meta.get("travetti_formula"))
        colori = {}
        disegnati = []
        for t in ordine_tipi:
            col = _PAL[colore_i[t] % len(_PAL)]
            for pz in gruppi[t]:
                pz = dict(pz)
                pz["_tipo"] = t
                disegnati.append(pz)
                colori[t] = col
        schema = svg_due_viste(disegnati, colori)
        tipi = []
        for t in ordine_tipi:
            camp = gruppi[t][0]
            est, area, vol = _misure(camp)
            col = colori[t]
            iso, pianta, laterale, sezione, inc = _viste_tipo(camp, col)
            incroci += inc
            nome = _nome_cutlist(camp, est[0]) or ("pezzo aggiunto" if not any(camp["nome"].endswith(suf) for suf in _SUFFISSI) else "pezzo")
            n_lati = len(camp["faces"][_faccia_pianta(camp["verts"], camp["faces"])]) if camp["faces"] else 0
            if chiave == "pareti" and n_lati == 3 and area < 0.02:
                nome = "ritaglio del guscio"
            elif chiave == "pareti" and n_lati == 3 and area < 0.10:
                nome = "timpano"
            tipi.append({"n": len(gruppi[t]), "strato": camp.get("strato"), "nome": nome, "colore": col,
                         "est": est, "iso": iso, "pianta": pianta, "laterale": laterale, "sezione": sezione,
                         "area": area * len(gruppi[t]), "volume": vol * len(gruppi[t]),
                         "anta": "anta" in camp["nome"] and "vetro" not in camp["nome"].replace("anta_vetro", ""),
                         "vetro_anta": "anta" in camp["nome"] and "vetro" in camp["nome"],
                         "luce": min(_altitudini([camp["verts"][i] for i in camp["faces"][_faccia_pianta(camp["verts"], camp["faces"])]]) or [0.0]),
                         "tilt": camp["tilt"], "mm_sol": camp})
        if chiave == "pareti":
            nomi = {t["nome"] for t in tipi}
            frasi = []
            if "ritaglio del guscio" in nomi:
                frasi.append("I triangoli piccoli sono ritagli del taglio col guscio, non una parete.")
            if "timpano" in nomi:
                frasi.append("Il timpano è la parete sopra l'architrave, fino al colmo.")
            if frasi:
                nota = " ".join(frasi)
        capitoli.append({"chiave": chiave, "titolo": titolo, "schema": schema, "tipi": tipi,
                         "n": len(pezzi), "n_tipi": len(tipi), "nota": nota})

        # quantità per il preventivo
        if chiave == "isolante":
            nome_mat = next((t["mm_sol"].get("materiale") for t in tipi if t["mm_sol"].get("materiale")), "") or "Canapa"
            riga = (prezzi or {}).get(nome_mat)
            secchi = {}
            for t in tipi:
                mm, _ = _mm_di(t["mm_sol"], meta, chiave)
                secchi.setdefault(None if mm is None else round(mm), 0.0)
                secchi[None if mm is None else round(mm)] += t["area"]
            for mm, area in secchi.items():
                if riga and ("m³" in str(riga.get("unita") or "") or "m3" in str(riga.get("unita") or "")) and mm:
                    qta, unita_q = area * mm / 1000.0, "m³"
                    euro, avviso = riga["prezzo"], ""
                else:
                    qta, unita_q = area, "m²"
                    euro, avviso = _prezzo_isolante(riga, mm)
                if avviso:
                    note.append(f"Isolante: {avviso}")
                kg, come = peso_di("isolante", area, "m²", mm, riga, None)
                importo = None if euro is None else round(qta * euro + 1e-9, 2)
                righe.append({"capitolo": "isolante", "chiave": "isolante", "voce": f"Isolante, {nome_mat}",
                              "materiale": nome_mat, "qta": qta, "unita": unita_q, "prezzo": euro,
                              "unita_prezzo": (riga or {}).get("unita", ""), "importo": importo,
                              "iva": "non dichiarata", "kg": kg, "come": come})
            continue
        if chiave == "aggiunto":
            note.append("Ci sono solidi in una collection senza un materiale assegnato: sono disegnati e non hanno prezzo.")
            continue
        if unita == "m³":
            if chiave == "porta":
                for etichetta, sel in (("Anta", lambda t: t["anta"]), ("Telaio della porta", lambda t: not t["anta"])):
                    vol = sum(t["volume"] for t in tipi if sel(t))
                    if vol > 1e-8:
                        _riga(righe, note, prezzi, "c24", "C24", etichetta, vol, "m³", None, False)
            else:
                vol = sum(t["volume"] for t in tipi)
                voce = {"scheletro": "Scheletro", "travetti": f"Travetti, {len(pezzi)} pezzi"}.get(chiave, titolo.split("·")[-1].strip().capitalize())
                if chiave == "dormienti" and meta.get("pav_tipo") == "pietroni":
                    voce = "Pali del pavimento"
                elif chiave == "dormienti":
                    voce = "Dormienti"
                _riga(righe, note, prezzi, "c24", "C24", voce, vol, "m³", None, False)
        elif chiave == "vetro":
            secchi = {}
            for t in tipi:
                prod = scegli_vetro(t["luce"], t["tilt"])
                secchi.setdefault((prod, t["strato"], t["vetro_anta"]), 0.0)
                secchi[(prod, t["strato"], t["vetro_anta"])] += t["area"]
            for (prod, strato, anta), area in secchi.items():
                if anta:
                    voce = "Vetro dell'anta"
                else:
                    nome = "Vetrocamera per luci maggiori" if prod == "vetro_grande" else "Vetrocamera della stella"
                    voce = f"{nome}, strato {strato}" if strato is not None else nome
                _riga(righe, note, prezzi, prod, nome if not anta else "Vetrocamera della stella", voce, area, "m²", None, False)
        else:
            secchi = {}
            for t in tipi:
                mm, usato_pannello = _mm_di(t["mm_sol"], meta, chiave)
                superfici_senza_spessore = superfici_senza_spessore or usato_pannello
                secchi.setdefault(None if mm is None else round(mm), 0.0)
                secchi[None if mm is None else round(mm)] += t["area"]
            for mm, area in secchi.items():
                if materiale == "perline":
                    euro, avviso, chiave_p, dalla = _prezzo_perline(prezzi, mm)
                    _riga_gia(righe, note, "perline", chiave_p, voce_capitolo(chiave, meta), "Perline",
                              area, "m²", mm, euro, avviso, dalla, prezzi)
                else:
                    _riga(righe, note, prezzi, "tegole", "Tegole bituminose", voce_capitolo(chiave, meta),
                          area, "m²", mm, False)
    if incroci:
        note.append("Su un pezzo il contorno in pianta si incrociava: al suo posto c'è l'inviluppo, senza linee che si attraversano.")
    spenti = [nome for nome, acc in (("esterno", opz.get("esterno", True)), ("perline", opz.get("perline", True)),
                                     ("vetrocamera", opz.get("vetro", True)), ("travi e travetti", opz.get("travi", True))) if not acc]
    if spenti:
        note.insert(1, "Questo foglio non comprende: " + ", ".join(spenti) + ".")
    totale = round(sum(r["importo"] or 0 for r in righe) + 1e-9, 2)
    fette, visti = [], []
    for r in righe:
        fk = _FETTA.get(r["capitolo"], (r["chiave"], r["voce"]))[0]
        if fk not in visti and any(x["capitolo"] == r["capitolo"] or _FETTA.get(x["capitolo"], ("",))[0] == fk for x in righe):
            visti.append(fk)
    for fk in ("c24", "est", "int", "pav", "iso", "vetro", "cop"):
        euro = sum(r["importo"] or 0 for r in righe if _FETTA.get(r["capitolo"], ("",))[0] == fk)
        if euro > 0:
            fette.append({"chiave": fk, "nome": {"c24": "C24", "est": "Esterno", "int": "Interno",
                                                 "pav": "Pavimento", "iso": "Isolante", "vetro": "Vetrocamera",
                                                 "cop": "Copertura"}[fk],
                          "euro": round(euro, 2), "colore": _COLORI_FETTA[fk]})
    for cap in capitoli:
        rs = [r for r in righe if r["capitolo"] == cap["chiave"]]
        cap["kg"] = sum(r["kg"] or 0 for r in rs)
        cap["area"] = sum(t["area"] for t in cap["tipi"])
        cap["volume"] = sum(t["volume"] for t in cap["tipi"])
        metri = []
        for r in rs:
            if r["unita"] == "m²" and r["kg"] and r["qta"]:
                metri.append(round(r["kg"] / r["qta"]))
        cap["kg_m2"] = sorted(set(metri))
    peso = round(sum(r["kg"] or 0 for r in righe), 1)
    testa = ""
    if par:
        sec = ""
        if par.get("cut"):
            sec = f" · secondario M {par.get('M2')}, θ {_n(par.get('theta2') or 0, 1)}°"
        h_txt = f"{_n(s.get('altezza_esterna'), 2)} m" if s.get("altezza_esterna") else "—"
        dal = f", {_n(h_pav, 2)} m dal pavimento finito" if h_pav is not None else ""
        testa = (f"N {par.get('N')} · M {par.get('M')} · θ {_n(par.get('theta') or 0, 2)}° · "
                 f"ZH {_n(par.get('ZH') or 0, 2)} m{sec} · altezza esterna {h_txt}{dal}")
    termico_meta = dict(meta)
    termico_meta["area_opaca_m2"], termico_meta["area_vetro_m2"] = _aree_guscio(capitoli, meta)
    return {"nome": meta.get("nome", "zome"), "testa": testa, "note": note, "capitoli": capitoli,
            "righe": righe, "totale": totale, "fette": fette, "peso": peso,
            "termico": blocco_termico(prezzi, termico_meta)}


def voce_capitolo(chiave, meta):
    return {"perline_est": "Esterno", "perline_int": "Interno", "pareti": "Pareti del corridoio",
            "tavolato": "Pavimento", "fondo": "Tavolato sotto i travetti", "copertura": "Copertura"}.get(chiave, chiave)


def _riga(righe, note, prezzi, chiave, materiale, voce, qta, unita, mm, dalla_nota):
    riga = (prezzi or {}).get(NOMI[chiave]) if chiave in NOMI else None
    euro, avviso = prezzo_spessore(riga, mm) if riga else (None, "Manca la riga nel foglio materiali.")
    if avviso:
        note.append(f"{voce}: {avviso}")
    _riga_gia(righe, note, chiave, chiave, voce, materiale, qta, unita, mm, euro, "", dalla_nota, prezzi)


def _riga_gia(righe, note, capitolo_prezzo, chiave_iva, voce, materiale, qta, unita, mm, euro, avviso, dalla_nota, prezzi):
    if avviso:
        note.append(f"{voce}: {avviso}")
    importo = None if euro is None else round(qta * euro + 1e-9, 2)
    riga = (prezzi or {}).get(NOMI.get(chiave_iva, ""), {}) if prezzi else {}
    dens_vetro = ((prezzi or {}).get(NOMI["vetro"]) or {}).get("densita") if prezzi else None
    kg, come = peso_di(chiave_iva if chiave_iva in NOMI else capitolo_prezzo, qta, unita, mm, riga or None, dens_vetro)
    righe.append({"capitolo": _capitolo_da_voce(voce), "chiave": chiave_iva, "voce": voce, "materiale": materiale,
                  "qta": qta, "unita": unita, "prezzo": euro, "unita_prezzo": (riga or {}).get("unita", ""),
                  "importo": importo, "iva": _iva(chiave_iva, dalla_nota), "kg": kg, "come": come})


def _capitolo_da_voce(voce):
    v = voce.lower()
    if v.startswith("scheletro"):
        return "scheletro"
    if "anta" in v and "vetro" not in v:
        return "porta"
    if "telaio" in v:
        return "porta"
    if "pali" in v or "dormient" in v:
        return "dormienti"
    if "travett" in v:
        return "travetti"
    if "sotto i travetti" in v:
        return "fondo"
    if "tavolato" in v or v.startswith("pavimento"):
        return "tavolato"
    if v.startswith("esterno") or "esterne" in v:
        return "perline_est"
    if "pareti" in v:
        return "pareti"
    if v.startswith("interno") or "interne" in v:
        return "perline_int"
    if v.startswith("isolante"):
        return "isolante"
    if "vetro" in v:
        return "vetro"
    if v.startswith("copertura") or v.startswith("tetto") or "gronda" in v or "falde" in v:
        return "copertura"
    return "aggiunto"


def html_scena(dati):
    note = "".join(f"<li>{_esc(t)}</li>" for t in dati["note"])
    blocchi = []
    dida = ("<p class='meta'>Pianta, laterale e sezione sono in proporzione vera. I centimetri stanno sul lato. "
            "Il grado sta sul vertice: è l'angolo interno, e tra parentesi c'è quanto manca a 90. "
            "L'isometrica del pezzo ha i bordi del suo colore e nasconde il retro. "
            "Lo schema è il pezzo montato, due volte: un lato e, girato di 180° attorno alla verticale, l'altra parte. "
            "Vale per una zome dritta e per una coricata.</p>")
    prima = True
    for cap in dati["capitoli"]:
        righe = []
        for t in cap["tipi"]:
            dove = f"strato {t['strato']}" if t["strato"] is not None else ""
            mis = " × ".join(f"{_n(x * 100, 1)} cm" for x in t["est"])
            righe.append(
                "<tr>"
                f"<td class='nome'><i style='background:{t['colore']}'></i><b>×{t['n']}</b>"
                f"{(' · ' + dove) if dove else ''}<br>{_esc(t['nome'])}<br>{mis}</td>"
                f"<td><div class='cap'>Isometrica</div>{t['iso']}</td>"
                f"<td><div class='cap'>Pianta</div>{t['pianta']}</td>"
                f"<td><div class='cap'>Laterale</div>{t['laterale']}</td>"
                f"<td><div class='cap'>Sezione</div>{t['sezione']}</td></tr>")
        nota_cap = f"<p class='meta'>{_esc(cap['nota'])}</p>" if cap.get("nota") else ""
        blocchi.append(
            f"<h2>{_esc(cap['titolo'])}</h2>"
            f"<p class='meta'>{cap['n']} pezzi, {cap['n_tipi']} tipi. Stesso colore, stesso pezzo: la riga ha la tinta dello schema.</p>"
            f"{nota_cap}"
            f"<div class='schema'>{cap['schema']}</div>"
            + (dida if prima else "")
            + "<table class='tipi'><tbody>" + "".join(righe) + "</tbody></table>"
            + _somma_capitolo(cap))
        prima = False
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"><title>Report — {_esc(dati['nome'])}</title>
<style>
body {{ font: 14px/1.4 "Segoe UI", sans-serif; color: #1c1c1c; margin: 28px auto; max-width: 1180px; }}
h1 {{ font-size: 22px; font-weight: 650; margin: 0; }}
h2 {{ font-size: 16px; margin: 28px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #ccc; }}
.sottotitolo, .meta {{ color: #444; margin: 4px 0 8px; }}
ul {{ margin: 8px 0; padding-left: 18px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #e2e2e2; padding: 4px 6px; text-align: left; vertical-align: top; }}
td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
table.tipi td.nome {{ width: 150px; font-size: 13px; }}
table.tipi i {{ display: inline-block; width: 14px; height: 14px; margin-right: 6px; vertical-align: -2px; }}
.cap {{ color: #666; font-size: 11px; margin-bottom: 2px; }}
.schema {{ margin: 4px 0 10px; }}
.doppio {{ display: flex; gap: 12px; }}
.doppio figure {{ flex: 1; margin: 0; }}
.doppio figcaption {{ font-size: 12px; color: #444; text-align: center; margin-top: 2px; }}
svg.solido {{ width: 100%; height: auto; background: #f7f7f7; }}
svg.disegno {{ background: #fafafa; }}
svg.disegno text {{ font: 10px "Segoe UI", sans-serif; fill: #333; text-anchor: middle; }}
svg.disegno text.ang {{ font-weight: 650; fill: #111; }}
.somma {{ font-size: 17px; font-weight: 650; margin: 10px 0 22px; }}
.totale {{ font-size: 18px; font-weight: 650; margin-top: 8px; }}
.costo {{ display: flex; gap: 18px; align-items: center; margin: 8px 0 4px; }}
.legenda {{ list-style: none; padding: 0; margin: 0; }}
.legenda li {{ margin: 4px 0; }}
.legenda i {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; }}
svg.torta {{ background: transparent; }}
svg.termico {{ width: 100%; height: auto; background: #fafafa; }}
svg.termico text {{ font: 11px "Segoe UI", sans-serif; fill: #444; }}
svg.termico text.asse {{ text-anchor: end; }}
svg.termico text.ora {{ text-anchor: middle; }}
.doppio figure figcaption {{ font-weight: 650; text-align: left; }}
</style></head><body>
<h1>Report — {_esc(dati['nome'])}</h1>
<p class="sottotitolo">{_esc(dati['testa'])}</p>
<p class="meta">{date.today().isoformat()} · sola materia prima · solidi della collection</p>
<h2>Preventivo di massima</h2>
{_tabella(dati['righe'])}
<p class="totale">Totale {_euro(dati['totale'])} €</p>
<p class="totale">Peso {_n(dati['peso'], 0)} kg</p>
{_blocco(dati)}
<p class="meta">Prezzi e densità da Riferimenti/proprieta_materiali.xlsx, foglio Materiali. Sono approssimati: il numero esatto si scrive in quel file. Una cella vuota non è stata riempita.</p>
<h2>Note</h2>
<ul>{note}</ul>
{dati.get("termico") or ""}
{''.join(blocchi)}
</body></html>"""


def _tabella(righe):
    if not righe:
        return "<p>Nessuna voce con questi filtri.</p>"
    corpo = []
    for r in righe:
        prezzo = "—" if r["prezzo"] is None else f'{_euro(r["prezzo"])} {r["unita_prezzo"]}'
        importo = "—" if r["importo"] is None else _euro(r["importo"])
        qta = f'{_n(r["qta"], 3 if r["unita"] == "m³" else 2)} {r["unita"]}'
        corpo.append("<tr>" + "".join(f"<td>{_esc(x)}</td>" if i < 2 else f'<td class="n">{_esc(x)}</td>'
                                       for i, x in enumerate((r["voce"], r["materiale"], qta, prezzo, importo, r["iva"])))
                     + "</tr>")
    return ("<table><thead><tr><th>Voce</th><th>Materiale</th><th class='n'>Quantità</th>"
            "<th class='n'>Prezzo</th><th class='n'>Importo (€)</th><th>IVA</th></tr></thead><tbody>"
            + "".join(corpo) + "</tbody></table>")


def _blocco(dati):
    totale = dati["totale"]
    voci = []
    for f in dati["fette"]:
        quota = 100.0 * f["euro"] / totale if totale else 0
        voci.append(f'<li><i style="background:{f["colore"]}"></i>{_esc(f["nome"])} '
                    f'<b>{_euro(f["euro"])} €</b> · {_n(quota, 1)}%</li>')
    torta = (f'<div class="costo">{svg_torta(dati["fette"], totale)}<ul class="legenda">{"".join(voci)}</ul></div>'
             if dati["fette"] else "")
    corpo = []
    for r in dati["righe"]:
        kg = "—" if r["kg"] is None else _n(r["kg"], 0)
        corpo.append(f"<tr><td>{_esc(r['voce'])}</td><td class='n'>{kg}</td><td>{_esc(r['come'])}</td></tr>")
    peso = (f"<h2>Peso</h2><table><thead><tr><th>Voce</th><th class='n'>kg</th><th>Come</th></tr></thead>"
            f"<tbody>{''.join(corpo)}</tbody></table>"
            f"<p class='meta'>Le pietre e ciò che non ha una massa nel foglio materiali non entrano.</p>")
    return torta + peso


def _somma_capitolo(cap):
    legno = cap["chiave"] in ("scheletro", "dormienti", "travetti", "porta")
    qta = f"{_n(cap['volume'], 3)} m³" if legno else f"{_n(cap['area'], 2)} m²"
    if cap.get("kg"):
        massa = f"{_n(cap['kg'], 0)} kg"
    elif cap["chiave"] == "copertura":
        massa = "senza chili"
    else:
        massa = "senza chili"
    metri = ""
    if cap["chiave"] == "vetro" and cap.get("kg_m2"):
        metri = " · " + " · ".join(f"{_n(x, 0)} kg/m²" for x in cap["kg_m2"])
    return f"<p class='somma'>Totale {qta} · {massa}{metri}</p>"


def scrivi_scena(percorso, oggetti, meta, opz, prezzi):
    dati = componi(oggetti, meta, opz, prezzi)
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(html_scena(dati))
    return dati
