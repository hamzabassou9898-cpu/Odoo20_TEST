# Crée (ou met à jour) un utilisateur INTERNE dans la base de TEST, par exemple pour Nick.
# Rien de personnel dans ce fichier : nom, courriel et mot de passe sont donnés au lancement.
#
#   NOM="Nick" COURRIEL="nick@exemple.ca" MOT_DE_PASSE="..." odoo-bin shell --no-http < ~/creer_utilisateur.py
#   Option : COMME="login_de_jose" -> mêmes droits que cet utilisateur.
#
# Sécurités : refuse de tourner si la base n'est pas neutralisée (sur la production, un utilisateur
# interne de plus est facturé par Odoo) ; une seule transaction.
import os

if not env["ir.config_parameter"].sudo().get_bool("database.is_neutralized"):
    raise SystemExit("ARRÊT : cette base n'est pas neutralisée (production ?). Rien n'a été fait.")

nom, courriel, mot_de_passe = (os.environ.get(c, "").strip() for c in ("NOM", "COURRIEL", "MOT_DE_PASSE"))
if not (nom and courriel and mot_de_passe):
    raise SystemExit('Il manque NOM, COURRIEL ou MOT_DE_PASSE. Exemple :\n'
                     'NOM="Nick" COURRIEL="nick@exemple.ca" MOT_DE_PASSE="..." '
                     'odoo-bin shell --no-http < ~/creer_utilisateur.py')

User = env["res.users"].sudo().with_context(no_reset_password=True, active_test=False)
modele = User.search([("login", "=", os.environ["COMME"])], limit=1) if os.environ.get("COMME") else User
if os.environ.get("COMME") and not modele:
    raise SystemExit("ARRÊT : aucun utilisateur avec le login %s. Rien n'a été fait." % os.environ["COMME"])

if modele:
    groupes = modele.group_ids
else:
    # Le travail de Monroy : Pilotage, Ventes / Location, CRM, Inventaire, Assistance, Facturation, Documents
    XMLIDS = ["base.group_user", "suivi_machines_pilotage.group_pilotage", "sales_team.group_sale_salesman_all_leads",
              "stock.group_stock_user", "helpdesk.group_helpdesk_user", "account.group_account_invoice",
              "documents.group_documents_user", "project.group_project_user"]
    groupes = env["res.groups"]
    for xmlid in XMLIDS:
        groupes |= env.ref(xmlid, raise_if_not_found=False) or env["res.groups"]

valeurs = {"name": nom, "login": courriel, "email": courriel, "password": mot_de_passe, "active": True,
           "group_ids": [(6, 0, groupes.ids)]}
if "lang" in env["res.users"]._fields and env["res.lang"]._lang_get("fr_CA"):
    valeurs["lang"] = "fr_CA"
utilisateur = User.search([("login", "=", courriel)], limit=1)
if utilisateur:
    utilisateur.write(valeurs)
    action = "mis à jour"
else:
    utilisateur = User.create(valeurs)
    action = "créé"

env.cr.commit()
print("\nUtilisateur %s : %s (login %s)" % (action, utilisateur.name, utilisateur.login))
print("Droits : %s" % ", ".join(sorted(utilisateur.group_ids.filtered(lambda g: not g.share).mapped("full_name"))[:15]))
