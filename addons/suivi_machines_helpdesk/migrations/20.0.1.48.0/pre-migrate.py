# -*- coding: utf-8 -*-
"""« Prolonger la location » : le contrat devient obligatoire dans la fenetre (elle s'ouvre aussi depuis le
contrat). Les anciennes fenetres fermees, sans contrat, empechent Odoo d'ajouter la contrainte : ce sont des
donnees temporaires (assistant), on les supprime avant la mise a jour."""
from odoo.tools.sql import table_exists


def migrate(cr, version):
    if table_exists(cr, "suivi_machines_prolonger_location"):
        cr.execute("DELETE FROM suivi_machines_prolonger_location")
