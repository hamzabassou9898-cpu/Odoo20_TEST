MODULE = "migration_contacts"

# ---------------------------------------------------------------- 1) Champs personnalises + vues
partner_model_id = kw("ir.model", "search", [[["model", "=", "res.partner"]]])[0]
for name, label, ttype in [("x_nom_legal", "Nom légal", "char"),
                           ("x_autres_numeros", "Autres numéros", "text")]:
    if not kw("ir.model.fields", "search", [[["model", "=", "res.partner"], ["name", "=", name]]]):
        kw("ir.model.fields", "create", [{"name": name, "field_description": label, "ttype": ttype,
                                          "model_id": partner_model_id, "state": "manual"}])
        print(f"Champ cree : {label}")
# Code de l'entreprise mere sur les fiches des contacts-personnes (modifiable = modifie l'entreprise)
champ = kw("ir.model.fields", "search", [[["model", "=", "res.partner"], ["name", "=", "x_code_societe"]]])
if champ:
    kw("ir.model.fields", "write", [champ, {"readonly": False}])
else:
    kw("ir.model.fields", "create", [{"name": "x_code_societe", "field_description": "Code client (entreprise)",
                                      "ttype": "char", "model_id": partner_model_id, "state": "manual",
                                      "related": "parent_id.ref", "readonly": False, "store": False}])
    print("Champ cree : Code client (entreprise)")

base_form = kw("ir.model.data", "search_read",
               [[["module", "=", "base"], ["name", "=", "view_partner_form"]]], {"fields": ["res_id"]})[0]["res_id"]
ARCH = """<data>
  <!-- Code client (= Reference) en grand, dans un cadre, en haut a droite de la fiche -->
  <xpath expr="//field[@name='image_1920']/.." position="inside">
    <div class="border border-2 border-dark rounded-3 px-3 py-2 text-center flex-shrink-0"
         style="width: 210px;">
      <div class="text-muted text-uppercase small fw-bold">Code client</div>
      <h2 class="mb-0 fw-bold" invisible="parent_id and type == 'contact'">
        <field name="ref" class="text-center fw-bold" placeholder="Code"/>
      </h2>
      <h2 class="mb-0 fw-bold" invisible="not parent_id or type != 'contact'">
        <field name="x_code_societe" class="text-center fw-bold" placeholder="Code"/>
      </h2>
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
    print("Fiche contact : cadre Code client + onglet 'Autres informations'")

# Contacts s'ouvre en vue Hierarchie
if DATA.get("hierarchie"):
    act = kw("ir.model.data", "search_read", [[["module", "=", "contacts"], ["name", "=", "action_contacts"]]],
             {"fields": ["res_id"]})
    vh = kw("ir.model.data", "search_read",
            [[["module", "=", "contacts"], ["name", "=", "res_partner_view_hierarchy"]]], {"fields": ["res_id"]})
    if act and vh:
        ex = kw("ir.actions.act_window.view", "search",
                [[["act_window_id", "=", act[0]["res_id"]], ["view_mode", "=", "hierarchy"]]])
        vals = {"act_window_id": act[0]["res_id"], "view_mode": "hierarchy", "view_id": vh[0]["res_id"],
                "sequence": -1}
        kw("ir.actions.act_window.view", "write", [ex, vals]) if ex else kw(
            "ir.actions.act_window.view", "create", [vals])
        print("Contacts s'ouvre en vue Hierarchie")

PF = champs("res.partner")

# ---------------------------------------------------------------- 2) Langues
langues_ok = {code for code in DATA["langues"] if activer_langue(code)}

# ---------------------------------------------------------------- 3) Etiquettes
tags = {}
for t in DATA["etiquettes"]:   # parents avant enfants
    parent = tags.get(t["parent"], False)
    tags[t["cle"]], _ = ecrire_ou_creer(t["cle"], "res.partner.category",
                                        {"name": t["nom"], "parent_id": parent, "color": t["couleur"]},
                                        [["name", "=", t["nom"]], ["parent_id", "=", parent]])
print(f"{len(tags)} etiquettes")

# ---------------------------------------------------------------- 4) Conditions de paiement
termes = {}
if modele_existe("account.payment.term"):
    LF = champs("account.payment.term.line")
    for t in DATA["termes"]:
        ids = kw("account.payment.term", "search", [[["name", "=", t["nom"]]]], {"context": {"active_test": False}})
        if ids:
            termes[t["nom"]] = ids[0]
            continue
        lignes = [(0, 0, {k: v for k, v in l.items() if k in LF}) for l in t["lignes"]]
        termes[t["nom"]] = kw("account.payment.term", "create", [{"name": t["nom"], "line_ids": lignes}])
        print(f"Condition de paiement creee : {t['nom']}")
else:
    print("! Module Facturation absent : conditions de paiement ignorees")

# ---------------------------------------------------------------- 5) Listes de prix
listes = {}
champ_liste = ("specific_property_product_pricelist" if "specific_property_product_pricelist" in PF
               else "property_product_pricelist")
if modele_existe("product.pricelist") and "property_product_pricelist" in PF:
    for l in DATA["listes"]:
        listes[l["nom"]] = liste_de_prix(l["nom"], l["devise"])
        kw("product.pricelist", "write", [[listes[l["nom"]]], {"sequence": l["sequence"]}])
    activer_listes_de_prix()
else:
    print("! Module Ventes absent : listes de prix ignorees")

# Position fiscale par province (si la localisation canadienne est installee)
positions = {}

def position_fiscale(etat_id):
    if not etat_id or "property_account_position_id" not in PF:
        return False
    if etat_id not in positions:
        fp = kw("account.fiscal.position", "search", [[["state_ids", "in", [etat_id]]]], {"limit": 1})
        positions[etat_id] = fp[0] if fp else False
    return positions[etat_id]

# ---------------------------------------------------------------- 6) Contacts
partenaires = {}
nb_new = nb_maj = 0
for p in DATA["partenaires"]:   # parents avant enfants
    pays, etat = etat_pays(p.pop("pays"), p.pop("etat"))
    parent = partenaires.get(p.pop("parent"), False)
    etiquettes = [tags[c] for c in p.pop("etiquettes") if c in tags]
    terme, liste = p.pop("terme"), p.pop("liste")
    cle = p.pop("cle")
    vals = {k: v for k, v in p.items() if k in PF}
    vals.update(parent_id=parent, country_id=pays, state_id=etat, category_id=[(6, 0, etiquettes)])
    if vals.get("lang") and vals["lang"] not in langues_ok:
        vals.pop("lang")
    # Champs de facturation : seulement sur l'entite commerciale (pas sur les personnes)
    if not (parent and vals.get("type") == "contact"):
        if termes and "property_payment_term_id" in PF:
            vals["property_payment_term_id"] = termes.get(terme, False)
        if listes and liste:
            vals[champ_liste] = listes.get(liste, False)
        fp = position_fiscale(etat)
        if fp:
            vals["property_account_position_id"] = fp
    chercher = ([["ref", "=", vals["ref"]], ["parent_id", "=", parent]] if vals.get("ref")
                else [["name", "=", vals["name"]], ["parent_id", "=", parent]])
    partenaires[cle], cree = ecrire_ou_creer(cle, "res.partner", vals, chercher)
    nb_new += cree
    nb_maj += not cree

print(f"\nTermine : {nb_new} contacts crees, {nb_maj} mis a jour "
      f"({len(DATA['partenaires'])} dans le fichier).")
