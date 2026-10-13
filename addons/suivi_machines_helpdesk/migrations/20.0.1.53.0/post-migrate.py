# -*- coding: utf-8 -*-
"""« Prolonger la location » retire (fait de facon native dans Location) : le produit « Prolongation de
location » est archive (il peut deja etre sur un contrat) et n'est plus gere par le module."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lien = env["ir.model.data"].search([("module", "=", "suivi_machines_helpdesk"),
                                        ("name", "=", "produit_prolongation_location")])
    if lien:
        env["product.product"].browse(lien.res_id).exists().product_tmpl_id.active = False
        lien.unlink()
