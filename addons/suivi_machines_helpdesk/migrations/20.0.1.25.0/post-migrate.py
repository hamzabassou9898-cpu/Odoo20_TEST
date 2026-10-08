# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Mise a jour : les actions Reprise et Entretiens tournent tout de suite."""
    from odoo.addons.suivi_machines_helpdesk.models.declencheurs import declencher
    declencher(api.Environment(cr, SUPERUSER_ID, {}))
