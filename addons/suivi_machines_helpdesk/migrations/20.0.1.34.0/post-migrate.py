# -*- coding: utf-8 -*-
"""La planification (a planifier / planifie / fait) couvre aussi les reparations : recalcul par l'ORM."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {"tracking_disable": True})
    Ticket = env["helpdesk.ticket"].with_context(active_test=False)
    tickets = Ticket.search([("type_demande", "in", ("reparation", "remplacement"))])
    env.add_to_compute(Ticket._fields["statut_entretien"], tickets)
    tickets.flush_recordset(["statut_entretien"])
