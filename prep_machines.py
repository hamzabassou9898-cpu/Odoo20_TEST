#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nettoie la liste Excel des numeros de machines et produit machines_data.json,
lu par import_machines.py.

  MODELE        -> produit + variante Odoo (voir MODELES ci-dessous)
  # SERIE       -> numero de serie, tel quel (aucun numero n'est invente : sans
                   # SERIE, la machine compte seulement dans la quantite en stock)
  # MACHINE     -> reference interne du numero de serie (tel que dans l'Excel)
  texte en plus dans # SERIE (neuve 2020, garantie p:01/20...) -> note du numero de serie

Usage : python3 prep_machines.py "VOLCAN_LISTE_COMPLE_TE_NUME_RO_MACHINE.xlsx"
(necessite openpyxl : python3 -m pip install --user openpyxl)
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))

# Modele Excel (espaces normalises, majuscules) -> (cible, variante)
MODELES = {
    "BUNN 2 TÊTES": ("BUNN2", None),
    "DEBOUT": ("F100", "Debout"),
    "COMPTOIR": ("F100", "Comptoir"),
    "VEVOR HAUTE PERFORMANCE": ("HP-VEV", None),
    "VEVOR 2 TÊTES": ("VEVOR2", None),
    "HAUTE PERFORMANCE": ("FROSTY", None),    # variante = modele lu dans # MACHINE
}
for fc in ("FC1", "FC2", "FC3"):
    MODELES[fc] = (fc, "Rég")
    MODELES[f"{fc} MILLENIUM"] = (fc, "Mill")
    MODELES[f"{fc}-LED ÉCO"] = (fc, "Éco")
    MODELES[f"{fc} LED ECO"] = (fc, "Éco")
    MODELES[f"{fc}-LED MILLENIUM"] = (fc, "LED Millenium")

def txt(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    v = str(v).replace("\xa0", " ").strip()
    return v or None


def une_ligne(v):
    return re.sub(r"\s+", " ", v).strip() if v else None


def main(src):
    ws = openpyxl.load_workbook(src, data_only=True).worksheets[0]
    series, sans_serie, ignores, avert = [], Counter(), Counter(), []
    vus = defaultdict(set)   # (cible, variante) -> noms de lots deja pris

    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        modele = une_ligne(txt(r[1]))
        machine = une_ligne(txt(r[2]))
        serie_brut = txt(r[3])
        if not modele:
            continue
        cle = modele.upper()
        if cle not in MODELES:
            ignores[modele] += 1       # lignes popcorn sans numero
            continue
        cible, variante = MODELES[cle]

        if cible == "FROSTY":          # "FROSTY modèle 232W" -> variante 232W
            variante = machine.split()[-1] if machine else None
            sans_serie[(cible, variante)] += 1
            continue
        if cible == "VEVOR2":
            sans_serie[(cible, None)] += 1
            continue

        # # SERIE : 1re ligne = numero si elle contient un chiffre, le reste = note
        lignes = [l.strip() for l in (serie_brut or "").split("\n") if l.strip()]
        serie = lignes[0] if lignes and re.search(r"\d", lignes[0]) else None
        note = " ".join(lignes[1:] if serie else lignes) or None
        if note and note.lower() == "non existant":
            note = "# série non existant"

        lot = serie
        if lot and lot in vus[(cible, variante)]:
            avert.append(f"ligne {i}: # serie {lot} ({machine}) deja utilise par une autre machine "
                         f"du meme produit -> compte sans numero de serie, a corriger dans l'Excel")
            lot = None
        if lot:
            vus[(cible, variante)].add(lot)

        series.append({"cible": cible, "variante": variante, "lot": lot,
                       "ref": machine, "note": note, "ligne": i})

    data = {"series": series,
            "sans_serie": [{"cible": c, "variante": v, "qte": q} for (c, v), q in sans_serie.items()]}
    with open(os.path.join(HERE, "machines_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    par = Counter((s["cible"], s["variante"]) for s in series)
    sans = Counter((s["cible"], s["variante"]) for s in series if not s["lot"])
    print(f"{len(series)} machines ({len(series) - sum(sans.values())} avec # serie) :")
    for (c, v), n in sorted(par.items(), key=lambda x: (x[0][0], x[0][1] or "")):
        print(f"   {c:7} {v or '':14} {n:4}   dont sans # serie : {sans[(c, v)]}")
    for d in data["sans_serie"]:
        print(f"Sans numero (quantite seulement) : {d['cible']} {d['variante'] or ''} x{d['qte']}")
    for m, n in ignores.items():
        print(f"Ignore (pas de numero) : {m} x{n}")
    for a in avert:
        print("AVERTISSEMENT", a)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
