"""Prove del foglio tecnico.  python test_zome_foglio.py"""
import math
import os
from zome_core import Params, build, shell
from zome_foglio import NOMI, blocco_termico, carica_prezzi, guadagno_faccia, html_foglio, prepara, scegli_vetro

QUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(QUI) if os.path.basename(QUI).lower() == "sistema" else QUI
PREZZI = carica_prezzi(os.path.join(ROOT, "Riferimenti", "proprieta_materiali.xlsx"))

assert abs(PREZZI[NOMI["c24"]]["prezzo"] - 661.38) < 1e-6
assert abs(PREZZI[NOMI["vetro"]]["prezzo"] - 110) < 1e-6
assert abs(PREZZI[NOMI["c24"]]["densita"] - 420) < 1e-6
assert abs(PREZZI[NOMI["vetro"]]["densita"] - 2500) < 1e-6
assert abs(PREZZI[NOMI["vetro"]]["lambda"] - 0.8) < 1e-6
g_fermo, u_fermo = guadagno_faccia([{"d": 0.02, "lam": 0.13, "rho": 500, "c": 1e-6}])
assert abs(abs(g_fermo) - 0.13 / (0.13 + 0.04 + 0.02 / 0.13)) < 0.002
assert abs(u_fermo - 1 / (0.13 + 0.04 + 0.02 / 0.13)) < 0.002
assert scegli_vetro(0.44, 35) == "vetro"
assert scegli_vetro(0.95, 21) == "vetro_grande"
assert scegli_vetro(1.00, 60) == "vetro"

p = Params(N=8, M=5, theta=55, ZH=2.6, floor=True, zfloor=0.30, porta=True, porta_modo="corridoio",
           porta_dist=1.15, porta_w=0.80, porta_h=2.0, porta_falda=0.10, stella_vetri=True,
           sporgenza_tetto=0.08, TW=0.06)
p.catalogo["wood_internal"]["spessore"] = 0.01
p.catalogo["glass_external"]["spessore"] = 0.03
p.catalogo["roof_external"]["spessore"] = 0.003
m = build(p)
shell(m, m["params"])
opz = {"nome": "prova", "esterno": True, "perline": True, "vetro": True, "travi": True,
       "TT": 0.04, "TW": 0.06, "giunto": "butt_ccw", "densita": 700.0, "scheletro": True,
       "porta_anta": True, "t_legno": 0.02, "t_tetto": 0.003, "t_int": 0.01}
d = prepara(m, opz, PREZZI)
assert d["pezzi"] and "<svg" in d["pezzi"][0]["pianta"] and "°" in d["pezzi"][0]["pianta"]
assert d["vetri"] and "<svg" in d["vetri"][0]["laterale"]
voci = {r["voce"]: r for r in d["righe"]}
assert voci["Scheletro"]["importo"] and abs(voci["Scheletro"]["prezzo"] - 661.38) < 1e-6
assert abs(voci["Perline interne"]["prezzo"] - 10.78) < 1e-6
assert voci["Perline interne"]["iva"] == "non dichiarata"
assert any(r["voce"].startswith("Vetrocamera") and r["prezzo"] == 110 for r in d["righe"])
assert d["totale"] == round(sum(r["importo"] or 0 for r in d["righe"]), 2)
assert abs(voci["Scheletro"]["kg"] - voci["Scheletro"]["qta"] * 420) < 0.05
assert abs(sum(f["euro"] for f in d["fette"]) - d["totale"]) < 0.02
testo = html_foglio(d)
assert "Pianta" in testo and "Laterale" in testo and "Preventivo" in testo
assert 'class="torta"' in testo and "<h2>Peso</h2>" in testo
assert "approssimati" in testo
assert "Travi e travetti" in testo and "Vetrocamera" in testo

from zome_pavimento import interasse_massimo
from zome_scena import _estensioni, _si_incrocia, _viste_tipo, componi, espandi, firma, html_scena, svg_schema


def _box(origine, size):
    x, y, z = origine
    dx, dy, dz = size
    v = [(x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z),
         (x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)]
    f = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return v, f


def _unisci(parti):
    verts, faces = [], []
    for v, f in parti:
        b = len(verts)
        verts.extend(v)
        faces.extend([[b + i for i in fac] for fac in f])
    return verts, faces


a = _box((0, 0, 0), (0.70, 0.04, 0.08))
b = _box((2, 0, 0), (0.70, 0.04, 0.08))
c = _box((0, 1, 0), (0.40, 0.04, 0.08))
ruotati = [((p[0] - p[1]) * 0.7071, (p[0] + p[1]) * 0.7071, p[2]) for p in a[0]]
est = sorted(_estensioni(ruotati))
assert abs(est[0] - 0.04) < 1e-3 and abs(est[1] - 0.08) < 1e-3 and abs(est[2] - 0.70) < 1e-3, est
assert firma(a[0], 1) == firma(b[0], 1)
specchio = [(p[0], -p[1], p[2]) for p in
            [(0, 0, 0), (0.70, 0, 0), (0.66, 0.05, 0), (0.04, 0.02, 0),
             (0, 0, 0.08), (0.70, 0, 0.08), (0.66, 0.05, 0.08), (0.04, 0.02, 0.08)]]
originale = [(0, 0, 0), (0.70, 0, 0), (0.66, 0.05, 0), (0.04, 0.02, 0),
             (0, 0, 0.08), (0.70, 0, 0.08), (0.66, 0.05, 0.08), (0.04, 0.02, 0.08)]
assert firma(originale, 1) != firma(specchio, 1)
assert _si_incrocia([(0, 0), (1, 1), (0, 1), (1, 0)])
assert not _si_incrocia([(0, 0), (1, 0), (1, 0.2), (0, 0.2)])

vs, fs = _unisci((a, b, c))
esterno = _box((0, 0, 1), (1.0, 0.80, 0.02))
interno = _box((0, 0, 2), (1.0, 0.80, 0.01))
oggetti = [
    {"nome": "zome_prova_scheletro", "ruolo": "Struttura", "verts": vs, "faces": fs, "strati": None, "classi": None, "cutlist": None},
    {"nome": "zome_prova_legno", "ruolo": "Esterno · legno", "verts": esterno[0], "faces": esterno[1], "strati": [1] * len(esterno[1]), "classi": None, "cutlist": None},
    {"nome": "zome_prova_perline", "ruolo": "Interno · perline", "verts": interno[0], "faces": interno[1], "strati": [1] * len(interno[1]), "classi": None, "cutlist": None},
]
assert len(espandi(oggetti[:1])) == 3
opz_s = {"nome": "prova", "esterno": True, "perline": True, "vetro": True, "travi": True}
dati_s = componi(oggetti, {"nome": "prova", "pav_tipo": "pietroni", "t_legno_mm": 20, "t_int_mm": 10, "t_tetto_mm": 3}, opz_s, PREZZI)
voci_s = {r["voce"]: r for r in dati_s["righe"]}
assert abs(voci_s["Scheletro"]["qta"] - 2 * 0.70 * 0.04 * 0.08 - 0.40 * 0.04 * 0.08) < 1e-6
assert abs(voci_s["Scheletro"]["prezzo"] - 661.38) < 1e-6
assert voci_s["Esterno"]["materiale"] == "Perline"
assert abs(voci_s["Esterno"]["prezzo"] - 11.90) < 1e-6
assert abs(voci_s["Interno"]["prezzo"] - 10.78) < 1e-6
assert "Tavole di abete" not in voci_s["Esterno"]["voce"]
html_s = html_scena(dati_s)
assert "Isometrica" in html_s and "Pianta" in html_s and "Laterale" in html_s and "Sezione" in html_s
assert "<h2>Strati</h2>" not in html_s and "peso non segue" not in html_s
assert "<h2>Esterno</h2>" in html_s and "<h2>Interno</h2>" in html_s
assert "L'altra parte" in html_s and "class='somma'" in html_s
i_euro = html_s.find('<p class="totale">Totale')
i_peso = html_s.find('<p class="totale">Peso')
i_torta = html_s.find('class="torta"')
assert 0 <= i_euro < i_peso < i_torta
assert html_s.find("<h2>Preventivo di massima</h2>") < html_s.find("<h2>Note</h2>") < html_s.find("Isometrica")
termo = blocco_termico(PREZZI, {"t_legno_mm": 20, "t_int_mm": 15, "t_isolante_mm": 80,
                                 "isolante_nome": "Argilla espansa",
                                 "area_opaca_m2": 19.3, "area_vetro_m2": 3.86})
assert termo.count("<svg") == 4 and "Luglio e agosto" in termo and "Gennaio" in termo and "ore dopo" in termo
assert "Yie" in termo and "Risultante" in termo
assert "110 €/m²" not in html_s and "sopra i 3 m" not in html_s
assert "approssimati" in html_s and "<h2>Peso</h2>" in html_s
assert ">×2<" in html_s
cubo_v, cubo_f = _box((0, 0, 0), (1, 1, 1))
n_facce = svg_schema([{"verts": cubo_v, "faces": cubo_f, "_tipo": 0}], {0: "#c0392b"}, 200, 200).count("<polygon")
assert 1 <= n_facce <= 3, n_facce
ang = math.radians(56.5)
c56, s56 = math.cos(ang), math.sin(ang)
trapezio = [(0, 0, 0), (0.849, 0, 0), (0.849 + 0.03 * c56, 0.03 * s56, 0), (0.03 * c56, 0.03 * s56, 0)]
alto = [(p[0], p[1], 0.08) for p in trapezio]
tv = trapezio + alto
tf = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]
_iso_t, pianta_t, _lat_t, _sez_t, _inc_t = _viste_tipo({"verts": tv, "faces": tf}, "#6c3483")
assert "56° (34°)" in pianta_t and "class=\"ang\"" in pianta_t and "cm" in pianta_t
i_trav, det_trav = interasse_massimo(4.98, 0.08, 0.12, 0.5)
assert det_trav["comanda"] == "freccia" and 0.40 < i_trav < 0.48, (i_trav, det_trav["comanda"])
solo_s = componi(oggetti, {"nome": "prova"}, dict(opz_s, esterno=False, perline=False, vetro=False), PREZZI)
assert all(r["chiave"] == "c24" for r in solo_s["righe"])
assert "<h2>Vetrocamera</h2>" not in html_scena(solo_s)

solo = dict(opz, esterno=False, perline=False, vetro=False)
d2 = prepara(m, solo, PREZZI)
assert d2["righe"] and all(r["gruppo"] == "travi" for r in d2["righe"])
assert "Vetrocamera" not in html_foglio(d2)
print("OK foglio", len(d["pezzi"]), "tipi,", d["totale"], "€")
