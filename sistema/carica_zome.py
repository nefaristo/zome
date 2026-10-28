# Nel Text editor di Blender: apri questo file e premi "Esegui script" (Alt+P).
# Cerca sistema/blenderzome.py risalendo dalla cartella del .blend aperto.
import os, sys, importlib, bpy
d = os.path.dirname(bpy.data.filepath)
codice = None
for _ in range(6):
    sistema = os.path.join(d, "sistema")
    if os.path.isfile(os.path.join(sistema, "blenderzome.py")):
        codice = sistema
        break
    if os.path.isfile(os.path.join(d, "blenderzome.py")):
        codice = d
        break
    nuovo = os.path.dirname(d)
    if nuovo == d:
        break
    d = nuovo
if not codice:
    raise RuntimeError("Non trovo sistema/blenderzome.py risalendo dal file aperto")
if codice not in sys.path:
    sys.path.append(codice)
import zome_core, blenderzome
importlib.reload(zome_core)
importlib.reload(blenderzome)
blenderzome.register()
print("Pannello Zome caricato da", codice)
