#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importe les clients dans Odoo 20 (Contacts), a partir de contacts_data.json
(produit par prep_contacts.py). Champs natifs, plus un onglet "Autres informations"
(Nom legal, Autres numeros) et le Code client (= Reference) en cadre en haut de la fiche.

  Nom du commerce            -> Nom
  Banniere                   -> Societe parente (Harnois, Filgo, Parkland...)
  # client                   -> Reference (affichee "Code client" en cadre, en haut)
  Nom legal / Autres numeros -> onglet "Autres informations"
  Adresse / Ville / CP       -> Adresse + Province Quebec + Pays Canada
  # telephone / Courriel     -> Telephone / Courriel
  Contact (M. X, gerant)     -> Contacts-personnes rattaches au commerce
  Terme paiement             -> Conditions de paiement
  Prix regulier / speciaux.. -> Liste de prix
  (taxes)                    -> Position fiscale du Quebec, si elle existe
  Ville (secteur)            -> Etiquette, ex. "Québec (Lebourgneuf)", "Lévis (St-Nicolas)"
  Langue                     -> Francais (Canada)
  Anciens #, autres courriels, route livraison, Corpo / Affilie, consignes -> Notes

Odoo 20 : un commerce place sous sa banniere devient une adresse de livraison de
celle-ci. Conditions de paiement, liste de prix et position fiscale sont alors
celles de la banniere : le script y met la valeur la plus courante de ses commerces.
Les commerces independants gardent les leurs.

Nettoie aussi ce qu'avait ajoute la version precedente (onglet, champs x_...).
Relançable sans risque : tout est retrouve par reference / nom et mis a jour.
Usage : python3 import_contacts.py
"""
import json
import os
import sys
import xmlrpc.client
from collections import Counter
from html import escape

# ===================== À REMPLIR =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
LANGUE   = "fr_CA"
# =====================================================

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "contacts_data.json"), encoding="utf-8") as f:
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

def ecrire_ou_creer(domaine, vals):
    ids = kw("res.partner", "search", [domaine], {"limit": 1, "context": {"active_test": False}})
    if ids:
        kw("res.partner", "write", [ids, vals])
        return ids[0], False
    return kw("res.partner", "create", [vals]), True

def plus_courant(valeurs):
    valeurs = [v for v in valeurs if v]
    return Counter(valeurs).most_common(1)[0][0] if valeurs else None

BANNIERES = sorted({c["parent"] for c in CLIENTS if c["parent"]})

# ---------------------------------------------------------------- 0) Nettoyage version precedente
vue = kw("ir.ui.view", "search", [[["name", "=", "res.partner.form.volcan"]]])
if vue:
    kw("ir.ui.view", "unlink", [vue])
    print("Ancien onglet retire de la fiche contact")
ANCIENS_CHAMPS = ["x_commerce_ids", "x_banniere_id", "x_anciens_no_client",
                  "x_soumission", "x_livraison", "x_telephones", "x_courriels"]
for name in ANCIENS_CHAMPS:   # x_commerce_ids d'abord : il depend de x_banniere_id
    ids = kw("ir.model.fields", "search", [[["model", "=", "res.partner"], ["name", "=", name]]])
    if ids:
        kw("ir.model.fields", "unlink", [ids])
        print(f"Ancien champ personnalise supprime : {name}")
# Les etiquettes ne servent plus qu'a l'endroit (ville / secteur) : retirer les anciennes categories
racines = kw("res.partner.category", "search", [[["parent_id", "=", False], ["name", "in",
             ["Région", "Route livraison", "Saison", "Type", "Bannière", "Produit"]]]])
a_supprimer = []
if racines:
    a_supprimer = kw("res.partner.category", "search", [[["parent_id", "in", racines]]]) + racines
if a_supprimer:
    kw("res.partner.category", "unlink", [a_supprimer])
    print(f"{len(a_supprimer)} anciennes etiquettes supprimees")

# ---------------------------------------------------------------- Onglet "Autres informations"
partner_model_id = kw("ir.model", "search", [[["model", "=", "res.partner"]]])[0]
for name, label, ttype in [("x_nom_legal", "Nom légal", "char"),
                           ("x_autres_numeros", "Autres numéros", "text")]:
    if not kw("ir.model.fields", "search", [[["model", "=", "res.partner"], ["name", "=", name]]]):
        kw("ir.model.fields", "create", [{"name": name, "field_description": label, "ttype": ttype,
                                          "model_id": partner_model_id, "state": "manual"}])
        print(f"Champ cree : {label}")
base_form = kw("ir.model.data", "search_read",
               [[["module", "=", "base"], ["name", "=", "view_partner_form"]]], {"fields": ["res_id"]})[0]["res_id"]
ARCH = """<data>
  <!-- Code client (= Reference) en grand, dans un cadre, en haut a droite de la fiche -->
  <xpath expr="//field[@name='image_1920']/.." position="inside">
    <div class="border border-2 border-dark rounded-3 px-3 py-2 text-center flex-shrink-0"
         style="width: 210px;">
      <div class="text-muted text-uppercase small fw-bold">Code client</div>
      <style>.o_code_client input { font-weight: 700 !important; font-size: 1.75rem; text-align: center; }</style>
      <field name="ref" class="o_code_client w-100" placeholder="Code"/>
    </div>
  </xpath>
  <xpath expr="//notebook" position="inside">
    <page string="Autres informations" name="autres_informations">
      <group>
        <group>
          <field name="x_nom_legal"/>
        </group>
        <group>
          <field name="x_autres_numeros"/>
        </group>
      </group>
    </page>
  </xpath>
</data>"""
vue = kw("ir.ui.view", "search", [[["name", "=", "res.partner.form.autres.informations"]]])
if vue:
    kw("ir.ui.view", "write", [vue, {"arch_db": ARCH}])
else:
    kw("ir.ui.view", "create", [{"name": "res.partner.form.autres.informations", "model": "res.partner",
                                 "inherit_id": base_form, "type": "form", "arch_db": ARCH}])
    print("Onglet 'Autres informations' ajoute a la fiche contact")

PF = kw("res.partner", "fields_get", [[]], {"attributes": ["type"]})

# ---------------------------------------------------------------- 1) Etiquettes = endroit
_tags = {}
def etiquette_endroit(ville):
    """1 etiquette par ville / quartier ('St-Marc des carrières' = 'St-Marc des Carrières')."""
    if not ville:
        return None
    key = ville.lower()
    if key not in _tags:
        ids = kw("res.partner.category", "search", [[["name", "=ilike", ville], ["parent_id", "=", False]]])
        _tags[key] = ids[0] if ids else kw("res.partner.category", "create", [{"name": ville}])
    return _tags[key]

# ---------------------------------------------------------------- 2) Conditions de paiement
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

# ---------------------------------------------------------------- 3) Listes de prix
listes = {}
# Odoo 18+ : la liste choisie a la main est stockee dans specific_property_product_pricelist
champ_liste = ("specific_property_product_pricelist" if "specific_property_product_pricelist" in PF
               else "property_product_pricelist")
if "property_product_pricelist" in PF:
    company = kw("res.users", "read", [[uid], ["company_id"]])[0]["company_id"][0]
    devise = kw("res.company", "read", [[company], ["currency_id"]])[0]["currency_id"][0]
    for nom in sorted({c["pricelist"] for c in CLIENTS if c["pricelist"]} | {"Prix régulier"}):
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

# ---------------------------------------------------------------- 4) Langue
lang = kw("res.lang", "search_read", [[["code", "=", LANGUE], ["active", "in", [True, False]]]],
          {"fields": ["active"]})
if lang and not lang[0]["active"]:
    wiz = kw("base.language.install", "create", [{"lang_ids": [(6, 0, [lang[0]["id"]])]}])
    kw("base.language.install", "lang_install", [[wiz]])
    print(f"Langue activee : {LANGUE}")
langue_ok = bool(lang)

# ---------------------------------------------------------------- 5) Pays / province / taxes
canada = kw("res.country", "search", [[["code", "=", "CA"]]])[0]
quebec = kw("res.country.state", "search", [[["code", "=", "QC"], ["country_id", "=", canada]]])
quebec = quebec[0] if quebec else False
position = False
if "property_account_position_id" in PF and quebec:
    fp = kw("account.fiscal.position", "search", [[["state_ids", "in", [quebec]]]], {"limit": 1})
    if fp:
        position = fp[0]
        print(f"Position fiscale utilisee : {kw('account.fiscal.position', 'read', [fp, ['name']])[0]['name']}")
    else:
        print("! Aucune position fiscale pour le Quebec (localisation canadienne non installee ?) : ignoree")
titres = {}
if "title" in PF:
    for t in ("Madame", "Monsieur"):
        ids = kw("res.partner.title", "search", [[["name", "=", t]]])
        titres[t] = ids[0] if ids else kw("res.partner.title", "create", [{"name": t}])

def facturation(clients):
    """Conditions de paiement / liste de prix / position fiscale (entite commerciale)."""
    vals = {}
    if termes:
        vals["property_payment_term_id"] = termes.get(plus_courant(c["terme"] for c in clients), False)
    if listes:
        vals[champ_liste] = listes.get(plus_courant(c["pricelist"] for c in clients), False)
    if position:
        vals["property_account_position_id"] = position
    return vals

# ---------------------------------------------------------------- 6) Bannieres (societes parentes)
parents = {}
for nom in BANNIERES:
    # type "invoice" : sur un devis d'un commerce, la facturation va a la banniere
    # (et non au 1er contact-personne du commerce), la livraison au commerce
    vals = {"name": nom, "type": "invoice", "country_id": canada, "state_id": quebec,
            **facturation([c for c in CLIENTS if c["parent"] == nom])}
    if langue_ok:
        vals["lang"] = LANGUE
    parents[nom], cree = ecrire_ou_creer([["name", "=", nom], ["parent_id", "=", False],
                                          ["ref", "=", False]], vals)
    if cree:
        print(f"Societe parente creee : {nom}")

# ---------------------------------------------------------------- 7-8) Commerces + contacts
nb_new = nb_maj = nb_pers = 0
for c in CLIENTS:
    tag = etiquette_endroit(c["endroit"])
    vals = {
        "name": c["nom"],
        "ref": c["ref"],
        "street": c["street"] or False,
        "city": c["city"] or False,
        "zip": c["zip"] or False,
        "state_id": quebec,
        "country_id": canada,
        "phone": c["phone"] or False,
        "email": c["email"] or False,
        "category_id": [(6, 0, [tag] if tag else [])],
        "x_nom_legal": c["nom_legal"] or False,
        "x_autres_numeros": c["autres_numeros"] or False,
        "comment": "".join(f"<p>{escape(l)}</p>" for l in c["notes"]) or False,
    }
    if langue_ok:
        vals["lang"] = LANGUE
    if c["parent"]:
        # Adresse de livraison de la banniere : garde sa propre adresse,
        # la facturation suit la banniere
        vals.update(parent_id=parents[c["parent"]], type="delivery")
    else:
        vals.update(parent_id=False, type="contact", **facturation([c]))

    pid, cree = ecrire_ou_creer([["ref", "=", c["ref"]]], vals)
    nb_new += cree
    nb_maj += not cree

    for p in c["contacts"]:
        pv = {"name": p["nom"], "parent_id": pid, "type": "contact",
              "function": p["fonction"] or False}
        if p.get("mobile"):
            pv["phone"] = p["mobile"]
        if titres and p["titre"]:
            pv["title"] = titres[p["titre"]]
        if langue_ok:
            pv["lang"] = LANGUE
        ecrire_ou_creer([["name", "=", p["nom"]], ["parent_id", "=", pid]], pv)
        nb_pers += 1

# Etiquettes de ville seule devenues inutiles (ex. "Charlesbourg" -> "Québec (Charlesbourg)")
vieilles = {c["city"] for c in CLIENTS if c["city"]} - {c["endroit"] for c in CLIENTS if c["endroit"]}
inutiles = kw("res.partner.category", "search", [[["name", "in", sorted(vieilles)],
                                                  ["parent_id", "=", False], ["partner_ids", "=", False]]])
if inutiles:
    kw("res.partner.category", "unlink", [inutiles])

print(f"\nTermine : {nb_new} commerces crees, {nb_maj} mis a jour, "
      f"{len(parents)} societes parentes, {nb_pers} contacts-personnes.")
