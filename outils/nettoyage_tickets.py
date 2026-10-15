# Nettoyage de la base de TEST : supprime les appels de service (tickets) dont le client n'a AUCUN
# contrat dans Odoo (anciens tests). Les tickets des clients qui ont un contrat (LOC…, Propriétaire…)
# sont gardés.
#
# Sécurités :
#   - refuse de tourner si la base n'est pas neutralisée (donc jamais sur la production) ;
#   - par défaut, AFFICHE seulement ce qui serait fait ; il faut NETTOYER=oui pour supprimer ;
#   - tout se fait en une seule transaction : en cas d'erreur, rien n'est enregistré.
import os

APPLIQUER = os.environ.get("NETTOYER") == "oui"

if not env["ir.config_parameter"].sudo().get_bool("database.is_neutralized"):
    raise SystemExit("ARRÊT : cette base n'est pas neutralisée (production ?). Rien n'a été fait.")

env = env(context=dict(env.context, lang="fr_CA", tracking_disable=True, mail_notrack=True))
Ticket = env["helpdesk.ticket"].sudo().with_context(active_test=False)

# Clients qui ont un contrat : contrat de location ou contrat avec un type (ex. Propriétaire), pas annulé
contrats = env["sale.order"].sudo().search([
    ("state", "!=", "cancel"), "|", ("type_commande", "=", "location"), ("type_contrat_id", "!=", False)])
avec_contrat = contrats.partner_id.commercial_partner_id

tickets = Ticket.search([]).filtered(
    lambda t: not t.partner_id or t.partner_id.commercial_partner_id not in avec_contrat)
print("\n=== %d ticket(s) sans contrat à supprimer (sur %d) ===" % (len(tickets), Ticket.search_count([])))
for t in tickets.sorted("id"):
    print("  #%-5s %-38s %-34s %s" % (t.id, (t.name or "")[:38], (t.partner_id.display_name or "— sans client")[:34],
                                       t.stage_id.name or ""))
if not tickets:
    raise SystemExit("Rien à nettoyer.")

Intervention = env["machine.intervention"].sudo()
interventions = Intervention.search([("ticket_id", "in", tickets.ids)])
bons = env["suivi.bon.intervention"].sudo().search(
    ["|", ("ticket_id", "in", tickets.ids), ("intervention_id", "in", interventions.ids)]) \
    if "suivi.bon.intervention" in env else []
transferts = env["stock.picking"].sudo().search([("ticket_assistance_id", "in", tickets.ids),
                                                ("state", "not in", ("done", "cancel"))])
print("\nInterventions liées à supprimer : %d" % len(interventions))
print("Bons d'intervention liés à supprimer : %d" % len(bons))
print("Transferts pas encore faits liés à annuler et supprimer : %d" % len(transferts))
print("Gardés : %d ticket(s) de clients qui ont un contrat" % (Ticket.search_count([]) - len(tickets)))

if not APPLIQUER:
    raise SystemExit("\nAPERÇU seulement : rien n'a été modifié. Relancer avec NETTOYER=oui pour supprimer.")

if bons:
    bons.unlink()
if transferts:
    transferts.action_cancel()
    transferts.unlink()
interventions.unlink()
tickets.unlink()

env.cr.commit()
print("\nTERMINÉ : %d ticket(s) supprimé(s)." % len(tickets))
