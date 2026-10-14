# -*- coding: utf-8 -*-
"""Types de contrat deja crees (donnees « noupdate ») : modele du texte du contrat et clause penale."""
from odoo import SUPERUSER_ID, api

VALEURS = {"type_contrat_location": ("location", 4000), "type_contrat_convention": ("convention", 4000),
           "type_contrat_popcorn": ("popcorn", 2500), "type_contrat_proprietaire": ("proprietaire", 4000)}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, (modele, penale) in VALEURS.items():
        type_contrat = env.ref("suivi_machines." + xmlid, raise_if_not_found=False)
        if type_contrat:
            valeurs = {"modele": modele}
            if not type_contrat.clause_penale:
                valeurs["clause_penale"] = penale
            type_contrat.write(valeurs)
