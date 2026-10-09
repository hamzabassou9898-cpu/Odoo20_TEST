# -*- coding: utf-8 -*-
"""Type de ticket (appel de service, entretien, reprise) pour le pilotage."""
from odoo import api, fields, models

TYPES_TICKET = [("appel", "Appel de service"), ("entretien", "Entretien"), ("reprise", "Reprise de machine")]


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    type_ticket = fields.Selection(TYPES_TICKET, "Type de ticket", compute="_compute_type_ticket",
                                   store=True, index=True)

    @api.depends("est_entretien", "commande_reprise_id")
    def _compute_type_ticket(self):
        for ticket in self:
            ticket.type_ticket = ("reprise" if ticket.commande_reprise_id
                                  else "entretien" if ticket.est_entretien else "appel")
