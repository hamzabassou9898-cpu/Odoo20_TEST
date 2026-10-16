# INVENTAIRE (lecture seule) de tout ce qui a été ajouté directement dans la base, hors des modules :
# champs personnalisés (x_..., Studio), vues modifiées, actions serveur, automatisations, actions
# planifiées, modèles personnalisés. Le résultat sert à intégrer ces ajouts dans le code des modules,
# pour qu'ils passent d'une base à une autre.
#
#   odoo-bin shell --no-http --log-level=warn < ~/exporter_personnalisations.py
#
# Ne modifie RIEN. Écrit ~/personnalisations.json (le détail) et affiche un résumé.
import json
import os

Data = env["ir.model.data"].sudo()
# Modules « maison » : ce qu'ils contiennent est déjà du code ; tout le reste, sauf Odoo, est à reprendre
NOS_MODULES = {"suivi_machines", "suivi_machines_helpdesk", "suivi_sage", "suivi_machines_pilotage",
               "suivi_machines_portail"}


def origine(record):
    """Module qui a créé l'enregistrement : '' = créé à la main (ou par Studio / un import)."""
    xmlids = Data.search([("model", "=", record._name), ("res_id", "=", record.id)])
    modules = set(xmlids.mapped("module"))
    vrais = modules - {"__export__", "__import__", "studio_customization", "__custom__"}
    return ",".join(sorted(vrais)), ",".join(sorted(modules - vrais))


resultat = {"champs": [], "modeles": [], "vues": [], "actions_serveur": [], "automatisations": [],
            "actions_planifiees": []}

# Champs personnalisés : state = manual (créés dans l'interface, par Studio, ou par code dans la base)
import re

for f in env["ir.model.fields"].sudo().search([("state", "=", "manual")], order="model, name"):
    if re.match(r"^x_plan\d+_id$", f.name):
        continue   # cree par Odoo lui-meme (plans analytiques), pas une personnalisation
    resultat["champs"].append({
        "modele": f.model, "nom": f.name, "libelle": f.field_description, "type": f.ttype,
        "relation": f.relation or "", "champ_inverse": f.relation_field or "", "requis": f.required,
        "stocke": f.store, "copie": f.copied, "traduit": bool(f.translate), "index": bool(f.index),
        "aide": f.help or "", "calcul": f.compute or "", "dependances": f.depends or "", "lie": f.related or "",
        "selection": [(s.value, s.name) for s in f.selection_ids] or (f.selection or ""), "domaine": f.domain or "",
        "nb_valeurs": env[f.model].sudo().search_count([(f.name, "!=", False)])
        if f.store and f.model in env and f.ttype not in ("one2many", "many2many", "binary") else None})

for m in env["ir.model"].sudo().search([("state", "=", "manual")]):
    resultat["modeles"].append({"modele": m.model, "nom": m.name,
                                "nb_enregistrements": env[m.model].sudo().search_count([]) if m.model in env else None})

# Vues : créées ou modifiées hors des modules (Studio, édition de vue, import)
for v in env["ir.ui.view"].sudo().with_context(active_test=False).search([], order="model, id"):
    module, autre = origine(v)
    if module and not (set(module.split(",")) & NOS_MODULES) and not autre:
        continue   # vue d'un module (Odoo ou autre) jamais retouchée a la main
    if set(module.split(",")) & NOS_MODULES:
        continue
    resultat["vues"].append({"id": v.id, "nom": v.name, "modele": v.model, "type": v.type, "actif": v.active,
                             "herite_de": v.inherit_id.xml_id or (v.inherit_id.name or ""),
                             "xmlid": autre, "arch": v.arch_db})

for a in env["ir.actions.server"].sudo().with_context(active_test=False).search([]):
    module, autre = origine(a)
    if module:
        continue
    resultat["actions_serveur"].append({"id": a.id, "nom": a.name, "modele": a.model_id.model, "etat": a.state,
                                        "code": a.code or "", "xmlid": autre})

if "base.automation" in env:
    for a in env["base.automation"].sudo().with_context(active_test=False).search([]):
        module, autre = origine(a)
        if module:
            continue
        resultat["automatisations"].append({
            "id": a.id, "nom": a.name, "modele": a.model_id.model, "declencheur": a.trigger, "actif": a.active,
            "filtre": a.filter_domain or "", "avant": getattr(a, "filter_pre_domain", "") or "",
            "actions": [{"nom": x.name, "etat": x.state, "code": x.code or ""} for x in a.action_server_ids]})

for c in env["ir.cron"].sudo().with_context(active_test=False).search([]):
    module, autre = origine(c)
    if module:
        continue
    resultat["actions_planifiees"].append({"id": c.id, "nom": c.name, "modele": c.model_id.model,
                                           "code": c.code or "", "actif": c.active,
                                           "intervalle": "%s %s" % (c.interval_number, c.interval_type)})

chemin = os.path.expanduser("~/personnalisations.json")
with open(chemin, "w", encoding="utf-8") as fichier:
    json.dump(resultat, fichier, ensure_ascii=False, indent=1)

print("\n=== Ajouts faits directement dans la base (à intégrer dans les modules) ===")
for cle, titre in (("champs", "Champs personnalisés"), ("modeles", "Modèles personnalisés"), ("vues", "Vues"),
                   ("actions_serveur", "Actions serveur"), ("automatisations", "Automatisations"),
                   ("actions_planifiees", "Actions planifiées")):
    print("\n%s : %d" % (titre, len(resultat[cle])))
    for x in resultat[cle][:60]:
        if cle == "champs":
            print("  %-22s %-28s %-10s %s%s" % (x["modele"], x["nom"], x["type"], x["libelle"],
                                               "  (%s valeurs)" % x["nb_valeurs"] if x["nb_valeurs"] else ""))
        else:
            print("  #%-5s %-24s %s" % (x.get("id", ""), x.get("modele", ""), x.get("nom", "")))
print("\nDétail complet écrit dans %s" % chemin)
