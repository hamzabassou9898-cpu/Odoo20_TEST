MODULE = "migration_inventaire"
INV = {"context": {"inventory_mode": True}}

# ---------------------------------------------------------------- 1) Categories
CF = champs("product.category")
categories = {}
for c in DATA["categories"]:   # parents avant enfants
    parent = categories.get(c["parent"], False)
    vals = {"name": c["nom"], "parent_id": parent}
    if "suivi_machine" in CF and c.get("suivi_machine") is not None:
        vals["suivi_machine"] = c["suivi_machine"]
    categories[c["cle"]], _ = ecrire_ou_creer(c["cle"], "product.category", vals,
                                              [["name", "=", c["nom"]], ["parent_id", "=", parent]])
print(f"{len(categories)} categories")

# ---------------------------------------------------------------- 2) Unites, etiquettes, attributs
uoms = {}

def unite(nom):
    if nom not in uoms:
        ids = kw("uom.uom", "search", [[["name", "=", nom]]]) if nom else []
        uoms[nom] = ids[0] if ids else False
    return uoms[nom]

tags = {}
if modele_existe("product.tag"):
    for t in DATA["etiquettes"]:
        tags[t["cle"]], _ = ecrire_ou_creer(t["cle"], "product.tag", {"name": t["nom"], "color": t["couleur"]},
                                            [["name", "=", t["nom"]]])

AF = champs("product.attribute")
attributs, valeurs = {}, {}
for a in DATA["attributs"]:
    vals = {k: v for k, v in {"name": a["nom"], "create_variant": a["create_variant"],
                              "display_type": a["display_type"]}.items() if k in AF and v}
    attributs[a["cle"]], _ = ecrire_ou_creer(a["cle"], "product.attribute", vals, [["name", "=", a["nom"]]])
    for v in a["valeurs"]:
        valeurs[v["cle"]], _ = ecrire_ou_creer(
            v["cle"], "product.attribute.value",
            {"name": v["nom"], "attribute_id": attributs[a["cle"]], "sequence": v["sequence"],
             **({"html_color": v["html_color"]} if v.get("html_color") else {})},
            [["name", "=", v["nom"]], ["attribute_id", "=", attributs[a["cle"]]]])
print(f"{len(attributs)} attributs, {len(valeurs)} valeurs")

# ---------------------------------------------------------------- 3) Produits + variantes
TF = champs("product.template")
VF = champs("product.product")
variantes = {}   # cle export -> product.product
nb_new = nb_maj = 0
for t in DATA["produits"]:
    vals = {k: v for k, v in t["vals"].items() if k in TF}
    vals["categ_id"] = categories.get(t["categorie"], False) or vals.get("categ_id")
    if not vals["categ_id"]:
        vals.pop("categ_id")
    if t.get("unite") and unite(t["unite"]):
        vals["uom_id"] = unite(t["unite"])
    if "product_tag_ids" in TF:
        vals["product_tag_ids"] = [(6, 0, [tags[c] for c in t["etiquettes"] if c in tags])]
    if t.get("image") and "image_1920" in TF:
        vals["image_1920"] = t["image"]
    tracking = vals.pop("tracking", None)   # pose apres les variantes
    tmpl, cree = ecrire_ou_creer(t["cle"], "product.template", vals,
                                 [["name", "=", vals["name"]], ["categ_id", "=", vals.get("categ_id", False)]])
    nb_new += cree
    nb_maj += not cree

    # Lignes d'attributs (ajoute les valeurs manquantes)
    for ligne in t["lignes"]:
        att = attributs[ligne["attribut"]]
        vids = [valeurs[v] for v in ligne["valeurs"]]
        ex = kw("product.template.attribute.line", "search_read",
                [[["product_tmpl_id", "=", tmpl], ["attribute_id", "=", att]]], {"fields": ["value_ids"]})
        if not ex:
            kw("product.template", "write", [[tmpl], {"attribute_line_ids": [
                (0, 0, {"attribute_id": att, "value_ids": [(6, 0, vids)]})]}])
        elif set(vids) - set(ex[0]["value_ids"]):
            kw("product.template.attribute.line", "write",
               [[ex[0]["id"]], {"value_ids": [(4, v) for v in vids if v not in ex[0]["value_ids"]]}])

    # Supplements de prix par valeur
    for e in t["extras"]:
        ptav = kw("product.template.attribute.value", "search",
                  [[["product_tmpl_id", "=", tmpl], ["product_attribute_value_id", "=", valeurs[e["valeur"]]]]])
        if ptav:
            kw("product.template.attribute.value", "write", [ptav, {"price_extra": e["price_extra"]}])

    # Variantes : retrouvees par leurs valeurs d'attributs
    cibles = {}
    for pv in kw("product.product", "search_read", [[["product_tmpl_id", "=", tmpl]]],
                 {"fields": ["product_template_attribute_value_ids"], "context": {"active_test": False}}):
        ptavs = kw("product.template.attribute.value", "read",
                   [pv["product_template_attribute_value_ids"], ["product_attribute_value_id"]])
        cibles[frozenset(x["product_attribute_value_id"][0] for x in ptavs)] = pv["id"]
    for v in t["variantes"]:
        pid = cibles.get(frozenset(valeurs[c] for c in v["valeurs"]))
        if not pid:
            print(f"! Variante introuvable pour {vals['name']} : {v['valeurs']}")
            continue
        variantes[v["cle"]] = pid
        kw("product.product", "write", [[pid], {k: x for k, x in v["vals"].items() if k in VF}])
    if tracking and "tracking" in TF:
        kw("product.template", "write", [[tmpl], {"tracking": tracking}])
print(f"Produits : {nb_new} crees, {nb_maj} mis a jour, {len(variantes)} variantes")

# ---------------------------------------------------------------- 4) Listes de prix (regles)
if modele_existe("product.pricelist"):
    IF = champs("product.pricelist.item")
    for l in DATA["listes"]:
        pl = liste_de_prix(l["nom"], l["devise"])
        kw("product.pricelist", "write", [[pl], {"sequence": l["sequence"]}])
        for it in l["regles"]:
            vals = {k: v for k, v in it["vals"].items() if k in IF}
            vals["pricelist_id"] = pl
            if it.get("produit"):
                tm = kw("ir.model.data", "search_read",
                        [[["module", "=", MODULE], ["name", "=", it["produit"]]]], {"fields": ["res_id"]})
                vals["product_tmpl_id"] = tm[0]["res_id"] if tm else False
            if it.get("variante"):
                vals["product_id"] = variantes.get(it["variante"], False)
            if it.get("categorie"):
                vals["categ_id"] = categories.get(it["categorie"], False)
            ecrire_ou_creer(it["cle"], "product.pricelist.item", vals)
    if DATA["listes"]:
        activer_listes_de_prix()
        print(f"{len(DATA['listes'])} listes de prix")

# ---------------------------------------------------------------- 5) Numeros de serie / lots
LF = champs("stock.lot")
lots = {}
company = kw("res.users", "read", [[uid], ["company_id"]])[0]["company_id"][0]
for lt in DATA["lots"]:
    pid = variantes.get(lt["variante"])
    if not pid:
        continue
    vals = {k: v for k, v in lt["vals"].items() if k in LF}
    vals.update(product_id=pid, company_id=company)
    lots[lt["cle"]], _ = ecrire_ou_creer(lt["cle"], "stock.lot", vals,
                                         [["name", "=", vals["name"]], ["product_id", "=", pid]])
print(f"{len(lots)} numeros de serie / lots")

# ---------------------------------------------------------------- 6) Stock
wh = kw("stock.warehouse", "search_read", [[["company_id", "=", company]]],
        {"fields": ["lot_stock_id"], "limit": 1})
STOCK = wh[0]["lot_stock_id"][0]
emplacements = {}

def emplacement(nom):
    if nom not in emplacements:
        ids = kw("stock.location", "search", [[["complete_name", "=", nom], ["usage", "=", "internal"]]])
        emplacements[nom] = ids[0] if ids else STOCK
    return emplacements[nom]

a_appliquer = []
for q in DATA["stock"]:
    pid = variantes.get(q["variante"])
    lot = lots.get(q["lot"], False) if q["lot"] else False
    if not pid or (q["lot"] and not lot):
        continue
    loc = emplacement(q["emplacement"])
    ex = kw("stock.quant", "search", [[["product_id", "=", pid], ["lot_id", "=", lot], ["location_id", "=", loc]]])
    if ex:
        kw("stock.quant", "write", [ex[:1], {"inventory_quantity": q["quantite"]}], INV)
        a_appliquer.append(ex[0])
    else:
        a_appliquer.append({"product_id": pid, "lot_id": lot, "location_id": loc,
                            "inventory_quantity": q["quantite"]})
for i in range(0, len(a_appliquer), 200):
    lot_q = a_appliquer[i:i + 200]
    ids = [x for x in lot_q if isinstance(x, int)]
    nouveaux = [x for x in lot_q if isinstance(x, dict)]
    if nouveaux:
        ids += kw("stock.quant", "create", [nouveaux], INV)
    kw("stock.quant", "action_apply_inventory", [ids])
print(f"{len(a_appliquer)} lignes de stock mises a jour")

# ---------------------------------------------------------------- 7) Interventions (module Suivi des machines)
if DATA["interventions"] and modele_existe("machine.intervention"):
    nb = 0
    for it in DATA["interventions"]:
        lot = lots.get(it.pop("lot"))
        if not lot:
            continue
        vals = dict(it.pop("vals"), lot_id=lot)
        for champ_p, cle_p in (("partner_id", it.pop("client")),):
            if cle_p:
                r = kw("ir.model.data", "search_read",
                       [[["module", "=", "migration_contacts"], ["name", "=", cle_p]]], {"fields": ["res_id"]})
                vals[champ_p] = r[0]["res_id"] if r else False
        ecrire_ou_creer(it["cle"], "machine.intervention", vals)
        nb += 1
    print(f"{nb} interventions")

print("\nTermine.")
