# -*- coding: utf-8 -*-
"""Tickets existants : type de ticket (obligatoire) et origine automatique, par l'ORM."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True, "mail_notrack": True})
    Ticket = env["helpdesk.ticket"].with_context(active_test=False)
    # Tickets crees par les actions planifiees (entretiens a echeance, fins de location)
    Ticket.search([("origine_auto", "=", False), ("est_entretien", "=", True)]).write(
        {"origine_auto": "entretien"})
    Ticket.search([("origine_auto", "=", False), ("commande_reprise_id", "!=", False)]).write(
        {"origine_auto": "reprise"})
    # Sans type : entretien / ramassage d'apres le ticket, sinon Reparation (obligatoire dans le formulaire)
    sans_type = Ticket.search([("type_demande", "=", False)])
    sans_type.filtered("est_entretien").write({"type_demande": "entretien"})
    sans_type.filtered(lambda t: not t.est_entretien and t.commande_reprise_id).write({"type_demande": "ramassage"})
    sans_type.filtered(lambda t: not t.est_entretien and not t.commande_reprise_id).write(
        {"type_demande": "reparation"})
