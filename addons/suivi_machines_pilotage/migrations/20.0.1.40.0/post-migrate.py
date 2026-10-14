# -*- coding: utf-8 -*-
"""Menus renommes (« Parc machines » -> « Inventaire », « Vue d'ensemble » -> « Parc machines ») : Odoo garde
l'ancienne traduction francaise a la mise a jour ; le nouveau nom est remis dans toutes les langues."""
from odoo import api, SUPERUSER_ID

MENUS = ("menu_pilotage_parc", "menu_pilotage_vue_ensemble")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    langues = [code for code, _nom in env["res.lang"].get_installed()]
    for xmlid in MENUS:
        menu = env.ref("suivi_machines_pilotage." + xmlid, raise_if_not_found=False)
        if menu:
            nom = menu.with_context(lang="en_US").name
            menu.update_field_translations("name", {lang: nom for lang in langues})
