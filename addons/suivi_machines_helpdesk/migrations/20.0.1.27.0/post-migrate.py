# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Tickets de reprise existants : un seul ticket par contrat (machines regroupees),
    place dans l'etape « Reprise de machine » de son equipe."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Ticket = env["helpdesk.ticket"].with_context(active_test=False)
    tickets = Ticket.search([("commande_reprise_id", "!=", False)], order="id")
    groupes = {}
    for ticket in tickets:
        if not ticket.machines_reprise_ids and ticket.lot_id:
            ticket.machines_reprise_ids = [(4, ticket.lot_id.id)]
        if ticket._est_ferme():
            continue
        groupes.setdefault((ticket.commande_reprise_id.id, ticket.date_fin_reprise), Ticket)
        groupes[(ticket.commande_reprise_id.id, ticket.date_fin_reprise)] |= ticket
    for groupe in groupes.values():
        garde, autres = groupe[:1], groupe[1:]
        garde.machines_reprise_ids = [(4, lot.id) for lot in autres.machines_reprise_ids | autres.lot_id]
        lies = env["stock.picking"].search_count([("ticket_assistance_id", "in", autres.ids)]) \
            + env["machine.intervention"].search_count([("ticket_id", "in", autres.ids)])
        if lies:
            # deja utilises (retour, intervention) : on les garde mais on les rattache au ticket principal
            autres.message_post(body="Regroupé dans le ticket %s." % garde.display_name)
        else:
            autres.unlink()
        garde._nommer_reprise()
        garde._mettre_en_reprise()
    from odoo.addons.suivi_machines_helpdesk.models.declencheurs import declencher
    declencher(env)
