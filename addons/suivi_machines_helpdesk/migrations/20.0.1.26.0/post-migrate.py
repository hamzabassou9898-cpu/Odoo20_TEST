# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Ticket de reprise : 30 jours avant la fin du contrat (au lieu de 3)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env["ir.config_parameter"].sudo()
    if hasattr(icp, "set_int"):
        icp.set_int("suivi_machines_helpdesk.jours_avant_reprise", 30)
    else:
        icp.set_param("suivi_machines_helpdesk.jours_avant_reprise", "30")
    from odoo.addons.suivi_machines_helpdesk.models.declencheurs import declencher
    declencher(env)
