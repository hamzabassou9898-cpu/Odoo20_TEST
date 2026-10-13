# -*- coding: utf-8 -*-
"""Entretien : le ticket et l'activite « Planifier entretien » arrivent un mois avant (30 jours au lieu de 7).
On ne change le parametre que s'il a encore l'ancienne valeur par defaut."""
from odoo import api, SUPERUSER_ID

CLE = "suivi_machines_helpdesk.jours_avant_entretien"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env["ir.config_parameter"]
    if icp.get_str(CLE) == "7":
        icp.set_str(CLE, "30")
