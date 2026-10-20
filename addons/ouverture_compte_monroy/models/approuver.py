# -*- coding: utf-8 -*-
from odoo import fields, models


class OuvertureCompteApprouver(models.TransientModel):
    _name = "ouverture.compte.approuver"
    _description = "Approuver une ouverture de compte"

    ouverture_id = fields.Many2one("ouverture.compte", required=True, ondelete="cascade")
    entreprise_nom = fields.Char(related="ouverture_id.entreprise_nom")
    code_client = fields.Char("Code client", required=True, help="Code du nouveau client, ex. MON134.")

    def action_approuver(self):
        """Approuve, ouvre la fiche du nouveau client et felicite Jose."""
        self.ensure_one()
        client = self.ouverture_id._approuver(self.code_client)
        return {
            "type": "ir.actions.act_window", "res_model": "res.partner", "res_id": client.id,
            "view_mode": "form", "views": [(False, "form")], "target": "current",
            "effect": {"fadeout": "slow", "type": "rainbow_man",
                       "message": self.env._("Félicitations ! %(client)s est maintenant client Monroy "
                                             "(code %(code)s).", client=client.name, code=client.ref)},
        }
