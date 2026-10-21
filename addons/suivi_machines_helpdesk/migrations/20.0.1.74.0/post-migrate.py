# -*- coding: utf-8 -*-
"""Etape « Installation de machine / Reprise » renommee « Livraison & installation / Reprise » : les bons de
livraison a faire s'affichent en haut de cette colonne (Pilotage)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["helpdesk.ticket"]._renommer_etape_installation()
