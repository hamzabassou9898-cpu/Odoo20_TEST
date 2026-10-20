# -*- coding: utf-8 -*-
"""Prochain entretien selon la saison du contrat (Annee, Ecole : renouvellement ; Ete : 1er novembre ;
Hiver : aucun) : recalcule une fois pour toutes les machines existantes."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lots = env["stock.lot"].search([("est_machine", "=", True)])
    env.add_to_compute(lots._fields["date_prochain_entretien"], lots)
    env.flush_all()
