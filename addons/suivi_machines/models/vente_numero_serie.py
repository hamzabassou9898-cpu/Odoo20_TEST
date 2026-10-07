# -*- coding: utf-8 -*-
"""Choix du n° de serie d'une machine des la soumission, reserve ensuite sur la livraison."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    type_commande = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Type", default="vente",
        required=True, copy=True, tracking=True,
        help="Vente : la machine livrée devient « Vendue ». "
             "Location : elle devient « En location » chez le client.")

    def write(self, vals):
        res = super().write(vals)
        if "type_commande" in vals:
            # Recalculer le statut des machines deja livrees par cette commande
            lots = self.order_line.move_ids.move_line_ids.lot_id.filtered("est_machine")
            if lots:
                self.env.add_to_compute(self.env["stock.lot"]._fields["machine_statut"], lots)
                lots._recompute_recordset(["machine_statut"])
        return res


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    est_machine = fields.Boolean(related="product_id.categ_id.suivi_machine")
    machine_lot_id = fields.Many2one(
        "stock.lot", "N° de série", copy=False, index="btree_not_null",
        domain="[('product_id', '=', product_id), ('location_id.usage', '=', 'internal')]",
        help="Machine précise à livrer : elle sera réservée sur le bon de livraison.")

    @api.onchange("product_id")
    def _onchange_product_machine_lot(self):
        if self.machine_lot_id and self.machine_lot_id.product_id != self.product_id:
            self.machine_lot_id = False

    @api.onchange("machine_lot_id")
    def _onchange_machine_lot_qty(self):
        if self.machine_lot_id:
            self.product_uom_qty = 1

    @api.constrains("machine_lot_id", "product_uom_qty", "product_id")
    def _check_machine_lot(self):
        for line in self.filtered("machine_lot_id"):
            if line.machine_lot_id.product_id != line.product_id:
                raise ValidationError(self.env._(
                    "Le n° de série %(lot)s n'appartient pas au produit %(prod)s.",
                    lot=line.machine_lot_id.name, prod=line.product_id.display_name))
            if line.product_uom_qty != 1:
                raise ValidationError(self.env._(
                    "Une ligne avec un n° de série (%s) doit avoir une quantité de 1.",
                    line.machine_lot_id.name))
            autre = self.search([("id", "!=", line.id), ("machine_lot_id", "=", line.machine_lot_id.id),
                                 ("state", "in", ("draft", "sent", "sale")),
                                 ("order_id", "=", line.order_id.id)], limit=1)
            if autre:
                raise ValidationError(self.env._(
                    "Le n° de série %s est déjà sur une autre ligne de cette soumission.",
                    line.machine_lot_id.name))

    def _prepare_procurement_values(self):
        values = super()._prepare_procurement_values()
        if self.machine_lot_id:
            values["machine_lot_id"] = self.machine_lot_id.id
        return values

    def write(self, vals):
        res = super().write(vals)
        if "machine_lot_id" in vals:
            # Soumission deja confirmee : mettre a jour la livraison pas encore faite
            moves = self.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
            for line in self:
                line_moves = moves.filtered(lambda m: m.sale_line_id == line)
                if line_moves:
                    line_moves._do_unreserve()
                    line_moves.machine_lot_id = line.machine_lot_id
                    line_moves._action_assign()
        return res


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _get_stock_move_values(self, product_id, product_qty, uom_id, location_dest_id,
                               name, origin, company_id, values):
        vals = super()._get_stock_move_values(product_id, product_qty, uom_id, location_dest_id,
                                              name, origin, company_id, values)
        if values.get("machine_lot_id"):
            vals["machine_lot_id"] = values["machine_lot_id"]
        return vals


class StockMove(models.Model):
    _inherit = "stock.move"

    machine_lot_id = fields.Many2one("stock.lot", "N° de série demandé", copy=False)

    def _update_reserved_quantity_vals(self, need, location_id, lot_id=None, package_id=None,
                                       owner_id=None, strict=True):
        # Reserver uniquement le n° de serie choisi sur la soumission
        if self.machine_lot_id and not lot_id:
            lot_id = self.machine_lot_id
        return super()._update_reserved_quantity_vals(need, location_id, lot_id, package_id,
                                                       owner_id, strict)
