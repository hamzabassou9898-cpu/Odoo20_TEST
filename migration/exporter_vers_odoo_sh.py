#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lit TON Odoo local et genere deux fichiers autonomes a lancer sur Odoo.sh :

  contacts_odoo.py   : contacts (entreprises, bannieres, commerces, personnes), tous les champs,
                       etiquettes, conditions de paiement, listes de prix, cadre Code client,
                       onglet "Autres informations", vue Hierarchie
  inventaire_odoo.py : categories, produits, variantes, prix, listes de prix, numeros de serie,
                       stock, interventions (module Suivi des machines)

Chaque fichier contient TOUTES ses donnees : il suffit de le copier et de le lancer.
Ce script ne modifie rien dans ton Odoo local.

Usage : python3 exporter_vers_odoo_sh.py
"""
import os
import pprint
import sys
import xmlrpc.client

# ===================== TON ODOO LOCAL (source) =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
IMAGES   = True    # inclure les images des produits
# ===================================================================

HERE = os.path.dirname(os.path.abspath(__file__))
uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee sur l'Odoo local - verifie URL / DB / USERNAME / PASSWORD."); sys.exit(1)
M = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
TOUT = {"context": {"active_test": False}}


def kw(model, method, args, opts=None):
    return M.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})


def existe(model):
    return bool(kw("ir.model", "search", [[["model", "=", model]]]))


def lire(model, domaine, champs_voulus, **opts):
    F = kw(model, "fields_get", [[]], {"attributes": ["type"]})
    champs = [c for c in champs_voulus if c in F]
    return kw(model, "search_read", [domaine], {"fields": champs, **TOUT, **opts}), F


def m2o(v):
    return v[0] if v else False


def nom(v):
    return v[1] if v else False


def profondeur(rec_id, parents):
    d, p = 0, parents.get(rec_id)
    while p:
        d, p = d + 1, parents.get(p)
    return d


# ============================================================ CONTACTS
def exporter_contacts():
    exclus = {m2o(u["partner_id"]) for u in kw("res.users", "search_read", [[]], {"fields": ["partner_id"], **TOUT})}
    exclus |= {m2o(c["partner_id"]) for c in kw("res.company", "search_read", [[]], {"fields": ["partner_id"]})}
    champs_p = ["name", "ref", "type", "street", "street2", "city", "zip", "phone", "email", "website",
                "function", "lang", "comment", "vat", "active", "x_nom_legal", "x_autres_numeros",
                "company_registry", "parent_id", "country_id", "state_id", "category_id",
                "property_payment_term_id", "property_product_pricelist", "specific_property_product_pricelist"]
    parts, _ = lire("res.partner", [["id", "not in", list(exclus)]], champs_p)
    ids = {p["id"] for p in parts}
    parents = {p["id"]: m2o(p["parent_id"]) if m2o(p["parent_id"]) in ids else False for p in parts}
    parts.sort(key=lambda p: (profondeur(p["id"], parents), p["id"]))

    pays = {c["id"]: c["code"] for c in kw("res.country", "search_read", [[]], {"fields": ["code"]})}
    etats = {s["id"]: s["code"] for s in kw("res.country.state", "search_read", [[]], {"fields": ["code"]})}

    cats, _ = lire("res.partner.category", [], ["name", "parent_id", "color"])
    cparents = {c["id"]: m2o(c["parent_id"]) for c in cats}
    cats.sort(key=lambda c: (profondeur(c["id"], cparents), c["id"]))
    etiquettes = [{"cle": f"pcat_{c['id']}", "nom": c["name"], "couleur": c.get("color", 0),
                   "parent": f"pcat_{m2o(c['parent_id'])}" if m2o(c["parent_id"]) else None} for c in cats]

    termes_ids = {m2o(p.get("property_payment_term_id")) for p in parts} - {False}
    termes, noms_termes = [], {}
    if termes_ids:
        for t in kw("account.payment.term", "read", [list(termes_ids), ["name", "line_ids"]]):
            lignes, _ = lire("account.payment.term.line", [["id", "in", t["line_ids"]]],
                             ["value", "value_amount", "nb_days", "delay_type", "days_next_month"])
            termes.append({"nom": t["name"], "lignes": [{k: v for k, v in l.items() if k != "id"} for l in lignes]})
            noms_termes[t["id"]] = t["name"]

    listes, noms_listes = [], {}
    if existe("product.pricelist"):
        pls, _ = lire("product.pricelist", [], ["name", "currency_id", "sequence"])
        # le nom affiche contient la devise ("Prix speciaux (USD)") : on garde le vrai nom
        noms_listes = {p["id"]: p["name"] for p in pls}
        listes = [{"nom": p["name"], "devise": nom(p.get("currency_id")), "sequence": p.get("sequence", 10)}
                  for p in pls]

    partenaires = []
    for p in parts:
        liste = noms_listes.get(m2o(p.get("specific_property_product_pricelist"))
                                or m2o(p.get("property_product_pricelist")))
        vals = {k: v for k, v in p.items() if k not in (
            "id", "parent_id", "country_id", "state_id", "category_id", "property_payment_term_id",
            "property_product_pricelist", "specific_property_product_pricelist")}
        vals.update(cle=f"partner_{p['id']}", parent=f"partner_{parents[p['id']]}" if parents[p["id"]] else None,
                    pays=pays.get(m2o(p.get("country_id"))), etat=etats.get(m2o(p.get("state_id"))),
                    etiquettes=[f"pcat_{c}" for c in p.get("category_id", [])],
                    terme=noms_termes.get(m2o(p.get("property_payment_term_id"))), liste=liste)
        partenaires.append(vals)

    langues = sorted({p.get("lang") for p in parts if p.get("lang")})
    return {"langues": langues, "etiquettes": etiquettes, "termes": termes, "listes": listes,
            "partenaires": partenaires, "hierarchie": True}


# ============================================================ INVENTAIRE
def exporter_inventaire():
    cats, CF = lire("product.category", [], ["name", "parent_id", "suivi_machine"])
    cparents = {c["id"]: m2o(c["parent_id"]) for c in cats}
    cats.sort(key=lambda c: (profondeur(c["id"], cparents), c["id"]))
    categories = [{"cle": f"categ_{c['id']}", "nom": c["name"],
                   "parent": f"categ_{m2o(c['parent_id'])}" if m2o(c["parent_id"]) else None,
                   "suivi_machine": c.get("suivi_machine")} for c in cats]

    etiquettes = []
    if existe("product.tag"):
        tg, _ = lire("product.tag", [], ["name", "color"])
        etiquettes = [{"cle": f"ptag_{t['id']}", "nom": t["name"], "couleur": t.get("color", 0)} for t in tg]

    atts, _ = lire("product.attribute", [], ["name", "create_variant", "display_type", "value_ids"])
    attributs = []
    for a in atts:
        vals, _ = lire("product.attribute.value", [["attribute_id", "=", a["id"]]], ["name", "sequence", "html_color"])
        attributs.append({"cle": f"attr_{a['id']}", "nom": a["name"], "create_variant": a.get("create_variant"),
                          "display_type": a.get("display_type"),
                          "valeurs": [{"cle": f"val_{v['id']}", "nom": v["name"], "sequence": v.get("sequence", 0),
                                       "html_color": v.get("html_color")} for v in vals]})

    # Produits crees par des modules Odoo (acompte, livraison...) : pas exportes
    systeme = {d["res_id"] for d in kw("ir.model.data", "search_read",
               [[["model", "=", "product.template"], ["module", "not like", "migration"],
                 ["module", "!=", "__export__"]]], {"fields": ["res_id"]})}
    champs_t = ["name", "type", "is_storable", "tracking", "sale_ok", "purchase_ok", "list_price",
                "description", "description_sale", "description_purchase", "weight", "volume", "rent_ok",
                "invoice_policy", "active", "categ_id", "uom_id", "product_tag_ids", "attribute_line_ids",
                "product_variant_ids", "service_type", "expense_policy"]
    tmpls, _ = lire("product.template", [["id", "not in", list(systeme)]], champs_t)
    champs_v = ["default_code", "barcode", "standard_price", "active", "weight", "volume",
                "product_template_attribute_value_ids"]
    produits = []
    for t in tmpls:
        lignes = []
        for l in kw("product.template.attribute.line", "read", [t.get("attribute_line_ids", []),
                                                                ["attribute_id", "value_ids"]]):
            lignes.append({"attribut": f"attr_{m2o(l['attribute_id'])}", "valeurs": [f"val_{v}" for v in l["value_ids"]]})
        ptavs = kw("product.template.attribute.value", "search_read",
                   [[["product_tmpl_id", "=", t["id"]]]], {"fields": ["product_attribute_value_id", "price_extra"]})
        ptav_val = {x["id"]: m2o(x["product_attribute_value_id"]) for x in ptavs}
        extras = [{"valeur": f"val_{ptav_val[x['id']]}", "price_extra": x["price_extra"]}
                  for x in ptavs if x.get("price_extra")]
        vars_, _ = lire("product.product", [["product_tmpl_id", "=", t["id"]]], champs_v)
        variantes = [{"cle": f"var_{v['id']}",
                      "valeurs": [f"val_{ptav_val[x]}" for x in v.get("product_template_attribute_value_ids", [])
                                  if x in ptav_val],
                      "vals": {k: x for k, x in v.items() if k not in ("id", "product_template_attribute_value_ids")}}
                     for v in vars_]
        image = None
        if IMAGES:
            img = kw("product.template", "read", [[t["id"]], ["image_1920"]])[0].get("image_1920")
            image = img or None
        vals = {k: v for k, v in t.items() if k not in (
            "id", "categ_id", "uom_id", "product_tag_ids", "attribute_line_ids", "product_variant_ids")}
        produits.append({"cle": f"tmpl_{t['id']}", "vals": vals, "categorie": f"categ_{m2o(t.get('categ_id'))}",
                         "unite": nom(t.get("uom_id")), "etiquettes": [f"ptag_{x}" for x in t.get("product_tag_ids", [])],
                         "image": image, "lignes": lignes, "extras": extras, "variantes": variantes})

    listes = []
    if existe("product.pricelist"):
        pls, _ = lire("product.pricelist", [], ["name", "currency_id", "sequence", "item_ids"])
        for p in pls:
            items, _ = lire("product.pricelist.item", [["pricelist_id", "=", p["id"]]],
                            ["applied_on", "compute_price", "fixed_price", "percent_price", "min_quantity", "base",
                             "price_discount", "price_surcharge", "price_round", "price_min_margin",
                             "price_max_margin", "date_start", "date_end", "product_tmpl_id", "product_id", "categ_id"])
            regles = [{"cle": f"plitem_{i['id']}",
                       "produit": f"tmpl_{m2o(i['product_tmpl_id'])}" if m2o(i.get("product_tmpl_id")) else None,
                       "variante": f"var_{m2o(i['product_id'])}" if m2o(i.get("product_id")) else None,
                       "categorie": f"categ_{m2o(i['categ_id'])}" if m2o(i.get("categ_id")) else None,
                       "vals": {k: v for k, v in i.items() if k not in ("id", "product_tmpl_id", "product_id", "categ_id")}}
                      for i in items]
            listes.append({"nom": p["name"], "devise": nom(p.get("currency_id")), "sequence": p.get("sequence", 10),
                           "regles": regles})

    lts, _ = lire("stock.lot", [], ["name", "ref", "note", "product_id", "machine_etat",
                                    "intervalle_entretien", "date_mise_service"])
    lots = [{"cle": f"lot_{l['id']}", "variante": f"var_{m2o(l['product_id'])}",
             "vals": {k: v for k, v in l.items() if k not in ("id", "product_id")}} for l in lts]

    qts, _ = lire("stock.quant", [["location_id.usage", "=", "internal"], ["quantity", "!=", 0]],
                  ["product_id", "lot_id", "location_id", "quantity"])
    stock = [{"variante": f"var_{m2o(q['product_id'])}", "lot": f"lot_{m2o(q['lot_id'])}" if m2o(q["lot_id"]) else None,
              "emplacement": nom(q["location_id"]), "quantite": q["quantity"]} for q in qts]

    interventions = []
    if existe("machine.intervention"):
        its, _ = lire("machine.intervention", [], ["name", "type", "date", "state", "description", "lot_id",
                                                   "partner_id"])
        interventions = [{"cle": f"interv_{i['id']}", "lot": f"lot_{m2o(i['lot_id'])}",
                          "client": f"partner_{m2o(i['partner_id'])}" if m2o(i.get("partner_id")) else None,
                          "vals": {k: v for k, v in i.items() if k not in ("id", "lot_id", "partner_id")}}
                         for i in its]

    return {"categories": categories, "etiquettes": etiquettes, "attributs": attributs, "produits": produits,
            "listes": listes, "lots": lots, "stock": stock, "interventions": interventions}


# ============================================================ ECRITURE DES FICHIERS
ENTETE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
{titre}
Genere automatiquement par exporter_vers_odoo_sh.py depuis {source}.
Contient toutes les donnees : aucun autre fichier n'est necessaire.
Relançable sans risque : ce qui existe deja est mis a jour, pas duplique.
{ordre}
Usage : python3 {fichier}
"""

# ===================== ODOO.SH (destination) - A REMPLIR =====================
URL      = "https://TON-PROJET.odoo.com"   # adresse de ta base Odoo.sh
DB       = "TON-PROJET-main-123456"         # nom de la base (Odoo.sh > ta branche > Base de donnees)
USERNAME = "ton.courriel@exemple.com"       # identifiant de connexion Odoo
PASSWORD = "CLE_API"                        # cle API : Preferences > Securite du compte > Nouvelle cle API
# =============================================================================

'''


def ecrire(fichier, titre, ordre, data, specifique):
    with open(os.path.join(HERE, "importeur_commun.py"), encoding="utf-8") as f:
        commun = f.read()
    with open(os.path.join(HERE, specifique), encoding="utf-8") as f:
        code = f.read()
    chemin = os.path.join(HERE, fichier)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(ENTETE.format(titre=titre, source=f"{URL} / {DB}", ordre=ordre, fichier=fichier))
        f.write("DATA = " + pprint.pformat(data, width=110, sort_dicts=False) + "\n\n")
        f.write(commun + "\n\n" + code)
    print(f"Ecrit : {chemin} ({os.path.getsize(chemin) // 1024} Ko)")


c = exporter_contacts()
print(f"Contacts : {len(c['partenaires'])} contacts, {len(c['etiquettes'])} etiquettes, "
      f"{len(c['termes'])} conditions de paiement, {len(c['listes'])} listes de prix")
ecrire("contacts_odoo.py", "Contacts : tous les contacts et la configuration de la fiche contact.",
       "A lancer EN PREMIER (avant inventaire_odoo.py).", c, "importeur_contacts.py")

inv = exporter_inventaire()
print(f"Inventaire : {len(inv['categories'])} categories, {len(inv['produits'])} produits, "
      f"{sum(len(p['variantes']) for p in inv['produits'])} variantes, {len(inv['lots'])} numeros de serie, "
      f"{len(inv['stock'])} lignes de stock, {len(inv['interventions'])} interventions")
ecrire("inventaire_odoo.py", "Inventaire : categories, produits, variantes, prix, numeros de serie et stock.",
       "A lancer APRES contacts_odoo.py (les interventions retrouvent leurs clients).",
       inv, "importeur_inventaire.py")
