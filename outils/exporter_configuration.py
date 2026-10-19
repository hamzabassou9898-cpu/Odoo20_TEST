# INVENTAIRE (lecture seule) de la CONFIGURATION d'une base : étapes de l'Assistance et du CRM,
# équipes, étiquettes, types d'activité, catégories de produits, types d'opération… Sert à reprendre
# dans les modules ce qui a été créé à la main dans une base (ex. Monroy_test), pour que toutes les
# bases (staging, production) aient la même configuration.
#
#   odoo-bin shell --no-http --log-level=warn < ~/exporter_configuration.py
#
# Ne modifie RIEN. N'exporte aucun client, contact ni document : seulement des listes de réglages.
# Écrit ~/configuration.json (le détail) et affiche un résumé à copier.
import json
import os

Data = env["ir.model.data"].sudo()

# Modèle -> champs utiles (ceux qui n'existent pas dans la base sont ignorés)
MODELES = {
    "helpdesk.team": ["name", "sequence", "stage_ids", "use_website_helpdesk_form", "use_sla", "use_rating",
                      "use_helpdesk_timesheet", "use_fsm", "assign_method", "member_ids", "privacy_visibility"],
    "helpdesk.stage": ["name", "sequence", "fold", "team_ids", "template_id", "legend_normal", "legend_done",
                       "legend_blocked"],
    "helpdesk.tag": ["name", "color"],
    "helpdesk.ticket.type": ["name", "sequence"],
    "helpdesk.sla": ["name", "team_id", "stage_id", "time", "priority", "tag_ids"],
    "crm.stage": ["name", "sequence", "fold", "is_won", "team_id", "requirements"],
    "crm.tag": ["name", "color"],
    "crm.lost.reason": ["name"],
    "crm.team": ["name", "sequence", "use_leads", "use_opportunities", "alias_name", "member_ids"],
    "res.partner.category": ["name", "parent_id", "color"],
    "mail.activity.type": ["name", "sequence", "res_model", "category", "delay_count", "delay_unit", "summary"],
    "product.category": ["name", "parent_id"],
    "stock.location": ["name", "complete_name", "usage", "location_id"],
    "stock.picking.type": ["name", "code", "sequence_code", "warehouse_id", "default_location_src_id",
                           "default_location_dest_id"],
    "sale.order.template": ["name"],
    "project.task.type": ["name", "sequence", "fold"],
    "documents.folder": ["name", "parent_folder_id"],
    "documents.tag": ["name", "folder_id"],
    "suivi.type.contrat": ["name", "type_commande", "modele", "forfait_montant", "couvre_reparations",
                           "frais_appel_inutile", "frais_deplacement", "taux_horaire", "clause_penale"],
}
# Seulement les enregistrements qu'il faut voir : pas les emplacements virtuels d'Odoo, etc.
FILTRES = {"stock.location": [("usage", "=", "internal")]}
ORIGINES_MAIN = {"__export__", "__import__", "studio_customization", "__custom__"}


def valeur(record, nom):
    champ = record._fields[nom]
    v = record[nom]
    if champ.type in ("many2one",):
        return v.display_name or False
    if champ.type in ("many2many", "one2many"):
        return v.mapped("display_name")
    return v


resultat = {}
for modele, champs in MODELES.items():
    if modele not in env:
        continue
    Model = env[modele].sudo().with_context(active_test=False)
    champs = [c for c in champs if c in Model._fields]
    lignes = []
    for record in Model.search(FILTRES.get(modele, [])):
        xmlids = Data.search([("model", "=", modele), ("res_id", "=", record.id)])
        modules = set(xmlids.mapped("module"))
        ligne = {"id": record.id, "xmlid": ",".join(xmlids.mapped("complete_name")),
                 "a_la_main": not (modules - ORIGINES_MAIN)}
        if "active" in Model._fields:
            ligne["actif"] = record.active
        for nom in champs:
            ligne[nom] = valeur(record, nom)
        lignes.append(ligne)
    resultat[modele] = lignes

# Applications et modules installés (pour installer les mêmes sur une autre base)
modules = env["ir.module.module"].sudo().search([("state", "=", "installed")], order="name")
resultat["modules_installes"] = modules.mapped("name")
applications = modules.filtered("application")

chemin = os.path.expanduser("~/configuration.json")
with open(chemin, "w", encoding="utf-8") as fichier:
    json.dump(resultat, fichier, ensure_ascii=False, indent=1, default=str)

print("\n=== Configuration de la base %s ===" % env.cr.dbname)
print("(* = créé à la main dans cette base, pas par un module)")
print("\nApplications installées (%d) : %s" % (len(applications), ", ".join(applications.mapped("name"))))
print("\nTous les modules installés (%d), pour comparer :" % len(modules))
print(",".join(modules.mapped("name")))
for modele, lignes in resultat.items():
    if modele == "modules_installes":
        continue
    print("\n%s : %d" % (modele, len(lignes)))
    for x in lignes[:80]:
        details = []
        for cle in ("sequence", "team_ids", "team_id", "stage_ids", "is_won", "fold", "usage", "code",
                    "res_model", "parent_id", "type_commande"):
            if x.get(cle) not in (None, False, [], ""):
                details.append("%s=%s" % (cle, x[cle]))
        print("  %s%s%s  %s" % ("*" if x["a_la_main"] else " ", x.get("complete_name") or x.get("name"),
                                "" if x.get("actif", True) else " (archivé)", " ".join(details)[:160]))
print("\nDétail complet écrit dans %s" % chemin)
