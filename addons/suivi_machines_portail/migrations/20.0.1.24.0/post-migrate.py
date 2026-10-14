# -*- coding: utf-8 -*-
"""Plus d'activites du bureau sur les interventions (notes et bons du portail) : elles vont sur le ticket
d'origine. On retire celles qui restent ouvertes sur des interventions (la note reste dans le fil de
l'intervention et dans « Notes de techniciens à lire »)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    notes = env["suivi.note.technicien"].search([("activity_id.res_model", "=", "machine.intervention")])
    activites = notes.activity_id
    bons = env["mail.activity"].search([("res_model", "=", "machine.intervention"),
                                        ("summary", "=like", "Bon %")])
    (activites | bons).unlink()
