# -*- coding: utf-8 -*-
"""Frais d'une intervention (deplacement, reparation, livraison, pieces...) -> bon de commande -> Sage."""
from odoo import api, fields, models
from odoo.exceptions import UserError


class MachineInterventionFrais(models.Model):
    _name = "machine.intervention.frais"
    _description = "Frais d'une intervention"
    _order = "sequence, id"

    intervention_id = fields.Many2one("machine.intervention", "Intervention", required=True,
                                      index=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", "Produit / service", required=True,
                                 domain="[('sale_ok', '=', True)]")
    name = fields.Char("Description")
    quantite = fields.Float("Quantité", default=1.0, digits="Product Unit")
    prix_unitaire = fields.Float("Prix unitaire", digits="Product Price")
    currency_id = fields.Many2one(related="intervention_id.currency_id")
    sous_total = fields.Monetary("Sous-total", compute="_compute_sous_total", store=True)

    @api.depends("quantite", "prix_unitaire")
    def _compute_sous_total(self):
        for frais in self:
            frais.sous_total = frais.quantite * frais.prix_unitaire

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.prix_unitaire = self.product_id.lst_price


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    frais_ids = fields.One2many("machine.intervention.frais", "intervention_id", "Frais", copy=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    montant_frais = fields.Monetary("Total des frais", compute="_compute_facturation", store=True)
    sale_order_id = fields.Many2one("sale.order", "Bon de commande", copy=False, index="btree_not_null",
                                    tracking=True)
    facture_sage = fields.Boolean("Facturé dans Sage", copy=False, tracking=True)
    etat_facturation = fields.Selection(
        [("aucun", "Aucuns frais"), ("a_facturer", "À facturer"),
         ("bon_cree", "Bon de commande créé"), ("facture", "Facturé dans Sage")],
        "Facturation", compute="_compute_facturation", store=True)

    @api.depends("frais_ids.sous_total", "sale_order_id", "facture_sage")
    def _compute_facturation(self):
        for interv in self:
            interv.montant_frais = sum(interv.frais_ids.mapped("sous_total"))
            if interv.facture_sage:
                interv.etat_facturation = "facture"
            elif interv.sale_order_id:
                interv.etat_facturation = "bon_cree"
            elif interv.frais_ids:
                interv.etat_facturation = "a_facturer"
            else:
                interv.etat_facturation = "aucun"

    def action_creer_bon_commande(self):
        """Bon de commande (vente) avec les frais : l'administrateur s'en sert pour facturer dans Sage."""
        self.ensure_one()
        if not self.frais_ids:
            raise UserError(self.env._("Ajoutez d'abord les frais de l'intervention."))
        if not self.partner_id:
            raise UserError(self.env._("Indiquez le client de l'intervention."))
        if not self.sale_order_id:
            self.sale_order_id = self.env["sale.order"].create({
                "partner_id": self.partner_id.id,
                "origin": self.name,
                "type_commande": "vente",
                "order_line": [(0, 0, {"product_id": f.product_id.id, "name": f.name or f.product_id.display_name,
                                       "product_uom_qty": f.quantite, "price_unit": f.prix_unitaire})
                               for f in self.frais_ids],
            })
            self.message_post(body=self.env._("Bon de commande %s créé avec les frais.", self.sale_order_id.name))
        return self.action_voir_bon_commande()

    def action_voir_bon_commande(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.sale_order_id.name, "res_model": "sale.order",
                "res_id": self.sale_order_id.id, "view_mode": "form", "views": [(False, "form")],
                "target": "current"}

    def action_facture_sage(self):
        self.write({"facture_sage": True})
