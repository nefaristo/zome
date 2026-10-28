"""Pavimento della zome (geometria in Python puro): fondazione a secco, dormienti, travetti e tavolato.

Il pavimento si basa sull'impronta della zome posata (poligono dei bordi liberi, qualunque sia l'inclinazione), quindi vale anche
per le versioni coricate o inclinate.  L'impronta SEGUE LA PORTA:
  - porta a parete: l'impronta e' tagliata dal piano della porta;
  - corridoio con il piano della porta fuori dalla zome: all'impronta si aggiunge il rettangolo del corridoio (larghezza del vano
    piu' il legno delle pareti) fino al piano della porta; il poligono non e' piu' convesso;
  - corridoio con il piano della porta dentro la zome: l'impronta resta quella della zome.

Due fondazioni (scelta `tipo`):
  "muretto"  : muro a secco di pietre irregolari a corsi sfalsati (spessore ~40 cm + una fila interna piu' bassa di 20 cm), continuo
               lungo tutto il perimetro, VUOTO sotto il pavimento (ventilazione e ispezione), con un dormiente squadrato sopra; i travetti
               stanno in un ribassamento sul lato interno, cosi' il pavimento finito e' quasi a filo con la cima del muretto.  Al piu'
               nessun varco (il dormiente restava sospeso); la fila principale esce al piu' 10 cm dal bordo, quindi si vede solo di lato.
  "pietroni" : un pietrone irregolare (~50 cm) per ogni vertice dell'impronta (corridoio compreso) e un palo squadrato di sopra,
               tagliato irregolare dal bosco, che va da un pietrone al successivo.
In entrambi i casi sopra poggiano i lati bassi dei triangoli (a quota zfloor) e i travetti del pavimento.
Il pavimento finito sta a zfloor - 1 cm (a filo con la base dei triangoli): niente scalino interno.
Il gradino e' una lastra di pietra irregolare davanti alla porta, sull'asse della porta, fuori dall'impronta, a meta' altezza.

Tutte le quote in metri; poliedri: {"v": [vertici], "f": [facce (indici)], "tinta": 0..1 (variazione di colore della pietra)}.
Dimensionamento dei travetti: indicativo (flessione e freccia L/300 con legno C24), non sostituisce un ingegnere.
"""
import math
import random

# sezioni commerciali (b, h) in m
SEZIONI = [(0.06, 0.10), (0.06, 0.12), (0.06, 0.14), (0.08, 0.12), (0.08, 0.14), (0.08, 0.16), (0.08, 0.18),
           (0.08, 0.20), (0.10, 0.20), (0.10, 0.22), (0.12, 0.24), (0.14, 0.28)]
T_TAVOLATO = 0.025
T_FONDO = 0.014          # tavolato sotto i travetti: ci appoggia l'isolante, e non resta a contatto col vuoto
FMD = 13.2               # N/mm2: C24, kmod 0.8, gammaM 1.45
E_MEDIO = 9000.0         # N/mm2, modulo medio del C24 (abete da costruzione), gia' ridotto per la deformazione nel tempo
TRAVETTO_B, TRAVETTO_H = 0.08, 0.12     # sezione solita, m: lo spessore e la larghezza sono dati, l'interasse si calcola
INTERASSE_MAX = 0.60     # m: oltre, il tavolato da 25 mm resta senza appoggio
H_DORMIENTE = 0.10       # dormiente squadrato sopra il muretto
H_PALO = 0.16            # palo del pietroni
W_MURETTO = 0.40
MURO_IN, MURO_OUT = -0.12, 0.10      # fila principale: da -12 a +10 cm dal bordo dell'impronta: fuori ne esce al piu' 10 cm
SEDE_IN, SEDE_OUT = -0.34, -0.10     # fila interna ribassata (sede dei travetti)
Z_FONDO = -0.05                      # le pietre scendono un po' sotto il terreno


def interasse_massimo(luce, b, h, carico):
    """Distanza massima fra i travetti, in metri.

    La sezione (b, h) e il modulo E del C24 sono dati. Il carico e' di servizio, in kN/m².
    Comanda il piu' stretto fra la freccia L/300 e la flessione.

        i = 384 · E · I / (1500 · q · L³)          freccia: 5·q·i·L⁴ / (384·E·I) = L/300
        i = 8 · f · W / (q · L²)                    flessione: q·i·L² / (8·W) = f

    I = b·h³/12, W = b·h²/6. Unita' interne: mm, N.
    """
    L = max(luce, 0.5) * 1000.0
    q = max(float(carico), 0.05) * 1e-3                            # kN/m² -> N/mm²
    bm, hm = b * 1000.0, h * 1000.0
    I = bm * hm ** 3 / 12.0
    W = bm * hm ** 2 / 6.0
    i_freccia = 384.0 * E_MEDIO * I / (1500.0 * q * L ** 3)
    i_flessione = 8.0 * FMD * W / (q * L * L)
    i = min(i_freccia, i_flessione) / 1000.0
    return i, {"E": E_MEDIO, "f": FMD, "q": float(carico), "L": max(luce, 0.5),
               "I_mm4": I, "W_mm3": W, "i_freccia": i_freccia / 1000.0,
               "i_flessione": i_flessione / 1000.0,
               "comanda": "freccia" if i_freccia <= i_flessione else "flessione"}


# --- geometria piana -------------------------------------------------------------------------------------------------
def _hull(pts):
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    low, up = [], []
    for q in pts:
        while len(low) >= 2 and cross(low[-2], low[-1], q) <= 1e-12:
            low.pop()
        low.append(q)
    for q in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 1e-12:
            up.pop()
        up.append(q)
    return low[:-1] + up[:-1]            # antiorario


def area(poly):
    n = len(poly)
    return abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))) / 2 if n >= 3 else 0.0


def sezione(facce, z, eps=1e-7):
    """Poligono convesso (antiorario, (x, y)) della sezione orizzontale a quota z delle facce (liste di punti 3D)."""
    pts = []
    for f in facce:
        k = len(f)
        for i in range(k):
            a, b = f[i], f[(i + 1) % k]
            da, db = a[2] - z, b[2] - z
            if abs(da) < eps:
                pts.append((a[0], a[1]))
            if da * db < -eps * eps:
                t = da / (da - db)
                pts.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return _hull(pts) if pts else []


def _offset(poly, d):
    """Poligono antiorario spostato di d (positivo = verso fuori): intersezione delle rette spostate (angoli a sperone)."""
    n = len(poly)
    rette = []
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        tx, ty = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = ty, -tx                                   # normale uscente (antiorario)
        rette.append((x0 + nx * d, y0 + ny * d, tx, ty))
    out = []
    for i in range(n):
        ax, ay, atx, aty = rette[i - 1]
        bx, by, btx, bty = rette[i]
        den = atx * bty - aty * btx
        if abs(den) < 1e-12:
            out.append((bx, by))
            continue
        t = ((bx - ax) * bty - (by - ay) * btx) / den
        out.append((ax + t * atx, ay + t * aty))
    return out


def _centro(poly):
    return (sum(q[0] for q in poly) / len(poly), sum(q[1] for q in poly) / len(poly))


def _corda(poly, x, c, dj, pj):
    """Estremi (t0, t1, base) della corda di un poligono qualunque lungo la direzione dj, a distanza laterale x dal centro c
    (le intersezioni piu' esterne: per un poligono 'stellato' lateralmente, come l'impronta col corridoio, e' tutta la corda)."""
    base = (c[0] + x * pj[0], c[1] + x * pj[1])
    n = len(poly)
    ts = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        sa = (a[0] - base[0]) * pj[0] + (a[1] - base[1]) * pj[1]
        sb = (b[0] - base[0]) * pj[0] + (b[1] - base[1]) * pj[1]
        if sa * sb > 0 or abs(sa - sb) < 1e-12:
            continue
        f = sa / (sa - sb)
        px, py = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
        ts.append((px - base[0]) * dj[0] + (py - base[1]) * dj[1])
    if len(ts) < 2 or max(ts) - min(ts) < 1e-6:
        return None
    return (min(ts), max(ts), base)


def _striscia(poly, x0, x1, c, pj):
    """Poligono dell'impronta fra due rette parallele ai travetti. x è la distanza laterale dal centro."""
    P = [(q[0], q[1], 0.0) for q in poly]
    pc = c[0] * pj[0] + c[1] * pj[1]
    P = _clip_semipiano(P, pj[0], pj[1], x1 + pc)
    if len(P) < 3:
        return None
    P = _clip_semipiano(P, -pj[0], -pj[1], -(x0 + pc))
    if len(P) < 3:
        return None
    area2 = abs(sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))) * 0.5
    if area2 < 0.02:
        return None
    return [(q[0], q[1]) for q in P]


def _clip_semipiano(P, nx, ny, d):
    """Taglia il poligono P ((x, y, z) antiorario) tenendo nx*x + ny*y <= d; la quota z si interpola sui nuovi vertici."""
    out = []
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        fa = nx * a[0] + ny * a[1] - d
        fb = nx * b[0] + ny * b[1] - d
        if fa <= 0:
            out.append(a)
        if fa * fb < 0:
            t = fa / (fa - fb)
            out.append(tuple(a[k] + t * (b[k] - a[k]) for k in range(3)))
    return out


def _con_corridoio(B, c, dwd, hw, T, zf):
    """Aggiunge all'impronta B (antioraria, (x, y, z)) il rettangolo del corridoio: larghezza 2*hw attorno all'asse, dal bordo di B
    fino a T (distanza dal centro c lungo dwd).  Ritorna (U, tipi, ok); tipi[i] e' "dome" o "corr" per il lato U[i] -> U[i+1]."""
    n = len(B)
    dj = (-dwd[1], dwd[0])
    def uscita(lat):
        best = None
        for i in range(n):
            a, b = B[i], B[(i + 1) % n]
            la = (a[0] - c[0]) * dj[0] + (a[1] - c[1]) * dj[1]
            lb = (b[0] - c[0]) * dj[0] + (b[1] - c[1]) * dj[1]
            if (la - lat) * (lb - lat) > 0 or abs(la - lb) < 1e-12:
                continue
            f = (lat - la) / (lb - la)
            px, py = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
            t = (px - c[0]) * dwd[0] + (py - c[1]) * dwd[1]
            if best is None or t > best[0]:
                best = (t, i, f)
        return best
    eL, eR = uscita(hw), uscita(-hw)
    if eL is None or eR is None or T - max(eL[0], eR[0]) < 0.25:
        return list(B), ["dome"] * n, False
    def pt(e):
        _, i, f = e
        a, b = B[i], B[(i + 1) % n]
        return tuple(a[k] + f * (b[k] - a[k]) for k in range(3))
    uL, uR = eL[1] + eL[2], eR[1] + eR[2]
    if uR > uL:
        idx = list(range(eL[1] + 1, eR[1] + 1))
    else:
        idx = list(range(eL[1] + 1, n)) + list(range(0, eR[1] + 1))
    PL, PR = pt(eL), pt(eR)
    U = [PL] + [B[j] for j in idx] + [PR]
    kind = ["E"] + ["v"] * len(idx) + ["E"]
    cr = (c[0] + dwd[0] * T - dj[0] * hw, c[1] + dwd[1] * T - dj[1] * hw, zf)
    cl = (c[0] + dwd[0] * T + dj[0] * hw, c[1] + dwd[1] * T + dj[1] * hw, zf)
    U += [cr, cl]
    kind += ["C", "C"]
    # niente vertici della zome a meno di 12 cm da un punto di uscita: darebbero lati cortissimi
    keep = []
    for k, q in enumerate(U):
        if kind[k] == "v":
            vicino = False
            for kk in (k - 1, (k + 1) % len(U)):
                if kind[kk] == "E" and math.hypot(U[kk][0] - q[0], U[kk][1] - q[1]) < 0.12:
                    vicino = True
            if vicino:
                continue
        keep.append(k)
    U2 = [U[k] for k in keep]
    kind2 = [kind[k] for k in keep]
    m = len(U2)
    tipi = []
    for k in range(m):
        a, b = kind2[k], kind2[(k + 1) % m]
        tipi.append("corr" if (a == "C" or b == "C") else "dome")
    return U2, tipi, True


# --- solidi --------------------------------------------------------------------------------------------------------
def _prisma(bot, top):
    """Solido tra due anelli corrispondenti di n punti 3D (basso, alto)."""
    n = len(bot)
    f = [list(range(n - 1, -1, -1)), list(range(n, 2 * n))]
    for i in range(n):
        j = (i + 1) % n
        f.append([i, j, n + j, n + i])
    return {"v": [tuple(q) for q in bot] + [tuple(q) for q in top], "f": f}


def _anelli(rings):
    """Solido da anelli successivi (dal basso in alto) di n punti 3D antiorari: base, cima e fasce laterali."""
    n = len(rings[0])
    v = [tuple(q) for r in rings for q in r]
    f = [list(range(n - 1, -1, -1)), list(range((len(rings) - 1) * n, len(rings) * n))]
    for k in range(len(rings) - 1):
        for i in range(n):
            j = (i + 1) % n
            f.append([k * n + i, k * n + j, (k + 1) * n + j, (k + 1) * n + i])
    return {"v": v, "f": f}


def _sasso(cx, cy, rx, ry, ztop, zbot, rng, n=9, rot=0.0):
    """Sasso irregolare con la faccia superiore piana a ztop: tre anelli (alto, mezzo, basso) di n vertici."""
    zmid = zbot + 0.65 * (ztop - zbot)
    ang = [rot + 2 * math.pi * k / n + rng.uniform(-0.25, 0.25) * 2 * math.pi / n for k in range(n)]
    def ring(z, s):
        return [(cx + rx * s * rng.uniform(0.82, 1.1) * math.cos(a), cy + ry * s * rng.uniform(0.82, 1.1) * math.sin(a), z) for a in ang]
    P = _anelli([ring(zbot, 0.62), ring(zmid, 1.0), ring(ztop, 0.92)])
    P["tinta"] = rng.random()
    return P


def _lastra(cx, cy, ex, ey, hw, hd, ztop, zbot, rng, n=14):
    """Lastra di pietra irregolare e arrotondata (il gradino): ellisse 'gonfia' con raggi disturbati, spigoli smussati.
    (ex, ey) = direzione della profondita' (l'asse della porta), la larghezza sta lungo la sua perpendicolare."""
    lat = (-ey, ex)
    ang = [2 * math.pi * k / n + rng.uniform(-0.22, 0.22) * 2 * math.pi / n for k in range(n)]
    fr = [rng.uniform(0.92, 1.08) for _ in ang]
    def ring(z, s, j, dz):
        out = []
        for a, f in zip(ang, fr):
            ca, sa = math.cos(a), math.sin(a)
            u = hd * math.copysign(abs(ca) ** 0.8, ca) * f * s + rng.uniform(-j, j)
            v = hw * math.copysign(abs(sa) ** 0.8, sa) * f * s + rng.uniform(-j, j)
            out.append((cx + ex * u + lat[0] * v, cy + ey * u + lat[1] * v, z + rng.uniform(-dz, dz)))
        return out
    P = _anelli([ring(zbot, 0.84, 0.01, 0.0), ring(ztop - 0.11, 1.0, 0.012, 0.01), ring(ztop - 0.03, 0.985, 0.008, 0.006),
                 ring(ztop, 0.90, 0.006, 0.006)])
    P["tinta"] = rng.random()
    return P


def _pietra_secco(A, B, C, D, zlo, zhi, nrm, rng, piatta):
    """Pietra del muro a secco.  A, B = punti sul lato interno (inizio, fine), D, C = sul lato esterno; zlo/zhi = quote bassa e alta
    nei quattro angoli (A, D, C, B); nrm = normale uscente.  Tre anelli di 6 vertici (base, mezzo, cima): base e cima rientrano, il
    mezzo gonfia e le facce lunghe sono bombate, cosi' tra le pietre restano i solchi del muro a secco.  piatta: cima esattamente a zhi."""
    cs = [A, D, C, B]
    g = (sum(q[0] for q in cs) / 4, sum(q[1] for q in cs) / 4)
    bo, bi = rng.uniform(0.008, 0.02), rng.uniform(0.008, 0.02)
    def punti(k):
        mDC = ((D[0] + C[0]) / 2 + nrm[0] * bo * k, (D[1] + C[1]) / 2 + nrm[1] * bo * k)
        mBA = ((B[0] + A[0]) / 2 - nrm[0] * bi * k, (B[1] + A[1]) / 2 - nrm[1] * bi * k)
        return [A, D, mDC, C, B, mBA]
    def zz(z):
        return [z[0], z[1], (z[1] + z[2]) / 2, z[2], z[3], (z[3] + z[0]) / 2]
    zl, zh = zz(zlo), zz(zhi)
    sb, sm, st = rng.uniform(0.88, 0.95), rng.uniform(1.0, 1.03), rng.uniform(0.95, 0.985)
    dh = rng.uniform(0.0, 0.016)                 # le pietre non arrivano tutte alla stessa quota
    anelli = []
    for k, (s, bul, j) in enumerate(((sb, 0.4, 0.010), (sm, 1.0, 0.014), (st, 0.5, 0.010))):
        pl = punti(bul)
        ring = []
        for m, q in enumerate(pl):
            x = g[0] + (q[0] - g[0]) * s + rng.uniform(-j, j)
            y = g[1] + (q[1] - g[1]) * s + rng.uniform(-j, j)
            if k == 0:
                z = zl[m] - rng.uniform(0.005, 0.02)
            elif k == 1:
                z = (zl[m] + zh[m]) / 2 + rng.uniform(-0.01, 0.01)
            else:
                z = zh[m] if piatta else zh[m] - dh - rng.uniform(0.0, 0.006)
            ring.append((x, y, z))
        anelli.append(ring)
    P = _anelli(anelli)
    P["tinta"] = rng.random()
    return P


def _giunti(a, b, rng, lmin, lmax, prev):
    """Posizioni (s) dei giunti che riempiono [a, b] con pietre lunghe lmin..lmax, lontani dai giunti del corso sotto (`prev`)."""
    gs, s = [a], a
    while b - s > 1e-9:
        e = b
        for _ in range(8):
            l = rng.uniform(lmin, lmax)
            if b - (s + l) < lmin * 0.8:
                l = b - s
            e = s + l
            if abs(e - b) < 1e-9 or all(abs(e - q) > 0.07 for q in prev):
                break
        gs.append(e)
        s = e
    return gs


def _muro_secco(U, Zv, off0, off1, ztop_f, hc, lmin, lmax, rng, varchi, cima_piatta=True):
    """Muro a secco continuo lungo il perimetro U (antiorario), tra gli spostamenti off0 (dentro) e off1 (fuori).  Pietre a corsi
    sfalsati (altezza media hc), giunti obliqui, angoli a sperone che combaciano; `varchi` = {lato: (f0, f1)} tratti senza pietre."""
    n = len(U)
    Pin, Pout = _offset(U, off0), _offset(U, off1)
    top_max = max(ztop_f(i, f) for i in range(n) for f in (0.0, 1.0))
    nc = max(2, int(round((top_max - Z_FONDO) / hc)))
    pesi = [rng.uniform(0.85, 1.2) for _ in range(nc)]
    tot, acc, fr = sum(pesi), 0.0, [0.0]
    for w in pesi:
        acc += w
        fr.append(acc / tot)
    pietre = []
    for i in range(n):
        j = (i + 1) % n
        ai, bi, ao, bo = Pin[i], Pin[j], Pout[i], Pout[j]
        ex, ey = U[j][0] - U[i][0], U[j][1] - U[i][1]
        Le = math.hypot(ex, ey)
        if Le < 1e-6:
            continue
        tx, ty = ex / Le, ey / Le
        nrm = (ty, -tx)
        Lin, Lout = math.hypot(bi[0] - ai[0], bi[1] - ai[1]), math.hypot(bo[0] - ao[0], bo[1] - ao[1])
        if (bi[0] - ai[0]) * tx + (bi[1] - ai[1]) * ty < 0.03 or (bo[0] - ao[0]) * tx + (bo[1] - ao[1]) * ty < 0.03:
            continue                                         # lato troppo corto: lo spostamento lo ha rovesciato
        Lm = (Lin + Lout) / 2
        if i in varchi:
            f0, f1 = varchi[i]
            segs = [(0.0, f0 * Lm), (f1 * Lm, Lm)]
        else:
            segs = [(0.0, Lm)]
        def pin(f):
            f = max(0.0, min(1.0, f))
            return (ai[0] + (bi[0] - ai[0]) * f, ai[1] + (bi[1] - ai[1]) * f)
        def pout(f):
            f = max(0.0, min(1.0, f))
            return (ao[0] + (bo[0] - ao[0]) * f, ao[1] + (bo[1] - ao[1]) * f)
        def zl(k, f):
            f = max(0.0, min(1.0, f))
            return Z_FONDO + (ztop_f(i, f) - Z_FONDO) * fr[k]
        prev = []
        for k in range(nc):
            cur = []
            for (a, b) in segs:
                if b - a < 0.05:
                    continue
                gs = _giunti(a, b, rng, lmin, lmax, prev)
                sk = [0.0] * len(gs)
                for m in range(1, len(gs) - 1):
                    sk[m] = rng.uniform(-0.05, 0.05)
                cur.extend(gs)
                for m in range(len(gs) - 1):
                    s0, s1 = gs[m], gs[m + 1]
                    if s1 - s0 < 0.04:
                        continue
                    fi0, fi1 = (s0 - sk[m] / 2) / Lm, (s1 - sk[m + 1] / 2) / Lm
                    fo0, fo1 = (s0 + sk[m] / 2) / Lm, (s1 + sk[m + 1] / 2) / Lm
                    A, B, D, C = pin(fi0), pin(fi1), pout(fo0), pout(fo1)
                    zlo = [zl(k, fi0), zl(k, fo0), zl(k, fo1), zl(k, fi1)]
                    zhi = [zl(k + 1, fi0), zl(k + 1, fo0), zl(k + 1, fo1), zl(k + 1, fi1)]
                    pietre.append(_pietra_secco(A, B, C, D, zlo, zhi, nrm, rng, cima_piatta and k == nc - 1))
            prev = cur
    return pietre


def impronta(facce, zf=None):
    """Impronta della zome posata: inviluppo convesso (x, y, z) dei vertici dei bordi liberi (spigoli di una sola faccia).
    Per la zome dritta e' il poligono di base; per quella coricata o inclinata comprende anche il taglio sul piano del pavimento."""
    cont = {}
    for f in facce:
        k = len(f)
        for i in range(k):
            a, b = f[i], f[(i + 1) % k]
            ka, kb = tuple(round(c, 6) for c in a), tuple(round(c, 6) for c in b)
            key = (ka, kb) if ka < kb else (kb, ka)
            cont[key] = cont.get(key, 0) + 1
    pts = {}
    for (ka, kb), n in cont.items():
        if n == 1:
            for kk in (ka, kb):
                xy = (kk[0], kk[1])
                pts[xy] = min(pts.get(xy, 1e9), kk[2])
    if zf is not None:                          # zome coricata: solo i punti sul piano del pavimento (la bocca aperta non fa salire il muretto)
        pts = {xy: z for xy, z in pts.items() if z <= zf + 0.02}
    if len(pts) < 3:
        return []
    H = _hull(list(pts))
    out = []
    for x, y in H:
        k = min(pts, key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
        out.append((x, y, pts[k]))
    return _semplifica(out)


def _semplifica(P, lmin=0.35, tol=0.03):
    """Toglie dall'impronta i vertici quasi allineati e fonde quelli a meno di lmin (il taglio col piano, o l'inclinazione, ne creano
    di ravvicinati): ogni vertice rimasto avra' un pietrone."""
    P = list(P)
    cambiato = True
    while cambiato and len(P) > 3:
        cambiato = False
        n = len(P)
        for i in range(n):
            a, b, c = P[i - 1], P[i], P[(i + 1) % n]
            ex, ey = c[0] - a[0], c[1] - a[1]
            L = math.hypot(ex, ey) or 1.0
            if abs((b[0] - a[0]) * ey - (b[1] - a[1]) * ex) / L < tol:           # quasi allineato
                P.pop(i)
                cambiato = True
                break
        if cambiato:
            continue
        n = len(P)
        for i in range(n):
            a, b = P[i], P[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < lmin:
                P[i] = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, max(a[2], b[2]))
                P.pop((i + 1) % n)
                cambiato = True
                break
    return P


def pavimento(facce, p_info):
    """Calcola il pavimento.  facce: facce della zome posata (senza il vano della porta);
    p_info: zf (quota del piano di posa), tipo, interasse, carico, seme, porta (angolo orizzontale mondo in gradi o None),
    porta_modo ("parete" | "fuori" | "dentro" | None), porta_dist (distanza orizzontale del piano della porta dal centro),
    porta_w (larghezza del vano), centro (x, y dell'asse), densita (kg/m3).  Ritorna None se manca l'impronta."""
    zf = p_info["zf"]
    tipo = p_info.get("tipo", "muretto")
    rng = random.Random(p_info.get("seme", 1) * 7919 + 13)
    Bz = impronta(facce, zf if p_info.get("solo_piano") else None)
    if len(Bz) < 3:
        return None
    c = p_info.get("centro") or _centro([(q[0], q[1]) for q in Bz])
    if p_info.get("porta") is not None:
        a = math.radians(p_info["porta"])
        dwd = (math.cos(a), math.sin(a))
    else:
        dwd = (0.0, -1.0)
    dj = (-dwd[1], dwd[0])                              # i travetti corrono di lato, il tavolato lungo l'asse della porta
    pj = (-dj[1], dj[0])
    modo = p_info.get("porta_modo") if p_info.get("porta") is not None else None
    dist = p_info.get("porta_dist")
    tipi = None
    corridoio = False
    if modo == "parete" and dist is not None:
        Q = _clip_semipiano(Bz, dwd[0], dwd[1], dwd[0] * c[0] + dwd[1] * c[1] + dist)
        if len(Q) >= 3 and area([(q[0], q[1]) for q in Q]) > 0.3:
            Bz = Q
            m = len(Bz)
            tipi = []
            for k in range(m):
                a_, b_ = Bz[k], Bz[(k + 1) % m]
                sa = (a_[0] - c[0]) * dwd[0] + (a_[1] - c[1]) * dwd[1]
                sb = (b_[0] - c[0]) * dwd[0] + (b_[1] - c[1]) * dwd[1]
                tipi.append("corr" if abs(sa - dist) < 1e-6 and abs(sb - dist) < 1e-6 else "dome")
    elif modo == "fuori" and dist is not None:
        hw = p_info.get("porta_w", 0.8) / 2 + 0.04               # asse del legno delle pareti del corridoio
        Bz, tipi, corridoio = _con_corridoio(Bz, c, dwd, hw, dist + 0.03, zf)
    if tipi is None:
        tipi = ["dome"] * len(Bz)
    B = [(x, y) for x, y, _ in Bz]
    Zv = [max(z, zf) for _, _, z in Bz]                 # quota a cui poggia la zome sul vertice (>= zf)
    n = len(B)
    inset = 0.22 if tipo == "muretto" else 0.10          # distanza degli appoggi dal bordo, per la luce libera
    # --- la luce e' la corda piu' lunga dell'impronta; da quella, con la sezione data, esce l'interasse
    xs_ = [(q[0] - c[0]) * pj[0] + (q[1] - c[1]) * pj[1] for q in B]
    xmin, xmax = min(xs_), max(xs_)
    luce, xprobe = 0.5, xmin
    while xprobe <= xmax + 1e-9:
        cd = _corda(B, xprobe, c, dj, pj)
        if cd:
            luce = max(luce, cd[1] - cd[0] - 2 * inset)
        xprobe += 0.05
    luce = max(luce, 0.5)
    carico = p_info.get("carico", 0.5)
    b, h = TRAVETTO_B, TRAVETTO_H
    i_calc, formula = interasse_massimo(luce, b, h, carico)
    while i_calc < 0.30 and (b, h) != SEZIONI[-1]:
        successivi = [s for s in SEZIONI if s[0] * s[1] > b * h + 1e-9]
        if not successivi:
            break
        b, h = successivi[0]
        i_calc, formula = interasse_massimo(luce, b, h, carico)
    interasse = min(INTERASSE_MAX, max(0.20, i_calc))
    formula = dict(formula, b=b, h=h, interasse=interasse, tetto=INTERASSE_MAX)
    xs = [0.0]
    k = 0
    while (k + 1) * interasse < max(abs(xmin), abs(xmax)) + 1e-9 and len(xs) < 120:
        k += 1
        xs += [k * interasse, -k * interasse]
    xs = [x for x in xs if xmin + 0.06 < x < xmax - 0.06]
    for xe in (xmin + 0.10, xmax - 0.10):                    # un travetto vicino a ciascun bordo
        if all(abs(xe - x) > 0.18 for x in xs):
            xs.append(xe)
    chord = {x: _corda(B, x, c, dj, pj) for x in xs}
    zd = zf - 0.01                                       # pavimento finito: quasi a filo con la base dei triangoli
    zt_top = zd - T_TAVOLATO                              # cima dei travetti
    zj = zt_top - h                                       # sede dei travetti
    res = {"tipo": tipo, "base": Bz, "zf": zf, "z_finito": zd, "travetto": (b, h), "luce": luce, "dir_porta": dwd,
           "corridoio": corridoio, "tipi": tipi}
    nrm_i, L_i = [], []
    for i in range(n):
        x0, y0 = B[i]; x1, y1 = B[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0) or 1e-9
        L_i.append(L)
        nrm_i.append(((y1 - y0) / L, -(x1 - x0) / L))
    def zlin(i, t):
        return Zv[i] + max(0.0, min(1.0, t)) * (Zv[(i + 1) % n] - Zv[i])
    pietre, dorm, varchi = [], [], []
    if tipo == "muretto":
        vd = {}                                           # niente varchi: il muro e' continuo sotto il dormiente
        # fila principale (cima sotto il dormiente) e fila interna ribassata (sede dei travetti)
        pietre += _muro_secco(B, Zv, MURO_IN, MURO_OUT, lambda i, f: zlin(i, f) - H_DORMIENTE, 0.17, 0.26, 0.48, rng, vd)
        pietre += _muro_secco(B, Zv, SEDE_IN, SEDE_OUT, lambda i, f: zj, 0.15, 0.20, 0.38, rng, vd)
        Bi, Bo = _offset(B, -0.06), _offset(B, 0.06)         # dormiente squadrato 12 cm
        for i in range(n):
            j = (i + 1) % n
            top = [(Bi[i][0], Bi[i][1], Zv[i]), (Bi[j][0], Bi[j][1], Zv[j]), (Bo[j][0], Bo[j][1], Zv[j]), (Bo[i][0], Bo[i][1], Zv[i])]
            bot = [(q[0], q[1], q[2] - H_DORMIENTE) for q in top]
            dorm.append(_prisma(bot, top))
        ext = MURO_OUT - 0.02
        libera = zj
    else:
        for i in range(n):
            pietre.append(_sasso(B[i][0], B[i][1], rng.uniform(0.22, 0.28), rng.uniform(0.22, 0.28), min(Zv[i] - H_PALO - 0.01, zj - 0.02), -0.03, rng,
                                 rot=rng.uniform(0, 6)))
        for i in range(n):
            j = (i + 1) % n
            P0, P1 = B[i], B[j]
            L = L_i[i]
            tang = ((P1[0] - P0[0]) / L, (P1[1] - P0[1]) / L)
            nrm = nrm_i[i]
            w = rng.uniform(0.17, 0.21)
            hh = rng.uniform(0.14, 0.18)
            hh = max(hh, max(Zv[i], Zv[j]) - (zj - 0.04))        # il palo scende fino sotto i travetti: sono incastrati
            ext_ = 0.10
            a0 = (P0[0] - tang[0] * ext_, P0[1] - tang[1] * ext_)
            a1 = (P1[0] + tang[0] * ext_, P1[1] + tang[1] * ext_)
            def q(pt_, side, z, k):
                return (pt_[0] + nrm[0] * side * k, pt_[1] + nrm[1] * side * k, z)
            top = [q(a0, -1, Zv[i], w / 2), q(a1, -1, Zv[j], w / 2), q(a1, 1, Zv[j], w / 2), q(a0, 1, Zv[i], w / 2)]
            sh = rng.uniform(-0.015, 0.015)
            bot = [q(a0, -1, Zv[i] - hh, w / 2 * 0.65 + sh), q(a1, -1, Zv[j] - hh * rng.uniform(0.9, 1.1), w / 2 * 0.65 + sh),
                   q(a1, 1, Zv[j] - hh * rng.uniform(0.9, 1.1), w / 2 * 0.65 - sh), q(a0, 1, Zv[i] - hh, w / 2 * 0.65 - sh)]
            dorm.append(_prisma(bot, top))
        ext = 0.22
        libera = zt_top - h
    res["pietre"], res["dormienti"], res["varchi"] = pietre, dorm, varchi
    # --- travetti: sulla sede (muretto) o tra i pali; gli estremi stanno a `m` dal bordo
    m_end = 0.12 if tipo == "muretto" else -0.05     # pietroni: i travetti entrano di 5 cm nel palo (incastro)
    trav, lung_tot = [], 0.0
    for x in sorted(xs):
        cd = chord[x]
        if not cd:
            continue
        t0, t1, base = cd[0] + m_end, cd[1] - m_end, cd[2]
        if t1 - t0 < 0.4:
            continue
        def pt(t, lat, z):
            return (base[0] + dj[0] * t + pj[0] * lat, base[1] + dj[1] * t + pj[1] * lat, z)
        bot = [pt(t0, -b / 2, zj), pt(t1, -b / 2, zj), pt(t1, b / 2, zj), pt(t0, b / 2, zj)]
        top = [(q_[0], q_[1], zt_top) for q_ in bot]
        trav.append(_prisma(bot, top))
        lung_tot += t1 - t0
    res["travetti"] = trav
    # fra un travetto e l'altro: isolante per tutta l'altezza, e un tavolato da 14 mm sotto, a filo del travetto
    fondi, isol_p = [], []
    ordine = sorted(xs)
    varchi_x = [(xmin, ordine[0] - b / 2)] if ordine else [(xmin, xmax)]
    for xa, xb in zip(ordine, ordine[1:]):
        varchi_x.append((xa + b / 2, xb - b / 2))
    if ordine:
        varchi_x.append((ordine[-1] + b / 2, xmax))
    for x0, x1 in varchi_x:
        if x1 - x0 < 0.03:
            continue
        poly = _striscia(B, x0, x1, c, pj)
        if not poly:
            continue
        basso = [(x, y, zj - T_FONDO) for x, y in poly]
        mezzo = [(x, y, zj) for x, y in poly]
        alto = [(x, y, zt_top) for x, y in poly]
        fondi.append(_prisma(basso, mezzo))
        isol_p.append(_prisma(mezzo, alto))
    res["fondo"] = fondi
    res["isolante"] = isol_p
    # --- tavolato: sull'impronta (anche non convessa: il corridoio)
    res["tavolato"] = _prisma([(x, y, zd - T_TAVOLATO) for x, y in B], [(x, y, zd) for x, y in B])
    # --- gradino: lastra irregolare sull'asse della porta, davanti, fuori dall'impronta (e dal muretto)
    res["gradino"] = None
    if p_info.get("porta") is not None:
        smax = None
        for i in range(n):
            x0, y0 = B[i]; x1, y1 = B[(i + 1) % n]
            ex, ey = x1 - x0, y1 - y0
            den = dwd[0] * ey - dwd[1] * ex
            if abs(den) < 1e-12:
                continue
            tt = ((x0 - c[0]) * ey - (y0 - c[1]) * ex) / den
            uu = ((x0 - c[0]) * dwd[1] - (y0 - c[1]) * dwd[0]) / den
            if tt > 0 and -1e-9 <= uu <= 1 + 1e-9:
                smax = tt if smax is None else max(smax, tt)
        if smax is not None:
            hd = 0.24
            hw = max(0.55, p_info.get("porta_w", 0.8) / 2 + 0.2)
            sc = smax + ext + hd
            res["gradino"] = _lastra(c[0] + dwd[0] * sc, c[1] + dwd[1] * sc, dwd[0], dwd[1], hw, hd, zd / 2, Z_FONDO, rng)
    # --- riepilogo
    dens = p_info.get("densita", 700.0)
    vol_trav = b * h * lung_tot
    perim = sum(L_i)
    if tipo == "muretto":
        vol_dorm = 0.12 * H_DORMIENTE * perim
    else:
        vol_dorm = sum(0.19 * 0.16 * (L_i[i] + 0.2) for i in range(n))
    A = area(B)
    res["summary"] = {"tipo": tipo, "travetti": len(trav), "travetto_b": b, "travetto_h": h, "luce": luce, "interasse": interasse,
                      "carico": carico, "formula": formula, "lunghezza_travetti": lung_tot, "volume_travetti": vol_trav,
                      "massa_travetti": vol_trav * dens, "perimetro": perim, "volume_dormienti": vol_dorm,
                      "massa_dormienti": vol_dorm * dens, "pietre": len(pietre), "varchi": len(varchi),
                      "z_finito": zd, "altezza_libera": libera, "area_tavolato": A, "volume_tavolato": A * T_TAVOLATO,
                      "vertici": n, "corridoio": corridoio}
    return res
