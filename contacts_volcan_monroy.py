#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importe les clients Volcan dans Odoo (Contacts), a partir de clients_volcan_data.json
(produit par prep_clients_volcan.py).

Ce que fait le script :
  1. Champs personnalises sur le contact (onglet "Volcan / Monroy") :
     Banniere (societe parente), Nom legal, Anciens # client, Soumission,
     Livraison (Monroy / Frais), Telephones (detail), Courriels (tous)
  2. Etiquettes : Region, Route livraison, Saison, Type, Banniere, Produit
  3. Conditions de paiement : PPA, Cheque, Net 7 jours, Depot bancaire
  4. Listes de prix : regulier, speciaux, Gaspesie, Harnois, Parkland, Jean Coutu, hiver
  5. Langue francais (Canada)
  6. Fiches bannieres (Harnois, Filgo, Parkland, ...)
  7. 1 fiche par # client, liee a sa banniere, adresse QC / Canada, telephone,
     courriel, reference, conditions de paiement, liste de prix, etiquettes, notes
  8. Les contacts-personnes (M. X, gerant...) rattaches a chaque commerce

Odoo 20 : un contact place SOUS un autre (champ parent) devient une simple adresse
de celui-ci et lui transfere facturation, conditions de paiement et liste de prix.
Chaque commerce doit rester son propre client -> la banniere est liee par le champ
"Banniere (societe parente)" et non par le champ parent natif.

Relançable sans risque : tout est retrouve par nom / reference et mis a jour.
Usage : python3 contacts_volcan_monroy.py
"""
import json
import os
import sys
import xmlrpc.client

# ===================== À REMPLIR =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
LANGUE   = "fr_CA"
# =====================================================

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "clients_volcan_data.json"), encoding="utf-8") as f:
    CLIENTS = json.load(f)

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie DB / USERNAME / PASSWORD."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

def kw(model, method, args, opts=None):
    return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})

def model_existe(model):
    return bool(kw("ir.model", "search", [[["model", "=", model]]]))

def trouver_ou_creer(model, domaine, vals):
    ids = kw(model, "search", [domaine], {"limit": 1, "context": {"active_test": False}})
    if ids:
        return ids[0], False
    return kw(model, "create", [vals]), True

# ---------------------------------------------------------------- 1) Champs
CHAMPS = [
    ("x_banniere_id", "Bannière (société parente)", "many2one", "res.partner"),
    ("x_nom_legal", "Nom légal", "char", None),
    ("x_anciens_no_client", "Anciens # client", "char", None),
    ("x_soumission", "Soumission", "char", None),
    ("x_livraison", "Livraison", "selection", [("monroy", "Monroy"), ("frais", "Frais de livraison")]),
    ("x_telephones", "Téléphones (détail)", "text", None),
    ("x_courriels", "Courriels (tous)", "text", None),
    ("x_commerce_ids", "Commerces de la bannière", "one2many", ("res.partner", "x_banniere_id")),
]
partner_model_id = kw("ir.model", "search", [[["model", "=", "res.partner"]]])[0]
for name, label, ttype, extra in CHAMPS:
    if kw("ir.model.fields", "search", [[["model", "=", "res.partner"], ["name", "=", name]]]):
        continue
    vals = {"name": name, "field_description": label, "ttype": ttype,
            "model_id": partner_model_id, "state": "manual"}
    if ttype == "selection":
        vals["selection_ids"] = [(0, 0, {"value": v, "name": n, "sequence": i})
                                 for i, (v, n) in enumerate(extra)]
    elif ttype == "many2one":
        vals.update(relation=extra, on_delete="set null")
    elif ttype == "one2many":
        vals.update(relation=extra[0], relation_field=extra[1])
    kw("ir.model.fields", "create", [vals])
    print(f"Champ cree : {label} ({name})")

# Onglet "Volcan / Monroy" sur la fiche contact
base_form = kw("ir.model.data", "search_read",
               [[["module", "=", "base"], ["name", "=", "view_partner_form"]]], {"fields": ["res_id"]})[0]["res_id"]
ARCH = """<data>
  <xpath expr="//notebook" position="inside">
    <page string="Volcan / Monroy" name="volcan_monroy">
      <group>
        <group string="Identification">
          <field name="x_banniere_id"/>
          <field name="x_nom_legal"/>
          <field name="x_anciens_no_client"/>
          <field name="x_soumission"/>
          <field name="x_livraison"/>
        </group>
        <group string="Coordonnées complètes">
          <field name="x_telephones"/>
          <field name="x_courriels"/>
        </group>
      </group>
      <field name="x_commerce_ids" invisible="not x_commerce_ids" readonly="1">
        <list>
          <field name="ref"/>
          <field name="name"/>
          <field name="city"/>
          <field name="phone"/>
        </list>
      </field>
    </page>
  </xpath>
</data>"""
vue = kw("ir.ui.view", "search", [[["name", "=", "res.partner.form.volcan"]]])
if vue:
    kw("ir.ui.view", "write", [vue, {"arch_db": ARCH}])
else:
    kw("ir.ui.view", "create", [{"name": "res.partner.form.volcan", "model": "res.partner",
                                 "inherit_id": base_form, "type": "form", "arch_db": ARCH}])
    print("Onglet 'Volcan / Monroy' ajoute a la fiche contact")

PF = kw("res.partner", "fields_get", [[]], {"attributes": ["type"]})

# ---------------------------------------------------------------- 2) Etiquettes
_tags = {}
def etiquette(parent, nom, couleur):
    if not nom:
        return None
    key = (parent, nom)
    if key not in _tags:
        pid, _ = trouver_ou_creer("res.partner.category",
                                  [["name", "=", parent], ["parent_id", "=", False]],
                                  {"name": parent, "color": couleur})
        tid, _ = trouver_ou_creer("res.partner.category",
                                  [["name", "=", nom], ["parent_id", "=", pid]],
                                  {"name": nom, "parent_id": pid, "color": couleur})
        _tags[key] = tid
    return _tags[key]

# ---------------------------------------------------------------- 3) Conditions de paiement
TERMES_JOURS = {"PPA": 0, "Chèque": 0, "Net 7 jours": 7, "Dépôt bancaire": 0}
termes = {}
if "property_payment_term_id" in PF and model_existe("account.payment.term"):
    LF = kw("account.payment.term.line", "fields_get", [[]], {"attributes": ["type"]})
    champ_jours = "nb_days" if "nb_days" in LF else "days"
    for nom, jours in TERMES_JOURS.items():
        ligne = {"value": "percent", "value_amount": 100, champ_jours: jours}
        if "value" not in LF:
            ligne = {champ_jours: jours}
        termes[nom], cree = trouver_ou_creer("account.payment.term", [["name", "=", nom]],
                                             {"name": nom, "line_ids": [(0, 0, ligne)]})
        if cree:
            print(f"Condition de paiement creee : {nom}")
else:
    print("! Module Facturation absent : conditions de paiement ignorees")

# ---------------------------------------------------------------- 4) Listes de prix
listes = {}
# Odoo 18+ : la liste choisie a la main est stockee dans specific_property_product_pricelist
champ_liste = ("specific_property_product_pricelist" if "specific_property_product_pricelist" in PF
               else "property_product_pricelist")
if "property_product_pricelist" in PF:
    company = kw("res.users", "read", [[uid], ["company_id"]])[0]["company_id"][0]
    devise = kw("res.company", "read", [[company], ["currency_id"]])[0]["currency_id"][0]
    for nom in sorted({c["pricelist"] for c in CLIENTS if c["pricelist"]}):
        listes[nom], cree = trouver_ou_creer("product.pricelist", [["name", "=", nom]],
                                             {"name": nom, "currency_id": devise})
        if cree:
            print(f"Liste de prix creee : {nom} (sans regle = prix de vente du produit)")
    # Client sans liste de prix -> Odoo prend la 1re liste : "Prix régulier" en tete
    for nom, lid in listes.items():
        kw("product.pricelist", "write", [[lid], {"sequence": 1 if nom == "Prix régulier" else 10}])
    # Sans l'option "Listes de prix" (Ventes > Configuration > Parametres),
    # Odoo ignore la liste de prix du client
    RS = kw("res.config.settings", "fields_get", [[]], {"attributes": ["type"]})
    if "group_product_pricelist" in RS:
        if not kw("res.config.settings", "default_get", [["group_product_pricelist"]]).get("group_product_pricelist"):
            wiz = kw("res.config.settings", "create", [{"group_product_pricelist": True}])
            kw("res.config.settings", "execute", [[wiz]])
            print("Option 'Listes de prix' activee")
else:
    print("! Module Ventes absent : listes de prix ignorees")

# ---------------------------------------------------------------- 5) Langue
lang = kw("res.lang", "search_read", [[["code", "=", LANGUE], ["active", "in", [True, False]]]],
          {"fields": ["active"]})
if lang and not lang[0]["active"]:
    wiz = kw("base.language.install", "create", [{"lang_ids": [(6, 0, [lang[0]["id"]])]}])
    kw("base.language.install", "lang_install", [[wiz]])
    print(f"Langue activee : {LANGUE}")
langue_ok = bool(lang)

# ---------------------------------------------------------------- Pays / province / titres
canada = kw("res.country", "search", [[["code", "=", "CA"]]])[0]
quebec = kw("res.country.state", "search", [[["code", "=", "QC"], ["country_id", "=", canada]]])
quebec = quebec[0] if quebec else False
titres = {}
if "title" in PF:
    for t in ("Madame", "Monsieur"):
        ids = kw("res.partner.title", "search", [[["name", "=", t]]])
        titres[t] = ids[0] if ids else kw("res.partner.title", "create", [{"name": t}])
a_mobile = "mobile" in PF

def html(lignes):
    from html import escape
    return "".join(f"<p>{escape(l)}</p>" for l in lignes) or False

def ecrire_ou_creer(domaine, vals):
    ids = kw("res.partner", "search", [domaine], {"limit": 1, "context": {"active_test": False}})
    if ids:
        kw("res.partner", "write", [ids, vals])
        return ids[0], False
    return kw("res.partner", "create", [vals]), True

# ---------------------------------------------------------------- 6) Bannieres
parents = {}
for nom in sorted({c["parent"] for c in CLIENTS if c["parent"]}):
    tag = etiquette("Bannière", nom, 4)
    vals = {"name": nom, "country_id": canada, "category_id": [(4, tag)]}
    if langue_ok:
        vals["lang"] = LANGUE
    parents[nom], cree = ecrire_ou_creer([["name", "=", nom], ["parent_id", "=", False],
                                          ["category_id", "in", [tag]]], vals)
    if cree:
        print(f"Banniere creee : {nom}")

# ---------------------------------------------------------------- 7-8) Commerces + contacts
nb_new = nb_maj = nb_pers = 0
for c in CLIENTS:
    tags = [
        etiquette("Région", c["region"], 10),
        etiquette("Route livraison", c["route"], 2),
        etiquette("Saison", f"Saison {c['saison']}" if c["saison"] else None, 3),
        etiquette("Type", f"Type {c['type']}" if c["type"] else None, 5),
        etiquette("Bannière", c["parent"], 4),
        etiquette("Bannière", c["statut_banniere"], 4),
        etiquette("Produit", "Slush" if c["slush"] else None, 1),
    ]
    vals = {
        "name": c["nom"],
        "x_banniere_id": parents.get(c["parent"], False),
        "ref": c["ref"],
        "street": c["street"] or False,
        "city": c["city"] or False,
        "zip": c["zip"] or False,
        "state_id": quebec,
        "country_id": canada,
        "phone": c["phone"] or False,
        "email": c["email"] or False,
        "category_id": [(6, 0, [t for t in tags if t])],
        "comment": html(c["notes"]),
        "x_nom_legal": c["nom_legal"] or False,
        "x_anciens_no_client": c["anciens_no"] or False,
        "x_soumission": c["soumission"] or False,
        "x_livraison": c["livraison"] or False,
        "x_telephones": c["telephones"] or False,
        "x_courriels": c["courriels"] or False,
    }
    if a_mobile:
        vals["mobile"] = c["mobile"] or False
    if langue_ok:
        vals["lang"] = LANGUE
    if termes:
        vals["property_payment_term_id"] = termes.get(c["terme"], False)
    if listes and c["pricelist"]:
        vals[champ_liste] = listes[c["pricelist"]]

    pid, cree = ecrire_ou_creer([["ref", "=", c["ref"]], ["parent_id", "=", False]], vals)
    nb_new += cree
    nb_maj += not cree

    for p in c["contacts"]:
        pv = {"name": p["nom"], "parent_id": pid, "type": "contact",
              "function": p["fonction"] or False}
        if p.get("mobile"):
            pv["mobile" if a_mobile else "phone"] = p["mobile"]
        if titres and p["titre"]:
            pv["title"] = titres[p["titre"]]
        if langue_ok:
            pv["lang"] = LANGUE
        ecrire_ou_creer([["name", "=", p["nom"]], ["parent_id", "=", pid]], pv)
        nb_pers += 1

print(f"\nTermine : {nb_new} commerces crees, {nb_maj} mis a jour, "
      f"{len(parents)} bannieres, {nb_pers} contacts-personnes.")
