# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OuvertureCompteEnvoyer(models.TransientModel):
    """Courriel de l'ouverture de compte, relu et modifie par Jose avant l'envoi."""
    _name = "ouverture.compte.envoyer"
    _description = "Envoyer le formulaire d'ouverture de compte"

    ouverture_id = fields.Many2one("ouverture.compte", required=True, ondelete="cascade")
    courriel = fields.Char("Destinataire", required=True)
    sujet = fields.Char("Objet", required=True)
    corps = fields.Html("Message", sanitize_style=True)
    piece_ids = fields.Many2many("ir.attachment", string="Pièces jointes")

    @api.model
    def default_get(self, fields_list):
        valeurs = super().default_get(fields_list)
        ouverture = self.env["ouverture.compte"].browse(valeurs.get("ouverture_id"))
        if ouverture:
            sujet, corps = ouverture._contenu_courriel()
            valeurs.update({"courriel": ouverture.courriel, "sujet": sujet, "corps": corps})
        return valeurs

    def action_envoyer(self):
        self.ensure_one()
        self.ouverture_id._envoyer(self.courriel, self.sujet, self.corps, self.piece_ids)
        return {"type": "ir.actions.act_window_close"}
