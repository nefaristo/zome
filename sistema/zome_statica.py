"""Statica del telaio dello scheletro, con Pynite (PyNiteFEA).

Un'asta per spigolo del guscio (rombi e triangoli), più le traverse accese
sullo strato. Nodi che resistono a momento, appoggi a cerniera sui nodi più
bassi. Unità SI: metri, newton, pascal.
Serve a confrontare due pose con la stessa sezione. Non è un calcolo NTC.

Pynite usa Y verso l'alto; il modello della zome usa Z. La conversione è interna.
Sezione: TT nel piano della faccia, TW perpendicolare verso l'esterno.
Il modulo debole è quello nel piano, il forte è quello contro la faccia.
"""

import math

# Legno tipo C24, valori medi (EN 338): confronto, non resistenze di calcolo.
E_PA = 11.0e9
G_PA = 0.69e9
NU = 0.3
G_GRAVITA = 9.81
COMBO = "peso+neve"


def _import_modello():
    try:
        from Pynite import FEModel3D
        return FEModel3D
    except ImportError:
        import site
        import sys
        user = site.getusersitepackages()
        if user and user not in sys.path:
            sys.path.append(user)
        from Pynite import FEModel3D
        return FEModel3D


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n < 1e-15:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _dist(a, b):
    return _norm(_sub(a, b))


def _newell(pts):
    nx = ny = nz = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


def _verso_pynite(p):
    """Blender (X, Y, Z su) -> Pynite (X, Z su, Y)."""
    return (float(p[0]), float(p[2]), float(p[1]))


def _torsione(tt, tw):
    """Momento d'inerzia torsionale di un rettangolo (lato lungo a, lato corto b)."""
    a, b = (tt, tw) if tt >= tw else (tw, tt)
    if a <= 0 or b <= 0:
        return 0.0
    r = b / a
    return a * b ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))


def _locale_z_base(i, j, x):
    """Asse locale z di Pynite prima della rotazione di sezione. i, j, x sono in coordinate Pynite."""
    xi, yi, zi = i
    xj, yj, zj = j
    if math.isclose(xi, xj) and math.isclose(zi, zj):
        return (0.0, 0.0, 1.0)
    if math.isclose(yi, yj):
        return _unit(_cross(x, (0.0, 1.0, 0.0)))
    proj = (xj - xi, 0.0, zj - zi)
    z = _cross(proj, x) if yj > yi else _cross(x, proj)
    return _unit(z)


def _rotazione_sezione(pi, pj, normale):
    """Gradi attorno all'asta affinché l'asse locale z di Pynite segua la normale della faccia."""
    i, j = _verso_pynite(pi), _verso_pynite(pj)
    x = _sub(j, i)
    lunghezza = _norm(x)
    if lunghezza < 1e-9:
        return 0.0
    x = _unit(x)
    n = _verso_pynite(normale)
    n = _sub(n, _scale(x, _dot(n, x)))
    if _norm(n) < 1e-8:
        return 0.0
    n = _unit(n)
    z0 = _locale_z_base(i, j, x)
    if _norm(z0) < 1e-8:
        return 0.0
    return math.degrees(math.atan2(_dot(_cross(z0, n), x), _dot(z0, n)))


def _scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _su_segmento(p, a, b, tol=1e-3):
    """Vero se p sta sull'asta ab, lontano dagli estremi (così un nodo in mezzo la divide)."""
    ab = _sub(b, a)
    lab = _norm(ab)
    if lab < 1e-6:
        return False
    t = _dot(_sub(p, a), ab) / (lab * lab)
    if t <= 1e-3 or t >= 1.0 - 1e-3:
        return False
    return _norm(_cross(ab, _sub(p, a))) / lab <= tol


def _spezza_aste(nodi, membri):
    """Se un nodo cade in mezzo a un'asta, l'asta diventa la catena dei tratti."""
    nuovi = []
    for a, b, normale, strato in membri:
        pa, pb = nodi[a], nodi[b]
        punti = [i for i, p in enumerate(nodi) if i != a and i != b and _su_segmento(p, pa, pb)]
        if not punti:
            nuovi.append((a, b, normale, strato))
            continue
        punti.sort(key=lambda i: _dist(nodi[i], pa))
        catena = [a] + punti + [b]
        for u, v in zip(catena, catena[1:]):
            if u != v and _dist(nodi[u], nodi[v]) >= 1e-3:
                nuovi.append((u, v, normale, strato))
    return nuovi


def _telaio(model):
    """Nodi, aste (i, j, normale media) e neve per nodo, dal guscio già posato."""
    indice = {}
    nodi = []

    def nid(p):
        chiave = tuple(round(float(c), 4) for c in p)
        if chiave not in indice:
            indice[chiave] = len(nodi)
            nodi.append((float(p[0]), float(p[1]), float(p[2])))
        return indice[chiave]

    aste = {}
    neve = {}
    for st in model["strata"]:
        for _tipo, pts in st["facce"]:
            if len(pts) < 3:
                continue
            grezzo = _newell(pts)
            area = 0.5 * _norm(grezzo)
            normale = _unit(grezzo)
            ids = [nid(p) for p in pts]
            for a, b in zip(ids, ids[1:] + ids[:1]):
                if a == b or _dist(nodi[a], nodi[b]) < 1e-3:
                    continue
                chiave = (min(a, b), max(a, b))
                rec = aste.setdefault(chiave, {"normali": [], "strati": []})
                rec["normali"].append(normale)
                rec["strati"].append(st["strato"])
            if area > 1e-8 and normale[2] > 0.0:
                quota = area * normale[2] / len(set(ids))
                for i in set(ids):
                    neve[i] = neve.get(i, 0.0) + quota
    from zome_core import segmenti_traverse
    for seg in segmenti_traverse(model):
        for q in seg.get("extra") or ():
            nid(q)
        ia, ib = nid(seg["a"]), nid(seg["b"])
        if ia == ib or _dist(nodi[ia], nodi[ib]) < 1e-3:
            continue
        chiave = (min(ia, ib), max(ia, ib))
        rec = aste.setdefault(chiave, {"normali": [], "strati": []})
        rec["normali"].append(seg["normale"])
        rec["strati"].append(seg["strato"])
    membri = []
    for (a, b), rec in aste.items():
        somma = (0.0, 0.0, 0.0)
        for n in rec["normali"]:
            somma = _add(somma, n)
        if _norm(somma) < 1e-8:
            somma = rec["normali"][0]
        membri.append((a, b, _unit(somma), min(rec["strati"])))
    return nodi, _spezza_aste(nodi, membri), neve


def _braccio(ids, nodi):
    """Distanza massima dei nodi dalla retta dei due più lontani. Zero se sono allineati."""
    if len(ids) < 2:
        return 0.0
    a = nodi[ids[0]]
    b = nodi[max(ids, key=lambda i: _dist(nodi[i], a))]
    ab = _sub(b, a)
    lab = _norm(ab)
    if lab < 1e-6:
        return 0.0
    return max(_norm(_cross(ab, _sub(nodi[i], a))) / lab for i in ids)


def _appoggi(nodi):
    """Nodi entro 3 cm dal punto più basso: sono quelli che toccano il pavimento."""
    if not nodi:
        return [], 0.03, False
    zmin = min(p[2] for p in nodi)
    fascia = 0.03
    ids = [i for i, p in enumerate(nodi) if p[2] <= zmin + fascia]
    stabile = len(ids) >= 3 and _braccio(ids, nodi) >= 0.15
    return ids, fascia, stabile


def _numero(v):
    if isinstance(v, tuple):
        v = v[0]
    return float(v)


def _da_pynite(v):
    """Pynite (X, Y su, Z) -> Blender (X, Y, Z su)."""
    return (float(v[0]), float(v[2]), float(v[1]))


def _posa(model):
    tilt = abs(float(getattr(model["params"], "tilt", 0.0)))
    if tilt < 5.0:
        return "dritta"
    if abs(tilt - 90.0) < 5.0:
        return "coricata"
    return f"inclinata di {tilt:.0f}°"


def _indice_nodi(nodi):
    return {tuple(round(float(c), 4) for c in p): i for i, p in enumerate(nodi)}


def _riparti(indice, pts, kg, acc):
    """Il peso della faccia va in parti uguali sui vertici del telaio, come la neve."""
    if kg <= 0 or len(pts) < 3:
        return
    ids = []
    for p in pts:
        i = indice.get(tuple(round(float(c), 4) for c in p))
        if i is None:
            return
        ids.append(i)
    quota = kg / len(set(ids))
    for i in set(ids):
        acc[i] = acc.get(i, 0.0) + quota


def _luce_faccia(pts):
    area = 0.5 * _norm(_newell(pts))
    if area < 1e-8:
        return 0.0
    lati = [_dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    lati = [lato for lato in lati if lato > 1e-6]
    if not lati:
        return 0.0
    return min(2.0 * area / lato for lato in lati)


def _tilt_faccia(pts):
    n = _unit(_newell(pts))
    return math.degrees(math.acos(min(1.0, abs(n[2]))))


def _peso_rivestimenti(model, nodi, pelli):
    """Chilogrammi di esterno, interno, copertura, vetro e isolante, e la quota su ogni nodo.

    Senza `pelli` non si aggiunge nulla: il telaio resta col solo peso proprio e la neve.
    L'isolante del pavimento non è qui: non poggia su queste aste.
    """
    vuoto = {"esterno": 0.0, "interno": 0.0, "copertura": 0.0, "vetro": 0.0, "isolante": 0.0}
    if not pelli:
        return vuoto, {}
    indice = _indice_nodi(nodi)
    facce = {}
    for st in model.get("strata") or []:
        for fi, (_kind, pts) in enumerate(st["facce"]):
            facce[(st["strato"], fi)] = pts
    acc = {}
    kg = dict(vuoto)
    dens_est = pelli.get("esterno")
    dens_int = pelli.get("interno")
    dens_tetto = pelli.get("tetto")
    tetto_mm = pelli.get("tetto_mm")
    for d in model.get("esterno") or []:
        pts = facce.get((d.get("strato"), d.get("faccia")))
        if not pts:
            continue
        chiave = d.get("chiave")
        if chiave == "wood_external" and dens_est and d.get("volume_copertura"):
            m = d["volume_copertura"] * float(dens_est)
            kg["esterno"] += m
            _riparti(indice, pts, m, acc)
        elif chiave == "roof_external" and dens_tetto and d.get("volume_copertura"):
            mm = float(d.get("spessore") or 0.0) * 1000.0
            if tetto_mm is None or abs(mm - float(tetto_mm)) <= 2.0:
                m = d["volume_copertura"] * float(dens_tetto)
                kg["copertura"] += m
                _riparti(indice, pts, m, acc)
        elif chiave == "glass_external" and d.get("area_copertura"):
            grande = (_luce_faccia(pts) >= float(pelli.get("luce_grande") or 0.90)
                      and _tilt_faccia(pts) <= float(pelli.get("tilt_neve") or 55.0))
            al_mq = pelli.get("vetro_grande_kg_m2") if grande else pelli.get("vetro_kg_m2")
            if al_mq:
                m = d["area_copertura"] * float(al_mq)
                kg["vetro"] += m
                _riparti(indice, pts, m, acc)
        if dens_int and d.get("volume_rivest_int"):
            m = d["volume_rivest_int"] * float(dens_int)
            kg["interno"] += m
            _riparti(indice, pts, m, acc)
    dens_iso = pelli.get("isolante")
    if dens_iso:
        for sl in model.get("isolante") or []:
            pts = facce.get((sl.get("strato"), sl.get("faccia")))
            if not pts:
                continue
            m = float(sl.get("area") or 0.0) * float(sl.get("spessore") or 0.0) * float(dens_iso)
            kg["isolante"] += m
            _riparti(indice, pts, m, acc)
    return kg, acc


def _righe_pelli(kg):
    righe = []
    for chiave, nome in (("esterno", "Esterno"), ("interno", "Interno"), ("copertura", "Copertura"),
                         ("vetro", "Vetrocamera"), ("isolante", "Isolante")):
        m = kg.get(chiave) or 0.0
        if m <= 0:
            continue
        righe.append(f"{nome} {m * G_GRAVITA / 1000:.2f} kN ({m:.0f} kg)")
    return righe


def analizza(model, TT, TW, density=700.0, snow_kN_m2=1.0, pelli=None):
    """Ritorna un dizionario con il testo del rapporto e i totali in newton."""
    if TT <= 0 or TW <= 0:
        return {"ok": False, "testo": "TT e TW devono essere positivi."}
    try:
        FEModel3D = _import_modello()
    except ImportError as e:
        return {"ok": False, "testo": "Manca Pynite nel Python di Blender: " + str(e)}

    from zome_core import segmenti_traverse
    segmenti = segmenti_traverse(model)
    n_tra = sum(1 for s in segmenti if s["quale"] == "t")
    n_anello = sum(1 for s in segmenti if s["quale"] == "a")
    nodi, membri, neve_area = _telaio(model)
    if len(membri) < 3:
        return {"ok": False, "testo": "Troppe poche aste: il guscio è vuoto o i tagli l'hanno tolto."}
    appoggi, fascia, appoggio_stabile = _appoggi(nodi)
    if len(appoggi) < 1:
        return {"ok": False, "testo": "Nessun nodo a terra: non c'è un appoggio."}

    A = TT * TW
    # Iy: inflessione lungo la normale (fuori dal piano della faccia), braccio TW.
    # Iz: inflessione nel piano della faccia, braccio TT.
    iy = TT * TW ** 3 / 12.0
    iz = TW * TT ** 3 / 12.0
    j = _torsione(TT, TW)

    fem = FEModel3D()
    fem.add_material("legno", E_PA, G_PA, NU, float(density))
    fem.add_section("asse", A, iy, iz, j)
    for i, p in enumerate(nodi):
        x, y, z = _verso_pynite(p)
        fem.add_node(f"N{i}", x, y, z)
    for k, (a, b, normale, _strato) in enumerate(membri):
        rot = _rotazione_sezione(nodi[a], nodi[b], normale)
        fem.add_member(f"M{k}", f"N{a}", f"N{b}", "legno", "asse", rotation=rot)
    # Cerniera se i nodi a terra formano una base. Se sono uno o due, sulla stessa retta,
    # il telaio girerebbe: quei nodi si incastrano, senza inchiodare al suolo i nodi più alti.
    incastro = not appoggio_stabile
    for i in appoggi:
        fem.def_support(f"N{i}", True, True, True, incastro, incastro, incastro)

    fem.add_member_self_weight("FY", -G_GRAVITA, case="Case 1")
    neve_n = 0.0
    q = float(snow_kN_m2) * 1000.0
    for i, area in neve_area.items():
        forza = -q * area
        if forza == 0.0:
            continue
        fem.add_node_load(f"N{i}", "FY", forza, case="Case 1")
        neve_n += -forza
    pelli_kg, pelli_nodi = _peso_rivestimenti(model, nodi, pelli)
    pelli_n = 0.0
    for i, kg in pelli_nodi.items():
        forza = -kg * G_GRAVITA
        if forza == 0.0:
            continue
        fem.add_node_load(f"N{i}", "FY", forza, case="Case 1")
        pelli_n += -forza
    fem.add_load_combo(COMBO, {"Case 1": 1.0})

    try:
        try:
            fem.analyze(check_stability=True, sparse=True)
        except ImportError:
            fem.analyze(check_stability=True, sparse=False)
    except Exception as e:
        testo = str(e)
        if any(parola in testo.lower() for parola in ("singular", "stabil", "instab", "mechanism")):
            testo = ("Il telaio non è stabile con questi appoggi: i nodi a terra sono troppo pochi "
                     "o stanno sulla stessa retta. Alza il taglio del pavimento o chiudi di più la base.")
        else:
            testo = "Analisi non riuscita: " + testo
        return {"ok": False, "testo": testo, "nodi": len(nodi), "aste": len(membri), "appoggi": len(appoggi)}

    lunghezze = [_dist(nodi[a], nodi[b]) for a, b, _n, _s in membri]
    peso_n = float(density) * A * sum(lunghezze) * G_GRAVITA
    reazione_z = 0.0
    spinta_max = 0.0
    reazioni = []
    for i in appoggi:
        nodo = fem.nodes[f"N{i}"]
        reazione_z += _numero(nodo.RxnFY[COMBO])
        fx = _numero(nodo.RxnFX[COMBO])
        fz = _numero(nodo.RxnFZ[COMBO])
        spinta_max = max(spinta_max, math.hypot(fx, fz))
        reazioni.append({"p": nodi[i], "R": _da_pynite((fx, _numero(nodo.RxnFY[COMBO]), fz))})

    spost_max = 0.0
    spost_vert = 0.0
    for nodo in fem.nodes.values():
        dx, dy, dz = (_numero(nodo.DX[COMBO]), _numero(nodo.DY[COMBO]), _numero(nodo.DZ[COMBO]))
        spost_max = max(spost_max, math.sqrt(dx * dx + dy * dy + dz * dz))
        spost_vert = max(spost_vert, abs(dy))

    aste_out = []
    compr_max = traz_max = mom_max = 0.0
    for k, (a, b, normale, strato) in enumerate(membri):
        mem = fem.members[f"M{k}"]
        nmin = _numero(mem.min_axial(COMBO))
        nmax = _numero(mem.max_axial(COMBO))
        # Pynite 3: sforzo normale positivo = compressione (verificato su un pilastro).
        compr = max(0.0, nmax)
        traz = max(0.0, -nmin)
        my_max = _numero(mem.max_moment("My", COMBO))
        my_min = _numero(mem.min_moment("My", COMBO))
        mz_max = _numero(mem.max_moment("Mz", COMBO))
        mz_min = _numero(mem.min_moment("Mz", COMBO))
        My = my_max if abs(my_max) >= abs(my_min) else my_min
        Mz = mz_max if abs(mz_max) >= abs(mz_min) else mz_min
        my, mz = abs(My), abs(Mz)
        mom = max(my, mz)
        # My piega fuori dal piano della faccia (costa TW); Mz piega nel piano (costa TT).
        # Il vettore è l'asse di rotazione, con il segno: il piano in cui l'asta ruota gli è perpendicolare.
        fuori = my >= mz
        segno = (1.0 if My >= 0.0 else -1.0) if fuori else (1.0 if Mz >= 0.0 else -1.0)
        sigma_m = (my * (TW / 2.0) / iy if fuori else mz * (TT / 2.0) / iz) / 1e6 if (iy and iz) else 0.0
        T = mem.T()
        riga = 1 if fuori else 2
        grezzo = _da_pynite((T[riga, 0], T[riga, 1], T[riga, 2]))
        asse = tuple(segno * c for c in grezzo)
        compr_max = max(compr_max, compr)
        traz_max = max(traz_max, traz)
        mom_max = max(mom_max, mom)
        aste_out.append({
            "n": k, "strato": strato, "lung": lunghezze[k],
            "a": nodi[a], "b": nodi[b],
            "N": compr if compr >= traz else -traz,
            "compr": compr, "traz": traz, "mom": mom,
            "piega": "fuori piano" if fuori else "nel piano",
            "sigma_m": sigma_m, "asse": asse, "normale": normale,
        })

    equilibrio = abs(reazione_z - peso_n - neve_n - pelli_n)
    atteso = max(peso_n + neve_n + pelli_n, 1.0)
    sigma_c = (compr_max / A / 1e6) if A else 0.0
    piegata = max(aste_out, key=lambda t: t["mom"])
    linee = [
        f"Statica del telaio — posa {_posa(model)}",
        "Confronto, non è un calcolo NTC. 1 kN ≈ 102 kg.",
        (f"Nodi {len(nodi)} (punti), aste {len(membri)} (spigoli e traverse)" if (n_tra or n_anello)
         else f"Nodi {len(nodi)} (punti), aste {len(membri)} (una per spigolo)"),
        f"A terra {len(appoggi)} " + ("cerniere: ferme, ma possono ruotare" if not incastro else "incastri: fermi e non ruotano"),
        f"Sono i nodi entro {fascia*100:.0f} cm dal punto più basso",
        f"Tavola larga {TT*100:.1f} cm nella faccia del rombo, spessa {TW*100:.1f} cm verso l'esterno",
        f"Peso del telaio {peso_n/1000:.2f} kN ({peso_n/9.81:.0f} kg)",
        *_righe_pelli(pelli_kg),
        f"Neve {neve_n/1000:.2f} kN ({neve_n/9.81:.0f} kg)",
        *([f"Traverse: {n_tra} tra anelli, {n_anello} sull'anello. Stessa sezione delle altre aste; all'incrocio si uniscono."]
          if (n_tra or n_anello) else []),
        f"La zome si abbassa al massimo di {spost_vert*1000:.1f} mm",
        f"Spinta di lato massima su un appoggio: {spinta_max/1000:.2f} kN ({spinta_max/9.81:.0f} kg)",
        f"Compressione max {compr_max/1000:.2f} kN = {sigma_c:.1f} MPa (il legno ne regge ~20)",
        f"Trazione max {traz_max/1000:.2f} kN",
        f"Momento max {mom_max/1000:.3f} kN·m sull'asta n°{piegata['n']}, lunga {piegata['lung']*100:.0f} cm",
        f"  picco al giunto, piega {piegata['piega']}: circa {piegata['sigma_m']:.0f} MPa (C24 ~24)",
        "n° è l'ordine nel calcolo, non un pezzo della lista tagli.",
        "Colore e lunghezza: posto in questa prova. Il massimo copre tutta l'asta.",
        "Il rosso non è una rottura: la soglia del materiale si userà dopo, e allora il colore seguirà quella.",
        "Frecce verso l'interno = compressa; verso l'esterno = tesa.",
        "Frecce gialle ai piedi = spinta del terreno.",
    ]
    if equilibrio > 0.05 * atteso:
        linee.append(f"Attenzione: l'equilibrio verticale non chiude ({equilibrio/1000:.2f} kN)")
    if spost_max > 0.05:
        linee.append("Oltre 5 cm: il calcolo lineare serve al confronto, non a prevedere la forma.")
    linee.append("Aste più compresse:")
    for t in sorted(aste_out, key=lambda s: -s["compr"])[:3]:
        sig = t["compr"] / A / 1e6 if A else 0.0
        linee.append(f"  n°{t['n']} strato {t['strato']} · {t['lung']*100:.0f} cm · {t['compr']/1000:.2f} kN ({sig:.1f} MPa)")
    linee.append("Aste più piegate:")
    for t in sorted(aste_out, key=lambda s: -s["mom"])[:3]:
        linee.append(f"  n°{t['n']} strato {t['strato']} · {t['lung']*100:.0f} cm · {t['mom']/1000:.3f} kN·m · {t['piega']}")

    return {
        "ok": True,
        "testo": "\n".join(linee),
        "nodi": len(nodi),
        "aste": len(membri),
        "appoggi": len(appoggi),
        "peso_N": peso_n,
        "neve_N": neve_n,
        "pelli_N": pelli_n,
        "pelli_kg": pelli_kg,
        "reazione_verticale_N": reazione_z,
        "spinta_massima_N": spinta_max,
        "spostamento_m": spost_max,
        "compressione_N": compr_max,
        "trazione_N": traz_max,
        "momento_Nm": mom_max,
        "aste_viste": aste_out,
        "reazioni": reazioni,
    }


def controlla_solutore():
    """Mensola e pilastro con la soluzione nota, più l'orientamento della sezione."""
    FEModel3D = _import_modello()
    m = FEModel3D()
    m.add_node("A", 0, 0, 0)
    m.add_node("B", 2, 0, 0)
    m.add_material("t", 10e9, 4e9, 0.3, 500)
    m.add_section("s", 0.01, 1e-4, 1e-6, 1e-6)
    m.add_member("M", "A", "B", "t", "s")
    m.def_support("A", True, True, True, True, True, True)
    m.add_node_load("B", "FY", -1000.0)
    m.add_load_combo("c", {"Case 1": 1.0})
    m.analyze(check_stability=True, sparse=False)
    atteso = -1000.0 * 8.0 / (3.0 * 10e9 * 1e-6)
    if abs(m.nodes["B"].DY["c"] - atteso) > 1e-9:
        raise AssertionError("la mensola non torna la freccia PL^3/3EI")
    if abs(_numero(m.members["M"].max_moment("Mz", "c")) - 2000.0) > 1e-6:
        raise AssertionError("il momento d'incastro della mensola non è PL")

    c = FEModel3D()
    c.add_node("A", 0, 0, 0)
    c.add_node("B", 0, 2, 0)
    c.add_material("t", 10e9, 4e9, 0.3, 500)
    c.add_section("s", 0.01, 1e-6, 1e-6, 1e-6)
    c.add_member("M", "A", "B", "t", "s")
    c.def_support("A", True, True, True, True, True, True)
    c.add_node_load("B", "FY", -1000.0)
    c.add_load_combo("c", {"Case 1": 1.0})
    c.analyze(check_stability=True, sparse=False)
    if abs(_numero(c.members["M"].max_axial("c")) - 1000.0) > 1e-4:
        raise AssertionError("la compressione non è lo sforzo normale positivo")

    r = FEModel3D()
    r.add_node("A", 0, 0, 0)
    r.add_node("B", 1, 0, 0)
    r.add_material("t", 10e9, 4e9, 0.3, 500)
    r.add_section("s", 0.01, 1e-6, 1e-6, 1e-6)
    normale = (0.0, 0.6, 0.8)  # già in Blender: Z su. In Pynite diventa (0, 0.8, 0.6)
    rot = _rotazione_sezione((0, 0, 0), (1, 0, 0), normale)
    r.add_member("M", "A", "B", "t", "s", rotation=rot)
    asse = r.members["M"].T()[2, 0:3]
    voluto = _unit(_verso_pynite(normale))
    if _dist(tuple(float(x) for x in asse), voluto) > 1e-6:
        raise AssertionError(f"l'asse della sezione non segue la faccia: {asse} vs {voluto}")


if __name__ == "__main__":
    controlla_solutore()
    print("solutore ok")
    from zome_core import Params, build
    base = dict(N=8, M=7, theta=55, ZH=2.9, cut=2, M2=3, theta2=60, floor=True, zfloor=0.4)
    for nome, extra in (("dritta", {}), ("coricata", {"tilt": 90.0, "pav_taglio": 50.0})):
        modello = build(Params(**base, **extra))
        esito = analizza(modello, TT=0.02, TW=0.05, density=700, snow_kN_m2=1.0)
        print("---", nome, "---")
        print(esito["testo"])
