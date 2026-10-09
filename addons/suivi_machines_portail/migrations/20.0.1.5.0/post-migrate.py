# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Un seul champ : « Technicien terrain » passe dans « Assigne a » (par l'ORM : statut d'entretien,
    synchronisation des interventions et Pilotage sont recalcules)."""
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True, "mail_notrack": True,
                                             "mail_auto_subscribe_no_notify": True})
    Ticket = env["helpdesk.ticket"].with_context(active_test=False)
    tickets = Ticket.search([("technicien_terrain_id", "!=", False)])
    for technicien, groupe in tickets.grouped("technicien_terrain_id").items():
        groupe.write({"user_id": technicien.id, "technicien_terrain_id": False})
