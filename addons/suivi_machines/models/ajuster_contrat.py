# -*- coding: utf-8 -*-
"""Ajuster un contrat de location (upgrade) : machines ou accessoires en plus, et/ou nouvelle date de fin.

Les ajouts deviennent des lignes du meme contrat : Odoo cree leur livraison (le n° de serie de chaque
machine se choisit a la livraison) et ils seront factures avec le contrat.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError


class AjusterContrat(models.TransientModel):
    _name = "suivi.machines.ajuster.contrat"
    _description = "Ajuster un contrat de location"

    commande_id = fields.Many2one("sale.order", "Contrat", required=True, readonly=True,
                                  domain="[('type_commande', '=', 'location'), ('state', '=', 'sale')]")
    partner_id = fields.Many2one(related="commande_id.partner_id", string="Client")
    currency_id = fields.Many2one(related="commande_id.currency_id")
    date_fin_actuelle = fields.Datetime(related="commande_id.date_fin_location", string="Fin actuelle")
    nouvelle_date_fin = fields.Datetime(
        "Nouvelle fin de location", help="Facultatif : pour prolonger le contrat en même temps.")
    ligne_ids = fields.One2many("suivi.machines.ajuster.contrat.ligne", "assistant_id", "À ajouter au contrat")

    def action_ajuster(self):
        self.ensure_one()
        contrat = self.commande_id
        if contrat.type_commande != "location" or contrat.state != "sale":
            raise UserError(self.env._("Seul un contrat de location confirmé peut être ajusté."))
        if not self.ligne_ids and not self.nouvelle_date_fin:
            raise UserError(self.env._("Ajoutez une machine ou un accessoire, ou une nouvelle date de fin."))
        if self.nouvelle_date_fin:
            if contrat.date_fin_location and self.nouvelle_date_fin <= contrat.date_fin_location:
                raise UserError(self.env._("La nouvelle date de fin doit être après la fin actuelle."))
            champ = "rental_return_date" if "rental_return_date" in contrat._fields else "date_fin_location"
            contrat.write({champ: self.nouvelle_date_fin})
            if champ != "date_fin_location":
                contrat.date_fin_location = self.nouvelle_date_fin
            contrat.message_post(body=self.env._(
                "Contrat ajusté : fin de location le %s.", fields.Date.to_string(self.nouvelle_date_fin.date())))
        if self.ligne_ids:
            # Lignes du meme contrat : la livraison et la trace dans le contrat sont faites a la creation
            self.env["sale.order.line"].create([{
                "order_id": contrat.id, "product_id": ligne.product_id.id,
                "product_uom_qty": ligne.quantite, "price_unit": ligne.prix_unitaire,
            } for ligne in self.ligne_ids])
        if contrat._livraisons_a_faire():
            return contrat.action_livraison_a_faire()
        return {"type": "ir.actions.act_window_close"}


class AjusterContratLigne(models.TransientModel):
    _name = "suivi.machines.ajuster.contrat.ligne"
    _description = "Ajout à un contrat de location"

    assistant_id = fields.Many2one("suivi.machines.ajuster.contrat", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="assistant_id.currency_id")
    product_id = fields.Many2one("product.product", "Machine ou accessoire", required=True,
                                 domain="[('sale_ok', '=', True)]")
    quantite = fields.Float("Quantité", default=1.0, required=True, digits="Product Unit")
    prix_unitaire = fields.Monetary("Prix unitaire", compute="_compute_prix_unitaire", store=True,
                                    readonly=False, currency_field="currency_id")

    @api.depends("product_id")
    def _compute_prix_unitaire(self):
        for ligne in self:
            ligne.prix_unitaire = ligne.product_id.lst_price

    @api.constrains("quantite")
    def _check_quantite(self):
        if any(ligne.quantite <= 0 for ligne in self):
            raise UserError(self.env._("La quantité doit être positive."))
