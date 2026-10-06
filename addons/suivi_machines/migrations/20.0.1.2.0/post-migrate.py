# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Statuts Vendue / En location / Chez un client : recalcul des machines deja sorties."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    lots = env["stock.lot"].search([("est_machine", "=", True),
                                    ("machine_statut", "not in", ("entrepot", "sans_emplacement"))])
    if lots:
        env.add_to_compute(env["stock.lot"]._fields["machine_statut"], lots)
        lots._recompute_recordset(["machine_statut"])
