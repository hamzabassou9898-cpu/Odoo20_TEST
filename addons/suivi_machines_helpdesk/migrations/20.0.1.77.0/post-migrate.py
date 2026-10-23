# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Statut des entretiens et reparations recalcule d'apres le nom francais de l'etape : un ticket dans une
    etape native renommee (ex. « Solved » devenue « Entretien & Reparation ») ne reste pas « Fait » a tort."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    tickets = env["helpdesk.ticket"].with_context(active_test=False).search([])
    env.add_to_compute(tickets._fields["statut_entretien"], tickets)
    tickets.flush_recordset(["statut_entretien"])
