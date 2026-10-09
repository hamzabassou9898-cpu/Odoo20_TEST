# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Ma journee : les techniciens deja assignes aux livraisons y ont acces tout de suite."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    techniciens = env["stock.picking"].search([("livreur_id", "!=", False)]).livreur_id
    if techniciens:
        env.ref("suivi_machines_pilotage.group_technicien").user_ids = [(4, u.id) for u in techniciens]
