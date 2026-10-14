# -*- coding: utf-8 -*-
"""Carte « Livraisons & ramassages faits ce mois » (titre dans chaque langue) ; type de tournee : l'emplacement
« Location » compte comme chez le client (livraisons de location)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    _renommer_carte(env)
    societes = env["res.company"].search([])
    if "rental_loc_id" not in societes._fields:
        return
    locations = societes.rental_loc_id
    if not locations:
        return
    pickings = env["stock.picking"].search(["|", ("location_id", "in", locations.ids),
                                            ("location_dest_id", "in", locations.ids)])
    env.add_to_compute(pickings._fields["type_tournee"], pickings)
    pickings._recompute_recordset(["type_tournee"])


def _renommer_carte(env):
    """La carte compte maintenant livraisons ET ramassages : nouveau titre dans chaque langue installee."""
    carte = env.ref("suivi_machines_pilotage.indicateur_livraisons_faites", raise_if_not_found=False)
    if not carte:
        return
    for code, _nom in env["res.lang"].get_installed():
        carte.with_context(lang=code).write({
            "name": "Livraisons & ramassages faits ce mois",
            "description": "Livraisons et ramassages terminés depuis le 1er du mois"})
