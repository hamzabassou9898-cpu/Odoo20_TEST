# -*- coding: utf-8 -*-
"""Etapes du CRM de Monroy creees a la main dans la base de test, reprises dans le module : creees
seulement si elles manquent, placees comme dans Monroy_test (propositions avant Gagne, Livre apres)."""
from odoo import api, models

from odoo.addons.suivi_machines_helpdesk.models.configuration import creer_si_absent, trouver_par_nom

MODULE = "suivi_machines_pilotage"
PROPOSITIONS = (("crm_etape_1ere_proposition", "🥇 1ère proposition"),
                ("crm_etape_2eme_proposition", "🥈 2ème proposition"))
LIVRE = ("crm_etape_livre", "✅ Livré / Terminé")


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model
    def _configuration_monroy(self):
        Etape = self.env["crm.stage"].sudo().with_context(active_test=False)
        gagne = Etape.search([("is_won", "=", True)], order="sequence, id", limit=1)
        en_cours = Etape.search([("is_won", "=", False)]) - self._etapes_monroy()
        sequence = max(en_cours.mapped("sequence") or [0])
        nouvelles = False
        for xmlid, nom in PROPOSITIONS:
            sequence += 1
            _etape, cree = creer_si_absent(self.env, MODULE, xmlid, "crm.stage", nom, {"sequence": sequence})
            nouvelles = nouvelles or cree
        # « Gagne » reste apres les propositions, seulement si elles viennent d'etre placees devant lui
        if nouvelles and gagne and gagne.sequence <= sequence:
            gagne.sequence = sequence + 1
        creer_si_absent(self.env, MODULE, LIVRE[0], "crm.stage", LIVRE[1],
                        {"sequence": (gagne.sequence if gagne else sequence) + 1})

    @api.model
    def _etapes_monroy(self):
        Etape = self.env["crm.stage"]
        etapes = Etape.browse()
        for _xmlid, nom in PROPOSITIONS + (LIVRE,):
            etapes |= trouver_par_nom(Etape, nom)
        return etapes


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _configuration_vue_contacts(self):
        """Contacts s'ouvre sur la vue Hierarchie. Odoo n'accepte qu'une vue par mode et par action : la vue
        Hierarchie deja ajoutee a la main (script du 7 octobre, Monroy_test, production) est reutilisee et
        placee en premier ; sinon elle est creee. Le xmlid « noupdate » la garde aux mises a jour."""
        action = self.env.ref("contacts.action_contacts", raise_if_not_found=False)
        if not action:
            return
        Vue = self.env["ir.actions.act_window.view"].sudo()
        vue = Vue.search([("act_window_id", "=", action.id), ("view_mode", "=", "hierarchy")], limit=1)
        premiere = min((action.view_ids - vue).mapped("sequence") or [0])
        if not vue:
            vue = Vue.create({"act_window_id": action.id, "view_mode": "hierarchy", "sequence": premiere - 1})
        elif vue.sequence >= premiere:
            vue.sequence = premiere - 1
        Data = self.env["ir.model.data"].sudo()
        donnee = Data.search([("module", "=", MODULE), ("name", "=", "action_contacts_vue_hierarchie")], limit=1)
        valeurs = {"model": "ir.actions.act_window.view", "res_id": vue.id, "noupdate": True}
        if donnee:
            donnee.write(valeurs)
        else:
            Data.create(dict(valeurs, module=MODULE, name="action_contacts_vue_hierarchie"))
