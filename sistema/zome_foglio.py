"""Foglio tecnico di una zome: riepilogo, strati, pezzi disegnati, preventivo di sola materia prima.

Il file è HTML, così pianta e laterale di ogni pezzo sono disegni veri (SVG) e il foglio
si apre nel browser. I prezzi vengono da Riferimenti/proprieta_materiali.xlsx: una cella
vuota non diventa un numero. Le quattro voci (esterno, perline, vetrocamera, travi e
travetti) si possono spegnere una per una.
"""
import cmath
import html
import math
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

from zome_core import (_area, _dist, _dot, _face_normal, _sub, beams, chiave_taglio,
                       porta_anta, porta_telaio)

LUCE_GRANDE = 0.90     # m: la riga da 150 €/m² scatta verso 90 cm–1 m di luce libera
TILT_NEVE = 55.0       # gradi sull'orizzontale: a 60° la neve scivola, sotto si considera che resti
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _n(x, cifre=2):
    """Numero in italiano, con la virgola."""
    s = f"{x:,.{cifre}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _euro(x):
    return _n(x, 2)


def _esc(s):
    return html.escape(str(s), quote=True)


def _unita(a):
    L = math.sqrt(_dot(a, a))
    return (a[0] / L, a[1] / L, a[2] / L) if L else (1.0, 0.0, 0.0)


def _croce(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


# --- prezzi ---------------------------------------------------------------------------------------------------------
def _col(cella):
    lettere = "".join(ch for ch in cella if ch.isalpha())
    n = 0
    for ch in lettere:
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


def _xml(z, nome):
    return ET.fromstring(z.read(nome))


def carica_prezzi(percorso):
    """Righe del foglio Materiali, per nome. Non calcola un prezzo che la cella non ha."""
    with zipfile.ZipFile(percorso) as z:
        nomi = z.namelist()
        strings = []
        if "xl/sharedStrings.xml" in nomi:
            root = _xml(z, "xl/sharedStrings.xml")
            for si in root.findall("m:si", NS):
                strings.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        libro = _xml(z, "xl/workbook.xml")
        fogli = {sh.attrib["name"]: sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                 for sh in libro.findall("m:sheets/m:sheet", NS)}
        rel = _xml(z, "xl/_rels/workbook.xml.rels")
        bersaglio = {}
        for r in rel:
            t = r.attrib["Target"].lstrip("/")
            bersaglio[r.attrib["Id"]] = t if t.startswith("xl/") else "xl/" + t
        foglio = _xml(z, bersaglio[fogli["Materiali"]])
    righe = []
    for row in foglio.findall("m:sheetData/m:row", NS):
        celle = {}
        for c in row.findall("m:c", NS):
            if c.attrib.get("t") == "inlineStr":
                testi = [t.text or "" for t in c.findall(".//m:t", NS)]
                if testi:
                    celle[_col(c.attrib["r"])] = "".join(testi)
                continue
            v = c.find("m:v", NS)
            if v is None or v.text is None:
                continue
            if c.attrib.get("t") == "s":
                celle[_col(c.attrib["r"])] = strings[int(v.text)]
            else:
                try:
                    celle[_col(c.attrib["r"])] = float(v.text)
                except ValueError:
                    celle[_col(c.attrib["r"])] = v.text
        if celle:
            righe.append(celle)
    testata = righe[0]
    i_cat = next(i for i, v in testata.items() if v == "Categoria")
    i_nome = next(i for i, v in testata.items() if v == "Materiale")
    i_prezzo = next(i for i, v in testata.items() if v == "Prezzo del solo materiale")
    i_unita = next(i for i, v in testata.items() if v == "Unità del prezzo")
    i_spess = next(i for i, v in testata.items() if v == "Spessore del prezzo (mm)")
    i_nota = next(i for i, v in testata.items() if v == "Nota sul prezzo")
    i_dens = next(i for i, v in testata.items() if v == "Peso specifico (kg/m³)")
    i_lam = next(i for i, v in testata.items() if str(v).startswith("Conducibilità"))
    i_cal = next(i for i, v in testata.items() if str(v).startswith("Calore specifico"))
    out = {}
    for r in righe[1:]:
        nome = r.get(i_nome)
        if not nome or i_prezzo not in r:
            continue
        out[nome] = {"nome": nome, "prezzo": float(r[i_prezzo]), "unita": r.get(i_unita, ""),
                     "spessore_mm": r.get(i_spess), "densita": r.get(i_dens), "nota": r.get(i_nota, "") or "",
                     "categoria": r.get(i_cat, ""), "lambda": r.get(i_lam), "calore": r.get(i_cal)}
    return out


def elenco_isolanti(prezzi):
    """Voci della categoria isolanti che hanno un prezzo.

    L'identificatore è un codice senza punti né spazi: Blender non accetta altro in un menu.
    Il nome visibile è quello della riga.
    """
    voci, visti = [], set()
    for nome, r in (prezzi or {}).items():
        if r.get("categoria") != "B - Isolanti" or r.get("prezzo") is None:
            continue
        ident = "".join(ch if ch.isalnum() else "_" for ch in nome).strip("_")[:60] or "isolante"
        while "__" in ident:
            ident = ident.replace("__", "_")
        base, n = ident, 2
        while ident in visti:
            ident = f"{base[:56]}_{n}"
            n += 1
        visti.add(ident)
        sp = r.get("spessore_mm")
        unita = r.get("unita") or ""
        dettaglio = f"{r['prezzo']:.2f} {unita}"
        if sp:
            dettaglio += f", pacco {float(sp):.0f} mm"
        voci.append((ident, nome, dettaglio))
    voci.sort(key=lambda t: (t[0] != "Canapa", t[1].lower()))
    return voci or [("Canapa", "Canapa", "")]


NOMI = {
    "c24": "Abete o pino da costruzione, classe C24 (tavole e morali)",
    "perline": "Perline di abete per interno, piallate e maschiate",
    "tavole": "Tavole di abete grezze per rivestimento esterno",
    "tegole": "Tegole bituminose (canadesi)",
    "vetro": "Vetro",
    "vetro_grande": "Vetrocamera da copertura, luci maggiori",
}


def prezzo_spessore(riga, mm):
    """Prezzo della cella se lo spessore coincide. Altrimenti un prezzo scritto nella nota per quello spessore.
    Ritorna (euro o None, avviso)."""
    if riga is None:
        return None, "Manca la riga nel foglio materiali."
    cella = riga["spessore_mm"]
    if cella is None or mm is None:
        return riga["prezzo"], ""
    scarto = abs(float(cella) - mm)
    if scarto <= 0.6:
        return riga["prezzo"], ""
    if scarto <= 2.0:
        return riga["prezzo"], (f"Il modello è {mm:.0f} mm, la cella è il prodotto da {float(cella):.0f} mm "
                                f"a {_euro(riga['prezzo'])} €. Per questo conto ho usato quel prezzo.")
    mm_i = int(round(mm))
    trovati = re.findall(rf"{mm_i}\s*mm.{{0,70}}?(\d+[.,]\d+)", riga["nota"])
    if trovati:
        val = float(trovati[0].replace(",", "."))
        return val, (f"La cella è {float(cella):.0f} mm a {_euro(riga['prezzo'])} €; "
                     f"per {mm_i} mm la nota del foglio indica {_euro(val)} €.")
    return None, (f"Nessun prezzo per {mm_i} mm: la cella è il prodotto da {float(cella):.0f} mm "
                  f"a {_euro(riga['prezzo'])} €.")


# Lastre di vetro nel pacchetto, senza la camera: stella 6 mm + 44.2 (due da 4 mm);
# luci maggiori 8 mm + 55.2 (due da 5 mm). Il 66.2 sarebbe due da 6 mm.
_VETRO_MM = {"vetro": 14.0, "vetro_grande": 18.0}
_ETICHETTE = {"travi": "Travi e travetti", "esterno": "Esterno", "perline": "Perline", "vetro": "Vetrocamera"}
_COLORI = {"travi": "#6b4f3a", "esterno": "#8d8474", "perline": "#c4b49a", "vetro": "#6d8a96"}


def peso_di(chiave, qta, unita, mm, riga, dens_vetro):
    """Chilogrammi e la frase che dice da dove vengono. None se il foglio non ha una massa per quella voce."""
    if riga is None:
        return None, ""
    if chiave in _VETRO_MM:
        if not dens_vetro:
            return None, ""
        mmv = _VETRO_MM[chiave]
        return qta * mmv / 1000.0 * dens_vetro, f"lastre {mmv:.0f} mm × {dens_vetro:.0f} kg/m³, la camera non pesa"
    dens = riga.get("densita")
    if not dens:
        return None, ""
    dens = float(dens)
    if unita == "m³":
        return qta * dens, f"{dens:.0f} kg/m³"
    if chiave == "tegole":
        sp = riga.get("spessore_mm")
        if sp and mm is not None and abs(float(sp) - mm) <= 2.0:
            return qta * float(sp) / 1000.0 * dens, f"{dens:.0f} kg/m³ × {float(sp):.0f} mm"
        return None, "lo spessore disegnato non è quello delle tegole"
    if unita == "m²" and mm:
        return qta * mm / 1000.0 * dens, f"{dens:.0f} kg/m³ × {mm:.0f} mm"
    return None, ""


def _iva(chiave, dalla_nota):
    if dalla_nota:
        return "non dichiarata"
    return {"c24": "esclusa", "perline": "inclusa", "tavole": "da ricontrollare",
            "tegole": "inclusa", "vetro": "non dichiarata", "vetro_grande": "non dichiarata"}.get(chiave, "non dichiarata")


# --- geometria dei disegni ------------------------------------------------------------------------------------------
def _pianta(vertici):
    """Quattro punti del pezzo nel piano della faccia, in metri: (x lungo il bordo, y verso l'interno)."""
    o0, o1, i1, i0 = vertici[:4]
    asse = _unita(_sub(o1, o0))
    normale = _unita(_sub(vertici[4], o0))
    lato = _unita(_croce(normale, asse))
    if _dot(_sub(i0, o0), lato) < 0:
        lato = (-lato[0], -lato[1], -lato[2])

    def xy(q):
        d = _sub(q, o0)
        return (_dot(d, asse), _dot(d, lato))

    def xz(q):
        d = _sub(q, o0)
        return (_dot(d, asse), _dot(d, normale))

    return [xy(q) for q in (o0, o1, i1, i0)], [xz(q) for q in vertici]


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


def _leggibile(pts, quota=0.32):
    """Allarga la quota corta: un'asse di 75 cm per 3 cm, in scala, è una riga e gli angoli non si leggono.
    I numeri scritti accanto restano quelli veri."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    if dx < 1e-9 or dy < 1e-9 or dy / dx >= quota:
        return pts
    k = quota * dx / dy
    medio = (min(ys) + max(ys)) / 2
    return [(x, medio + (y - medio) * k) for x, y in pts]


def _scala(pts, w, h, bordo=16):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    dx, dy = max(maxx - minx, 1e-6), max(maxy - miny, 1e-6)
    s = min((w - 2 * bordo) / dx, (h - 2 * bordo) / dy)

    def m(p):
        return (bordo + (p[0] - minx) * s, h - bordo - (p[1] - miny) * s)

    return m, s


def _poligono(pts, w, h, etichette):
    """SVG di un poligono. etichette: (testo, indice del lato), scritta a metà di quel lato."""
    mappa, _s = _scala(pts, w, h)
    q = [mappa(p) for p in pts]
    punti = " ".join(f"{x:.1f},{y:.1f}" for x, y in q)
    n = len(q)
    testi = []
    for testo, lato in etichette:
        a, b = q[lato % n], q[(lato + 1) % n]
        testi.append(f'<text x="{(a[0]+b[0])/2:.1f}" y="{(a[1]+b[1])/2:.1f}">{_esc(testo)}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<polygon points="{punti}"/>{"".join(testi)}</svg>')


def svg_pezzo(beam):
    """Pianta (nel piano della faccia, con gli angoli di testa) e laterale (spessore, teste a squadra)."""
    pianta, lato = _pianta(beam["vertici"])
    def _lung(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])
    piano = _poligono(_leggibile(pianta), 220, 92, [
        (f'{_n(_lung(pianta[0], pianta[1]) * 100, 1)} cm', 0),
        (f'{beam["taglio_fine"]:.0f}°', 1),
        (f'{_n(_lung(pianta[2], pianta[3]) * 100, 1)} cm', 2),
        (f'{beam["taglio_inizio"]:.0f}°', 3)])
    inv = _inviluppo(lato)
    alto = max(p[1] for p in inv) * 100
    lato_svg = _poligono(_leggibile(inv), 220, 64, [(f'{_n(beam["lung_max"] * 100, 1)} cm', 0),
                                         (f'{_n(alto, 1)} cm', 1), ("90°", 3)])
    return piano, lato_svg


def _nel_piano(pts):
    o = pts[0]
    asse = _unita(_sub(pts[1], o))
    nrm = _face_normal(pts)
    lato = _unita(_croce(nrm, asse))
    return [(_dot(_sub(q, o), asse), _dot(_sub(q, o), lato)) for q in pts]


def svg_faccia(pts, tilt):
    """Forma vera della faccia, e il profilo di lato con l'angolo sull'orizzontale."""
    p2 = _nel_piano(pts)
    lati = [_dist(pts[i], pts[(i + 1) % len(pts)]) * 100 for i in range(len(pts))]
    piano = _poligono(p2, 200, 120, [(f"{_n(L, 1)}", i) for i, L in enumerate(lati)])
    # laterale: un rettangolo lungo il lato maggiore, alto lo spessore non c'è; si disegna la corda inclinata
    L = max(lati) / 100.0
    a = math.radians(tilt)
    profilo = [(0, 0), (L * math.cos(a), L * math.sin(a))]
    mappa, _s = _scala(profilo + [(0, 0), (L, 0)], 200, 70, 18)
    axy, bxy = mappa(profilo[0]), mappa(profilo[1])
    base = mappa((L, 0))
    orig = mappa((0, 0))
    lato = (f'<svg viewBox="0 0 200 70" width="200" height="70">'
            f'<line x1="{orig[0]:.1f}" y1="{orig[1]:.1f}" x2="{base[0]:.1f}" y2="{base[1]:.1f}"/>'
            f'<line x1="{axy[0]:.1f}" y1="{axy[1]:.1f}" x2="{bxy[0]:.1f}" y2="{bxy[1]:.1f}"/>'
            f'<text x="{(axy[0]+bxy[0])/2:.1f}" y="{(axy[1]+bxy[1])/2 - 4:.1f}">{tilt:.0f}°</text></svg>')
    return piano, lato


def svg_profilo(model, w=280, h=170):
    """Silhouette lungo l'asse della zome, prima della posa: raggio a destra e a sinistra, quota in su."""
    punti = []
    for _nome, anelli in model["parts"].items():
        for ring in anelli:
            r = math.hypot(ring[0][0], ring[0][1])
            punti.append((r, ring[0][2]))
    if not punti:
        return ""
    usati = []
    for r, z in punti:
        if not any(abs(r - a) < 1e-4 and abs(z - b) < 1e-4 for a, b in usati):
            usati.append((r, z))
    usati.sort(key=lambda q: q[1])
    poly = [(-r, z) for r, z in usati] + [(r, z) for r, z in reversed(usati)]
    return _poligono(poly, w, h, [])


def _altitudini(pts):
    """Luce fra i bordi: sui rombi la distanza fra i lati opposti, sui triangoli le altezze."""
    n = len(pts)
    if n == 4:
        out = []
        for i, j in ((0, 2), (1, 3)):
            a, b = pts[i], pts[(i + 1) % n]
            bordo = _sub(b, a)
            L = math.sqrt(_dot(bordo, bordo)) or 1e-9
            meta = ((pts[j][0] + pts[(j + 1) % n][0]) / 2, (pts[j][1] + pts[(j + 1) % n][1]) / 2,
                    (pts[j][2] + pts[(j + 1) % n][2]) / 2)
            out.append(math.sqrt(_dot(_croce(_sub(meta, a), bordo), _croce(_sub(meta, a), bordo))) / L)
        return out
    if n == 3:
        area = _area(pts)
        return [2 * area / _dist(pts[i], pts[(i + 1) % 3]) for i in range(3)]
    return []


def scegli_vetro(luce_libera, tilt):
    """Chiave del prezzo. La riga grossa solo se la luce arriva verso 90 cm e la faccia tiene la neve."""
    if luce_libera >= LUCE_GRANDE and tilt <= TILT_NEVE:
        return "vetro_grande"
    return "vetro"


def _pts(model, strato, faccia):
    for st in model["strata"]:
        if st["strato"] == strato and faccia < len(st["facce"]):
            return st["facce"][faccia][1]
    return None


def _nome_pezzo(b):
    if b.get("ruolo") == "traversa":
        return "traversa tra anelli" if b["tipo"] == "tra_anelli" else "traversa sull'anello"
    return "bordo del rombo" if b["tipo"] == "rombo" else "bordo del triangolo"


def _volume_anta(p, TT):
    an = porta_anta(p, TT, apertura=0.0)
    vol = 0.0
    for prism in an["legno"]:
        n = len(prism) // 2
        basso = prism[:n]
        nrm = _face_normal(basso)
        vol += _area(basso) * abs(_dot(_sub(prism[n], basso[0]), nrm))
    area_vetro = _area(an["vetro"][0])
    return vol, area_vetro


# --- quantità e testo -----------------------------------------------------------------------------------------------
def prepara(model, opz, prezzi):
    """opz: esterno, perline, vetro, travi (bool), più TT, TW in metri e il nome."""
    p = model["params"]
    s = model["summary"]
    TT, TW = opz["TT"], opz["TW"]
    note = []
    righe = []
    riga_vetro = (prezzi or {}).get(NOMI["vetro"]) or {}
    dens_vetro = riga_vetro.get("densita")

    def aggiungi(gruppo, voce, materiale, qta, unita_q, chiave, mm=None, dalla_nota=False):
        riga = prezzi.get(NOMI[chiave]) if prezzi else None
        euro, avviso = prezzo_spessore(riga, mm) if riga else (None, "Manca la riga nel foglio materiali.")
        if avviso:
            note.append(f"{voce}: {avviso}")
        importo = None if euro is None else round(qta * euro + 1e-9, 2)
        iva = _iva(chiave, dalla_nota or (avviso.startswith("La cella") if avviso else False))
        kg, come = peso_di(chiave, qta, unita_q, mm, riga, dens_vetro)
        righe.append({"gruppo": gruppo, "voce": voce, "materiale": materiale,
                      "qta": qta, "unita": unita_q, "prezzo": euro, "unita_prezzo": (riga or {}).get("unita", ""),
                      "importo": importo, "iva": iva, "kg": kg, "come": come})

    h_est = s.get("altezza_esterna")
    h_pav = s.get("altezza_esterna_su_pavimento", h_est)
    if h_pav is not None and h_pav > 3.0:
        note.append(f"Altezza esterna dal pavimento finito { _n(h_pav, 2) } m: sopra i 3 m.")
    if s.get("base_rientrante"):
        note.append("La base è più stretta della pancia: l'anello a terra è oltre la metà del poliedro.")
    if p.cut:
        note.append(f"C'è la riduzione di punta: zome secondario, M {p.M2}, θ { _n(p.theta2, 1) }°.")
    porta = s.get("porta")
    if porta and not porta.get("entra"):
        note.append("Il vano della porta non entra nella sezione.")
    elif porta and porta.get("fuori"):
        note.append("Il piano della porta sta fuori dalla zome: il corridoio va verso il guscio.")

    # scheletro e pavimento
    pezzi = []
    if opz["travi"] and opz.get("scheletro", True):
        lista = beams(model, TT, TW, opz.get("giunto", "butt_ccw"), True, opz.get("densita", 700.0))
        gruppi = {}
        for b in lista:
            g = gruppi.setdefault(chiave_taglio(b), {"n": 0, "campione": b, "volume": 0.0})
            g["n"] += 1
            g["volume"] += b["volume"]
        for g in sorted(gruppi.values(), key=lambda g: (g["campione"]["strato"], g["campione"].get("ruolo") != "traversa",
                                                        -g["campione"]["lung_max"])):
            b = g["campione"]
            pianta, laterale = svg_pezzo(b)
            pezzi.append({"strato": b["strato"], "nome": _nome_pezzo(b), "n": g["n"],
                          "lung_max": b["lung_max"], "lung_min": b["lung_min"],
                          "a0": b["taglio_inizio"], "a1": b["taglio_fine"],
                          "pianta": pianta, "laterale": laterale})
        vol = sum(b["volume"] for b in lista)
        aggiungi("travi", "Scheletro", f"C24, sezione {_n(TT*100, 1)}×{_n(TW*100, 1)} cm",
                 vol, "m³", "c24")
    if p.porta and opz.get("porta_anta", True):
        vol_a, area_v = _volume_anta(p, TT)
        if opz["travi"]:
            aggiungi("travi", "Anta", "C24, spessore 4 cm", vol_a, "m³", "c24")
        if opz["vetro"]:
            aggiungi("vetro", "Vetro dell'anta", "Vetrocamera della stella", area_v, "m²", "vetro")
    if opz["travi"] and p.porta:
        tel = sum(t["volume"] for t in porta_telaio(p, TT, TW))
        aggiungi("travi", "Telaio della porta", "C24", tel, "m³", "c24")
    if opz["travi"] and model.get("pavimento"):
        pv = model["pavimento"]["summary"]
        b, h = pv["travetto_b"], pv["travetto_h"]
        aggiungi("travi", "Dormienti" if pv["tipo"] == "muretto" else "Pali del pavimento",
                 "C24", pv["volume_dormienti"], "m³", "c24")
        aggiungi("travi", f"Travetti, {pv['travetti']} pezzi",
                 f"C24, sezione {_n(b*100, 0)}×{_n(h*100, 0)} cm, luce {_n(pv['luce'], 2)} m",
                 pv["volume_travetti"], "m³", "c24")
        aggiungi("travi", "Tavolato", "Tavole di abete grezze", pv["area_tavolato"], "m²", "tavole", mm=25)
        note.append(f"I travetti sono dimensionati in modo indicativo (C24, freccia L/300, carico { _n(pv['carico'], 1) } kN/m²). "
                    "Il tavolato del modello è 25 mm; il prezzo delle tavole, se c'è, è quello del listone da 20 mm.")
        note.append(f"Le pietre della fondazione ({pv['pietre']}) e il gradino non hanno un prezzo di listino in questo conto.")

    # rivestimenti
    tot = model.get("esterno_totali") or {}
    if opz["esterno"]:
        if "wood_external" in tot:
            aggiungi("esterno", "Rivestimento esterno", "Tavole di abete grezze",
                     tot["wood_external"]["area"], "m²", "tavole", mm=opz.get("t_legno", 0.02) * 1000)
        if "roof_external" in tot:
            aggiungi("esterno", "Tetto e gronda", "Tegole bituminose",
                     tot["roof_external"]["area"], "m²", "tegole", mm=opz.get("t_tetto", 0.003) * 1000)
        legno_caps, tetto_caps = 0.0, 0.0
        for nome, poly in (model.get("caps") or {}).items():
            if nome == "pavimento" or poly is None:
                continue
            area = _area(poly)
            if "falda" in nome:
                tetto_caps += area
            else:
                legno_caps += area
        if legno_caps > 1e-4:
            aggiungi("esterno", "Pareti di porta e tagli", "Tavole di abete grezze",
                     legno_caps, "m²", "tavole", mm=opz.get("t_legno", 0.02) * 1000)
        if tetto_caps > 1e-4:
            aggiungi("esterno", "Falde del corridoio", "Tegole bituminose",
                     tetto_caps, "m²", "tegole", mm=opz.get("t_tetto", 0.003) * 1000)
    if opz["perline"] and "wood_internal" in tot:
        aggiungi("perline", "Perline interne", "Abete piallato",
                 tot["wood_internal"]["area"], "m²", "perline", mm=opz.get("t_int", 0.01) * 1000,
                 dalla_nota=abs(opz.get("t_int", 0.01) * 1000 - 14) > 1.5)

    vetri = []
    if opz["vetro"]:
        gruppi = {}
        for d in model.get("esterno") or []:
            if d.get("chiave") != "glass_external" or d.get("sotto_tetto"):
                continue
            pts = _pts(model, d["strato"], d["faccia"])
            if not pts:
                continue
            alts = _altitudini(pts)
            luce_bordi = min(alts) if alts else 0.0
            luce = max(0.0, luce_bordi - 2 * TT)
            chiave = scegli_vetro(luce, d["inclinazione"])
            lato = max(_dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
            g = gruppi.setdefault((chiave, d["strato"], round(lato, 3)),
                                  {"n": 0, "area": 0.0, "luce": luce, "tilt": d["inclinazione"],
                                   "lato": lato, "pts": pts, "chiave": chiave, "strato": d["strato"]})
            g["n"] += 1
            g["area"] += d["area_copertura"]
        for g in gruppi.values():
            pianta, laterale = svg_faccia(g["pts"], g["tilt"])
            nome = "Vetrocamera per luci maggiori" if g["chiave"] == "vetro_grande" else "Vetrocamera della stella"
            vetri.append({"nome": nome, "n": g["n"], "strato": g["strato"], "area": g["area"],
                          "luce": g["luce"], "tilt": g["tilt"], "lato": g["lato"],
                          "pianta": pianta, "laterale": laterale})
            aggiungi("vetro", f"{nome}, strato {g['strato']}, ×{g['n']}",
                     f"lato {_n(g['lato']*100, 1)} cm, luce libera {_n(g['luce']*100, 0)} cm, {g['tilt']:.0f}°",
                     g["area"], "m²", g["chiave"])
        if vetri:
            note.append("Il vetro è una vetrocamera: 110 €/m² per la stella (luce intorno ai 45 cm). "
                        f"La riga da 150 €/m² entra solo se la luce libera è almeno {_n(LUCE_GRANDE*100, 0)} cm "
                        f"e la faccia è a {_n(TILT_NEVE, 0)}° o meno sull'orizzontale. "
                        "A 60° la neve scivola e resta la vetrocamera della stella. "
                        "Il prezzo è al metro quadro di fornitura, già con la lavorazione, e non va riportato a euro al metro cubo.")

    spenti = [nome for nome, acc in (("esterno", opz["esterno"]), ("perline", opz["perline"]),
                                     ("vetrocamera", opz["vetro"]), ("travi e travetti", opz["travi"])) if not acc]
    if spenti:
        note.insert(0, "Questo foglio non comprende: " + ", ".join(spenti) + ".")
    note.append("Sola materia prima, senza posa. Niente elettricità, idraulica, sanitari, ferramenta, isolamento. "
                "L'IVA non è la stessa su ogni riga: il totale somma i prezzi come sono scritti. "
                "Prezzi e densità sono approssimati: sono i numeri scritti in Riferimenti/proprieta_materiali.xlsx. "
                "Per un valore più preciso si apre quel file e si mette il numero nella cella della riga, "
                "il prezzo o il peso specifico. Il foglio tecnico li rilegge da lì.")

    if any(r["kg"] and r["gruppo"] == "travi" for r in righe):
        dens_c24 = ((prezzi or {}).get(NOMI["c24"]) or {}).get("densita")
        if dens_c24:
            note.append(f"Il peso del C24 è la massa media della classe, {_n(float(dens_c24), 0)} kg/m³. "
                        "Il pannello, per il telaio, usa la densità che c'è scritta lì.")
    totale = round(sum(r["importo"] or 0 for r in righe) + 1e-9, 2)
    fette = []
    for chiave in ("travi", "esterno", "perline", "vetro"):
        euro = sum(r["importo"] or 0 for r in righe if r["gruppo"] == chiave)
        if euro > 0:
            fette.append({"chiave": chiave, "nome": _ETICHETTE[chiave], "euro": round(euro, 2), "colore": _COLORI[chiave]})
    peso = round(sum(r["kg"] or 0 for r in righe), 1)
    return {"nome": opz.get("nome", "zome"), "summary": s, "params": p, "note": note,
            "strati": model["strata"], "profilo": svg_profilo(model), "pezzi": pezzi,
            "vetri": vetri, "righe": righe, "totale": totale, "fette": fette, "peso": peso,
            "con_travi": opz["travi"], "con_vetro": opz["vetro"],
            "pavimento": (model.get("pavimento") or {}).get("summary")}


def svg_torta(fette, totale):
    """Torta del contributo di ogni tipologia al costo. Una fetta sola è un cerchio."""
    if not fette or totale <= 0:
        return ""
    cx, cy, r = 88, 88, 72
    ang = -math.pi / 2
    parti = []
    if len(fette) == 1:
        parti.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fette[0]["colore"]}"/>')
    else:
        for f in fette:
            a = 2 * math.pi * f["euro"] / totale
            x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            ang += a
            x2, y2 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            grande = 1 if a > math.pi else 0
            parti.append(
                f'<path d="M {cx} {cy} L {x1:.2f} {y1:.2f} A {r} {r} 0 {grande} 1 {x2:.2f} {y2:.2f} Z" '
                f'fill="{f["colore"]}"/>')
    return f'<svg class="torta" viewBox="0 0 176 176" width="176" height="176">{"".join(parti)}</svg>'


def _blocco_costo(dati):
    totale = dati["totale"]
    voci = []
    for f in dati["fette"]:
        quota = 100.0 * f["euro"] / totale if totale else 0
        voci.append(
            f'<li><i style="background:{f["colore"]}"></i>{_esc(f["nome"])} '
            f'<b>{_euro(f["euro"])} €</b> · {_n(quota, 1)}%</li>')
    torta = (f'<div class="costo">{svg_torta(dati["fette"], totale)}<ul class="legenda">{"".join(voci)}</ul></div>'
             if dati["fette"] else "")
    corpo = []
    for r in dati["righe"]:
        kg = "—" if r["kg"] is None else _n(r["kg"], 0)
        corpo.append(f"<tr><td>{_esc(r['voce'])}</td><td class='n'>{kg}</td><td>{_esc(r['come'])}</td></tr>")
    peso = (f"<h2>Peso</h2><table><thead><tr><th>Voce</th><th class='n'>kg</th><th>Come</th></tr></thead>"
            f"<tbody>{''.join(corpo)}</tbody></table><p class='totale'>Peso {_n(dati['peso'], 0)} kg</p>"
            f"<p class='meta'>Le pietre e ciò che non ha una massa nel foglio materiali non entrano. "
            f"Il peso non segue il prezzo: una voce senza importo può avere i chili lo stesso.</p>")
    return torta + peso


def _tabella_righe(righe):
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


def html_foglio(dati):
    s, p = dati["summary"], dati["params"]
    h_est = s.get("altezza_esterna")
    h_txt = f"{_n(h_est, 2)} m" if h_est else "—"
    h_pav = s.get("altezza_esterna_su_pavimento")
    dal_pav = f", {_n(h_pav, 2)} m dal pavimento finito" if h_pav is not None else ""
    sec = ""
    if "ZH_secondario" in s:
        sec = f" · secondario ZH {_n(s['ZH_secondario'], 2)} m, lato {_n(s['l_secondario']*100, 1)} cm"
    testa = (f"<p class='sottotitolo'>N {p.N} · M {p.M} · θ {_n(p.theta, 2)}° · ZH {_n(p.ZH, 2)} m{sec} · "
             f"lato {_n(s['l']*100, 1)} cm · altezza esterna {h_txt}{dal_pav}</p>")
    note = "".join(f"<li>{_esc(t)}</li>" for t in dati["note"])
    strati = []
    for st in dati["strati"]:
        lato = st["lati"][0] if st["tipo"] == "rombo" else st.get("lato", st["lati"][0])
        extra = f", base {_n(st['base']*100, 1)} cm" if st.get("base") else ""
        pts = max(st["facce"], key=lambda f: _area(f[1]))[1]
        mini = _poligono(_nel_piano(pts), 72, 48, [])
        strati.append(f"<tr><td>{mini}</td><td>{st['strato']}</td><td>{_esc(st['parte'][:3])} {_esc(st['tipo'])}</td>"
                      f"<td class='n'>{st['n']}</td><td class='n'>{_n(lato*100, 1)}{extra}</td>"
                      f"<td class='n'>{_n(st['area'], 3)}</td><td class='n'>{_n(st['area_totale'], 2)}</td></tr>")
    schede = []
    for g in dati["pezzi"]:
        schede.append(
            "<article class='pezzo'>"
            f"<header>Strato {g['strato']} · {_esc(g['nome'])} · ×{g['n']}</header>"
            f"<p>{_n(g['lung_max']*100, 1)} / {_n(g['lung_min']*100, 1)} cm · teste {g['a0']:.0f}° / {g['a1']:.0f}°</p>"
            f"<div class='viste'><figure><figcaption>Pianta</figcaption>{g['pianta']}</figure>"
            f"<figure><figcaption>Laterale</figcaption>{g['laterale']}</figure></div></article>")
    vetri = []
    for g in dati["vetri"]:
        vetri.append(
            "<article class='pezzo'>"
            f"<header>{_esc(g['nome'])} · strato {g['strato']} · ×{g['n']} · {_n(g['area'], 2)} m²</header>"
            f"<p>lato {_n(g['lato']*100, 1)} cm · luce libera {_n(g['luce']*100, 0)} cm · {g['tilt']:.0f}° sull'orizzontale</p>"
            f"<div class='viste'><figure><figcaption>Pianta</figcaption>{g['pianta']}</figure>"
            f"<figure><figcaption>Laterale</figcaption>{g['laterale']}</figure></div></article>")
    pav = ""
    if dati["pavimento"]:
        pv = dati["pavimento"]
        pav = (f"<p>Pavimento {pv['tipo']}: {pv['travetti']} travetti "
               f"{_n(pv['travetto_b']*100, 0)}×{_n(pv['travetto_h']*100, 0)} cm, "
               f"luce {_n(pv['luce'], 2)} m, interasse {_n(pv['interasse']*100, 0)} cm. "
               f"Dormienti o pali {_n(pv['volume_dormienti'], 3)} m³. "
               f"Tavolato {_n(pv['area_tavolato'], 2)} m².</p>")
    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"><title>Report — {_esc(dati['nome'])}</title>
<style>
body {{ font: 14px/1.4 "Segoe UI", sans-serif; color: #1c1c1c; margin: 28px auto; max-width: 980px; }}
h1 {{ font-size: 22px; font-weight: 650; margin: 0; }}
h2 {{ font-size: 16px; margin: 26px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #ccc; }}
.sottotitolo, .meta {{ color: #444; margin: 4px 0 0; }}
ul {{ margin: 8px 0; padding-left: 18px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #e2e2e2; padding: 4px 6px; text-align: left; vertical-align: middle; }}
td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
.teste {{ display: flex; gap: 18px; align-items: flex-start; }}
.griglia {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; }}
.pezzo {{ border: 1px solid #ddd; padding: 8px; break-inside: avoid; }}
.pezzo header {{ font-weight: 650; }}
.pezzo p, figcaption {{ margin: 2px 0 6px; color: #444; font-size: 12px; }}
.viste {{ display: flex; gap: 6px; }}
svg {{ background: #fafafa; }}
polygon, line {{ fill: none; stroke: #222; stroke-width: 1.2; }}
text {{ font: 10px "Segoe UI", sans-serif; fill: #333; text-anchor: middle; }}
.totale {{ font-size: 18px; font-weight: 650; margin-top: 8px; }}
.costo {{ display: flex; gap: 18px; align-items: center; margin: 8px 0 4px; }}
.legenda {{ list-style: none; padding: 0; margin: 0; }}
.legenda li {{ margin: 4px 0; }}
.legenda i {{ display: inline-block; width: 12px; height: 12px; margin-right: 6px; vertical-align: -1px; }}
svg.torta {{ background: transparent; }}
</style></head><body>
<h1>Report — {_esc(dati['nome'])}</h1>
{testa}
<p class="meta">{date.today().isoformat()} · sola materia prima</p>
<h2>Note</h2>
<ul>{note}</ul>
<h2>Riepilogo</h2>
<div class="teste">{dati['profilo']}
<div><p>{s['strati']} strati, {s['facce']} facce. h {_n(s['h']*100, 1)} cm, lato {_n(s['l']*100, 1)} cm.</p>
<p>Base ø {_n(s['diametro_base'], 2)} m, { _n(s['area_base'], 2) } m².
Diametro massimo {_n(s['diametro_max'], 2)} m.</p>
<p>Superficie interna {_n(s['area_superficie_interna'], 2)} m².
Altezza della struttura {_n(s['altezza_totale'], 2)} m.</p>
{pav}</div></div>
<h2>Strati</h2>
<table><thead><tr><th></th><th>Strato</th><th>Tipo</th><th class="n">n</th><th class="n">Lato (cm)</th>
<th class="n">Area faccia (m²)</th><th class="n">Area strato (m²)</th></tr></thead><tbody>
{''.join(strati)}</tbody></table>
{('<h2>Pezzi di scheletro</h2><p class="meta">Nei disegni la sezione è allargata, così si leggono gli angoli. I centimetri scritti sono quelli veri.</p><div class="griglia">' + (''.join(schede) or '<p>Nessun pezzo: lo scheletro è spento.</p>') + '</div>') if dati['con_travi'] else ''}
{('<h2>Vetrocamera</h2><div class="griglia">' + (''.join(vetri) or '<p>Nessuna faccia di vetro.</p>') + '</div>') if dati['con_vetro'] else ''}
<h2>Preventivo di massima</h2>
{_tabella_righe(dati['righe'])}
<p class="totale">Totale {_euro(dati['totale'])} €</p>
{_blocco_costo(dati)}
<p class="meta">Prezzi da Riferimenti/proprieta_materiali.xlsx, foglio Materiali. Una cella vuota non è stata riempita.</p>
</body></html>"""


def scrivi(percorso, model, opz, prezzi):
    dati = prepara(model, opz, prezzi)
    os.makedirs(os.path.dirname(percorso), exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(html_foglio(dati))
    return dati


# --- andamento termico ----------------------------------------------------------------------------------------------
# Giornata di Neirone, entroterra genovese, circa 350 m. Medie pluriennali (weatherapi, dal 2009):
# luglio massima 26 e minima 21, agosto 27 e 21; gennaio, il mese più freddo, da 6 a 10.
# L'onda è il primo armonico delle 24 ore, massimo alle 15: è l'ingresso del metodo periodico.
_RSI = 0.13          # m²K/W, parete verticale, ISO 6946
_RSE = 0.04
_ORA_MAX = 15.0
_GIORNI = (
    {"titolo": "Luglio e agosto", "min": 21.0, "max": 26.5, "interno": 26.0},
    {"titolo": "Gennaio", "min": 6.0, "max": 10.0, "interno": 20.0},
)
# Pacchetto della riga Vetro: lastra esterna 6 mm, camera, stratificato 44.2 (due da 4 mm).
# I 15 mm della camera sono quelli dei pacchetti argon citati accanto, non un campo del pannello.
# La resistenza è l'intercapedine d'aria non ventilata da 15 mm, flusso orizzontale, ISO 6946.
# Il basso emissivo della riga non entra: la riga non dà l'emissività.
_VETRO_EST_MM = 6.0
_VETRO_INT_MM = 8.0
_CAMERA_R = 0.17


def _strato(d_m, riga):
    if d_m <= 0 or not riga:
        return None
    lam, rho, c = riga.get("lambda"), riga.get("densita"), riga.get("calore")
    if lam is None or rho is None or c is None:
        return None
    lam, rho, c = float(lam), float(rho), float(c)
    if lam <= 0 or rho <= 0 or c <= 0:
        return None
    return {"d": d_m, "lam": lam, "rho": rho, "c": c}


def _matrice_strato(s, omega):
    """Dal lato esterno dello strato verso quello interno. Il flusso è positivo verso l'interno."""
    if "R" in s:
        return ((1 + 0j, s["R"] + 0j), (0j, 1 + 0j))
    d, lam = s["d"], s["lam"]
    kappa = cmath.sqrt(1j * omega * s["rho"] * s["c"] / lam)
    z = kappa * d
    ch, sh = cmath.cosh(z), cmath.sinh(z)
    return ((ch, sh / (lam * kappa)), (lam * kappa * sh, ch))


def _moltiplica(a, b):
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def guadagno_faccia(strati):
    """Guadagno complesso della faccia interna, e trasmittanza stazionaria.

    L'aria interna è ferma. Il guadagno moltiplica l'ampiezza dell'aria esterna:
    la faccia interna si muove di |G| volte quell'ampiezza, in ritardo di −arg(G).
    """
    omega = 2 * math.pi / 86400.0
    m = ((1 + 0j, _RSE + 0j), (0j, 1 + 0j))
    resistenza = _RSE + _RSI
    for s in strati:
        m = _moltiplica(m, _matrice_strato(s, omega))
        resistenza += s["R"] if "R" in s else s["d"] / s["lam"]
    m = _moltiplica(m, ((1 + 0j, _RSI + 0j), (0j, 1 + 0j)))
    return _RSI / m[0][1], 1.0 / resistenza


def _ritardo_ore(guadagno):
    ore = -cmath.phase(guadagno) * 24.0 / (2 * math.pi)
    while ore <= -12:
        ore += 24
    while ore > 12:
        ore -= 24
    return ore


def _curva(media, ampiezza, guadagno):
    punti = []
    for i in range(49):
        ora = i * 0.5
        dev = guadagno * ampiezza * cmath.exp(1j * (2 * math.pi / 24.0) * (ora - _ORA_MAX))
        punti.append((ora, media + dev.real))
    return punti


def _passo_asse(span):
    for soglia, passo in ((8, 1), (16, 2), (40, 5), (100, 10), (250, 25), (600, 50), (1500, 100)):
        if span <= soglia:
            return passo
    return 200


def _svg_curve(serie):
    """serie: (colore, punti, spessore). L'asse verticale copre tutti i valori."""
    w, h = 520, 250
    sinistra, destra, alto, basso = 48, 12, 14, 26
    pw, ph = w - sinistra - destra, h - alto - basso
    valori = [v for _, punti, _ in serie for _, v in punti]
    ymin, ymax = min(valori), max(valori)
    if ymax - ymin < 1:
        ymin, ymax = ymin - 0.5, ymax + 0.5
    span = ymax - ymin
    ymin -= 0.08 * span
    ymax += 0.08 * span
    span = ymax - ymin

    def x(ora):
        return sinistra + pw * ora / 24.0

    def y(val):
        return alto + ph * (ymax - val) / span

    passo = _passo_asse(span)
    primo = math.ceil(ymin / passo) * passo
    griglia = []
    tick = primo
    while tick < ymax:
        yy = y(tick)
        griglia.append(f"<line x1='{sinistra}' y1='{yy:.1f}' x2='{w - destra}' y2='{yy:.1f}' stroke='#e4e4e4'/>")
        griglia.append(f"<text class='asse' x='{sinistra - 6}' y='{yy + 4:.1f}'>{_n(tick, 0)}</text>")
        tick += passo
    for ora in (0, 6, 12, 18, 24):
        griglia.append(f"<text class='ora' x='{x(ora):.1f}' y='{h - 8}'>{ora}</text>")
    linee = []
    for colore, punti, peso in serie:
        d = " ".join(f"{x(ora):.1f},{y(val):.1f}" for ora, val in punti)
        linee.append(f"<polyline fill='none' stroke='{colore}' stroke-width='{peso}' points='{d}'/>")
    return (f"<svg class='termico' viewBox='0 0 {w} {h}' role='img'>"
            + "".join(griglia) + "".join(linee) + "</svg>")


def _svg_giorno(giorno):
    return _svg_curve((("#222", giorno["aria"], 2), ("#8a5a2a", giorno["parete"], 2),
                       ("#2a6f8a", giorno["vetro"], 2)))


def _flusso(media, ampiezza, interno, u, guadagno):
    """W/m² verso l'interno: la parte ferma è U, l'onda è la trasmittanza periodica, ritardata."""
    yie = guadagno / _RSI
    punti = []
    for i in range(49):
        ora = i * 0.5
        onda = ampiezza * cmath.exp(1j * (2 * math.pi / 24.0) * (ora - _ORA_MAX))
        punti.append((ora, u * (media - interno) + (yie * onda).real))
    return punti


def _ora_di(h):
    h = h % 24.0
    ore = int(h)
    minuti = int(round((h - ore) * 60))
    if minuti == 60:
        ore, minuti = ore + 1, 0
    return f"{ore % 24}:{minuti:02d}"


def _voce_ritardo(nome, colore, ritardo, escursione):
    if ritardo >= 0:
        quando = f"massimo {_n(ritardo, 1)} ore dopo l'aria"
    else:
        quando = f"massimo {_n(-ritardo, 1)} ore prima dell'aria"
    cifre = 1 if escursione >= 0.5 else 2
    return (f"<li><i style='background:{colore}'></i>{_esc(nome)} · {quando}"
            f" · escursione {_n(escursione, cifre)} °C</li>")


def blocco_termico(prezzi, meta):
    """Due giornate, parete opaca e vetrocamera sulla faccia interna. Stringa vuota se manca uno spessore."""
    meta = meta or {}
    if meta.get("t_legno_mm") is None or meta.get("t_int_mm") is None or meta.get("t_isolante_mm") is None:
        return ""
    prezzi = prezzi or {}
    nome_iso = meta.get("isolante_nome") or ""
    legno_est = _strato(float(meta["t_legno_mm"]) / 1000.0, prezzi.get(NOMI["tavole"]))
    isolante = _strato(float(meta["t_isolante_mm"]) / 1000.0, prezzi.get(nome_iso))
    legno_int = _strato(float(meta["t_int_mm"]) / 1000.0, prezzi.get(NOMI["perline"]))
    vetro = prezzi.get(NOMI["vetro"])
    lastra_est = _strato(_VETRO_EST_MM / 1000.0, vetro)
    lastra_int = _strato(_VETRO_INT_MM / 1000.0, vetro)
    mancano = []
    if not legno_est:
        mancano.append("le tavole esterne")
    if not isolante:
        mancano.append(nome_iso or "l'isolante")
    if meta.get("t_int_mm") and not legno_int:
        mancano.append("le perline interne")
    if not lastra_est or not lastra_int:
        mancano.append("il vetro")
    if mancano or not nome_iso:
        return ("<h2>Andamento termico</h2><p class='meta'>Manca un dato termico per "
                + _esc(", ".join(mancano) or "l'isolante") + ".</p>")
    parete = [s for s in (legno_est, isolante, legno_int) if s]
    vetri = [lastra_est, {"R": _CAMERA_R}, lastra_int]
    g_parete, u_parete = guadagno_faccia(parete)
    g_vetro, u_vetro = guadagno_faccia(vetri)
    figure = []
    for giorno in _GIORNI:
        media = 0.5 * (giorno["min"] + giorno["max"])
        ampiezza = 0.5 * (giorno["max"] - giorno["min"])
        aria = _curva(media, ampiezza, 1 + 0j)
        faccia = _curva(media, ampiezza, g_parete)
        camera = _curva(media, ampiezza, g_vetro)
        svg = _svg_giorno({"aria": aria, "parete": faccia, "vetro": camera})
        legenda = (
            f"<li><i style='background:#222'></i>Aria esterna · da {_n(giorno['min'], 1)} a {_n(giorno['max'], 1)} °C</li>"
            + _voce_ritardo("Parete opaca", "#8a5a2a", _ritardo_ore(g_parete), 2 * abs(g_parete) * ampiezza)
            + _voce_ritardo("Vetrocamera", "#2a6f8a", _ritardo_ore(g_vetro), 2 * abs(g_vetro) * ampiezza))
        figure.append(
            f"<figure><figcaption>{_esc(giorno['titolo'])}</figcaption>{svg}"
            f"<ul class='legenda'>{legenda}</ul></figure>")
    yie_p, yie_v = abs(g_parete) / _RSI, abs(g_vetro) / _RSI
    area_p = float(meta.get("area_opaca_m2") or 0)
    area_v = float(meta.get("area_vetro_m2") or 0)
    flussi = ""
    if area_p > 0 and area_v > 0:
        figure_q = []
        for giorno in _GIORNI:
            media = 0.5 * (giorno["min"] + giorno["max"])
            ampiezza = 0.5 * (giorno["max"] - giorno["min"])
            qp = _flusso(media, ampiezza, giorno["interno"], u_parete, g_parete)
            qv = _flusso(media, ampiezza, giorno["interno"], u_vetro, g_vetro)
            somma = [(a[0], area_p * a[1] + area_v * b[1]) for a, b in zip(qp, qv)]
            ora_max, qmin, qmax = max(somma, key=lambda p: p[1])[0], min(q for _, q in somma), max(q for _, q in somma)
            svg = _svg_curve((("#8a5a2a", [(o, area_p * q) for o, q in qp], 1.5),
                              ("#2a6f8a", [(o, area_v * q) for o, q in qv], 1.5),
                              ("#111", somma, 2.5)))
            legenda = (
                f"<li><i style='background:#8a5a2a'></i>Parete opaca · {_n(area_p, 1)} m²</li>"
                f"<li><i style='background:#2a6f8a'></i>Vetrocamera · {_n(area_v, 1)} m²</li>"
                f"<li><i style='background:#111'></i>Risultante · da {_n(qmin, 0)} a {_n(qmax, 0)} W"
                f" · massimo alle {_ora_di(ora_max)}</li>")
            figure_q.append(
                f"<figure><figcaption>{_esc(giorno['titolo'])}, aria interna {_n(giorno['interno'], 0)} °C</figcaption>"
                f"{svg}<ul class='legenda'>{legenda}</ul></figure>")
        flussi = (
            "<p class='meta'>Il flusso verso l'interno, in watt, è la trasmittanza sul salto di temperatura "
            "più l'onda del giorno, ritardata. La risultante è la somma delle due aree. "
            "Sopra lo zero il calore entra. L'isolante del pavimento non c'è: non vede quest'aria.</p>"
            f"<div class='doppio'>{''.join(figure_q)}</div>")
    pacchetto = (f"Parete opaca, dall'esterno: tavole {_n(float(meta['t_legno_mm']), 0)} mm, "
                 f"{nome_iso} {_n(float(meta['t_isolante_mm']), 0)} mm, "
                 f"perline {_n(float(meta['t_int_mm']), 0)} mm. "
                 f"Vetrocamera della stella: vetro {_n(_VETRO_EST_MM, 0)} mm, camera d'aria 15 mm, "
                 f"stratificato {_n(_VETRO_INT_MM, 0)} mm. "
                 f"U {_n(u_parete, 2)} e {_n(u_vetro, 2)} W/m²K. "
                 f"Yie {_n(yie_p, 2)} e {_n(yie_v, 2)} W/m²K. "
                 f"Sfasamento {_n(_ritardo_ore(g_parete), 1)} e {_n(_ritardo_ore(g_vetro), 1)} ore.")
    return (
        "<h2>Andamento termico</h2>"
        "<p class='meta'>Neirone, entroterra genovese. La curva è la media del periodo e l'oscillazione di un giorno, "
        "con il massimo alle 15. Sopra, la faccia interna con l'aria della stanza ferma sulla media del giorno: "
        "si vede lo smorzamento, non il salto fra dentro e fuori. "
        "U è la trasmittanza a regime. Il ritardo non si somma a U: resta lo sfasamento, in ore, "
        "e la trasmittanza periodica Yie, ancora in W/m²K, è l'ampiezza del flusso per un grado di oscillazione fuori.</p>"
        f"<p class='meta'>{_esc(pacchetto)} Resistenze superficiali di parete verticale, ISO 6946. "
        "La camera è un'intercapedine d'aria da 15 mm, senza il basso emissivo: la riga del vetro non ne dà l'emissività.</p>"
        f"<div class='doppio'>{''.join(figure)}</div>"
        f"{flussi}")
