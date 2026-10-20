# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .ouverture_compte import ETATS


class ResPartner(models.Model):
    _inherit = "res.partner"

    ouverture_compte_ids = fields.One2many("ouverture.compte", "partner_id", "Ouvertures de compte")
    ouverture_compte_id = fields.Many2one("ouverture.compte", "Ouverture de compte",
                                          compute="_compute_ouverture_compte",
                                          help="Dernière ouverture de compte du client.")
    ouverture_compte_etat = fields.Selection(ETATS, "Compte client", compute="_compute_ouverture_compte")

    @api.depends("ouverture_compte_ids.state", "commercial_partner_id.ouverture_compte_ids.state")
    def _compute_ouverture_compte(self):
        for partner in self:
            ouvertures = partner.ouverture_compte_ids | partner.commercial_partner_id.ouverture_compte_ids
            partner.ouverture_compte_id = ouvertures.sorted("id", reverse=True)[:1]
            partner.ouverture_compte_etat = partner.ouverture_compte_id.state

    def action_ouverture_compte(self):
        """Bouton de la fiche : la demande en cours, sinon une nouvelle, preparee avec la fiche."""
        self.ensure_one()
        ouverture = self.ouverture_compte_id
        if not ouverture or ouverture.state in ("approuve", "refuse"):
            ouverture = self.env["ouverture.compte"].create(
                self.env["ouverture.compte"]._valeurs_depuis_client(self))
        return {"type": "ir.actions.act_window", "res_model": "ouverture.compte", "res_id": ouverture.id,
                "view_mode": "form", "views": [(False, "form")]}
