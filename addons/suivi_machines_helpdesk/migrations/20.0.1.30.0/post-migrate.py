# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Tickets existants avec un client mais sans code client : on remplit le code."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Ticket = env["helpdesk.ticket"].with_context(tracking_disable=True)
    tickets = Ticket.search([("partner_id", "!=", False), ("code_client", "in", (False, ""))])
    for ticket in tickets:
        code = Ticket._code_du_client(ticket.partner_id)
        if code:
            ticket.code_client = code
