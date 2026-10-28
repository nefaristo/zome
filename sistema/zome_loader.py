"""zome_loader.py - add-on minimo che carica il pannello Zome ad ogni avvio di Blender.

Copia in: %APPDATA%/Blender Foundation/Blender/5.2/scripts/addons/zome_loader.py
Poi Preferenze > Add-on > "Zome (pannello)" acceso. Il codice resta nella cartella BlenderZome:
il loader la trova da solo, nell'ordine:
  1. il campo "Cartella BlenderZome" nelle preferenze di questo add-on (se compilato);
  2. la variabile d'ambiente ZOME_CARTELLA;
  3. ~/Documents/@DriveMirror/Appunti/Valle degli eremi/Strutturali zome/BlenderZome  (~ = cartella utente di questo computer);
  4. la cartella del file .blend aperto, o una delle sue cartelle madri (anche una sottocartella "BlenderZome").
Cosi' non c'e' un percorso con il nome utente scritto nel codice: sul secondo computer, se la cartella e' sincronizzata nello
stesso posto sotto la cartella utente, parte da sola; altrimenti basta compilare il campo nelle preferenze.
Il pannello sta in BlenderZome/sistema/blenderzome.py. Il campo delle preferenze indica la cartella BlenderZome, non sistema/.
"""
bl_info = {"name": "Zome (pannello)", "author": "Stefano", "version": (1, 3, 0), "blender": (5, 2, 0),
           "location": "Vista 3D > barra laterale (N) > Zome",
           "description": "Carica il pannello Zome da BlenderZome/sistema/blenderzome.py", "category": "Mesh"}

import importlib
import os
import sys

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty

RELATIVO = os.path.join("Documents", "@DriveMirror", "Appunti", "Valle degli eremi", "Strutturali zome", "BlenderZome")
_mod = None


def _codice(d):
    """Cartella da mettere su sys.path (sistema/, oppure la radice se il codice e' ancora li'), o None."""
    if not d:
        return None
    d = os.path.abspath(bpy.path.abspath(d))
    sistema = os.path.join(d, "sistema")
    if os.path.isfile(os.path.join(sistema, "blenderzome.py")):
        return sistema
    if os.path.isfile(os.path.join(d, "blenderzome.py")):
        return d
    return None


def _filepath_blend():
    """Percorso del .blend aperto. Durante l'accensione dell'add-on Blender sostituisce bpy.data
    con un oggetto vuoto (_RestrictData): in quel momento il percorso non si legge, e non e' un errore."""
    try:
        return bpy.data.filepath or ""
    except AttributeError:
        return ""


def _trova():
    """Primo percorso valido tra i candidati (vedi sopra), oppure None."""
    cand = []
    try:
        cand.append(bpy.context.preferences.addons[__name__].preferences.cartella)
    except Exception:
        pass
    cand.append(os.environ.get("ZOME_CARTELLA", ""))
    cand.append(os.path.join(os.path.expanduser("~"), RELATIVO))
    f = _filepath_blend()
    if f:
        d = os.path.dirname(os.path.abspath(f))
        for _ in range(5):
            cand += [d, os.path.join(d, "BlenderZome")]
            nuovo = os.path.dirname(d)
            if nuovo == d:
                break
            d = nuovo
    for c in cand:
        codice = _codice(c)
        if codice:
            return codice
    return None


def _cartella_cambiata(self, _context):
    _carica()


class ZomeLoaderPrefs(bpy.types.AddonPreferences):
    bl_idname = __name__
    cartella: StringProperty(name="Cartella BlenderZome", subtype='DIR_PATH', default="",
                             description="Cartella del progetto (quella che contiene sistema/). Lasciare vuoto per la ricerca automatica",
                             update=_cartella_cambiata)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "cartella")
        trovata = _trova()
        col.label(text=("In uso: " + trovata) if trovata else "Cartella non trovata: compila il campo qui sopra",
                  icon='CHECKMARK' if trovata else 'ERROR')


def _carica():
    """Carica il pannello se la cartella si trova; ritorna True se riuscito."""
    global _mod
    if _mod is not None:
        return True
    d = _trova()
    if not d:
        return False
    if d not in sys.path:
        sys.path.append(d)
    import zome_core, blenderzome
    importlib.reload(zome_core)
    importlib.reload(blenderzome)
    try:
        blenderzome.register()
    except AttributeError:
        # All'accensione dell'add-on bpy.data e' ancora _RestrictData: si riprova all'apertura del file.
        return False
    _mod = blenderzome
    return True


@persistent
def _dopo_apertura(*_):
    # Il clic sulla casella nasconde bpy.data: si riprova un attimo dopo, e di nuovo all'apertura di un .blend.
    if _carica() and _dopo_apertura in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_dopo_apertura)
    return None


def register():
    bpy.utils.register_class(ZomeLoaderPrefs)
    if not _carica():
        print("Zome: cartella BlenderZome non trovata; compilala nelle preferenze dell'add-on (Zome (pannello)) "
              "o apri un .blend dentro la cartella")
        if _dopo_apertura not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_dopo_apertura)
        if not bpy.app.timers.is_registered(_dopo_apertura):
            bpy.app.timers.register(_dopo_apertura, first_interval=0.1)


def unregister():
    global _mod
    if bpy.app.timers.is_registered(_dopo_apertura):
        bpy.app.timers.unregister(_dopo_apertura)
    if _dopo_apertura in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_dopo_apertura)
    if _mod is not None:
        _mod.unregister()
        _mod = None
    bpy.utils.unregister_class(ZomeLoaderPrefs)
