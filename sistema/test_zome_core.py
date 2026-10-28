"""Prove di zome_core.py.  Esecuzione: python3 test_zome_core.py (dalla cartella)"""
import math
from collections import Counter
from zome_core import Params, build, rings, ground_radius, solve_secondary_total_height

def close(a, b, tol=1e-9): return abs(a - b) <= tol * max(1.0, abs(a), abs(b))

def edges_pairing(model):
    cnt = Counter()
    for st in model["strata"]:
        for _, pts in st["facce"]:
            for a in range(len(pts)):
                u, v = pts[a], pts[(a+1) % len(pts)]
                key = tuple(sorted([tuple(round(x, 9) for x in u), tuple(round(x, 9) for x in v)]))
                cnt[key] += 1
    return cnt

n = 0
# 1) primario: lato, raggio, raggio chiuso, piani, quote equidistanti (6 casi, N/M/theta/ZH)
for N, M, th, ZH in [(8,5,55.565,4.3),(7,5,58.514,3.5),(8,6,55,3),(6,4,60,3),(10,7,52,2.03),(12,8,50,3)]:
    m = build(Params(N=N, M=M, theta=th, ZH=ZH)); s = m["summary"]
    h = ZH/(M-1); l = h/math.cos(math.radians(th))
    assert close(s["l"], l)
    assert close(s["raggio_base"], ground_radius(N, M, th, ZH)), (N,M)
    assert s["fuori_piano_max"] < 1e-12
    for st in m["strata"]:
        lati = st["lati"] if st["tipo"] == "rombo" else [st["lati"][0], st["lati"][2]]   # triangolo: due lati l e la base
        assert all(close(x, l) for x in lati), st["lati"]
    assert close(s["altezza_totale"], ZH)
    # Hutton: l = (ZH/D)/(N cos theta) con D = (M-1)/N
    D = (M-1)/N
    assert close((ZH/D)/(N*math.cos(math.radians(th))), l)
    # bordo chiuso: ogni spigolo in due facce, tranne i N spigoli a terra
    c = edges_pairing(m)
    assert sum(1 for v in c.values() if v == 1) == N and all(v in (1, 2) for v in c.values())
    n += 1

# 2) secondario
for N, M, th, ZH, cut, M2, th2 in [(10,7,52,2.03,2,3,35),(10,7,52,2.03,3,4,45),(12,8,55,3,3,3,30),(8,6,58,3,1,3,40)]:
    m = build(Params(N=N, M=M, theta=th, ZH=ZH, cut=cut, M2=M2, theta2=th2)); s = m["summary"]
    assert s["fuori_piano_max"] < 1e-9, s["fuori_piano_max"]
    sec = [st for st in m["strata"] if st["parte"] == "secondaria"]
    l2 = s["l_secondario"]
    for st in sec:
        lati = st["lati"] if st["tipo"] == "rombo" else [st["lati"][0], st["lati"][2]]
        assert all(close(x, l2, 1e-9) for x in lati), (st["lati"], l2)
    # la base del secondario ha corda uguale a quella dell'anello del primario
    base = sec[-1]
    pr_cut = [st for st in m["strata"] if st["parte"] == "primaria"][0]
    assert pr_cut["tipo"] == "triangolo_giu"
    assert close(base["base"], pr_cut["base"], 1e-9)                  # corda alla base
    # chiusura: spigoli liberi solo i N a terra
    c = edges_pairing(m)
    assert sum(1 for v in c.values() if v == 1) == N, sum(1 for v in c.values() if v == 1)
    assert all(v in (1, 2) for v in c.values())
    assert close(s["altezza_totale"], rings(N, M, th, ZH)[cut][0][2] + s["ZH_secondario"], 1e-9)
    # tre strati di triangoli: terra, primario sotto il taglio, base del secondario
    tri = [st for st in m["strata"] if st["tipo"].startswith("triangolo")]
    assert len(tri) == 3, [t["tipo"] for t in tri]
    n += 1


# 4) scheletro (tavole di struttura): parallelepipedi perpendicolari alla faccia, che coprono esattamente la fascia del bordo
from zome_core import beams, cutlist, board_plan, JOINTS, _area
for N, M, th, ZH in [(10,7,52,2.03),(8,5,55,3)]:
    m = build(Params(N=N, M=M, theta=th, ZH=ZH))
    TT, TW = 0.02, 0.05
    for joint in JOINTS:
        bl = beams(m, TT, TW, joint)
        assert len(bl) == 4 * N * (M - 2)             # 4 pezzi per rombo, rombi = N*(M-2)
        for st in m["strata"]:
            if st["tipo"] != "rombo":
                continue
            for kind, pts in st["facce"]:
                plan = board_plan(pts, TT, joint)
                strip = sum(_area(q) for q in plan)
                # area interna = poligono dei punti Q (intersezione delle rette spostate di TT)
                inner = _area([q[3] for q in plan]) if joint == "miter" else None
                if inner is not None:
                    assert close(strip, _area(pts) - inner, 1e-9), (joint, strip)
                else:
                    # testa-testa: nessuna sovrapposizione, stessa copertura della fascia
                    Qs = [plan[i][3] if joint == "butt_ccw" else plan[i][2] for i in range(len(plan))]
                    assert close(strip, _area(pts) - _area(Qs), 1e-9), (joint, strip)
        for b in bl:
            v = b["vertici"]
            # il piano di base del pezzo e' quello della faccia: i 4 punti superiori sono spostati di TW lungo la normale
            from zome_core import _sub, _norm
            for k in range(4):
                assert close(_norm(_sub(v[4 + k], v[k])), TW)
            assert close(b["volume"], b["area_pianta"] * TW)
        # i pezzi di uno strato si dividono in pochi tipi uguali tra i N pezzi
        assert len(cutlist(bl)) <= 2 * (M - 2), len(cutlist(bl))
        n += 1

# 3) altezza totale imposta (3 m) con secondario
p = Params(N=10, M=7, theta=52, ZH=2.0, cut=2, M2=3, theta2=35)
zh = solve_secondary_total_height(p, 3.0, esterna=False)
assert close(build(Params(**{**p.__dict__, "ZH": zh}))["summary"]["altezza_totale"], 3.0, 1e-9)
n += 1

# 3b) altezza ESTERNA (con copertura del tetto) imposta
from zome_core import shell
zh = solve_secondary_total_height(p, 3.0)
m = build(Params(**{**p.__dict__, "ZH": zh}), _pav=False); shell(m, m["params"])
assert close(m["summary"]["altezza_esterna"], 3.0, 1e-6)
assert m["summary"]["ingombro_x_esterno"] > 1.0

# 4) posa e tagli (luglio 2025)
from zome_core import apply_pose_and_cuts
base = build(Params(N=10, M=7, theta=52, ZH=2.03))
A0 = base["summary"]["area_superficie_interna"]
# 4a) rotazione e traslazione non cambiano le aree
for tilt, orient in ((90, 0), (37, 123), (180, 0)):
    m = build(Params(N=10, M=7, theta=52, ZH=2.03, tilt=tilt, orient=orient, px=1, py=-2, pz=0.5))
    assert close(m["summary"]["area_superficie_interna"], A0, 1e-9), (tilt, orient)
    assert m["summary"]["fuori_piano_max"] < 1e-9
# 4b) coricata: asse lungo X, altezza = massimo raggio
m = build(Params(N=10, M=7, theta=52, ZH=2.03, tilt=90))
zs = [q[2] for st in m["strata"] for _, pt in st["facce"] for q in pt]
assert close(max(zs) - min(zs), base["summary"]["diametro_max"], 1e-9), (max(zs), min(zs))
# 4c) coricata e tagliata a meta' col pavimento: tutto sopra z=0, tappo = sezione piana
m = build(Params(N=10, M=7, theta=52, ZH=2.03, tilt=90, floor=True, zfloor=0.0))
zs = [q[2] for st in m["strata"] for _, pt in st["facce"] for q in pt]
assert min(zs) > -1e-9 and close(m["summary"]["altezza_totale"], max(zs))
assert "pavimento" in m["caps"] and all(abs(q[2]) < 1e-7 for q in m["caps"]["pavimento"])
assert 0 < m["summary"]["area_superficie_interna"] < A0
# il pavimento, 3 m: con ZH grande la zome coricata sta in 3 m se il diametro massimo e' < 6 m
# 4d) taglio radiale 180: meta' esatta per simmetria, tappo nel piano di taglio
m = build(Params(N=10, M=7, theta=52, ZH=2.03, radial=180))
assert close(m["summary"]["area_superficie_interna"], A0 / 2, 1e-9), (m["summary"]["area_superficie_interna"], A0/2)
assert len(m["caps"]) == 2 or len(m["caps"]) == 1
# 4e) quarto di zome (270) e pavimento + parete alta
m = build(Params(N=10, M=7, theta=52, ZH=2.03, radial=270))
assert 0 < m["summary"]["area_superficie_interna"] < A0 / 2
m = build(Params(N=10, M=7, theta=52, ZH=2.03, tilt=90, floor=True, ztop=1.0))
assert m["summary"]["altezza_totale"] <= 1.0 + 1e-9 and "parete alta" in m["caps"]
# 4f) apertura a facce intere (< 180): meno facce, nessuna ritagliata
m = build(Params(N=10, M=7, theta=52, ZH=2.03, radial=60))
assert m["summary"]["facce"] < base["summary"]["facce"]
assert close(m["summary"]["area_superficie_interna"], sum(st["area_totale"] for st in m["strata"]))
# 4g) lo scheletro funziona anche sulle facce ritagliate
m = build(Params(N=10, M=7, theta=52, ZH=2.03, tilt=90, floor=True))
bl = beams(m, 0.04, 0.10, "butt_ccw", triangles=True)
assert len(bl) > 0 and all(b["volume"] > 0 for b in bl)
n += 7

# 5) esterno: catalogo, regola di pendenza, scelte manuali
import json
from zome_core import shell, offset_surface, face_use, _face_normal, _dot, _sub, CATALOGO, APERTO
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0)
m = shell(build(p), p)
ex = m["esterno"]
chiavi = {d["chiave"] for d in ex}
assert chiavi == {"roof_external", "wood_external"}, chiavi
# regola: tetto solo se guarda in su e pendenza <= soglia
for d in ex:
    assert (d["chiave"] == "roof_external") == (d["inclinazione"] <= p.pendenza_tetto and d["strato"] > 0 and d["copertura_est"] is not None and d["inclinazione"] < 90 and True) or d["chiave"] == "wood_external"
# manuale: strato 4 tutto vetro, faccia 3.0 aperta
man = {f"4.{f}": "glass_external" for f in range(10)}; man["3.0"] = APERTO
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0, usi_manuali=json.dumps(man))
m = shell(build(p), p)
tot = m["esterno_totali"]
assert tot["glass_external"]["facce"] == 10 and tot[APERTO]["facce"] == 1
assert [d for d in m["esterno"] if d["strato"] == 3 and d["faccia"] == 0][0]["copertura_est"] is None
# spessori dal catalogo e distanza dalla faccia
cat = {k: dict(v) for k, v in CATALOGO.items()}; cat["roof_external"]["spessore"] = 0.04
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0, catalogo=cat)
m = shell(build(p), p)
flat = [pts for st in m["strata"] for _, pts in st["facce"]]
per_faccia = {(st["strato"], f): pts for st in m["strata"] for f, (_, pts) in enumerate(st["facce"])}
for d in m["esterno"]:
    if d["copertura_est"]:
        pts = per_faccia[(d["strato"], d["faccia"])]
        nrm = _face_normal(pts)
        dist = [_dot(nrm, _sub(q, pts[0])) for q in d["copertura_est"]]
        atteso = 0.05 + 0.02 + (0.04 if d["chiave"] == "roof_external" else 0.0)   # il tetto poggia sul legno
        assert abs(sum(dist)/len(dist) - atteso) < 1e-6, (d["chiave"], sum(dist)/len(dist))
# il tetto e' a parte: sotto ogni faccia di tetto c'e' il legno, che combacia con la base del tetto
for d in m["esterno"]:
    if d["chiave"] == "roof_external":
        sotto = [w for w in m["esterno"] if w.get("sotto_tetto") and (w["strato"], w["faccia"]) == (d["strato"], d["faccia"])]
        assert len(sotto) == 1 and sotto[0]["chiave"] == "wood_external"
        pf = per_faccia[(d["strato"], d["faccia"])]
        nf = _face_normal(pf)
        # il tetto poggia sul piano esterno del legno: stessa distanza dalla faccia (i contorni differiscono di qualche cm)
        dw = [_dot(nf, _sub(q, pf[0])) for q in sotto[0]["copertura_est"]]
        dt = [_dot(nf, _sub(q, pf[0])) for q in d["copertura_int"]]
        assert all(close(x, 0.05 + 0.02, 1e-9) for x in dw + dt)
# rivestimento interno: solo dove c'e' copertura non a vetro
cat["wood_internal"]["spessore"] = 0.015
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0, catalogo=cat, usi_manuali=json.dumps(man))
m = shell(build(p), p)
assert all(("rivestimento_int" in d) == (d["chiave"] in ("roof_external", "wood_external")) for d in m["esterno"] if not d.get("sotto_tetto"))
# faccia per faccia: esattamente piana
ps = offset_surface(flat, [0.07]*len(flat), shared=False)
for pts, q4 in zip(flat, ps):
    nrm = _face_normal(pts)
    for q in q4:
        assert close(_dot(nrm, _sub(q, pts[0])), 0.07, 1e-6)
assert m["summary"]["altezza_esterna"] > m["summary"]["altezza_totale"]
n += 4
# 6) default: stella di vetri in cima, finestre, gronda
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05)
m = shell(build(p), p)
assert all(d["chiave"] == "glass_external" for d in m["esterno"] if d["strato"] == 1)
fin = [d for d in m["esterno"] if d["strato"] == 4 and d["chiave"] == "glass_external"]
assert len(fin) == 3, len(fin)
def _area_tetto(model):
    return sum(d["area_copertura"] for d in model["esterno"]
               if d["chiave"] == "roof_external" and not d.get("sotto_tetto"))
assert m["gronda"] == []
p0 = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0)
m0 = shell(build(p0), p0)
p_sp = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05, stella_vetri=False, finestre=0, sporgenza_tetto=0.10)
m_sp = shell(build(p_sp), p_sp)
assert not any(d["chiave"] == "glass_external" for d in m0["esterno"]) and m0["gronda"] == [] and m_sp["gronda"] == []
assert _area_tetto(m_sp) > _area_tetto(m0) + 0.05
n += 3
# 7) esterno faccia per faccia: ogni pannello e' piano e alla distanza esatta dalla sua faccia
p = Params(N=10, M=7, theta=52, ZH=2.03, TW=0.05)
m = shell(build(p), p)
per_faccia = {(st["strato"], f): pts for st in m["strata"] for f, (_, pts) in enumerate(st["facce"])}
for d in m["esterno"]:
    if d["copertura_est"]:
        pts = per_faccia[(d["strato"], d["faccia"])]
        nrm = _face_normal(pts)
        atteso = 0.05 + 0.02 + (0.003 if d["chiave"] == "roof_external" else 0.0)   # legno e vetro a D, bituminosa da 3 mm sopra il legno
        for q in d["copertura_est"]:
            assert close(_dot(nrm, _sub(q, pts[0])), atteso, 1e-6)
        assert 0.9 < d["area_copertura"] / _area(pts) < 2.5
        assert close(_dot(nrm, _sub(d["copertura_int"][0], pts[0])), atteso - d["spessore"], 1e-6)
assert m["summary"]["fuori_piano_esterno"] < 1e-9
n += 1
# 8) porta: sezione verticale con vano minimo
from zome_core import porta_dist_max, porta_entra, porta_telaio, _sezione_verticale
p = Params(N=10, M=7, theta=52, ZH=2.9, cut=2, M2=3, theta2=58.1, porta=True, porta_dir=90.0, porta_w=0.8, porta_h=2.0)
mx = porta_dist_max(p)
assert 0.9 < mx < 1.1, mx
q = Params(**{**p.__dict__, "porta_dist": mx - 1e-3}); m = build(q)
assert m["summary"]["porta"]["entra"]
# tutto cio' che resta sta dalla parte dell'asse
assert all(pt[0] <= q.porta_dist + 1e-6 for st in m["strata"] for _, f in st["facce"] for pt in f)
# la parete e' la sezione meno il vano (1,6 m2): area dei pezzi + vano = area della sezione convessa
hull = _sezione_verticale([f for st in build(Params(**{**p.__dict__, "porta": False}))["strata"] for _, f in st["facce"]], 0.0, q.porta_dist)
ah = 0.5 * abs(sum(hull[i][0] * hull[(i + 1) % len(hull)][1] - hull[(i + 1) % len(hull)][0] * hull[i][1] for i in range(len(hull))))
assert close(sum(m["summary"]["tappi"].values()) + 0.8 * 2.0, ah, 1e-6), (sum(m["summary"]["tappi"].values()), ah)
# oltre la distanza massima il vano non entra
assert not build(Params(**{**p.__dict__, "porta_dist": mx + 0.05}))["summary"]["porta"]["entra"]
# telaio: 2 stipiti + architrave, volumi TT x TW x lunghezza
tel = porta_telaio(q, 0.02, 0.05)
assert [t["nome"] for t in tel] == ["stipite sinistro", "stipite destro", "architrave"]
assert close(tel[0]["volume"], 0.02 * 2.0 * 0.05) and close(tel[2]["volume"], (0.8 + 0.04) * 0.02 * 0.05)
n += 5
# 9) corridoio: zome intera, scatola con soffitto a due falde tolta dalla porta verso l'esterno
from zome_core import _clip_poly, _corridoio_piani, _dist
NOMI = {"corridoio: parete sinistra", "corridoio: parete destra", "corridoio: falda sinistra", "corridoio: falda destra",
        "corridoio: timpano"}
pc = Params(**{**p.__dict__, "porta_modo": "corridoio", "porta_dist": mx - 1e-3})
mc = build(pc)
m_senza = build(Params(**{**p.__dict__, "porta": False}))
assert mc["summary"]["facce"] <= m_senza["summary"]["facce"] + 12                # niente spigoli finti: pochi pezzi in piu'
box = _corridoio_piani(pc)["scatola"]
def _dentro(poly):
    q = poly
    for n_, d_ in box:
        q, _ = _clip_poly(q, n_, d_)
        if q is None:
            return 0.0
    return _area(q)
orig = sum(_area(f) for st in m_senza["strata"] for _, f in st["facce"])
resta = sum(_area(f) for st in mc["strata"] for _, f in st["facce"])
tolta = sum(_dentro(f) for st in m_senza["strata"] for _, f in st["facce"])
assert tolta > 0 and close(orig - tolta, resta, 1e-6), (orig, tolta, resta)      # area conservata
assert set(mc["caps"]) == NOMI, set(mc["caps"])
assert set(build(__import__("dataclasses").replace(pc, caps=False))["caps"]) == NOMI      # le pareti del corridoio non dipendono da "Chiudi i tagli"
assert close(_area(mc["caps"]["corridoio: parete sinistra"]), _area(mc["caps"]["corridoio: parete destra"]), 1e-6)
assert close(_area(mc["caps"]["corridoio: falda sinistra"]), _area(mc["caps"]["corridoio: falda destra"]), 1e-6)
n += 4
# 10) corridoio col piano della porta fuori dalla zome: le pareti collegano il telaio al profilo d'incontro col guscio
R_ = max(math.hypot(v[0], v[1]) for st in m_senza["strata"] for _, f in st["facce"] for v in f)
pf_ = Params(**{**pc.__dict__, "porta_dist": R_ + 0.3})
mf = build(pf_)
assert mf["params"].porta_fuori and not mc["params"].porta_fuori and mf["summary"]["porta"]["entra"]
assert mf["caps"] and all(k.startswith("corridoio:") for k in mf["caps"]), set(mf["caps"])
assert all(_area(v) > 0 for v in mf["caps"].values())
def _somma(m, chiave):
    return sum(_area(v) for k, v in m["caps"].items() if chiave in k)
assert close(_somma(mf, "sinistra"), _somma(mf, "destra"), 1e-6)
assert all(q[2] > -1e-9 for poly in mf["caps"].values() for q in poly)
# la porta troppo grande per la zome non e' "fuori": non entra
mg = build(Params(**{**pc.__dict__, "porta_dist": R_ + 0.3, "porta_w": 5.0}))
assert not mg["params"].porta_fuori and not mg["summary"]["porta"]["entra"]
# telaio (corridoio): 2 stipiti + architrave, TW verso la parte tolta (fuori: verso la zome)
tc = porta_telaio(mc["params"], 0.02, 0.05)
assert [t_["nome"] for t_ in tc] == ["stipite sinistro", "stipite destro", "architrave"]
tf = porta_telaio(mf["params"], 0.02, 0.05)
assert tf[0]["vertici"][4] != tf[0]["vertici"][0] and close(_dist(tf[0]["vertici"][0], tf[0]["vertici"][4]), 0.05, 1e-9)
n += 6
# anta: 4 pezzi di legno attorno al rombo, vetro di 4 vertici
from zome_core import porta_anta
an = porta_anta(mc["params"])
assert len(an["legno"]) == 4 and all(len(x) == 10 for x in an["legno"]) and len(an["vetro"][0]) == 4 and len(an["maniglia"]) == 6
n += 1
# 11) pavimento: zome posata sul piano z = zfloor, fondazione, travetti, tavolato, risultati
for tipo in ("muretto", "pietroni"):
    pp = Params(N=8, M=7, theta=55, ZH=2.9, cut=2, M2=3, theta2=60, floor=True, zfloor=0.40, pav_tipo=tipo, porta=True,
                porta_modo="corridoio", porta_dist=0.9, porta_h=1.985)
    mp_ = build(pp)
    pv = mp_["pavimento"]
    assert pv and close(pv["zf"], 0.40) and close(pv["z_finito"], 0.39)
    assert min(q[2] for st in mp_["strata"] for _, f in st["facce"] for q in f) >= 0.40 - 1e-6        # la zome sta sopra il piano
    assert mp_["params"].porta_z0 == 0.0 and pv["tavolato"] and len(pv["travetti"]) >= 5 and close(pv["z_finito"], 0.39)
    assert pv["gradino"] and len(pv["pietre"]) >= 8 and len(pv["dormienti"]) == 8 and pv["summary"]["altezza_libera"] > 0.15
    # l'impronta e' tutto il poligono di base: i vertici stanno attorno all'asse, non da una parte sola
    xs_ = [q[0] for q in pv["base"]]; ys_ = [q[1] for q in pv["base"]]
    assert min(xs_) < -1.0 < 1.0 < max(xs_) and min(ys_) < -1.0 < 1.0 < max(ys_) and len(pv["base"]) == 8
    s_ = mp_["summary"]
    assert s_["area_pavimento"] > 0 and s_["area_180"] > 0 and s_["quota_max"] > 3.0 and s_["ingombro_x"] > 3.0
    assert pv["summary"]["travetto_h"] >= 0.10
    # il gradino sta sull'asse della porta (porta verso -Y): x vicino a 0, y negativo e fuori dall'impronta
    gx = sum(q[0] for q in pv["gradino"]["v"]) / len(pv["gradino"]["v"]); gy = sum(q[1] for q in pv["gradino"]["v"]) / len(pv["gradino"]["v"])
    assert abs(gx) < 0.3 and gy < min(ys_) - 0.2, (gx, gy)
    if tipo == "muretto":
        assert len(pv["varchi"]) == 0
n += 2
# 12) il pavimento segue la porta: corridoio con il piano fuori dalla zome -> l'impronta si allunga, varchi perpendicolari alla porta
import math as _m
for tipo in ("muretto", "pietroni"):
    pf_ = Params(N=8, M=7, theta=55, ZH=2.9, cut=2, M2=3, theta2=60, floor=True, zfloor=0.40, pav_tipo=tipo, porta=True,
                 porta_modo="corridoio", porta_dist=2.158, porta_h=1.985)
    mf = build(pf_)
    pv = mf["pavimento"]
    assert mf["params"].porta_fuori and pv["corridoio"] and pv["summary"]["vertici"] == 10, (tipo, pv["summary"]["vertici"])
    ys_ = [q[1] for q in pv["base"]]
    assert min(ys_) < -2.15, min(ys_)                                  # il piano della porta (a -2.158) e' coperto dall'impronta
    assert pv["gradino"] and sum(q[1] for q in pv["gradino"]["v"]) / len(pv["gradino"]["v"]) < min(ys_) - 0.2
    gx = sum(q[0] for q in pv["gradino"]["v"]) / len(pv["gradino"]["v"])
    assert abs(gx) < 0.2
    if tipo == "muretto":
        assert len(pv["varchi"]) == 0
        assert len(pv["pietre"]) >= 60                                  # muro continuo, tante pietre
    else:
        assert len(pv["pietre"]) == 10                                  # un pietrone per vertice, corridoio compreso
# porta a parete: l'impronta e' tagliata dal piano della porta
pw_ = Params(N=8, M=7, theta=55, ZH=2.9, floor=True, zfloor=0.40, porta=True, porta_modo="parete", porta_dist=0.5, porta_h=1.985)
mw = build(pw_)
assert min(q[1] for q in mw["pavimento"]["base"]) >= -0.5 - 1e-6 and max(q[1] for q in mw["pavimento"]["base"]) > 1.0
# 13) cerniere: l'anta aperta di 20 gradi e' l'anta chiusa ruotata di 20 gradi attorno all'asse della cerniera
from zome_core import porta_cerniera
for kw in (dict(porta_modo="parete", porta_dist=0.5), dict(porta_modo="corridoio", porta_dist=3.0, porta_fuori=True, tilt=-3.6, orient=-18.75, pz=0.4)):
    pc = Params(porta=True, porta_dir=0, **kw)
    ce = porta_cerniera(pc)
    P_, a_ = ce["punto"], ce["asse"]
    A0, A20 = porta_anta(pc, apertura=0.0)["legno"][3], porta_anta(pc, apertura=20.0)["legno"][3]
    def _r(q, ang):
        v = [q[i] - P_[i] for i in range(3)]
        d = sum(v[i] * a_[i] for i in range(3))
        cr = (a_[1] * v[2] - a_[2] * v[1], a_[2] * v[0] - a_[0] * v[2], a_[0] * v[1] - a_[1] * v[0])
        return [P_[i] + v[i] * _m.cos(ang) + cr[i] * _m.sin(ang) + a_[i] * d * (1 - _m.cos(ang)) for i in range(3)]
    assert max(_m.dist(_r(q, _m.radians(20)), r) for q, r in zip(A0, A20)) < 1e-9
    assert len(ce["cerniere"]) == 9
# 14) altezza esterna dal pavimento finito (limite dei 3 m): massimo del tetto meno la quota del tavolato, non da terra
mh = build(Params(N=8, M=7, theta=55, ZH=2.9, floor=True, zfloor=0.40))
shell(mh, mh["params"])
sh_ = mh["summary"]
assert close(sh_["altezza_esterna_su_pavimento"], sh_["altezza_esterna"] - sh_["quota_pavimento"], 1e-9)
assert sh_["quota_pavimento"] > 0.3 and sh_["altezza_esterna_su_pavimento"] < sh_["altezza_esterna"]
n += 1
# 15) corridoio col piano della porta che taglia la zome (dentro in basso, fuori in alto): il guscio oltre il piano non copre la porta,
#     pareti = parte fuori (rettangoli meno solido) + sezione della zome oltre il piano
pm = Params(N=10, M=6, theta=44.0, ZH=3.9, porta=True, porta_modo="corridoio", porta_dist=2.0, porta_w=0.8, porta_h=1.7,
            porta_falda=0.1578, floor=True)
mm = build(pm)
assert mm["params"].porta_fuori and mm["summary"]["porta"]["entra"]
assert {"corridoio: parete sinistra (sezione)", "corridoio: parete destra (sezione)"} <= set(mm["caps"]), set(mm["caps"])
assert all(_area(v) > 0 for v in mm["caps"].values())
scat = _corridoio_piani(mm["params"])["scatola"]
dentro_ = [q for st in mm["strata"] for _, f in st["facce"] for q in f
           if all(n_[0] * q[0] + n_[1] * q[1] + n_[2] * q[2] > d_ + 1e-6 for n_, d_ in scat)]
assert not dentro_, len(dentro_)                         # nessun vertice del guscio resta dentro il corridoio
n += 1
# 16) zome coricata: il pavimento taglia a triangoli interi (indice 0..100), mai facce ritagliate dal piano
cnt_ = []
for t_ in (0, 20, 50, 80, 100):
    mt = build(Params(N=10, M=6, theta=44.0, ZH=3.9, tilt=90.0, floor=True, zfloor=0.4, pav_taglio=float(t_)))
    fz_ = [(k_, f_) for st in mt["strata"] for k_, f_ in st["facce"]]
    assert fz_ and all((k_ == "rombo" and len(f_) == 4) or (k_.startswith("triangolo") and len(f_) == 3) for k_, f_ in fz_)
    assert min(q[2] for _, f_ in fz_ for q in f_) >= 0.4 - 1e-6                      # niente sotto il piano del pavimento
    assert abs(min(q[2] for _, f_ in fz_ for q in f_) - 0.4) < 1e-6                  # il piano passa per il vertice piu' basso
    assert "pavimento" not in mt["caps"]                                             # nessun tappo di taglio col piano
    cnt_.append(len(fz_))
assert cnt_[0] == 50 and cnt_ == sorted(cnt_, reverse=True) and cnt_[-1] >= 1, cnt_
ma_ = build(Params(N=10, M=6, theta=44.0, ZH=3.9, tilt=90.0, floor=True, zfloor=0.4, pav_taglio=50.0))
mp_ = build(Params(N=10, M=6, theta=44.0, ZH=3.9, tilt=90.0, floor=True, zfloor=0.4, pz=0.0))
assert ma_["summary"]["area_pavimento"] > 5 and ma_["pavimento"] is not None
n += 1
n += 3
# 17) statica: mensola e pilastro tornano la soluzione nota; il telaio chiude l'equilibrio
import zome_statica
zome_statica.controlla_solutore()
for kw in ({"floor": True, "zfloor": 0.0}, {"tilt": 90.0, "floor": True, "zfloor": 0.4, "pav_taglio": 50.0}):
    ms = build(Params(N=8, M=6, theta=50, ZH=2.5, **kw))
    r = zome_statica.analizza(ms, TT=0.02, TW=0.05, density=700, snow_kN_m2=1.0)
    assert r["ok"], r["testo"]
    atteso = r["peso_N"] + r["neve_N"]
    assert abs(r["reazione_verticale_N"] - atteso) <= 0.02 * max(atteso, 1.0), (r["reazione_verticale_N"], atteso)
    assert r["aste"] > 10 and r["appoggi"] >= 2 and r["spostamento_m"] < 1.0
n += 1
# 18) traverse: tra anelli e sull'anello, anche sui triangoli e con la zome coricata; la statica le include
from zome_core import segmenti_traverse, toggle_traverse, _asse_zome, _dot as _dot_asse, _dist as _dist_t
assert toggle_traverse("", 1, "t") == "1:t"
assert toggle_traverse("1:t", 1, "a") == "1:ta"
assert toggle_traverse("1:ta", 1, "t") == "1:a"
assert toggle_traverse("1:a", 1, "a") == ""
base_t = build(Params(N=8, M=5, theta=50, ZH=2.5))
assert segmenti_traverse(base_t) == []
solo_t = build(Params(N=8, M=5, theta=50, ZH=2.5, traverse="2:t"))
seg_t = segmenti_traverse(solo_t)
assert len(seg_t) == 8 and {s["quale"] for s in seg_t} == {"t"}
entrambe = build(Params(N=8, M=5, theta=50, ZH=2.5, traverse="2:ta"))
seg_ta = segmenti_traverse(entrambe)
assert len(seg_ta) == 16 and {s["quale"] for s in seg_ta} == {"t", "a"}
per_faccia = {}
for s in seg_ta:
    per_faccia.setdefault(s["faccia"], []).append(s)
assert len(per_faccia) == 8
for coppia in per_faccia.values():
    assert len(coppia) == 2 and coppia[0]["extra"] and _dist_t(coppia[0]["extra"][0], coppia[1]["extra"][0]) < 1e-9
tri = build(Params(N=8, M=5, theta=50, ZH=2.5, traverse="4:a"))
assert segmenti_traverse(tri) == []
tri = build(Params(N=8, M=5, theta=50, ZH=2.5, traverse="4:ta"))
seg_tri = segmenti_traverse(tri)
assert len(seg_tri) == 8 and all(s["quale"] == "t" for s in seg_tri)
nodi_t, membri_t, _ = zome_statica._telaio(tri)
for s in seg_tri:
    im = min(range(len(nodi_t)), key=lambda i: _dist_t(nodi_t[i], s["b"]))
    assert _dist_t(nodi_t[im], s["b"]) < 1e-3
    collegati = [b if a == im else a for a, b, _n, _st in membri_t if a == im or b == im]
    assert len(collegati) >= 3
coricata = build(Params(N=8, M=5, theta=50, ZH=2.5, tilt=90, traverse="1:ta"))
asse = _asse_zome(coricata["params"])
seg_c = segmenti_traverse(coricata)
assert len(seg_c) == 16
for s in seg_c:
    salto = abs(_dot_asse(s["a"], asse) - _dot_asse(s["b"], asse))
    if s["quale"] == "a":
        assert salto < 1e-6
    else:
        assert salto > 0.05
b0 = beams(base_t, 0.04, 0.10, triangles=True)
b1 = beams(solo_t, 0.04, 0.10, triangles=True)
assert sum(1 for p in b0 if p.get("ruolo") == "traversa") == 0
assert sum(1 for p in b1 if p.get("ruolo") == "traversa") == 8
assert len(b1) == len(b0) + 8
r0 = zome_statica.analizza(base_t, TT=0.02, TW=0.05, density=700, snow_kN_m2=1.0)
r_ta = zome_statica.analizza(entrambe, TT=0.02, TW=0.05, density=700, snow_kN_m2=1.0)
r_tri = zome_statica.analizza(tri, TT=0.02, TW=0.05, density=700, snow_kN_m2=1.0)
assert r_ta["ok"] and r_tri["ok"], (r_ta.get("testo"), r_tri.get("testo"))
assert r_ta["aste"] == r0["aste"] + 32
assert r_tri["aste"] == r0["aste"] + 16
assert r_ta["peso_N"] > r0["peso_N"] and r_tri["peso_N"] > r0["peso_N"]
for rr in (r_ta, r_tri):
    atteso = rr["peso_N"] + rr["neve_N"]
    assert abs(rr["reazione_verticale_N"] - atteso) <= 0.02 * max(atteso, 1.0)
nodi_x, membri_x, _ = zome_statica._telaio(entrambe)
centro = seg_ta[0]["extra"][0]
ic = min(range(len(nodi_x)), key=lambda i: _dist_t(nodi_x[i], centro))
grado = sum(1 for a, b, _n, _st in membri_x if a == ic or b == ic)
assert grado == 4, grado
n += 1
print("OK", n, "gruppi di prove")
