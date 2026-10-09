# -*- coding: utf-8 -*-
"""Statut Sage sur toutes les pieces de facturation : factures et avoirs, clients et fournisseurs."""
from odoo import api, fields, models

TYPES_FACTURATION = ("out_invoice", "out_refund", "in_invoice", "in_refund")
STATUTS_SAGE = [("non_concerne", "Non concerné"), ("a_transferer", "À enregistrer dans Sage"),
                ("transfere", "Enregistré dans Sage")]


class AccountMove(models.Model):
    _inherit = "account.move"

    sage_transfere = fields.Boolean("Enregistré dans Sage", copy=False, tracking=True)
    sage_date = fields.Date("Date d'enregistrement Sage", copy=False, tracking=True)
    sage_reference = fields.Char("N° de pièce Sage", copy=False, tracking=True)
    statut_sage = fields.Selection(STATUTS_SAGE, "Statut Sage", compute="_compute_statut_sage", store=True,
                                   index=True)

    @api.depends("move_type", "state", "sage_transfere")
    def _compute_statut_sage(self):
        for move in self:
            if move.move_type not in TYPES_FACTURATION or move.state != "posted":
                move.statut_sage = "transfere" if move.sage_transfere else "non_concerne"
            else:
                move.statut_sage = "transfere" if move.sage_transfere else "a_transferer"

    def write(self, vals):
        # Case cochee dans la liste : date du jour ; decochee : date videe
        if "sage_transfere" in vals and "sage_date" not in vals:
            vals = dict(vals, sage_date=fields.Date.context_today(self) if vals["sage_transfere"] else False)
        return super().write(vals)

    def action_transfere_sage(self):
        """Marque les pieces (une ou plusieurs) comme transferees dans Sage."""
        a_marquer = self.filtered(lambda m: m.move_type in TYPES_FACTURATION and not m.sage_transfere)
        a_marquer.write({"sage_transfere": True, "sage_date": fields.Date.context_today(self)})
        return True

    def action_annuler_transfert_sage(self):
        self.write({"sage_transfere": False, "sage_date": False})
        return True


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    @api.depends("frais_ids.sous_total", "sale_order_id", "facture_sage",
                 "sale_order_id.invoice_ids.sage_transfere", "sale_order_id.invoice_ids.state")
    def _compute_facturation(self):
        super()._compute_facturation()
        # Bon de commande facture et facture(s) transferee(s) dans Sage : intervention facturee
        for interv in self.filtered(lambda i: i.etat_facturation == "bon_cree"):
            factures = interv.sale_order_id.invoice_ids.filtered(
                lambda f: f.state == "posted" and f.move_type == "out_invoice")
            if factures and all(factures.mapped("sage_transfere")):
                interv.etat_facturation = "facture"
