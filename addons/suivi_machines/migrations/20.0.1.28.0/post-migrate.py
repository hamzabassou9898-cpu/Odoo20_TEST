# -*- coding: utf-8 -*-
"""Types de contrat deja crees (donnees « noupdate ») : montants des appels de service (clause 7.3)
et couverture des reparations, s'ils n'ont pas encore ete regles."""
from odoo import SUPERUSER_ID, api

VALEURS = {
    "type_contrat_location": {"couvre_reparations": True, "frais_appel_inutile": 125},
    "type_contrat_convention": {"couvre_reparations": True, "frais_appel_inutile": 125},
    "type_contrat_popcorn": {"couvre_reparations": True, "frais_appel_inutile": 70},
    "type_contrat_proprietaire": {"couvre_reparations": False, "frais_deplacement": 125, "taux_horaire": 105},
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid, valeurs in VALEURS.items():
        type_contrat = env.ref("suivi_machines." + xmlid, raise_if_not_found=False)
        if type_contrat and not (type_contrat.frais_appel_inutile or type_contrat.frais_deplacement
                                 or type_contrat.taux_horaire):
            type_contrat.write(valeurs)
