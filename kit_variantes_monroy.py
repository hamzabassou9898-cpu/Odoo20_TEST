#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bascule le "Kit bouteilles" de 21 produits separes vers UN produit a variantes :
  - attribut "Saveur" (21 valeurs)
  - 1 produit "Kit bouteilles" (6,50 $) -> 21 variantes auto
  - reference (KIT-...) posee sur chaque variante
  - suppression des 21 anciens produits separes
Relançable sans risque. Usage : python3 kit_variantes_monroy.py
"""
import sys
import xmlrpc.client

# ===================== À REMPLIR =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
SUPPRIMER_ANCIENS = True   # mettre False pour garder les 21 fiches separees
# =====================================================

CAT = "Accessoires et articles promotionnels"
PRIX = 6.50

# (saveur, reference)
SAVEURS = [
    ("Ananas-mangue","KIT-ANAMAN"), ("Banane","KIT-BANANE"), ("Barbe à papa","KIT-BARBE"),
    ("Bleuet","KIT-BLEUET"), ("Cerise","KIT-CERISE"), ("Crème soda","KIT-CRSODA"),
    ("Fraise","KIT-FRAISE"), ("Framboise","KIT-FRAMB"), ("Fruit dragon","KIT-FDRAGON"),
    ("Gomme balloune","KIT-GOMME"), ("Kiwi-fraise","KIT-KIWI"), ("Limette","KIT-LIMET"),
    ("Melon d'eau","KIT-MELON"), ("Mûre","KIT-MURE"), ("Orange","KIT-ORANGE"),
    ("Pêche","KIT-PECHE"), ("Pomme surette","KIT-POMME"), ("Raisin arctique","KIT-RAISIN"),
    ("Yumberry","KIT-YUM"), ("Traitement choc","KIT-CHOC"), ("Potion secrète","KIT-POTION"),
]
sav_to_ref = {s: r for s, r in SAVEURS}

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie DB / USERNAME / PASSWORD."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, opts=None):
    return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})

F = kw("product.template", "fields_get", [[]], {"attributes": ["string"]})
has_storable = "is_storable" in F
has_tags     = "product_tag_ids" in F

# 1) Attribut "Saveur"
attr = kw("product.attribute", "search", [[["name", "=", "Saveur"]]])
if attr:
    attr_id = attr[0]
else:
    attr_id = kw("product.attribute", "create", [{"name": "Saveur", "create_variant": "always"}])

# 2) Valeurs d'attribut (21 saveurs)
val_ids = []
for sav, _ in SAVEURS:
    v = kw("product.attribute.value", "search", [[["name", "=", sav], ["attribute_id", "=", attr_id]]])
    val_ids.append(v[0] if v else kw("product.attribute.value", "create", [{"name": sav, "attribute_id": attr_id}]))

# 3) Categorie + etiquette
cat = kw("product.category", "search", [[["name", "=", CAT]]])
cat_id = cat[0] if cat else kw("product.category", "create", [{"name": CAT}])
tag_vals = {}
if has_tags:
    t = kw("product.tag", "search", [[["name", "=", "Kit bouteilles"]]])
    tag_vals = {"product_tag_ids": [(4, t[0] if t else kw("product.tag", "create", [{"name": "Kit bouteilles"}]))]}

# 4) Produit template unique
tmpl = kw("product.template", "search", [[["name", "=", "Kit bouteilles"], ["categ_id", "=", cat_id]]])
if tmpl:
    tmpl_id = tmpl[0]
else:
    vals = {"name": "Kit bouteilles", "categ_id": cat_id, "sale_ok": True, "list_price": PRIX}
    if has_storable:
        vals["type"] = "consu"; vals["is_storable"] = True
    vals.update(tag_vals)
    tmpl_id = kw("product.template", "create", [vals])

# 5) Ligne d'attribut -> genere les variantes
line = kw("product.template.attribute.line", "search",
          [[["product_tmpl_id", "=", tmpl_id], ["attribute_id", "=", attr_id]]])
if not line:
    kw("product.template.attribute.line", "create",
       [{"product_tmpl_id": tmpl_id, "attribute_id": attr_id, "value_ids": [(6, 0, val_ids)]}])

# 6) Reference sur chaque variante
variants = kw("product.product", "search_read", [[["product_tmpl_id", "=", tmpl_id]]],
              {"fields": ["id", "product_template_attribute_value_ids"]})
all_ptav = sorted({i for v in variants for i in v["product_template_attribute_value_ids"]})
ptav_name = {}
if all_ptav:
    for p in kw("product.template.attribute.value", "read", [all_ptav], {"fields": ["name"]}):
        ptav_name[p["id"]] = p["name"]
refs_set = 0
for v in variants:
    noms = [ptav_name.get(i, "") for i in v["product_template_attribute_value_ids"]]
    sav = noms[0] if noms else ""
    ref = sav_to_ref.get(sav)
    if ref:
        kw("product.product", "write", [[v["id"]], {"default_code": ref}])
        refs_set += 1

# 7) Supprimer les 21 anciens produits separes
deleted = 0
if SUPPRIMER_ANCIENS:
    old_refs = [r for _, r in SAVEURS]
    olds = kw("product.template", "search",
              [[["default_code", "in", old_refs], ["id", "!=", tmpl_id]]])
    if olds:
        try:
            kw("product.template", "unlink", [olds]); deleted = len(olds)
        except Exception as e:
            print(f"[!] Suppression partielle/impossible des anciens : {e}")

print("===== Kit bouteilles -> variantes =====")
print(f"Produit unique : 'Kit bouteilles' (id {tmpl_id}), prix {PRIX:.2f} $")
print(f"Attribut 'Saveur' : {len(val_ids)} valeurs | Variantes : {len(variants)} | references posees : {refs_set}")
print(f"Anciens produits separes supprimes : {deleted}")
print("\nVerifie dans Odoo : Inventaire -> Produits -> 'Kit bouteilles' (onglet Ventes/Variantes).")
