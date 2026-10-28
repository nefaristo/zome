"""zome_core.py - geometria dell'INTERNO di una zome, in Python puro.

Nessuna dipendenza da Blender: si puo' provare con python3, e serve anche
per inventario e preventivo.  Versione 2.0 (2026-10-19).

Nomenclatura (vedi README.md):
  N      lati del poligono di base (= rombi per strato)
  M      livelli = anelli di vertici, apice e terra compresi; gli STRATI sono M-1
  theta  angolo degli elementi del primo strato con la verticale (gradi)
  ZH     altezza della zome primaria (unita' libere, di solito metri)
  h      altezza di uno strato = ZH/(M-1), uguale per tutti
  l      lato di rombi e triangoli = h/cos(theta), uguale per tutti
  H      altezza del poliedro intero = N*h
Zome secondario (facoltativo): sopra l'anello `cut` (contato dall'apice, 1..M-2)
si scarta la parte alta del primario e si appoggia un secondo zome con lo
stesso N, angolo `theta2` e `M2` livelli; la sua base coincide con l'anello.
"""
import math
from dataclasses import dataclass, field


# Catalogo dei rivestimenti: ogni faccia rimanda a una chiave (spessori in m).  Si puo' estendere con altre voci
# {"uso": nome per i materiali, "lato": "esterno"|"interno", "spessore": m, "materiale": nome materiale}.
CATALOGO = {
    "roof_external":  {"uso": "tetto", "lato": "esterno", "spessore": 0.003, "materiale": "tiles_01"},
    "wood_external":  {"uso": "legno", "lato": "esterno", "spessore": 0.02, "materiale": "wood_01"},
    "glass_external": {"uso": "vetro", "lato": "esterno", "spessore": 0.01, "materiale": "glass"},
    "wood_internal":  {"uso": "legno", "lato": "interno", "spessore": 0.0,  "materiale": "perline_01"},
}
APERTO = "aperto"          # niente copertura: buco


@dataclass
class Params:
    N: int = 10
    M: int = 7
    theta: float = 52.0
    ZH: float = 2.03
    cut: int = 0          # 0 = nessun secondario
    M2: int = 3
    theta2: float = 40.0
    top_height: float = 0.0   # riduzione punta del vecchio pannello (stesse unita' di ZH)
    top_levels: int = 0       # numero di livelli abbassati (apice compreso)
    # --- posa e tagli (versione luglio 2025: rotazione, taglio radiale, piani) ---
    tilt: float = 0.0         # inclinazione (gradi) attorno a Y: 90 = zome coricata, asse lungo X
    orient: float = 0.0       # rotazione (gradi) attorno a Z dopo l'inclinazione
    px: float = 0.0           # posizione dell'origine (base al centro) dopo le rotazioni
    py: float = 0.0
    pz: float = 0.0
    radial: float = 0.0       # apertura (gradi, 0..270) di un cuneo tagliato attorno all'asse, centrato su +X
    floor: bool = False       # taglia con il piano z = zfloor, tenendo z >= zfloor (pavimento)
    zfloor: float = 0.0
    ztop: float = 0.0         # se > 0 taglia con il piano z = ztop, tenendo z <= ztop (parete chiusa in alto)
    pav_soglia: float = 0.0   # DERIVATO da build() con pav_taglio: soglia dei baricentri meno la quota del pavimento
    pav_taglio: float = -1.0  # con floor: se >= 0 (0..100) il pavimento taglia la zome coricata a triangoli interi invece che con il piano:
                              # 0 = nessun taglio, 100 = resta solo la cima.  Il piano del pavimento (zfloor) passa per il vertice piu' basso
                              # dei triangoli tenuti; i rombi tagliati si spezzano in triangoli.  < 0 = taglio con il piano, come prima
    caps: bool = True         # chiude con una parete (tappo) le sezioni dei tagli
    # --- porta: sezione verticale che taglia la zome e lascia un'apertura minima (misure come ZH) ---
    porta: bool = False
    porta_dir: float = 0.0    # direzione dall'asse verso la porta (gradi, nel sistema della zome): 0 = sud (-Y), 90 = est (+X)
    porta_modo: str = "parete"   # "parete": taglio con parete piana e vano; "corridoio": zome intera, corridoio rettangolare tolto
                                 # (prisma a casetta); se il piano della porta sta dentro la zome il prisma va verso l'esterno, se sta fuori
                                 # (porta_fuori, derivato) va verso la zome: le pareti collegano sempre il telaio al profilo d'incontro col guscio
    porta_dist: float = 1.0   # distanza del piano di taglio dall'asse; si tiene la parte verso l'asse
    porta_w: float = 0.80     # larghezza minima del vano
    porta_h: float = 2.00     # altezza minima del vano (dal piano della base); in corridoio e' l'altezza al colmo
    porta_z0: float = 0.0     # DERIVATO: quota del pavimento finito sopra la base (con il pavimento acceso il vano parte da li')
    porta_fuori: bool = False  # DERIVATO da build(): il vano non entra nella sezione, il piano della porta e' fuori dalla zome
    porta_falda: float = 0.15 # corridoio: il soffitto e' a due falde, i lati sono piu' bassi del colmo di questa quota (0 = piano)
    # --- pavimento (con floor acceso: zome posata sul piano z = zfloor, fondazione, dormienti, travetti, tavolato) ---
    pav_tipo: str = "muretto"    # "muretto" (a secco, con due varchi) o "pietroni" (uno per vertice, con pali)
    pav_carico: float = 0.5      # kN/m2 di riferimento del solaio (circa 50 kg/m2): l'interasse dei travetti si calcola da qui
    pav_interasse: float = 0.40  # interasse dei travetti (m)
    pav_seme: int = 1            # seme delle irregolarita' delle pietre
    # --- esterno e rivestimenti (unita' come ZH, di solito metri) ---
    TW: float = 0.05          # altezza dei pezzi dello scheletro = distanza tra superficie strutturale interna ed esterna
    traverse: str = ""        # per strato, es. "1:ta,4:t": t = tra anelli, a = sull'anello. Vuoto = nessuna
    pendenza_tetto: float = 65.0   # faccia = tetto se guarda in su e la sua inclinazione sull'orizzontale e' <= di questo (gradi)
    stella_vetri: bool = True      # strato 1 (apice) tutto a vetro: la stella di vetri in cima
    finestre: int = 3              # numero di finestre (vetri) distribuite sullo strato `strato_finestre`
    strato_finestre: int = 4
    sporgenza_tetto: float = 0.10  # gronda: il tetto sporge oltre il bordo basso (m); 0 = nessuna
    usi_manuali: str = ""     # scelte a mano: JSON {"strato.faccia": chiave del catalogo | "aperto"}
    catalogo: dict = field(default_factory=lambda: {k: dict(v) for k, v in CATALOGO.items()})


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def _dot(a, b): return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def _norm(a): return math.sqrt(_dot(a, a))
def _dist(a, b): return _norm(_sub(a, b))


def porta_angolo(p: Params):
    """Direzione della porta in gradi matematici (0 = +X): la convenzione del pannello e' 0 = sud (-Y)."""
    return p.porta_dir - 90.0


def validate(p: Params):
    if p.N < 3:
        raise ValueError("N deve essere almeno 3")
    if not (2 <= p.M <= p.N):
        raise ValueError("M deve essere tra 2 e N (M-1 strati, meno di N)")
    if not (0 < p.theta < 90):
        raise ValueError("theta deve stare tra 0 e 90 gradi")
    if p.ZH <= 0:
        raise ValueError("ZH deve essere positivo")
    if p.pav_taglio > 100:
        raise ValueError("pav_taglio deve stare tra 0 e 100 (o essere negativo per il taglio con il piano)")
    if not (0 <= p.radial <= 270):
        raise ValueError("radial deve stare tra 0 e 270 gradi")
    if p.pav_tipo not in ("muretto", "pietroni"):
        raise ValueError("pav_tipo deve essere 'muretto' o 'pietroni'")
    if p.porta_modo not in ("parete", "corridoio"):
        raise ValueError("porta_modo deve essere 'parete' o 'corridoio'")
    if p.porta and (p.porta_dist <= 0 or p.porta_w <= 0 or p.porta_h <= 0):
        raise ValueError("porta: distanza, larghezza e altezza devono essere positive")
    if p.porta and not (0 <= p.porta_falda < p.porta_h):
        raise ValueError("porta: la falda deve stare tra 0 e l'altezza")
    if p.ztop and p.floor and p.ztop <= p.zfloor:
        raise ValueError("ztop deve essere sopra zfloor")
    if p.cut:
        if not (1 <= p.cut <= p.M - 2):
            raise ValueError("cut deve stare tra 1 e M-2 (anello contato dall'apice)")
        if not (2 <= p.M2 <= p.N):
            raise ValueError("M2 deve essere tra 2 e N")
        if not (0 < p.theta2 < 90):
            raise ValueError("theta2 deve stare tra 0 e 90 gradi")


def rings(N, M, theta_deg, ZH):
    """Anelli dall'apice (indice 0, un solo punto) al suolo (indice M-1)."""
    th, h, al = math.radians(theta_deg), ZH / (M - 1), 2 * math.pi / N
    l = h / math.cos(th)
    apex = (0.0, 0.0, ZH)
    L = [[apex]]
    if M >= 2:
        L.append([(l*math.sin(th)*math.cos(k*al), l*math.sin(th)*math.sin(k*al), ZH - h) for k in range(N)])
    for i in range(2, M):
        ring = []
        for k in range(N):
            A = apex if i == 2 else L[i-2][(k+1) % N]
            B, C = L[i-1][k], L[i-1][(k+1) % N]
            ring.append(tuple(b + c - a for a, b, c in zip(A, B, C)))
        L.append(ring)
    return L


def ring_radius(N, theta_deg, h, k):
    """Raggio dell'anello k (dall'apice) di una zome con altezza di strato h."""
    return h * math.tan(math.radians(theta_deg)) * math.sin(k*math.pi/N) / math.sin(math.pi/N)


def ground_radius(N, M, theta_deg, ZH):
    """Formula chiusa del raggio a terra."""
    return ZH * math.tan(math.radians(theta_deg)) * math.sin((M-1)*math.pi/N) / ((M-1) * math.sin(math.pi/N))


def _faces_of(Lr, base_z_extra=0, first=1, last=None, cut_stratum=None):
    """Facce per strato di un insieme di anelli.  Ritorna dict strato(j) -> lista di (tipo, vertici)."""
    N = len(Lr[1]) if len(Lr) > 1 else 0
    M = len(Lr)
    out = {}
    for j in range(1, M):
        faces = []
        for k in range(N):
            B, C = Lr[j][k], Lr[j][(k+1) % N]
            A = Lr[0][0] if j == 1 else Lr[j-1][(k+1) % N]
            D = Lr[j+1][k] if j + 1 < M else None
            if cut_stratum == j:                 # rombo tagliato dall'alto: triangolo con la punta in basso
                faces.append(("triangolo_giu", (B, C, D)))
            elif D is None:                      # strato di base: triangoli con la punta in alto
                faces.append(("triangolo", (A, B, C)))
            else:
                faces.append(("rombo", (A, C, D, B)))
        out[j] = faces
    return out


def _outward(face, axis_z):
    """Orienta la faccia con la normale verso l'esterno."""
    pts = face
    n = (0.0, 0.0, 0.0)
    for i in range(1, len(pts) - 1):
        n = _add(n, _cross(_sub(pts[i], pts[0]), _sub(pts[i+1], pts[0])))
    cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
    cz = sum(p[2] for p in pts) / len(pts)
    if _dot(n, (cx, cy, cz - axis_z)) < 0:
        return tuple(reversed(pts))
    return tuple(pts)


def _area(pts):
    n = (0.0, 0.0, 0.0)
    for i in range(1, len(pts) - 1):
        n = _add(n, _cross(_sub(pts[i], pts[0]), _sub(pts[i+1], pts[0])))
    return 0.5 * _norm(n)


def _nonplanarity(pts):
    if len(pts) < 4:
        return 0.0
    n = _cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0]))
    ln = _norm(n)
    if ln == 0:
        return 0.0
    return max(abs(_dot(_sub(p, pts[0]), n)) / ln for p in pts[3:])


def _stats(s):
    """Misure di uno strato dalla sua lista di facce (la prima faccia intera fa da riferimento)."""
    new = s["facce"]
    kind0, pts0 = max(new, key=lambda f: _area(f[1]))
    n = len(pts0)
    s["tipo"] = kind0
    s["n"] = len(new)
    s["lati"] = [_dist(pts0[a], pts0[(a+1) % n]) for a in range(n)]
    s["base"] = None                      # solo triangoli: lunghezza del lato orizzontale
    if n == 3:
        for a in range(n):
            if abs(pts0[a][2] - pts0[(a+1) % n][2]) < 1e-9:
                s["base"] = s["lati"][a]
                s["lato"] = [x for i, x in enumerate(s["lati"]) if i != a][0]
    s["area"] = _area(pts0)
    s["area_totale"] = sum(_area(pt) for _, pt in new)
    s["fuori_piano"] = max(_nonplanarity(pt) for _, pt in new)


# ---------------------------------------------------------------------------
# Posa (rotazione/traslazione) e tagli piani, dalla versione di luglio 2025.
#  tilt/orient/px,py,pz : la zome viene ruotata (Ry poi Rz) e traslata.
#  floor/ztop           : tagli con piani orizzontali (pavimento, parete chiusa in alto).
#  radial               : cuneo di apertura attorno all'asse, centrato su +X (sistema della zome):
#                         >= 180 gradi taglio vero con piani (si tiene il resto, convesso);
#                         <  180 gradi apertura "a facce intere": si tolgono le facce con il baricentro nel cuneo.
# Si tiene sempre il semispazio {x : n.x >= d}.  Le facce si ritagliano (Sutherland-Hodgman) e i
# segmenti che nascono sul piano di taglio diventano "tappi" (pareti di chiusura).
# ---------------------------------------------------------------------------
def _rot(q, tilt, orient):
    t, o = math.radians(tilt), math.radians(orient)
    x, y, z = q
    x1, z1 = x*math.cos(t) + z*math.sin(t), -x*math.sin(t) + z*math.cos(t)     # Ry: +Z verso +X
    return (x1*math.cos(o) - y*math.sin(o), x1*math.sin(o) + y*math.cos(o), z1)


def _clip_poly(pts, n, d, eps=1e-9):
    """Tiene n.x >= d.  Ritorna (poligono o None, segmento sul piano o None)."""
    res = []
    m = len(pts)
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        da, db = _dot(n, a) - d, _dot(n, b) - d
        if da >= -eps:
            res.append(a)
        if (da > eps and db < -eps) or (da < -eps and db > eps):
            t = da / (da - db)
            res.append((a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]), a[2] + t*(b[2]-a[2])))
    clean = []
    for q in res:
        if not clean or _dist(q, clean[-1]) > 1e-9:
            clean.append(q)
    if len(clean) > 1 and _dist(clean[0], clean[-1]) <= 1e-9:
        clean.pop()
    if len(clean) < 3 or _area(clean) < 1e-9:
        return None, None
    on = [q for q in clean if abs(_dot(n, q) - d) <= 1e-7]
    seg = None
    if len(on) >= 2:
        far = max(((_dist(a, b), a, b) for a in on for b in on), key=lambda x: x[0])
        if far[0] > 1e-7:
            seg = (far[1], far[2])
    return clean, seg


def _cap_polygon(segs, n):
    pts = []
    for a, b in segs:
        for q in (a, b):
            if not any(_dist(q, r) < 1e-6 for r in pts):
                pts.append(q)
    if len(pts) < 3:
        return None
    c = tuple(sum(q[i] for q in pts) / len(pts) for i in range(3))
    outn = (-n[0], -n[1], -n[2])                   # normale uscente dal solido
    u = _unit(_sub(pts[0], c))
    v = _cross(outn, u)
    pts.sort(key=lambda q: math.atan2(_dot(_sub(q, c), v), _dot(_sub(q, c), u)))
    return pts


def pose_planes(p: Params):
    """Piani di taglio (nome, n, d) nel sistema del mondo."""
    off = (p.px, p.py, p.pz)
    planes = []
    if p.radial >= 180:
        h = math.radians(p.radial / 2)
        lst = [("taglio radiale 1", (-math.sin(h), math.cos(h), 0.0)),
               ("taglio radiale 2", (-math.sin(h), -math.cos(h), 0.0))]
        if p.radial == 180:              # i due piani coincidono: ne basta uno
            lst = lst[:1]
        for nm, nl in lst:
            nw = _rot(nl, p.tilt, p.orient)
            planes.append((nm, nw, _dot(nw, off)))
    if p.porta and p.porta_modo == "parete":
        a = math.radians(porta_angolo(p))
        nw = _rot((-math.cos(a), -math.sin(a), 0.0), p.tilt, p.orient)     # si tiene il lato verso l'asse
        planes.append(("porta", nw, -p.porta_dist + _dot(nw, off)))
    if p.floor and p.pav_taglio < 0:
        planes.append(("pavimento", (0.0, 0.0, 1.0), p.zfloor))
    if p.ztop:
        planes.append(("parete alta", (0.0, 0.0, -1.0), -p.ztop))
    return planes


_EPS_Z = 1e-6


def _selez_triangoli(kind, pts, p: Params, off, soglia):
    """Taglio del pavimento a triangoli: si tiene una faccia se il suo baricentro (nel mondo) sta a quota >= soglia; un rombo
    che non passa si spezza lungo la diagonale orizzontale (nel sistema della zome) e si tengono i triangoli il cui baricentro passa.
    Cosi' in basso restano sempre dei triangoli e i rombi toccano il piano del pavimento con un vertice.
    Ritorna [(tipo, vertici nel sistema della zome)]."""
    zw = [_add(_rot(q, p.tilt, p.orient), off)[2] for q in pts]
    if sum(zw) / len(zw) >= soglia - _EPS_Z:
        return [(kind, pts)]
    if kind != "rombo" or len(pts) != 4:
        return []
    zl = [q[2] for q in pts]
    i = 0 if abs(zl[0] - zl[2]) < 1e-9 else (1 if abs(zl[1] - zl[3]) < 1e-9 else None)
    if i is None:
        return []
    alto = max(range(4), key=lambda k: zl[k])
    out = []
    for idx in ([i, (i + 1) % 4, (i + 2) % 4], [(i + 2) % 4, (i + 3) % 4, i]):
        if sum(zw[k] for k in idx) / 3.0 >= soglia - _EPS_Z:
            out.append(("triangolo" if alto in idx else "triangolo_giu", tuple(pts[k] for k in idx)))
    return out


def _livello_taglio(p0: Params):
    """Taglio del pavimento sulla zome coricata.  Ritorna (livello, scarto): `livello` e' la quota (prima di spostare la zome sul
    pavimento) del vertice piu' basso dei triangoli tenuti, cioe' dove poggia il pavimento; `scarto` = soglia dei baricentri - livello.
    pav_taglio sale da 0 (si tiene tutto) a 100 (resta solo la faccia piu' alta); la soglia scatta sui baricentri dei triangoli."""
    from dataclasses import replace as _rep
    m = build(_rep(p0, tilt=0.0, orient=0.0, px=0.0, py=0.0, pz=0.0, radial=0.0, floor=False, ztop=0.0, porta=False,
                   pav_taglio=-1.0, pav_soglia=0.0, caps=False), _pav=False)
    off = (p0.px, p0.py, p0.pz)
    facce = [(kind, pts) for st in m["strata"] for kind, pts in st["facce"]]
    def zw(pts):
        return [_add(_rot(q, p0.tilt, p0.orient), off)[2] for q in pts]
    cent = []
    for kind, pts in facce:
        z_ = zw(pts)
        cent.append(sum(z_) / len(z_))
        if kind == "rombo" and len(pts) == 4:
            zl = [q[2] for q in pts]
            i = 0 if abs(zl[0] - zl[2]) < 1e-9 else (1 if abs(zl[1] - zl[3]) < 1e-9 else None)
            if i is not None:
                for idx in ([i, (i + 1) % 4, (i + 2) % 4], [(i + 2) % 4, (i + 3) % 4, i]):
                    cent.append(sum(z_[k] for k in idx) / 3.0)
    quote = sorted(set(round(c, 7) for c in cent))
    z0, z1 = quote[0], quote[-1]
    bers = z0 + max(0.0, min(100.0, p0.pav_taglio)) / 100.0 * (z1 - z0)
    soglia = next((q for q in quote if q >= bers - 1e-9), z1)
    tenuti = [q for kind, pts in facce for _, f in _selez_triangoli(kind, pts, p0, off, soglia) for q in zw(f)]
    if not tenuti:
        tenuti = [soglia]
    liv = min(tenuti)
    return liv, soglia - liv


def apply_pose_and_cuts(strata, p: Params):
    """Ruota, trasla e taglia le facce degli strati (in place).  Ritorna i tappi {nome: poligono}."""
    off = (p.px, p.py, p.pz)
    planes = pose_planes(p)
    segs = {}
    corr = _corridoio_piani(p) if (p.porta and p.porta_modo == "corridoio") else None
    originali = []
    door = None
    if 0 < p.radial < 180:
        door = math.radians(p.radial / 2)
        dir_w = _rot((1.0, 0.0, 0.0), p.tilt, p.orient)
        # per l'apertura a facce intere si usa l'angolo nel sistema della zome (prima della posa)
    kept = []
    sel = p.floor and p.pav_taglio >= 0
    for st in strata:
        faces = []
        lista = []
        for kind, pts in st["facce"]:
            lista.extend(_selez_triangoli(kind, pts, p, off, p.zfloor + p.pav_soglia) if sel else [(kind, pts)])
        for kind, pts in lista:
            loc = pts
            if door is not None:
                cx = sum(q[0] for q in loc) / len(loc); cy = sum(q[1] for q in loc) / len(loc)
                if abs(math.atan2(cy, cx)) < door:
                    continue
            poly = [_add(_rot(q, p.tilt, p.orient), off) for q in pts]
            ok = True
            for nm, n, d in planes:
                poly2, seg = _clip_poly(poly, n, d)
                if poly2 is None:
                    ok = False
                    break
                if seg:
                    segs.setdefault(nm, []).append(seg)
                poly = poly2
            if ok and corr:
                originali.append(poly)
                for nm, n, d in corr["muri"]:   # segmenti per le pareti del corridoio (sezione della zome)
                    _, seg = _clip_poly(poly, n, d)
                    if seg:
                        segs.setdefault(nm, []).append(seg)
                for pezzo in _sottrai_scatola(poly, corr["scatola"]):
                    faces.append((kind, tuple(pezzo)))
            elif ok:
                faces.append((kind, tuple(poly)))
        st["facce"] = faces
        if faces:
            kept.append(st)
    strata[:] = kept
    caps = {}
    if p.caps or p.floor:
        for nm, n, d in planes:
            if nm in segs and (p.caps or nm == "pavimento"):
                poly = _cap_polygon(segs[nm], n)
                if poly and nm == "porta":
                    caps.update(_porta_pezzi(poly, p))
                elif poly:
                    caps[nm] = poly
    if corr:
        tim = porta_timpano(p)
        if tim:
            caps["corridoio: timpano"] = tim
    # pareti del corridoio: sono parti della porta, non tappi dei tagli, quindi ci sono anche con "Chiudi i tagli" spento
    if corr and corr["fuori"]:
        caps.update(_pareti_fuori(p, originali))
    if corr:
        # parte del corridoio oltre il piano della porta (s >= dist): pareti = sezione della zome.  Se il piano della porta sta
        # fuori dalla zome questa parte e' vuota; se il piano taglia la zome (dentro in basso, fuori in alto) servono entrambe
        for nm, n, d in corr["muri"]:
            if nm in segs:
                poly = _cap_polygon(segs[nm], n)
                for n2, d2 in corr["limiti"][nm]:          # solo la parte dentro il corridoio
                    if poly:
                        poly, _ = _clip_poly(poly, n2, d2)
                if poly and _area(poly) > 1e-9:
                    caps[f"{nm} (sezione)" if corr["fuori"] else nm] = poly
    return caps


# ---------------------------------------------------------------------------
# Porta: sezione verticale a distanza `porta_dist` dall'asse, nella direzione `porta_dir`.  Si tiene la parte verso l'asse;
# la parete piana che chiude il taglio ha un vano di porta_w x porta_h appoggiato sul piano della base e centrato sul
# piede dell'asse.  La sezione di un poliedro convesso e' un poligono convesso: il vano entra se lo contengono i 4 angoli.
# ---------------------------------------------------------------------------
def _unit_plane(n, d):
    L = math.sqrt(_dot(n, n))
    return (_scale(n, 1.0 / L), d / L)


def _sottrai_scatola(poly, piani, eps=1e-6):
    """poly (convesso) meno la scatola convessa {n.x > d per ogni piano}.  Ritorna i contorni del resto (di solito uno solo,
    non convesso, con la tacca: niente spigoli finti dove la faccia e' continua).  Il contorno e' fatto dai tratti del bordo
    di poly che non stanno dentro la scatola, piu' i tratti del bordo della scatola che stanno dentro poly (percorsi al contrario)."""
    K = poly
    for n, d in piani:
        K, _ = _clip_poly(K, n, d)
        if K is None:
            return [list(poly)]
    nrm = _face_normal(poly)
    if _area(K) > _area(poly) * (1 - 1e-9):
        return []

    def dentro_scatola(q):
        return all(_dot(n, q) - d > 1e-9 for n, d in piani)

    def dentro_poly(q):
        m = len(poly)
        for i in range(m):
            a, b = poly[i], poly[(i + 1) % m]
            if _dot(_cross(nrm, _sub(b, a)), _sub(q, a)) <= 1e-9 * max(1.0, _dist(a, b)):
                return False
        return True

    archi = []
    m = len(poly)
    for i in range(m):
        a, b = poly[i], poly[(i + 1) % m]
        ts = {0.0, 1.0}
        for n, d in piani:
            da, db = _dot(n, a) - d, _dot(n, b) - d
            if da * db < 0:
                ts.add(da / (da - db))
        ts = sorted(ts)
        inw = _unit(_cross(nrm, _sub(b, a)))
        for t0, t1 in zip(ts, ts[1:]):
            if t1 - t0 < 1e-12:
                continue
            p0 = tuple(a[k] + t0 * (b[k] - a[k]) for k in range(3))
            p1 = tuple(a[k] + t1 * (b[k] - a[k]) for k in range(3))
            mid = tuple((p0[k] + p1[k]) / 2 + eps * inw[k] for k in range(3))
            if not dentro_scatola(mid):
                archi.append((p0, p1))
    mk = len(K)
    for i in range(mk):
        a, b = K[i], K[(i + 1) % mk]
        if _dist(a, b) < 1e-9:
            continue
        outw = _scale(_unit(_cross(nrm, _sub(b, a))), -1.0)
        mid = tuple((a[k] + b[k]) / 2 + eps * outw[k] for k in range(3))
        if dentro_poly(mid):
            archi.append((b, a))
    contorni, usati = [], [False] * len(archi)
    for s0 in range(len(archi)):
        if usati[s0]:
            continue
        usati[s0] = True
        loop = [archi[s0][0]]
        fine = archi[s0][1]
        while _dist(fine, loop[0]) > 1e-6:
            nxt = next((k for k, (a, b) in enumerate(archi) if not usati[k] and _dist(a, fine) < 1e-6), None)
            if nxt is None:
                break
            usati[nxt] = True
            loop.append(archi[nxt][0])
            fine = archi[nxt][1]
        # toglie i vertici allineati
        pulito = []
        for k in range(len(loop)):
            a, b, c2 = loop[k - 1], loop[k], loop[(k + 1) % len(loop)]
            if _dist(_cross(_sub(b, a), _sub(c2, b)), (0.0, 0.0, 0.0)) > 1e-9:
                pulito.append(b)
        if len(pulito) >= 3 and _area(pulito) > 1e-9:
            contorni.append(pulito)
    return contorni


def _corridoio_piani(p: Params):
    """Corridoio tolto verso l'esterno: da `porta_dist` in poi, largo porta_w, con soffitto a due falde: al colmo (asse) alto
    porta_h dalla base, ai lati porta_h - porta_falda.
    scatola = piani (n, d) con n.x > d dentro il corridoio; muri = piani delle pareti (sezione della zome) con la normale
    verso la parte che resta; limiti = piani che ritagliano ogni parete al solo corridoio."""
    foot, tw, up, out = _porta_frame(p)
    W2, H, R = p.porta_w / 2, p.porta_h, p.porta_falda
    m = R / W2                                                # pendenza delle falde
    ft, fu, fo = _dot(tw, foot), _dot(up, foot), _dot(out, foot)
    neg = lambda v: _scale(v, -1)
    zc = fu + p.porta_z0 + H                                  # quota del colmo
    zl = zc - R                                               # quota ai lati
    s_ok = _unit_plane(out, fo)                               # s >= dist
    t_sx, t_dx = _unit_plane(tw, ft - W2), _unit_plane(neg(tw), -(ft + W2))
    f_dx = _unit_plane(_add(neg(up), neg(_scale(tw, m))), -zc - m * ft)    # sotto la falda per u >= 0: z + m u <= zc
    f_sx = _unit_plane(_add(neg(up), _scale(tw, m)), -zc + m * ft)         # sotto la falda per u <= 0: z - m u <= zc
    z_lat = _unit_plane(neg(up), -zl)                         # z <= zl (per le pareti laterali)
    muri = [("corridoio: parete sinistra", *_unit_plane(neg(tw), W2 - ft)),
            ("corridoio: parete destra", *_unit_plane(tw, ft + W2)),
            ("corridoio: falda destra", *_unit_plane(_add(up, _scale(tw, m)), zc + m * ft)),
            ("corridoio: falda sinistra", *_unit_plane(_add(up, neg(_scale(tw, m))), zc - m * ft))]
    u_pos, u_neg = _unit_plane(tw, ft), _unit_plane(neg(tw), -ft)
    limiti = {"corridoio: parete sinistra": [s_ok, z_lat], "corridoio: parete destra": [s_ok, z_lat],
              "corridoio: falda destra": [s_ok, u_pos, t_dx], "corridoio: falda sinistra": [s_ok, u_neg, t_sx]}
    if p.porta_fuori:                                         # il prisma va dal piano della porta verso la zome (fino all'asse)
        # si toglie tutto il corridoio da s >= 0 (l'asse) in fuori: oltre il piano della porta la zome c'e' solo se il piano la
        # taglia (dentro in basso, fuori in alto): li' servono le pareti di sezione come per il piano dentro
        s_ax = _unit_plane(out, fo - p.porta_dist)
        return {"scatola": [s_ax, t_sx, t_dx, f_dx, f_sx], "muri": muri, "limiti": limiti, "fuori": True}
    return {"scatola": [s_ok, t_sx, t_dx, f_dx, f_sx], "muri": muri, "limiti": limiti, "fuori": False}


def _pareti_fuori(p: Params, facce):
    """Piano della porta fuori dalla zome: le pareti (due laterali e due falde di soffitto) vanno dall'asse al piano della
    porta, ma si tiene solo la parte fuori dal solido della zome: collegano il telaio al profilo d'incontro col guscio."""
    foot, tw, up, out = _porta_frame(p)
    W2, H, R = p.porta_w / 2, p.porta_h, p.porta_falda
    ft, fu, fo = _dot(tw, foot), _dot(up, foot), _dot(out, foot)
    s0 = fo - p.porta_dist
    def pt(s, u, z):
        return _add(_add(_scale(out, s), _scale(tw, ft + u)), _scale(up, z))
    z0, zl, zc = fu, fu + p.porta_z0 + H - R, fu + p.porta_z0 + H
    rett = {"corridoio: parete sinistra": [pt(s0, -W2, z0), pt(fo, -W2, z0), pt(fo, -W2, zl), pt(s0, -W2, zl)],
            "corridoio: parete destra": [pt(s0, W2, z0), pt(s0, W2, zl), pt(fo, W2, zl), pt(fo, W2, z0)],
            "corridoio: falda sinistra": [pt(s0, -W2, zl), pt(fo, -W2, zl), pt(fo, 0, zc), pt(s0, 0, zc)],
            "corridoio: falda destra": [pt(s0, 0, zc), pt(fo, 0, zc), pt(fo, W2, zl), pt(s0, W2, zl)]}
    tutti = [v for f in facce for v in f]
    if not tutti:
        return rett
    cen = tuple(sum(v[j] for v in tutti) / len(tutti) for j in range(3))
    solido = []
    for f in facce:
        k = len(f)
        nx = sum((f[i][1] - f[(i + 1) % k][1]) * (f[i][2] + f[(i + 1) % k][2]) for i in range(k))
        ny = sum((f[i][2] - f[(i + 1) % k][2]) * (f[i][0] + f[(i + 1) % k][0]) for i in range(k))
        nz = sum((f[i][0] - f[(i + 1) % k][0]) * (f[i][1] + f[(i + 1) % k][1]) for i in range(k))
        n = _unit_plane((nx, ny, nz), 0.0)[0]
        d = _dot(n, f[0])
        if _dot(n, cen) < d:
            n, d = _scale(n, -1), -d
        solido.append((n, d))
    res = {}
    for nome, poly in rett.items():
        for k, pezzo in enumerate(_sottrai_scatola(poly, solido)):
            if _area(pezzo) < 0.02:                    # ritaglio del taglio col guscio, non una parete
                continue
            res[nome if k == 0 else f"{nome} {k + 1}"] = list(pezzo)
    return res


def _porta_frame(p: Params):
    """Riferimento della porta nel mondo: (piede dell'asse sul piano, asse u lungo la parete, asse z, uscente dal solido)."""
    a = math.radians(porta_angolo(p))
    off = (p.px, p.py, p.pz)
    out = _rot((math.cos(a), math.sin(a), 0.0), p.tilt, p.orient)
    tw = _rot((-math.sin(a), math.cos(a), 0.0), p.tilt, p.orient)
    up = _rot((0.0, 0.0, 1.0), p.tilt, p.orient)
    foot = _add(off, _scale(out, p.porta_dist))
    return foot, tw, up, out


def _porta_pezzi(poly, p: Params):
    """Divide la parete (poligono convesso) in pezzi attorno al vano: stipite sinistro e destro, sopra, sotto (se il vano e' rialzato)."""
    foot, tw, up, out = _porta_frame(p)
    W2, H = p.porta_w / 2, p.porta_h
    ft, fu = _dot(tw, foot), _dot(up, foot)
    z0 = p.porta_z0
    pezzi = {}
    def taglia(base, piani):
        q = base
        for n, d in piani:
            q, _ = _clip_poly(q, n, d)
            if q is None:
                return None
        return q
    sx = taglia(poly, [(_scale(tw, -1), W2 - ft)])
    dx = taglia(poly, [(tw, W2 + ft)])
    alto = taglia(poly, [(tw, -W2 + ft), (_scale(tw, -1), -W2 - ft), (up, H + z0 + fu)])
    basso = taglia(poly, [(tw, -W2 + ft), (_scale(tw, -1), -W2 - ft), (_scale(up, -1), -(z0 + fu))]) if z0 > 1e-9 else None
    for nome, q in (("porta: parete a sinistra", sx), ("porta: parete a destra", dx),
                    ("porta: sopra il vano", alto), ("porta: sotto il vano", basso)):
        if q:
            pezzi[nome] = q
    return pezzi


def _sezione_verticale(faces, a_deg, c):
    """Poligono convesso (u, z) della sezione col piano verticale a distanza c dall'asse (nel sistema della zome)."""
    a = math.radians(a_deg)
    n = (math.cos(a), math.sin(a), 0.0)
    t = (-math.sin(a), math.cos(a), 0.0)
    pts = []
    for f in faces:
        m = len(f)
        for i in range(m):
            q1, q2 = f[i], f[(i + 1) % m]
            d1, d2 = _dot(n, q1) - c, _dot(n, q2) - c
            if abs(d1) < 1e-12:
                pts.append((_dot(t, q1), q1[2]))
            if d1 * d2 < 0:
                k = d1 / (d1 - d2)
                q = tuple(q1[j] + k * (q2[j] - q1[j]) for j in range(3))
                pts.append((_dot(t, q), q[2]))
    pts = sorted(set((round(u, 9), round(z, 9)) for u, z in pts))
    if len(pts) < 3:
        return []
    def mezzo(seq):
        h = []
        for q in seq:
            while len(h) >= 2 and (h[-1][0]-h[-2][0])*(q[1]-h[-2][1]) - (h[-1][1]-h[-2][1])*(q[0]-h[-2][0]) <= 0:
                h.pop()
            h.append(q)
        return h
    inf, sup = mezzo(pts), mezzo(pts[::-1])
    return inf[:-1] + sup[:-1]


def _in_convesso(hull, u, z, eps=1e-9):
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        if (b[0]-a[0])*(z-a[1]) - (b[1]-a[1])*(u-a[0]) < -eps:
            return False
    return True


def porta_entra(faces, a_deg, c, W, H, z0=0.0):
    """True se il vano W x H (dal piano z0, centrato) sta dentro la sezione a distanza c."""
    hull = _sezione_verticale(faces, a_deg, c)
    return bool(hull) and all(_in_convesso(hull, u, z) for u in (-W/2, W/2) for z in (z0, z0 + H))


def porta_dist_max(p: Params, tol=1e-4):
    """Distanza massima del piano dall'asse per cui il vano porta_w x porta_h entra ancora (0 se non entra neppure al centro)."""
    from dataclasses import replace
    q = replace(p, porta=False, tilt=0.0, orient=0.0, px=0.0, py=0.0, pz=0.0, radial=0.0, floor=False, ztop=0.0)
    he = p.porta_h - (p.porta_falda if p.porta_modo != "parete" else 0.0)
    m = build(q)
    faces = [pts for st in m["strata"] for _, pts in st["facce"]]
    R = max(math.hypot(v[0], v[1]) for f in faces for v in f)
    if not porta_entra(faces, porta_angolo(p), 1e-9, p.porta_w, he, p.porta_z0):
        return 0.0
    lo, hi = 0.0, R
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if porta_entra(faces, porta_angolo(p), mid, p.porta_w, he, p.porta_z0):
            lo = mid
        else:
            hi = mid
    return lo


def porta_h_utile(p: Params):
    """Altezza ai lati del vano (dal pavimento finito): in corridoio il soffitto ha due falde, i lati sono porta_falda piu' bassi del colmo."""
    return p.porta_h - (p.porta_falda if p.porta_modo != "parete" else 0.0)


def _porta_pt(p: Params, u, z, w):
    """Punto della porta nel mondo: u lungo la parete, z dalla base della zome, w dal piano della porta verso la parte tolta del prisma."""
    a = math.radians(porta_angolo(p))
    out = (math.cos(a), math.sin(a), 0.0)
    tg = (-math.sin(a), math.cos(a), 0.0)
    verso = -1.0 if p.porta_fuori else 1.0
    q = _add(_add(_scale(out, p.porta_dist + verso * w), _scale(tg, u)), (0.0, 0.0, z))
    return _add(_rot(q, p.tilt, p.orient), (p.px, p.py, p.pz))


def porta_timpano(p: Params, TT=0.02):
    """Corridoio: triangolo di parete fissa sopra l'architrave, sul piano della porta, fino al colmo del soffitto (la porta resta rettangolare)."""
    if p.porta_modo == "parete" or p.porta_falda <= TT + 0.005:
        return None
    zl, zc = p.porta_z0 + porta_h_utile(p) + TT, p.porta_z0 + p.porta_h
    W2 = p.porta_w / 2
    a = math.radians(porta_angolo(p))
    out = (math.cos(a), math.sin(a), 0.0)
    tg = (-math.sin(a), math.cos(a), 0.0)
    def pt(u, z):
        q = _add(_add(_scale(out, p.porta_dist), _scale(tg, u)), (0.0, 0.0, z))
        return _add(_rot(q, p.tilt, p.orient), (p.px, p.py, p.pz))
    return [pt(-W2, zl), pt(W2, zl), pt(0.0, zc)]


def porta_anta(p: Params, TT=0.02, spessore=0.04, apertura=20.0):
    """Anta rettangolare di legno con una finestra a rombo (vetro) e una maniglia a rombo.  Cerniera a sinistra entrando, maniglia a
    destra, socchiusa verso l'interno (verso la zome) di `apertura` gradi.
    Ritorna {"legno": [prismi], "vetro": [poligono], "maniglia": [prismi]} nel mondo (prismi: anello basso + anello alto)."""
    W2, H, z0 = p.porta_w / 2, porta_h_utile(p), p.porta_z0
    g = 0.005                                                   # gioco dentro il telaio
    u0, u1, zb, zt = -W2 + g, W2 - g, z0 + g, z0 + H - g
    ra, rb = 0.15, 0.33                                         # semi-diagonali del rombo: piu' alto che largo
    cy = max(min(z0 + 1.45, zt - rb - 0.08), zb + rb + 0.2)     # centro del rombo ad altezza di sguardo
    ph = math.radians(apertura)
    verso = -1.0 if p.porta_fuori else 1.0
    v0, v1 = (0.005, 0.005 + spessore) if verso > 0 else (-0.005 - spessore, -0.005)
    vc = (v0 + v1) / 2
    def pt(u, z, v):                                            # v: distanza dal piano, positiva verso l'esterno della zome
        du, dv = u - u0, v - vc                                 # cerniera sul lato sinistro; ruota di -apertura: il bordo libero va verso la zome
        u2 = u0 + du * math.cos(ph) + dv * math.sin(ph)
        v2 = vc - du * math.sin(ph) + dv * math.cos(ph)
        a = math.radians(porta_angolo(p))
        out = (math.cos(a), math.sin(a), 0.0)
        tg = (-math.sin(a), math.cos(a), 0.0)
        q = _add(_add(_scale(out, p.porta_dist + v2), _scale(tg, u2)), (0.0, 0.0, z))
        return _add(_rot(q, p.tilt, p.orient), (p.px, p.py, p.pz))
    pent = [[(u0, cy), (-ra, cy), (0, cy + rb), (0, zt), (u0, zt)],
            [(0, cy + rb), (ra, cy), (u1, cy), (u1, zt), (0, zt)],
            [(u0, zb), (0, zb), (0, cy - rb), (-ra, cy), (u0, cy)],
            [(0, zb), (u1, zb), (u1, cy), (ra, cy), (0, cy - rb)]]
    legno = [[pt(u, z, v0) for u, z in poly] + [pt(u, z, v1) for u, z in poly] for poly in pent]
    vetro = [[pt(-ra, cy, vc), pt(0, cy - rb, vc), pt(ra, cy, vc), pt(0, cy + rb, vc)]]
    uc, zh = u1 - 0.07, z0 + 1.0                                # maniglia a destra, a un metro dal pavimento
    man = []
    for vf, sg in ((v1, 1.0), (v0, -1.0)):                      # su entrambe le facce
        def pr(poly, va, vb):
            return [pt(u, z, vf + sg * va) for u, z in poly] + [pt(u, z, vf + sg * vb) for u, z in poly]
        man.append(pr([(uc - 0.022, zh), (uc, zh - 0.05), (uc + 0.022, zh), (uc, zh + 0.05)], 0.0, 0.006))               # placca a rombo
        man.append(pr([(uc - 0.008, zh - 0.008), (uc + 0.008, zh - 0.008), (uc + 0.008, zh + 0.008), (uc - 0.008, zh + 0.008)], 0.006, 0.034))  # montante
        man.append(pr([(uc - 0.065, zh - 0.008), (uc + 0.01, zh - 0.008), (uc + 0.01, zh + 0.008), (uc - 0.065, zh + 0.008)], 0.034, 0.05))   # impugnatura
    return {"legno": legno, "vetro": vetro, "maniglia": man}


def _porta_pv(p: Params, u, z, v):
    """Punto nel mondo: u lungo la parete (verso destra entrando), z dalla base, v dal piano della porta (positivo verso l'esterno)."""
    a = math.radians(porta_angolo(p))
    out = (math.cos(a), math.sin(a), 0.0)
    tg = (-math.sin(a), math.cos(a), 0.0)
    q = _add(_add(_scale(out, p.porta_dist + v), _scale(tg, u)), (0.0, 0.0, z))
    return _add(_rot(q, p.tilt, p.orient), (p.px, p.py, p.pz))


def porta_cerniera(p: Params, spessore=0.04):
    """Cerniere dell'anta (3 perni e le piastre) sul lato sinistro entrando.  Ritorna {"punto": un punto dell'asse di rotazione,
    "asse": versore dell'asse (verticale della zome), "cerniere": [prismi nel mondo: anello basso + anello alto]}.  L'anta si apre
    ruotando di +apertura gradi attorno a quest'asse (verso la zome); le parti sono modellate a porta chiusa."""
    W2, H, z0 = p.porta_w / 2, porta_h_utile(p), p.porta_z0
    u0 = -W2 + 0.005
    verso = -1.0 if p.porta_fuori else 1.0
    v0, v1 = (0.005, 0.005 + spessore) if verso > 0 else (-0.005 - spessore, -0.005)
    vc = (v0 + v1) / 2
    asse = _unit(_rot((0.0, 0.0, 1.0), p.tilt, p.orient))
    res = []
    n = 8
    for zc in (z0 + 0.25, z0 + H / 2, z0 + H - 0.25):
        r, hl = 0.014, 0.055
        ang = [2 * math.pi * k / n for k in range(n)]
        res.append([_porta_pv(p, u0 + r * math.cos(t), zc - hl, vc + r * math.sin(t)) for t in ang] +
                   [_porta_pv(p, u0 + r * math.cos(t), zc + hl, vc + r * math.sin(t)) for t in ang])
        for vf, sg in ((v1, 1.0), (v0, -1.0)):                  # piastra su ciascuna faccia dell'anta
            q = [(u0, zc - 0.05), (u0 + 0.075, zc - 0.05), (u0 + 0.075, zc + 0.05), (u0, zc + 0.05)]
            res.append([_porta_pv(p, u, z, vf) for u, z in q] + [_porta_pv(p, u, z, vf + sg * 0.004) for u, z in q])
    return {"punto": _porta_pv(p, u0, z0, vc), "asse": asse, "cerniere": res}


def porta_telaio(p: Params, TT, TW):
    """Telaio del vano sul piano della porta: due stipiti e un architrave, sezione TT x TW, TW verso la parte tolta (verso l'esterno,
    o verso la zome se il piano sta fuori).  Pezzi di 8 vertici nel mondo (0-3 sul piano della porta, 4-7 a TW)."""
    W2, H, z0 = p.porta_w / 2, porta_h_utile(p), p.porta_z0
    sezioni = [("stipite sinistro", [(-W2 - TT, z0), (-W2, z0), (-W2, z0 + H), (-W2 - TT, z0 + H)]),
               ("stipite destro", [(W2, z0), (W2 + TT, z0), (W2 + TT, z0 + H), (W2, z0 + H)]),
               ("architrave", [(-W2 - TT, z0 + H), (W2 + TT, z0 + H), (W2 + TT, z0 + H + TT), (-W2 - TT, z0 + H + TT)])]
    res = []
    for nome, sez in sezioni:
        v = [_porta_pt(p, u, z, 0.0) for u, z in sez] + [_porta_pt(p, u, z, TW) for u, z in sez]
        du, dz = sez[2][0] - sez[0][0], sez[2][1] - sez[0][1]
        res.append({"nome": nome, "vertici": v, "lunghezza": max(du, dz), "volume": du * dz * TW})
    return res


def build(p: Params, _pav=True):
    """Ritorna dict: params, vertices (rings per parte), strata (da apice a terra), summary."""
    validate(p)
    p0 = p
    m0, pav, fz0 = None, None, None
    if _pav:
        # la zome posata senza il vano della porta: serve per il pavimento e per le aree di sezione
        from dataclasses import replace as _rep
        lv, sg = _livello_taglio(p0) if (p0.floor and p0.pav_taglio >= 0) else (None, 0.0)
        # con il taglio a triangoli m0 e' la zome tagliata con il piano (serve l'impronta del pavimento vera) allo stesso livello
        m0 = build(_rep(p0, porta=False, ztop=p0.ztop, **({} if lv is None else {"pav_taglio": -1.0, "pz": p0.pz - lv})), _pav=False)
        fz0 = [pts for s_ in m0["strata"] for _, pts in s_["facce"]]
        if p0.floor:
            p = _rep(p0, pz=p0.pz + p0.zfloor - (0.0 if lv is None else lv), pav_soglia=sg)
    elif p.floor:
        from dataclasses import replace as _rep
        p = _rep(p, pz=p.pz + p.zfloor)
    N, M = p.N, p.M
    h = p.ZH / (M - 1)
    P = rings(N, M, p.theta, p.ZH)

    # riduzione punta (vecchio pannello): abbassa i primi `top_levels` anelli dall'apice, in modo cumulativo
    if p.top_levels > 0 and p.top_height != 0 and not p.cut:
        delta = 0.0
        for k in range(p.top_levels - 1, -1, -1):
            delta -= p.top_height / p.top_levels
            P[k] = [(v[0], v[1], v[2] + delta) for v in P[k]]

    strata = []   # lista di dict, dall'alto (strato 1) in basso
    parts = {"primaria": P}

    if p.cut:
        c = p.cut
        # secondario: stesso N, base = anello c del primario
        Rc = ring_radius(N, p.theta, h, c)
        r2 = p.M2 - 1
        ZH2 = Rc * r2 * math.sin(math.pi/N) / (math.tan(math.radians(p.theta2)) * math.sin(r2*math.pi/N))
        S = rings(N, p.M2, p.theta2, ZH2)
        zc = P[c][0][2]
        ang_p = math.atan2(P[c][0][1], P[c][0][0])
        ang_s = math.atan2(S[-1][0][1], S[-1][0][0])
        phi = ang_p - ang_s
        cp, sp = math.cos(phi), math.sin(phi)
        S = [[(v[0]*cp - v[1]*sp, v[0]*sp + v[1]*cp, v[2] + zc) for v in ring] for ring in S]
        S[-1] = list(P[c])                       # la base del secondario e' l'anello c del primario
        parts["secondaria"] = S
        sec_faces = _faces_of(S)
        for j in sorted(sec_faces):
            strata.append({"parte": "secondaria", "j": j, "facce": sec_faces[j]})
        # primario: dall'anello c in giu'
        pf = _faces_of(P, cut_stratum=c)
        for j in range(c, M):
            strata.append({"parte": "primaria", "j": j, "facce": pf[j]})
        axis_z = 0.0
    else:
        pf = _faces_of(P)
        for j in sorted(pf):
            strata.append({"parte": "primaria", "j": j, "facce": pf[j]})
        axis_z = 0.0

    # orienta e misura
    all_vertices_z = []
    for i, s in enumerate(strata, start=1):
        s["strato"] = i
        new = []
        for kind, pts in s["facce"]:
            pts = _outward(pts, axis_z + 0.5 * p.ZH)
            new.append((kind, pts))
            all_vertices_z.extend(q[2] for q in pts)
        s["facce"] = new
        _stats(s)

    posed = bool(p.tilt or p.orient or p.px or p.py or p.pz or p.radial or p.floor or p.ztop or p.porta)
    caps = {}
    porta_info = None
    fuori = False
    if p.porta:
        fz = [pts for s_ in strata for _, pts in s_["facce"]]
        he = p.porta_h - (p.porta_falda if p.porta_modo != "parete" else 0.0)       # altezza ai lati
        entra = porta_entra(fz, porta_angolo(p), p.porta_dist, p.porta_w, he, p.porta_z0)
        if p.porta_modo != "parete":
            entra = entra and porta_entra(fz, porta_angolo(p), p.porta_dist, 0.0, p.porta_h, p.porta_z0)   # anche il colmo
        fuori = False
        if p.porta_modo != "parete" and not entra:
            # il vano non entra a questa distanza: se entra al centro, il piano della porta sta fuori dalla zome (il passaggio
            # collega il guscio al piano), altrimenti la porta e' troppo grande per la zome
            if porta_entra(fz, porta_angolo(p), 1e-9, p.porta_w, he, p.porta_z0) and porta_entra(fz, porta_angolo(p), 1e-9, 0.0, p.porta_h, p.porta_z0):
                fuori, entra = True, True
        if fuori:
            from dataclasses import replace as _replace
            p = _replace(p, porta_fuori=True)
        porta_info = {"entra": entra, "fuori": fuori,
                      "larghezza": p.porta_w, "altezza": p.porta_h, "distanza": p.porta_dist}
    if _pav and p0.floor and fz0:
        # il pavimento segue la porta: a parete taglia l'impronta, in corridoio fuori dalla zome la allunga fino al piano della porta
        from zome_pavimento import pavimento
        pa, modo, dist_h = None, None, None
        if p0.porta:
            a_ = math.radians(porta_angolo(p0))
            dd = _rot((math.cos(a_), math.sin(a_), 0.0), p0.tilt, p0.orient)
            pa = math.degrees(math.atan2(dd[1], dd[0]))
            dist_h = p0.porta_dist * math.hypot(dd[0], dd[1])
            modo = "parete" if p0.porta_modo == "parete" else ("fuori" if fuori else "dentro")
        pav = pavimento(fz0, {"zf": p0.zfloor, "tipo": p0.pav_tipo, "interasse": p0.pav_interasse, "carico": p0.pav_carico,
                              "seme": p0.pav_seme, "porta": pa, "porta_modo": modo, "porta_dist": dist_h, "porta_w": p0.porta_w,
                              "densita": 700.0, "centro": (p0.px, p0.py), "solo_piano": p0.pav_taglio >= 0})
    if posed:
        caps = apply_pose_and_cuts(strata, p)
        for i, s_ in enumerate(strata, start=1):
            s_["strato"] = i
            _stats(s_)
        all_vertices_z = [q[2] for s_ in strata for _, pt in s_["facce"] for q in pt]
        if not strata:
            raise ValueError("i tagli eliminano tutta la zome")
    total_h = max(all_vertices_z)
    ground = P[M-1]
    R = math.hypot(ground[0][0], ground[0][1])
    R_max = max(math.hypot(v[0], v[1]) for ring in P for v in ring)
    summary = {
        "N": N, "M": M, "strati": len(strata),
        "h": h, "l": h / math.cos(math.radians(p.theta)),
        "H_poliedro": N * h,
        "altezza_totale": total_h,
        "raggio_base": R, "diametro_base": 2 * R,
        "diametro_max": 2 * R_max,
        "base_rientrante": R_max > R * (1 + 1e-9),      # vero se M-1 > N/2: la parete si chiude verso il basso
        "area_base": 0.5 * N * R * R * math.sin(2*math.pi/N),
        "facce": sum(s["n"] for s in strata),
        "area_superficie_interna": sum(s_["area_totale"] for s_ in strata),
        "z_min": min(all_vertices_z),
        "tappi": {k: _area(v) for k, v in caps.items()},
        "fuori_piano_max": max(s["fuori_piano"] for s in strata),
    }
    if porta_info:
        summary["porta"] = porta_info
    if p.cut:
        summary.update({"ZH_secondario": ZH2, "l_secondario": ZH2 / (p.M2 - 1) / math.cos(math.radians(p.theta2)),
                        "quota_taglio": zc})
    if m0 is not None:
        from zome_pavimento import sezione, area as _area_xy
        f0 = [pts for s_ in m0["strata"] for _, pts in s_["facce"]]
        zs0 = [q[2] for f in f0 for q in f]
        zref = pav["z_finito"] if pav else min(zs0)
        summary.update({"quota_max": max(zs0), "ingombro_x": max(q[0] for f in f0 for q in f) - min(q[0] for f in f0 for q in f),
                        "ingombro_y": max(q[1] for f in f0 for q in f) - min(q[1] for f in f0 for q in f),
                        "quota_pavimento": zref, "area_pavimento": pav["summary"]["area_tavolato"] if pav else _area_xy(sezione(f0, zref)),
                        "area_180": _area_xy(sezione(f0, zref + 1.80))})
        if pav:
            summary["pavimento"] = pav["summary"]
    return {"params": p, "parts": parts, "strata": strata, "caps": caps, "summary": summary, "pavimento": pav}



# ---------------------------------------------------------------------------
# Esterno e rivestimenti.  Ogni faccia ha un USO ("tetto", "legno", "vetro"), assegnato per regola:
#   strato <= strati_tetto  -> tetto;  elenco `vetri` -> vetro;  tutto il resto -> legno.
# Le 4 superfici di riferimento: struttura interna = la faccia; struttura esterna = faccia spostata di TW;
# copertura interna = struttura esterna (la copertura poggia sullo scheletro); copertura esterna = struttura + spessore.
# Rivestimento interno: da -t_int a 0.  I vertici di ogni superficie sono l'intersezione dei piani spostati
# della faccia e delle due vicine (lungo i due spigoli); sul bordo libero si usa il piano perpendicolare alla faccia.
# ---------------------------------------------------------------------------
def _manuali(txt):
    import json
    if not txt:
        return {}
    d = json.loads(txt)
    return {(int(k.split(".")[0]), int(k.split(".")[1])): v for k, v in d.items()}


def face_tilt(pts):
    """Inclinazione (gradi) della faccia sull'orizzontale, e se guarda verso l'alto."""
    n = _face_normal(pts)
    return math.degrees(math.acos(max(-1.0, min(1.0, n[2])))), n[2] > 0


def face_use(p, strato, faccia, pts, manuali=None):
    """Chiave del catalogo (esterna) di una faccia, o "aperto".  Regola: tetto se guarda in su con pendenza
    <= pendenza_tetto, altrimenti legno; le scelte manuali (usi_manuali) hanno la precedenza."""
    manuali = _manuali(p.usi_manuali) if manuali is None else manuali
    if (strato, faccia) in manuali:
        return manuali[(strato, faccia)]
    if p.stella_vetri and strato == 1:
        return "glass_external"
    if p.finestre > 0 and strato == p.strato_finestre:
        n = max(p.N, 1)
        if faccia in {(i * n // p.finestre + n // (2 * p.finestre)) % n for i in range(p.finestre)}:
            return "glass_external"
    tilt, up = face_tilt(pts)
    return "roof_external" if (up and tilt <= p.pendenza_tetto) else "wood_external"


def _solve3(planes):
    """Intersezione di tre piani (n, d): n.x = d.  None se degenere."""
    (a, da), (b, db), (c, dc) = planes
    det = _dot(a, _cross(b, c))
    if abs(det) < 1e-9:
        return None
    t1, t2, t3 = _cross(b, c), _cross(c, a), _cross(a, b)
    return tuple((da*t1[i] + db*t2[i] + dc*t3[i]) / det for i in range(3))


def _edge_key(a, b):
    ka = tuple(round(x, 6) for x in a); kb = tuple(round(x, 6) for x in b)
    return (ka, kb) if ka <= kb else (kb, ka)


def offset_surface(faces, offsets, shared=True):
    """faces: lista di poligoni (vertici antiorari visti da fuori); offsets: spostamento di ciascuna
    lungo la sua normale esterna.  shared=True: un solo vertice per ogni vertice interno (minimi quadrati sui piani
    spostati; le facce restano quasi piane).  shared=False: ogni faccia e' esattamente piana (intersezione dei piani
    suo e dei due vicini), ma le facce vicine non combaciano ai vertici."""
    nrm = [_face_normal(pts) for pts in faces]
    edges = {}
    for fi, pts in enumerate(faces):
        for i in range(len(pts)):
            edges.setdefault(_edge_key(pts[i], pts[(i + 1) % len(pts)]), []).append(fi)

    def plane(fi, off):
        n = nrm[fi]
        return (n, _dot(n, faces[fi][0]) + off)

    def across(fi, i):                       # piano della faccia oltre lo spigolo i -> i+1
        pts = faces[fi]
        a, b = pts[i], pts[(i + 1) % len(pts)]
        others = [g for g in edges[_edge_key(a, b)] if g != fi]
        if others:
            g = others[0]
            return plane(g, offsets[g])
        n = _unit(_cross(_sub(b, a), nrm[fi]))      # perpendicolare alla faccia, passante per lo spigolo
        return (n, _dot(n, a))

    if shared:
        # un solo punto per vertice: minimi quadrati sulle distanze dai piani spostati di tutte le facce che lo toccano
        at = {}
        for fi, pts in enumerate(faces):
            for q in pts:
                at.setdefault(tuple(round(x, 6) for x in q), []).append(fi)
        pos = {}
        for key, fl in at.items():
            A = [[0.0]*3 for _ in range(3)]; bvec = [0.0]*3
            for fi in fl:
                n, d = plane(fi, offsets[fi])
                for i in range(3):
                    bvec[i] += n[i]*d
                    for j in range(3):
                        A[i][j] += n[i]*n[j]
            # piccola regolarizzazione verso lo spostamento medio lungo le normali, per i vertici con facce quasi parallele
            c0 = tuple(sum(nrm[fi][i]*offsets[fi] for fi in fl)/len(fl) + key[i] for i in range(3))
            lam = 1e-9
            for i in range(3):
                A[i][i] += lam; bvec[i] += lam*c0[i]
            q = _solve3([(tuple(A[0]), bvec[0]), (tuple(A[1]), bvec[1]), (tuple(A[2]), bvec[2])])
            pos[key] = q if q is not None else c0
        return [[pos[tuple(round(x, 6) for x in q)] for q in pts] for pts in faces]

    out = []
    for fi, pts in enumerate(faces):
        m = len(pts)
        new = []
        for i in range(m):
            q = _solve3([plane(fi, offsets[fi]), across(fi, (i - 1) % m), across(fi, i)])
            if q is None:
                q = _add(pts[i], _scale(nrm[fi], offsets[fi]))
            new.append(q)
        out.append(new)
    return out


def shell(model, p: Params):
    """Aggiunge model['esterno'] (una voce per faccia, con la copertura esterna e il rivestimento interno)
    e le somme per chiave del catalogo."""
    cat = p.catalogo
    man = _manuali(p.usi_manuali)
    flat = [(st["strato"], f, kind, pts) for st in model["strata"] for f, (kind, pts) in enumerate(st["facce"])]
    polys = [pts for _, _, _, pts in flat]
    chiave = [face_use(p, s_, f, pts, man) for s_, f, _, pts in flat]
    for k in chiave:
        if k != APERTO and k not in cat:
            raise ValueError(f"voce di catalogo sconosciuta: {k}")
    layer = [cat[k] if k != APERTO else None for k in chiave]
    ext_ok = [ly is not None and ly["lato"] == "esterno" for ly in layer]
    t_ext = [ly["spessore"] if ok else 0.0 for ly, ok in zip(layer, ext_ok)]
    int_key = [("wood_internal" if (ok and k != "glass_external" and cat.get("wood_internal", {}).get("spessore", 0) > 0) else None)
               for k, ok in zip(chiave, ext_ok)]
    t_int = [cat[k]["spessore"] if k else 0.0 for k in int_key]
    # SUPERFICIE ESTERNA CALCOLATA: faccia + D con D = TW + spessore massimo delle coperture, uguale per tutte le facce,
    # cosi' i pannelli vicini si toccano esattamente lungo gli spigoli (colmi e displuvi) e la superficie e' chiusa.
    # I pannelli resi sono lastre che rientrano da questa superficie verso l'interno di t (tetto, legno, vetro).
    nrm_f = [_face_normal(pts) for pts in polys]
    # IL TETTO E' UNO STRATO A PARTE: sotto ogni faccia di tetto c'e' sempre il legno (wood_external); il tetto poggia
    # sulla superficie esterna del legno (D) e arriva a D + spessore del tetto. Legno e vetro non sporgono: superficie D.
    es_tetto = [bool(ok and chiave[i] == "roof_external") for i, ok in enumerate(ext_ok)]
    t_legno_cat = cat.get("wood_external", {}).get("spessore", 0.0)
    tbase = max([t_ext[i] for i in range(len(polys)) if ext_ok[i] and not es_tetto[i]] + [t_legno_cat if any(es_tetto) else 0.0])
    D = p.TW + tbase
    struct_out = offset_surface(polys, [p.TW] * len(polys), shared=False)
    base_out = offset_surface(polys, [D] * len(polys), shared=False)
    tr = max([t_ext[i] for i in range(len(polys)) if es_tetto[i]] + [0.0])
    # NON si mescolano spostamenti diversi nella stessa superficie (le linee d'incontro tra falde quasi parallele scappano):
    # due superfici uniformi, legno/vetro a D e "inviluppo del tetto" a D + tetto; del secondo si usano solo le facce di tetto.
    env_out = offset_surface(polys, [D + tr] * len(polys), shared=False) if tr > 0 else base_out
    cover_out = [env_out[i] if es_tetto[i] else base_out[i] for i in range(len(polys))]
    cover_in = [[_add(q, _scale(nrm_f[i], -t_ext[i])) for q in cover_out[i]] for i in range(len(polys))]
    # rivestimento interno (perline): lastra che parte dalla faccia e rientra verso l'interno; superficie unica, cosi' gli
    # spigoli tra facce vicine combaciano (regola: mai spostamenti diversi nella stessa superficie)
    lin_in = offset_surface(polys, [-t_int[i] for i in range(len(polys))], shared=False) if any(t > 0 for t in t_int) else None
    ext, tot = [], {}
    for k, (s_, f, kind, pts) in enumerate(flat):
        uso = layer[k]["uso"] if layer[k] else "aperto"
        d = {"strato": s_, "faccia": f, "tipo": kind, "chiave": chiave[k], "uso": uso, "spessore": t_ext[k],
             "fuori_piano": _nonplanarity(cover_out[k]), "struttura_est": struct_out[k],
             "copertura_est": cover_out[k] if ext_ok[k] else None,
             "copertura_int": cover_in[k] if ext_ok[k] else None,
             "area_struttura": _area(struct_out[k]), "area_copertura": 0.0, "volume_copertura": 0.0,
             "inclinazione": face_tilt(pts)[0]}
        if ext_ok[k]:
            d["area_copertura"] = _area(cover_out[k])
            d["volume_copertura"] = 0.5 * (_area(cover_in[k]) + d["area_copertura"]) * t_ext[k]
            g = tot.setdefault(chiave[k], {"facce": 0, "area": 0.0, "volume": 0.0})
            g["facce"] += 1; g["area"] += d["area_copertura"]; g["volume"] += d["volume_copertura"]
        else:
            g = tot.setdefault(APERTO, {"facce": 0, "area": 0.0, "volume": 0.0})
            g["facce"] += 1; g["area"] += d["area_struttura"]
        if es_tetto[k] and t_legno_cat > 0:                   # il legno sotto il tetto (conta nel materiale)
            base_in = [_add(q, _scale(nrm_f[k], -t_legno_cat)) for q in base_out[k]]
            vb = 0.5 * (_area(base_in) + _area(base_out[k])) * t_legno_cat
            ext.append({"strato": s_, "faccia": f, "tipo": kind, "chiave": "wood_external", "uso": "legno",
                        "spessore": t_legno_cat, "fuori_piano": _nonplanarity(base_out[k]), "struttura_est": struct_out[k],
                        "copertura_est": base_out[k], "copertura_int": base_in, "area_struttura": d["area_struttura"],
                        "area_copertura": _area(base_out[k]), "volume_copertura": vb, "inclinazione": d["inclinazione"],
                        "sotto_tetto": True})
            gw = tot.setdefault("wood_external", {"facce": 0, "area": 0.0, "volume": 0.0})
            gw["facce"] += 1; gw["area"] += _area(base_out[k]); gw["volume"] += vb
        if lin_in and t_int[k] > 0:
            d["rivestimento_int"] = lin_in[k]
            d["rivestimento_int_alto"] = pts
            d["chiave_int"] = int_key[k]
            d["volume_rivest_int"] = 0.5 * (_area(lin_in[k]) + _area(pts)) * t_int[k]
            g = tot.setdefault(int_key[k], {"facce": 0, "area": 0.0, "volume": 0.0})
            g["facce"] += 1; g["area"] += _area(lin_in[k]); g["volume"] += d["volume_rivest_int"]
        ext.append(d)
    # GRONDA. Regola unica: il bordo basso del tetto e' la catena dei lati di tetto che confinano con una faccia piu' bassa
    # NON tetto. Ogni lato della catena sporge di `sporgenza_tetto` nel piano della propria falda (poliedro convesso: resta
    # fuori dalle facce sotto). In ogni vertice della catena due sporgenze si uniscono in UN punto solo, sulla retta in cui
    # i piani delle due falde si incontrano (due lati dello stesso rombo: bisettrice dell'angolo; falde diverse: la retta
    # comune dei due piani, che e' lo spigolo prolungato quando le falde lo dividono). Il punto e' sui due piani, quindi le
    # due sporgenze restano piane e combaciano esattamente. Un vertice senza compagna chiude con un taglio perpendicolare.
    gronda = []
    if p.sporgenza_tetto > 0:
        dg = p.sporgenza_tetto
        edges = {}
        for k, pts in enumerate(polys):
            for i in range(len(pts)):
                edges.setdefault(_edge_key(pts[i], pts[(i + 1) % len(pts)]), []).append(k)
        cz = [sum(q[2] for q in pts) / len(pts) for pts in polys]
        info = []
        for k, pts in enumerate(polys):
            if chiave[k] != "roof_external" or not ext_ok[k]:
                continue
            co = cover_out[k]
            n = len(co)
            cen = tuple(sum(q[j] for q in co) / n for j in range(3))
            for i in range(n):
                others = [g for g in edges[_edge_key(pts[i], pts[(i + 1) % n])] if g != k]
                if not (others and chiave[others[0]] != "roof_external" and cz[others[0]] < cz[k]):
                    continue
                a, b = co[i], co[(i + 1) % n]
                nrm = _face_normal(co)
                u = _unit(_sub(b, a))
                dirn = _unit(_cross(nrm, u))
                if _dot(dirn, _sub(tuple((a[j] + b[j]) / 2 for j in range(3)), cen)) < 0:
                    dirn = _scale(dirn, -1)
                info.append({"k": k, "ends": [a, b], "nrm": nrm, "u": u, "dirn": dirn,
                             "orig": [pts[i], pts[(i + 1) % n]]})

        def retta_piani(k1, k2):
            n1 = _face_normal(cover_out[k1]); c1 = _dot(n1, cover_out[k1][0])
            n2 = _face_normal(cover_out[k2]); c2 = _dot(n2, cover_out[k2][0])
            e = _cross(n1, n2)
            ee = _dot(e, e)
            if ee < 1e-12:
                return None
            p0 = _scale(_add(_scale(_cross(n2, e), c1), _scale(_cross(e, n1), c2)), 1.0 / ee)
            return p0, _unit(e)

        def sulla_retta(f, end, p0, e):
            """Punto della retta (p0, e) a distanza dg dal lato della sporgenza f, misurata nel piano di f."""
            et = _dot(e, f["dirn"])
            if abs(et) < 1e-6:
                return None
            lam = (dg + _dot(_sub(f["ends"][0], p0), f["dirn"])) / et
            P = _add(p0, _scale(e, lam))
            return P if _norm(_sub(P, f["ends"][end])) <= 4 * dg else None

        def unisci(m1, m2):
            (f1, e1), (f2, e2) = m1, m2
            F1, F2 = info[f1], info[f2]
            if F1["k"] == F2["k"]:                           # due lati dello stesso rombo: bisettrice
                v = F1["ends"][e1]
                d1 = _unit(_sub(F1["ends"][1 - e1], v))
                d2 = _unit(_sub(F2["ends"][1 - e2], F2["ends"][e2]))
                bis = _add(d1, d2)
                if _norm(bis) < 1e-9:
                    return None
                P = sulla_retta(F1, e1, v, _scale(_unit(bis), -1.0))
                return P
            r = retta_piani(F1["k"], F2["k"])
            if r is None:
                return None
            P1 = sulla_retta(F1, e1, r[0], r[1])
            P2 = sulla_retta(F2, e2, r[0], r[1])
            if P1 is None or P2 is None:
                return None
            return tuple((P1[j] + P2[j]) / 2 for j in range(3))

        punti = []                                           # [posizione originale, [(sporgenza, estremo), ...]]
        for fi, F in enumerate(info):
            for end in (0, 1):
                v = F["orig"][end]
                for rec in punti:
                    if _norm(_sub(rec[0], v)) < 1e-5:
                        rec[1].append((fi, end))
                        break
                else:
                    punti.append([v, [(fi, end)]])
        punta = {}
        for v, membri in punti:
            resto = list(membri)
            while len(resto) > 1:
                m1 = resto.pop(0)
                miglior, mp = None, -1
                for m2 in resto:
                    k1, k2 = info[m1[0]]["k"], info[m2[0]]["k"]
                    if k1 == k2:
                        pt = 2
                    else:
                        pt = 2 if sum(1 for x in polys[k1] for y in polys[k2] if _norm(_sub(x, y)) < 1e-5) >= 2 else 1
                    if pt > mp:
                        miglior, mp = m2, pt
                resto.remove(miglior)
                P = unisci(m1, miglior)
                if P is not None:
                    punta[m1] = P
                    punta[miglior] = P
        # Lo spiovente non è un pezzo a parte: è il tetto che prosegue, nello stesso piano della falda.
        extra = {}
        for fi, F in enumerate(info):
            Pa = punta.get((fi, 0)) or _add(F["ends"][0], _scale(F["dirn"], dg))
            Pb = punta.get((fi, 1)) or _add(F["ends"][1], _scale(F["dirn"], dg))
            co = cover_out[F["k"]]
            for i in range(len(co)):
                if _norm(_sub(co[i], F["ends"][0])) < 1e-4 and _norm(_sub(co[(i + 1) % len(co)], F["ends"][1])) < 1e-4:
                    extra.setdefault(F["k"], {})[i] = (Pa, Pb)
                    break
        coperti = {(d["strato"], d["faccia"]): d for d in ext
                   if d["chiave"] == "roof_external" and not d.get("sotto_tetto")}
        for k, lati in extra.items():
            s_, f, _, _ = flat[k]
            d = coperti.get((s_, f))
            if d is None:
                continue
            co = d["copertura_est"]
            nco = len(co)
            salto = {((i + 1) % nco) for i in lati if (i + 1) % nco in lati}
            nuovo = []
            for i, q in enumerate(co):
                if i not in salto:
                    nuovo.append(q)
                if i in lati:
                    nuovo.extend(lati[i])
            pulito = []
            for q in nuovo:
                if not pulito or _norm(_sub(q, pulito[-1])) > 1e-5:
                    pulito.append(q)
            if len(pulito) > 2 and _norm(_sub(pulito[0], pulito[-1])) < 1e-5:
                pulito.pop()
            nuovo = pulito
            inn = [_add(q, _scale(nrm_f[k], -t_ext[k])) for q in nuovo]
            vecchia_a, vecchia_v = d["area_copertura"], d["volume_copertura"]
            d["copertura_est"] = nuovo
            d["copertura_int"] = inn
            d["area_copertura"] = _area(nuovo)
            d["volume_copertura"] = 0.5 * (_area(inn) + d["area_copertura"]) * t_ext[k]
            d["fuori_piano"] = _nonplanarity(nuovo)
            g = tot["roof_external"]
            g["area"] += d["area_copertura"] - vecchia_a
            g["volume"] += d["volume_copertura"] - vecchia_v
    model["gronda"] = []
    model["esterno"] = ext
    model["esterno_totali"] = tot
    zs = [q[2] for d in ext for q in (d["copertura_est"] or d["struttura_est"])]
    model["summary"]["altezza_esterna"] = max(zs)
    # il limite dei 3 m si misura dal punto piu' alto (con il tetto) fino al pavimento finito (sopra il tavolato), non da terra
    model["summary"]["altezza_esterna_su_pavimento"] = max(zs) - model["summary"].get("quota_pavimento", 0.0)
    model["summary"]["z_min_esterna"] = min(zs)
    # ingombro con la copertura e la gronda (il tetto sporge oltre il bordo): larghezza reale della zome finita
    pe = [q for d in ext for q in (d["copertura_est"] or d["struttura_est"])] + [q for g_ in gronda for q in (g_["pts"] + g_["bot"])]
    model["summary"]["ingombro_x_esterno"] = max(q[0] for q in pe) - min(q[0] for q in pe)
    model["summary"]["ingombro_y_esterno"] = max(q[1] for q in pe) - min(q[1] for q in pe)
    model["summary"]["fuori_piano_esterno"] = max(d["fuori_piano"] for d in ext)
    return model


# ---------------------------------------------------------------------------
# Scheletro (travi, le "tavole" di struttura): parallelepipedi posati sul bordo di ogni faccia.
#   TT = spessore, nel piano della faccia, verso l'interno della faccia
#   TW = altezza, perpendicolare alla faccia, verso l'ESTERNO
# Giunti agli angoli: "butt_ccw" e "butt_cw" (testa-testa, un pezzo passa e l'altro si ferma),
# "miter" (taglio sulla bisettrice).  Geometria derivata da beams_polygon del vecchio pannello.
# ---------------------------------------------------------------------------
JOINTS = ("butt_ccw", "butt_cw", "miter")
BEAM_FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))  # indici dei vertici


def _unit(a):
    n = _norm(a)
    return (a[0]/n, a[1]/n, a[2]/n)


def _scale(a, k): return (a[0]*k, a[1]*k, a[2]*k)


def _face_normal(pts):
    n = (0.0, 0.0, 0.0)
    for i in range(1, len(pts) - 1):
        n = _add(n, _cross(_sub(pts[i], pts[0]), _sub(pts[i+1], pts[0])))
    return _unit(n)


def parse_traverse(txt):
    """'1:ta,4:t' -> {1: {'t','a'}, 4: {'t'}}. t = tra anelli, a = sull'anello."""
    out = {}
    for parte in str(txt or "").split(","):
        parte = parte.strip()
        if ":" not in parte:
            continue
        num, lettere = parte.split(":", 1)
        try:
            i = int(num)
        except ValueError:
            continue
        accesi = {c for c in lettere if c in ("t", "a")}
        if accesi:
            out[i] = accesi
    return out


def toggle_traverse(txt, strato, quale):
    """Accende o spegne la lettera `quale` ('t' o 'a') sullo strato."""
    flags = parse_traverse(txt)
    i = int(strato)
    accesi = set(flags.get(i, ()))
    if quale in accesi:
        accesi.discard(quale)
    else:
        accesi.add(quale)
    if accesi:
        flags[i] = accesi
    else:
        flags.pop(i, None)
    parti = []
    for k in sorted(flags):
        lettere = "".join(c for c in ("t", "a") if c in flags[k])
        if lettere:
            parti.append(f"{k}:{lettere}")
    return ",".join(parti)


def _asse_zome(p):
    """Direzione dell'asse della zome nel mondo. Nello zome dritto è +Z; coricata, lungo X."""
    return _rot((0.0, 0.0, 1.0), p.tilt, p.orient)


def _quota_asse(q, asse):
    return _dot(q, asse)


def _medio(a, b):
    return tuple((a[c] + b[c]) * 0.5 for c in range(3))


_EPS_ANELLO = 1e-5   # m: due vertici dello stesso anello restano a questa quota lungo l'asse, anche dopo la posa


def segmenti_traverse(model):
    """Traverse accese, una per faccia intera. Le misure sono nel sistema della zome, non del mondo:
    «tra anelli» unisce un anello a quello successivo (nello zome dritto è la diagonale verticale);
    «sull'anello» unisce i due vertici dello stesso anello (nello zome dritto è orizzontale).
    Sul triangolo esiste solo «tra anelli»: dal vertice al punto medio del lato che sta su un anello.
    Se sul rombo sono accese entrambe, `extra` è il punto d'incrocio (il telaio le unisce lì).
    Una faccia tagliata, che non è più un rombo o un triangolo intero, non riceve traverse."""
    p = model.get("params")
    flags = parse_traverse(getattr(p, "traverse", "") if p is not None else "")
    if not flags:
        return []
    asse = _asse_zome(p)
    out = []
    for st in model["strata"]:
        accesi = flags.get(st["strato"])
        if not accesi:
            continue
        for f, (kind, pts) in enumerate(st["facce"]):
            if len(pts) < 3:
                continue
            nrm = _face_normal(pts)
            if kind == "rombo" and len(pts) == 4 and ("t" in accesi or "a" in accesi):
                q = [_quota_asse(v, asse) for v in pts]
                d02, d13 = abs(q[0] - q[2]), abs(q[1] - q[3])
                if min(d02, d13) > _EPS_ANELLO:
                    continue
                if d02 <= d13:
                    anello, tra = (0, 2), (1, 3)
                else:
                    anello, tra = (1, 3), (0, 2)
                pezzi = []
                if "a" in accesi:
                    pezzi.append(("a", "sull_anello", anello))
                if "t" in accesi:
                    pezzi.append(("t", "tra_anelli", tra))
                extra = []
                if len(pezzi) == 2:
                    extra = [_medio(_medio(pts[anello[0]], pts[anello[1]]), _medio(pts[tra[0]], pts[tra[1]]))]
                for quale, tipo, (i, j) in pezzi:
                    a, b = pts[i], pts[j]
                    if _dist(a, b) < 1e-4:
                        continue
                    out.append({"strato": st["strato"], "parte": st["parte"], "faccia": f,
                                "quale": quale, "tipo": tipo, "a": a, "b": b, "normale": nrm, "extra": extra})
            elif str(kind).startswith("triangolo") and len(pts) == 3 and "t" in accesi:
                q = [_quota_asse(v, asse) for v in pts]
                i = min(range(3), key=lambda k: abs(q[k] - q[(k + 1) % 3]))
                if abs(q[i] - q[(i + 1) % 3]) > _EPS_ANELLO:
                    continue
                j, k = (i + 1) % 3, (i + 2) % 3
                medio = _medio(pts[i], pts[j])
                if _dist(pts[k], medio) < 1e-4:
                    continue
                out.append({"strato": st["strato"], "parte": st["parte"], "faccia": f,
                            "quale": "t", "tipo": "tra_anelli", "a": pts[k], "b": medio,
                            "normale": nrm, "extra": []})
    return out


def _trave_traversa(seg, TT, TW, density):
    """Tavola sulla diagonale: larga TT nel piano della faccia, spessa TW verso l'esterno, centrata sulla linea."""
    a, b, nrm = seg["a"], seg["b"], seg["normale"]
    lung = _dist(a, b)
    if lung < 1e-4:
        return None
    asse = _unit(_sub(b, a))
    lato = _cross(nrm, asse)
    if _norm(lato) < 1e-8:
        return None
    lato = _scale(_unit(lato), TT * 0.5)
    p0, p1 = _sub(a, lato), _sub(b, lato)
    p2, p3 = _add(b, lato), _add(a, lato)
    up = _scale(nrm, TW)
    quad = (p0, p1, p2, p3)
    area = lung * TT
    vol = area * TW
    return {"strato": seg["strato"], "parte": seg["parte"], "faccia": seg["faccia"], "lato": -1,
            "tipo": seg["tipo"], "ruolo": "traversa", "vertici": list(quad) + [_add(v, up) for v in quad],
            "lung_max": lung, "lung_min": lung, "taglio_inizio": 90.0, "taglio_fine": 90.0,
            "area_pianta": area, "volume": vol, "massa": vol * density}


def board_plan(pts, TT, joint="butt_ccw"):
    """Per ogni lato della faccia (vertici in senso antiorario visti da fuori) ritorna i 4 punti
    nel piano: (esterno0, esterno1, interno1, interno0).  Punti 'esterno' = sul bordo della faccia."""
    if joint not in JOINTS:
        raise ValueError(f"giunto sconosciuto: {joint}")
    n = len(pts)
    nxt, prv, delta, Q = [], [], [], []
    for i in range(n):
        a = _unit(_sub(pts[(i + 1) % n], pts[i]))      # lungo il lato che parte da i
        b = _unit(_sub(pts[(i - 1) % n], pts[i]))      # verso il vertice precedente
        sin_al = _norm(_cross(a, b))
        if sin_al < 1e-9:
            raise ValueError("angolo degenere in una faccia")
        d = TT / sin_al
        nxt.append(a); prv.append(b); delta.append(d)
        Q.append(_add(pts[i], _scale(_add(a, b), d)))
    out = []
    for i in range(n):
        j = (i + 1) % n
        if joint == "butt_ccw":
            o0, i0 = _add(pts[i], _scale(nxt[i], delta[i])), Q[i]
            o1, i1 = pts[j], _add(pts[j], _scale(nxt[j], delta[j]))
        elif joint == "butt_cw":
            o0, i0 = pts[i], _add(pts[i], _scale(prv[i], delta[i]))
            o1, i1 = _add(pts[j], _scale(prv[j], delta[j])), Q[j]
        else:
            o0, i0, o1, i1 = pts[i], Q[i], pts[j], Q[j]
        out.append((o0, o1, i1, i0))
    return out


def _segmenti_incrociati(a, b, c, d):
    """Due segmenti complanari si attraversano nel mezzo, non solo in un vertice."""
    n = _cross(_sub(b, a), _sub(d, c))
    if _norm(n) < 1e-12:
        n = _cross(_sub(b, a), _sub(c, a))
    if _norm(n) < 1e-12:
        return False

    def lato(p, q, r):
        return _dot(_cross(_sub(q, p), _sub(r, p)), n)

    return lato(a, b, c) * lato(a, b, d) < 0 and lato(c, d, a) * lato(c, d, b) < 0


def _tavola_valida(o0, o1, i1, i0, TT):
    """Una tavola collassata (lato più corto del giunto, o i bordi che si incrociano) non è un pezzo."""
    if _area([o0, o1, i1, i0]) < TT * TT * 0.25:
        return False

    def dist_linea(a, b, c):
        ab = _sub(b, a)
        L = _norm(ab)
        return _norm(_cross(ab, _sub(c, a))) / L if L > 1e-9 else 0.0

    larg = 0.5 * (dist_linea(o0, o1, i0) + dist_linea(o0, o1, i1))
    if larg < TT * 0.35:
        return False
    if _segmenti_incrociati(o0, o1, i1, i0) or _segmenti_incrociati(o0, i0, o1, i1):
        return False
    return True


def _cavita_faccia(pts, TT):
    """Poligono del rombo rientrato delle tavole. Su una faccia non convessa resta il contorno intero."""
    n = len(pts)
    if n < 3:
        return None
    nrm = _face_normal(pts)
    if _norm(nrm) < 1e-12:
        return None
    segni = []
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        segni.append(_dot(_cross(_sub(b, a), _sub(c, b)), nrm))
    convesso = all(s >= -1e-8 for s in segni) or all(s <= 1e-8 for s in segni)
    if not convesso or TT <= 0:
        return list(pts)
    Q = []
    for i in range(n):
        a = _unit(_sub(pts[(i + 1) % n], pts[i]))
        b = _unit(_sub(pts[(i - 1) % n], pts[i]))
        sin_al = _norm(_cross(a, b))
        if sin_al < 1e-6:
            return list(pts)
        Q.append(_add(pts[i], _scale(_add(a, b), TT / sin_al)))
    if _area(Q) < max(TT * TT, 1e-4):
        return None
    return Q


def isolante_guscio(model, TT):
    """Un prisma per ogni rombo che non è vetro: riempie l'altezza dello scheletro, dentro le tavole."""
    p = model["params"]
    cat = getattr(p, "catalogo", None) or {}
    man = _manuali(getattr(p, "usi_manuali", ""))
    out = []
    for st in model["strata"]:
        for f, (kind, pts) in enumerate(st["facce"]):
            if kind != "rombo" or len(pts) < 3:
                continue
            uso = face_use(p, st["strato"], f, pts, man)
            if uso == "glass_external" or uso == "aperto" or uso not in cat:
                continue
            Q = _cavita_faccia(pts, TT)
            if not Q:
                continue
            nrm = _unit(_face_normal(pts))
            top = [_add(q, _scale(nrm, p.TW)) for q in Q]
            out.append({"strato": st["strato"], "faccia": f, "spessore": p.TW, "area": _area(Q), "in": Q, "out": top})
    return out


def beams(model, TT, TW, joint="butt_ccw", triangles=False, density=700.0):
    """Scheletro: pezzi di tutti i rombi (e, se richiesto, dei triangoli).  Unita' come ZH; densita' in kg/m3
    (volume e massa sono corretti se le unita' sono metri)."""
    if TT <= 0 or TW <= 0:
        raise ValueError("TT e TW devono essere positivi")
    out = []
    for st in model["strata"]:
        for f, (kind, pts) in enumerate(st["facce"]):
            if kind != "rombo" and not triangles:
                continue
            nrm = _face_normal(pts)
            up = _scale(nrm, TW)
            for e, quad in enumerate(board_plan(pts, TT, joint)):
                o0, o1, i1, i0 = quad
                if not _tavola_valida(o0, o1, i1, i0, TT):
                    continue
                verts = [o0, o1, i1, i0] + [_add(v, up) for v in (o0, o1, i1, i0)]
                axis = _unit(_sub(pts[(e + 1) % len(pts)], pts[e]))
                lens = [_dist(o0, o1), _dist(i0, i1)]
                def cut_angle(a, b):            # angolo tra l'asse del pezzo e il taglio di testa
                    c = abs(_dot(axis, _unit(_sub(b, a))))
                    return math.degrees(math.acos(min(1.0, c)))
                area = _area([o0, o1, i1, i0])
                vol = area * TW
                out.append({"strato": st["strato"], "parte": st["parte"], "faccia": f, "lato": e, "tipo": kind,
                            "ruolo": "bordo", "vertici": verts, "lung_max": max(lens), "lung_min": min(lens),
                            "taglio_inizio": cut_angle(o0, i0), "taglio_fine": cut_angle(o1, i1),
                            "area_pianta": area, "volume": vol, "massa": vol * density})
    for seg in segmenti_traverse(model):
        pezzo = _trave_traversa(seg, TT, TW, density)
        if pezzo:
            out.append(pezzo)
    return out


def chiave_taglio(b, ndigits=4):
    """Identità di un pezzo nella lista tagli: strato, bordo o traversa, lunghezze e angoli di testa."""
    return (b["strato"], b.get("ruolo", "bordo"), round(b["lung_max"], ndigits), round(b["lung_min"], ndigits),
            round(b["taglio_inizio"], 2), round(b["taglio_fine"], 2))


def cutlist(beam_list, ndigits=4):
    """Raggruppa i pezzi identici (per strato di appartenenza, misure e tagli) e le conta."""
    groups = {}
    for b in beam_list:
        key = chiave_taglio(b, ndigits)
        g = groups.setdefault(key, {"strato": b["strato"], "tipo": b["tipo"], "ruolo": b.get("ruolo", "bordo"),
                                    "lung_max": b["lung_max"], "lung_min": b["lung_min"],
                                    "taglio_inizio": b["taglio_inizio"], "taglio_fine": b["taglio_fine"],
                                    "n": 0, "volume": 0.0, "massa": 0.0})
        g["n"] += 1; g["volume"] += b["volume"]; g["massa"] += b["massa"]
    return sorted(groups.values(), key=lambda g: (g["strato"], g["ruolo"] != "traversa", -g["lung_max"]))


def beams_summary(beam_list, TT, TW):
    cl = cutlist(beam_list)
    return {"pezzi": len(beam_list), "tipi": len(cl),
            "volume": sum(b["volume"] for b in beam_list), "massa": sum(b["massa"] for b in beam_list),
            "lunghezza_totale": sum(b["lung_max"] for b in beam_list), "sezione": (TT, TW)}


def solve_secondary_total_height(p: Params, total, esterna=True):
    """Trova ZH del primario tale che l'altezza totale (con secondario) sia `total`.  Bisezione.  Con `esterna` (di partenza)
    l'altezza e' quella ESTERNA, cioe' con la copertura del tetto (e le lastre dei vetri); altrimenti quella della sola struttura."""
    lo, hi = total * 0.2, total * 20.0
    for _ in range(45 if esterna else 200):
        mid = 0.5 * (lo + hi)
        q = Params(**{**p.__dict__, "ZH": mid})
        m = build(q, _pav=False)
        if esterna:
            shell(m, m["params"])
            h = m["summary"].get("altezza_esterna", m["summary"]["altezza_totale"])
        else:
            h = m["summary"]["altezza_totale"]
        if h < total:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def report(model):
    s = model["summary"]
    lines = [f"N={s['N']} M={s['M']} strati={s['strati']}  h={s['h']:.4f}  l={s['l']:.4f}  H poliedro={s['H_poliedro']:.4f}",
             f"altezza totale={s['altezza_totale']:.4f}  diametro base={s['diametro_base']:.4f}  area base={s['area_base']:.4f}",
             f"facce={s['facce']}  superficie interna={s['area_superficie_interna']:.3f}  fuori piano max={s['fuori_piano_max']:.2e}"]
    for st in model["strata"]:
        lati = " ".join(f"{x:.3f}" for x in st["lati"])
        lines.append(f"strato {st['strato']:2d} {st['parte'][:3]} {st['tipo']:14s} x{st['n']}  lati: {lati}  area {st['area']:.4f}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(build(Params())))
