# -*- coding: utf-8 -*-
"""Fiche contact : la vue faite a la main est remplacee par celle du module (voir retirer_vue_contact_a_la_main)."""
from odoo import SUPERUSER_ID, api

from odoo.addons.suivi_machines import retirer_vue_contact_a_la_main


def migrate(cr, version):
    retirer_vue_contact_a_la_main(api.Environment(cr, SUPERUSER_ID, {}))
