# -*- coding: utf-8 -*-
"""Reglages crees a la main dans la base de test (Monroy_test), repris dans le module pour que toutes
les bases (staging, production) aient les memes. Rien n'est cree s'il existe deja un reglage du meme
nom (meme archive) : pas de doublon, et les reglages deja en place ne sont jamais modifies."""
from odoo import api, models

LANGUES = ("fr_CA", "fr_FR", "en_US")


def trouver_par_nom(Model, nom):
    """Enregistrement du meme nom, actif ou archive, quelle que soit la langue dans laquelle il a ete saisi."""
    Model = Model.sudo().with_context(active_test=False)
    installees = dict(Model.env["res.lang"].get_installed())
    for langue in (code for code in LANGUES if code in installees):
        trouve = Model.with_context(lang=langue).search([("name", "=", nom)], limit=1)
        if trouve:
            return trouve
    return Model.browse()


def creer_si_absent(env, module, xmlid, modele, nom, valeurs=None):
    """Retourne (enregistrement, cree). Cree seulement s'il n'existe ni l'enregistrement du module ni un
    enregistrement du meme nom ; le nouvel enregistrement recoit un xmlid « noupdate » : les retouches
    faites ensuite dans la base (nom, ordre, couleur) sont gardees aux mises a jour."""
    record = env.ref("%s.%s" % (module, xmlid), raise_if_not_found=False)
    if record:
        return record, False
    record = trouver_par_nom(env[modele], nom)
    if record:
        return record, False
    champs = env[modele]._fields
    valeurs = {cle: valeur for cle, valeur in (valeurs or {}).items() if cle in champs}
    record = env[modele].sudo().create(dict(valeurs, name=nom))
    env["ir.model.data"].sudo().create({"module": module, "name": xmlid, "model": modele,
                                        "res_id": record.id, "noupdate": True})
    return record, True


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    @api.model
    def _configuration_monroy(self):
        """Etape et etiquette « Machine a remplacer » (tickets d'echange de machine)."""
        Etape = self.env["helpdesk.stage"]
        valeurs = {"sequence": 3}
        if "team_ids" in Etape._fields:
            valeurs["team_ids"] = [(6, 0, self.env["helpdesk.team"].sudo().search([]).ids)] \
                if "helpdesk.team" in self.env else []
        creer_si_absent(self.env, "suivi_machines_helpdesk", "etape_machine_a_remplacer", "helpdesk.stage",
                        "Machine à remplacer", valeurs)
        creer_si_absent(self.env, "suivi_machines_helpdesk", "tag_machine_a_remplacer", "helpdesk.tag",
                        "Machine à remplacer")
