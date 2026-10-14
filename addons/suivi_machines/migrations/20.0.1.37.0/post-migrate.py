# -*- coding: utf-8 -*-
"""Documents du client : les PDF deja ranges deviennent visibles par le bureau (proprietaire interne, acces
interne) et les commandes recentes envoyees ou confirmees sont rangees dans le profil de leur client."""
from datetime import timedelta

from odoo import api, fields, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    depuis = fields.Datetime.now() - timedelta(days=120)
    commandes = env["sale.order"].search([("state", "in", ("sent", "sale")), ("date_order", ">=", depuis)],
                                         order="date_order desc", limit=300)
    commandes._archiver_pdf_client()
