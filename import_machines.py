#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Machines & equipements : suivi par numero de serie + stock selon l'Excel,
a partir de machines_data.json (produit par prep_machines.py).

  1. Congelateurs FC1 / FC2 / FC3 : ajoute la valeur "LED Millenium" a l'attribut
     "Déclinaison" la ou l'Excel en a (Rég / Mill / Éco / LED Millenium = modele Excel)
  2. Congelateur F100 : attribut "Format" -> variantes Debout / Comptoir
  3. Cree "Machine Frosty haute performance" (variantes 232W / 289)
     et "Machine Vevor 2 têtes" : sans numero -> quantite seulement
  4. Suivi par numero de serie unique sur les produits qui ont des # SÉRIE dans l'Excel
  5. Cree les numeros de serie : # SÉRIE tel quel (aucun numero invente),
     reference interne = # MACHINE, note = texte en plus de l'Excel
  6. Met la quantite en stock : 1 par numero de serie ; les machines sans # SÉRIE
     sont comptees en stock sans numero de serie

Relançable sans risque : les numeros deja crees ou deja en stock sont sautes.
Usage : python3 import_machines.py
"""
import json
import os
import sys
import xmlrpc.client

# ===================== À REMPLIR =====================
URL         = "http://localhost:8070"
DB          = "test_v20"
USERNAME    = "admin"
PASSWORD    = "admin"
ENTREPOT_ID = 139     # entrepot ou mettre le stock (id dans l'URL) ; None = entrepot principal
# =====================================================

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "machines_data.json"), encoding="utf-8") as f:
    DATA = json.load(f)

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie DB / USERNAME / PASSWORD."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

def kw(model, method, args, opts=None):
    try:
        return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})
    except xmlrpc.client.Fault as e:
        # methode executee, mais qui ne renvoie rien (ex. action_apply_inventory)
        if "cannot marshal None" in e.faultString:
            return None
        raise

def un(model, domaine):
    ids = kw(model, "search", [domaine], {"limit": 1, "context": {"active_test": False}})
    return ids[0] if ids else None

# ---------------------------------------------------------------- Emplacement
wh = None
if ENTREPOT_ID:
    wh = kw("stock.warehouse", "search_read", [[["id", "=", ENTREPOT_ID]]], {"fields": ["lot_stock_id", "name"]})
if not wh:
    wh = kw("stock.warehouse", "search_read", [[]], {"fields": ["lot_stock_id", "name"], "limit": 1})
if not wh:
    print("Aucun entrepot : installe le module Inventaire."); sys.exit(1)
LOC = wh[0]["lot_stock_id"][0]
print(f"Stock mis dans : {wh[0]['lot_stock_id'][1]} (entrepot {wh[0]['name']})")

categ = un("product.category", [["name", "=", "Machines & équipements"]])
if not categ:
    print("Categorie 'Machines & équipements' introuvable."); sys.exit(1)

# ---------------------------------------------------------------- Outils variantes
def attribut(nom, valeurs):
    """Attribut + valeurs (crees si absents) -> (id, {valeur: id})."""
    att = un("product.attribute", [["name", "=", nom]]) or kw(
        "product.attribute", "create", [{"name": nom, "create_variant": "always"}])
    ids = {}
    for v in valeurs:
        ids[v] = un("product.attribute.value", [["name", "=", v], ["attribute_id", "=", att]]) or kw(
            "product.attribute.value", "create", [{"name": v, "attribute_id": att}])
    return att, ids

def ajouter_variantes(tmpl, att, val_ids):
    """Ajoute l'attribut au produit, ou les valeurs manquantes a sa ligne d'attribut."""
    ligne = kw("product.template.attribute.line", "search_read",
               [[["product_tmpl_id", "=", tmpl], ["attribute_id", "=", att]]], {"fields": ["value_ids"]})
    if not ligne:
        kw("product.template", "write", [[tmpl], {"attribute_line_ids": [
            (0, 0, {"attribute_id": att, "value_ids": [(6, 0, val_ids)]})]}])
    else:
        manquantes = [v for v in val_ids if v not in ligne[0]["value_ids"]]
        if manquantes:
            kw("product.template.attribute.line", "write",
               [[ligne[0]["id"]], {"value_ids": [(4, v) for v in manquantes]}])

def variante(tmpl, att, valeur_id):
    """product.product du produit pour une valeur d'attribut."""
    ptav = un("product.template.attribute.value", [["product_tmpl_id", "=", tmpl],
              ["attribute_id", "=", att], ["product_attribute_value_id", "=", valeur_id]])
    return un("product.product", [["product_tmpl_id", "=", tmpl],
                                  ["product_template_attribute_value_ids", "in", [ptav]]])

def template_par_code(*codes):
    p = kw("product.product", "search_read", [[["default_code", "in", list(codes)]]],
           {"fields": ["product_tmpl_id"], "limit": 1, "context": {"active_test": False}})
    return p[0]["product_tmpl_id"][0] if p else None

def creer_template(nom, code=None):
    t = un("product.template", [["name", "=", nom], ["categ_id", "=", categ]])
    if t:
        return t
    vals = {"name": nom, "categ_id": categ, "type": "consu", "is_storable": True, "sale_ok": True}
    if code:
        vals["default_code"] = code
    print(f"Produit cree : {nom}")
    return kw("product.template", "create", [vals])

PRODUITS = {}   # (cible, variante) -> product.product id
SERIE_TMPLS = set()

# ---------------------------------------------------------------- 1) FC1 / FC2 / FC3
att_decl, decl = attribut("Déclinaison", ["Rég", "Mill", "Éco", "LED Millenium"])
SUFFIXE = {"Rég": "REG", "Mill": "MIL", "Éco": "ECO", "LED Millenium": "LMI"}
for fc in ("FC1", "FC2", "FC3"):
    tmpl = template_par_code(f"{fc}-REG", f"{fc}-MIL", f"{fc}-ECO") or un(
        "product.template", [["name", "=", f"Congélateur {fc}"]])
    if not tmpl:
        print(f"! Congélateur {fc} introuvable : ignore"); continue
    # seulement les declinaisons presentes dans l'Excel pour ce congelateur
    utilisees = {s["variante"] for s in DATA["series"] if s["cible"] == fc}
    ajouter_variantes(tmpl, att_decl, [decl[v] for v in utilisees])
    for nom in utilisees:
        pid = variante(tmpl, att_decl, decl[nom])
        kw("product.product", "write", [[pid], {"default_code": f"{fc}-{SUFFIXE[nom]}"}])
        PRODUITS[(fc, nom)] = pid
    SERIE_TMPLS.add(tmpl)

# ---------------------------------------------------------------- 2) F100 Debout / Comptoir
tmpl = template_par_code("F100", "F100-DEB", "F100-COMP")
if tmpl:
    att_fmt, fmt = attribut("Format", ["Debout", "Comptoir"])
    ajouter_variantes(tmpl, att_fmt, list(fmt.values()))
    for nom, code in (("Debout", "F100-DEB"), ("Comptoir", "F100-COMP")):
        pid = variante(tmpl, att_fmt, fmt[nom])
        kw("product.product", "write", [[pid], {"default_code": code}])
        PRODUITS[("F100", nom)] = pid
    SERIE_TMPLS.add(tmpl)
else:
    print("! Congélateur F100 introuvable : machines Debout / Comptoir ignorees")

# ---------------------------------------------------------------- BUNN 2 tetes / H.P. Vevor
for cible in ("BUNN2", "HP-VEV"):
    tmpl = template_par_code(cible)
    if tmpl:
        PRODUITS[(cible, None)] = kw("product.product", "search", [[["product_tmpl_id", "=", tmpl]]])[0]
        SERIE_TMPLS.add(tmpl)
    else:
        print(f"! Produit {cible} introuvable : ignore")

# ---------------------------------------------------------------- 3) Frosty / Vevor 2 tetes
tmpl = creer_template("Machine Frosty haute performance")
att_fr, fr = attribut("Modèle Frosty", sorted({d["variante"] for d in DATA["sans_serie"] if d["cible"] == "FROSTY"}))
ajouter_variantes(tmpl, att_fr, list(fr.values()))
for nom, vid in fr.items():
    pid = variante(tmpl, att_fr, vid)
    kw("product.product", "write", [[pid], {"default_code": f"FROSTY-{nom}"}])
    PRODUITS[("FROSTY", nom)] = pid
tmpl = creer_template("Machine Vevor 2 têtes", "VEVOR-2T")
PRODUITS[("VEVOR2", None)] = kw("product.product", "search", [[["product_tmpl_id", "=", tmpl]]])[0]

# ---------------------------------------------------------------- 4) Suivi par numero de serie
# seulement les produits qui ont au moins un vrai # SÉRIE dans l'Excel
avec_serie = {PRODUITS[(s["cible"], s["variante"])] for s in DATA["series"]
              if s["lot"] and (s["cible"], s["variante"]) in PRODUITS}
SERIE_TMPLS = {p["product_tmpl_id"][0] for p in kw("product.product", "read",
               [sorted(avec_serie), ["product_tmpl_id"]])}
kw("product.template", "write", [sorted(SERIE_TMPLS), {"is_storable": True, "tracking": "serial"}])
print(f"Suivi par numero de serie unique active sur {len(SERIE_TMPLS)} produits")

# ---------------------------------------------------------------- 5) Numeros de serie
company = kw("res.users", "read", [[uid], ["company_id"]])[0]["company_id"][0]
lots = {}   # (product_id, nom) -> lot id
nouveaux = []
for pid in {PRODUITS[(s["cible"], s["variante"])] for s in DATA["series"] if (s["cible"], s["variante"]) in PRODUITS}:
    for l in kw("stock.lot", "search_read", [[["product_id", "=", pid]]], {"fields": ["name"]}):
        lots[(pid, l["name"])] = l["id"]
for s in DATA["series"]:
    pid = PRODUITS.get((s["cible"], s["variante"]))
    if not pid or not s["lot"] or (pid, s["lot"]) in lots:
        continue
    nouveaux.append({"name": s["lot"], "product_id": pid, "ref": s["ref"] or False,
                     "note": f"<p>{s['note']}</p>" if s["note"] else False, "company_id": company})
for i in range(0, len(nouveaux), 200):
    ids = kw("stock.lot", "create", [nouveaux[i:i + 200]])
    for v, lid in zip(nouveaux[i:i + 200], ids):
        lots[(v["product_id"], v["name"])] = lid
print(f"{len(nouveaux)} numeros de serie crees ({len(DATA['series'])} dans l'Excel)")

# ---------------------------------------------------------------- 6) Quantites en stock
INV = {"context": {"inventory_mode": True}}
en_stock = {q["lot_id"][0] for q in kw("stock.quant", "search_read",
            [[["lot_id", "in", list(lots.values())], ["location_id.usage", "=", "internal"],
              ["quantity", ">", 0]]], {"fields": ["lot_id"]}) if q["lot_id"]}
quants = []
sans_numero = {}   # product_id -> nb de machines sans # SÉRIE
for s in DATA["series"]:
    pid = PRODUITS.get((s["cible"], s["variante"]))
    if not pid:
        continue
    if not s["lot"]:
        sans_numero[pid] = sans_numero.get(pid, 0) + 1
        continue
    lid = lots.get((pid, s["lot"]))
    if lid and lid not in en_stock:
        quants.append({"product_id": pid, "lot_id": lid, "location_id": LOC, "inventory_quantity": 1})
        en_stock.add(lid)
for d in DATA["sans_serie"]:
    pid = PRODUITS[(d["cible"], d["variante"])]
    sans_numero[pid] = sans_numero.get(pid, 0) + d["qte"]
for pid, qte in sans_numero.items():   # quantite sans numero = celle de l'Excel
    q = kw("stock.quant", "search", [[["product_id", "=", pid], ["location_id", "=", LOC],
                                       ["lot_id", "=", False]]])
    if q:
        kw("stock.quant", "write", [q[:1], {"inventory_quantity": qte}], INV)
        quants.append(q[0])
    else:
        quants.append({"product_id": pid, "location_id": LOC, "inventory_quantity": qte})
nb = 0
for i in range(0, len(quants), 200):
    lot_q = quants[i:i + 200]
    ids = [q for q in lot_q if isinstance(q, int)]
    vals = [q for q in lot_q if isinstance(q, dict)]
    if vals:
        ids += kw("stock.quant", "create", [vals], INV)
    kw("stock.quant", "action_apply_inventory", [ids])
    nb += len(ids)
print(f"{nb} lignes de stock mises a jour")

for pid, qte in sorted(sans_numero.items()):
    nom = kw("product.product", "read", [[pid], ["display_name"]])[0]["display_name"]
    print(f"   {nom} : {qte} machine(s) en stock sans # SÉRIE dans l'Excel")

print("\nTermine.")
