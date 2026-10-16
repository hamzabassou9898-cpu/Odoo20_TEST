# -*- coding: utf-8 -*-
"""Fiche contact : la vue ajoutee a la main dans la base (« res.partner.form.autres.informations ») est
remplacee par celle du module ; la garder afficherait deux fois le code client et l'onglet. Les champs
x_nom_legal, x_autres_numeros et x_code_societe sont maintenant ceux du module (valeurs gardees)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    vues = env["ir.ui.view"].with_context(active_test=False).search(
        [("name", "=", "res.partner.form.autres.informations"), ("model", "=", "res.partner")])
    a_la_main = vues.filtered(lambda v: not env["ir.model.data"].search_count(
        [("model", "=", "ir.ui.view"), ("res_id", "=", v.id), ("module", "not in", ("__export__", "studio_customization"))]))
    a_la_main.unlink()
