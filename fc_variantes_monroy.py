#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bascule les congelateurs FC1 / FC2 / FC3 vers des produits a variantes :
  - attribut "Déclinaison" (Rég / Jaune / Mill / Éco)
  - 1 produit par FC (3 au total) -> 4 variantes chacun
  - reference (FC1-REG, ...) posee sur chaque variante
  - reprend categorie, prix, etiquettes et description des anciens
  - supprime les 12 anciens produits separes
Relançable sans risque. Usage : python3 fc_variantes_monroy.py
"""
import sys
import xmlrpc.client

# ===================== À REMPLIR =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
SUPPRIMER_ANCIENS = True   # False pour garder les anciennes fiches le temps de verifier
# =====================================================

DECL = [("Rég", "REG"), ("Jaune", "JAU"), ("Mill", "MIL"), ("Éco", "ECO")]
decl_to_suf = {d: s for d, s in DECL}
FCS = ["FC1", "FC2", "FC3"]

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie DB / USERNAME / PASSWORD."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def kw(model, method, args, opts=None):
    return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})

F = kw("product.template", "fields_get", [[]], {"attributes": ["string"]})
has_storable = "is_storable" in F
has_rent     = "rent_ok" in F
has_desc     = "description_sale" in F
has_tags     = "product_tag_ids" in F

# 1) Attribut "Déclinaison" + valeurs
attr = kw("product.attribute", "search", [[["name", "=", "Déclinaison"]]])
attr_id = attr[0] if attr else kw("product.attribute", "create", [{"name": "Déclinaison", "create_variant": "always"}])
val_ids = []
for d, _ in DECL:
    v = kw("product.attribute.value", "search", [[["name", "=", d], ["attribute_id", "=", attr_id]]])
    val_ids.append(v[0] if v else kw("product.attribute.value", "create", [{"name": d, "attribute_id": attr_id}]))

total_new = total_var = total_refs = total_del = 0

for fc in FCS:
    old_refs = [f"{fc}-{suf}" for _, suf in DECL]
    olds = kw("product.template", "search", [[["default_code", "in", old_refs]]])
    if not olds:
        print(f"[{fc}] aucun ancien produit trouve, ignore.")
        continue

    # Reprendre les infos d'un ancien
    fields = ["categ_id", "list_price"]
    if has_desc: fields.append("description_sale")
    if has_tags: fields.append("product_tag_ids")
    if has_storable: fields.append("is_storable")
    if has_rent: fields.append("rent_ok")
    info = kw("product.template", "read", [[olds[0]], fields])[0]

    # Creer le template unique
    tmpl = kw("product.template", "search", [[["name", "=", f"Congélateur {fc}"], ["categ_id", "=", info["categ_id"][0]]]])
    if tmpl:
        tmpl_id = tmpl[0]
    else:
        vals = {"name": f"Congélateur {fc}", "categ_id": info["categ_id"][0],
                "sale_ok": True, "list_price": info["list_price"]}
        if has_storable: vals["type"] = "consu"; vals["is_storable"] = info.get("is_storable", True)
        if has_rent and info.get("rent_ok"): vals["rent_ok"] = True
        if has_desc and info.get("description_sale"): vals["description_sale"] = info["description_sale"]
        if has_tags and info.get("product_tag_ids"): vals["product_tag_ids"] = [(6, 0, info["product_tag_ids"])]
        tmpl_id = kw("product.template", "create", [vals])
        total_new += 1

    # Ligne d'attribut -> variantes
    line = kw("product.template.attribute.line", "search",
              [[["product_tmpl_id", "=", tmpl_id], ["attribute_id", "=", attr_id]]])
    if not line:
        kw("product.template.attribute.line", "create",
           [{"product_tmpl_id": tmpl_id, "attribute_id": attr_id, "value_ids": [(6, 0, val_ids)]}])

    # References sur les variantes
    variants = kw("product.product", "search_read", [[["product_tmpl_id", "=", tmpl_id]]],
                  {"fields": ["id", "product_template_attribute_value_ids"]})
    total_var += len(variants)
    all_ptav = sorted({i for v in variants for i in v["product_template_attribute_value_ids"]})
    ptav_name = {p["id"]: p["name"] for p in kw("product.template.attribute.value", "read", [all_ptav], {"fields": ["name"]})} if all_ptav else {}
    for v in variants:
        noms = [ptav_name.get(i, "") for i in v["product_template_attribute_value_ids"]]
        suf = decl_to_suf.get(noms[0]) if noms else None
        if suf:
            kw("product.product", "write", [[v["id"]], {"default_code": f"{fc}-{suf}"}])
            total_refs += 1

    # Supprimer les anciens
    if SUPPRIMER_ANCIENS:
        to_del = [i for i in olds if i != tmpl_id]
        if to_del:
            try:
                kw("product.template", "unlink", [to_del]); total_del += len(to_del)
            except Exception as e:
                print(f"[{fc}] suppression impossible : {e}")
    print(f"[{fc}] -> produit 'Congélateur {fc}' avec {len(variants)} variantes.")

print("\n===== FC1/FC2/FC3 -> variantes =====")
print(f"Produits a variantes crees : {total_new} | variantes : {total_var} | references posees : {total_refs}")
print(f"Anciens produits supprimes : {total_del}")
print("\nVerifie dans Odoo : Inventaire -> Produits ('Congélateur FC1/FC2/FC3', onglet Attributs et variantes).")
