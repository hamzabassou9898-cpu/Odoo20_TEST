# -*- coding: utf-8 -*-
"""Choix du n° de serie d'une machine des la soumission, reserve ensuite sur la livraison."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    type_commande = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Type", default=lambda s: s._default_type_commande(),
        required=True, copy=True, tracking=True,
        help="Vente : la machine livrée devient « Vendue ». "
             "Location : elle devient « En location » chez le client.")

    date_debut_location = fields.Datetime(
        "Début de la location", compute="_compute_date_debut_location", store=True, readonly=False,
        help="Reprise de l'application Location si elle est installée, sinon à saisir.")
    date_fin_location = fields.Datetime(
        "Fin de la location", compute="_compute_date_fin_location", store=True, readonly=False,
        help="Date de reprise prévue : reprise de l'application Location si elle est installée, "
             "sinon à saisir. Sert à créer le ticket de reprise.")
    date_fin_auto = fields.Boolean(compute="_compute_date_fin_auto")
    machine_ids = fields.Many2many("stock.lot", string="Machines", compute="_compute_machine_ids")
    nb_machines = fields.Integer("Fiche de machine", compute="_compute_machine_ids")

    @api.depends(lambda self: ["rental_start_date"] if "rental_start_date" in self._fields else [])
    def _compute_date_debut_location(self):
        auto = "rental_start_date" in self._fields
        for order in self:
            order.date_debut_location = order.rental_start_date if auto else order.date_debut_location

    @api.depends(lambda self: ["rental_return_date"] if "rental_return_date" in self._fields else [])
    def _compute_date_fin_location(self):
        # Application Location (Enterprise) : sa date de retour fait foi
        auto = "rental_return_date" in self._fields
        for order in self:
            # sinon : date saisie a la main, conservee
            order.date_fin_location = order.rental_return_date if auto else order.date_fin_location

    def _compute_date_fin_auto(self):
        for order in self:
            order.date_fin_auto = "rental_return_date" in self._fields

    @api.depends("order_line.machine_lot_id", "order_line.move_ids.move_line_ids.lot_id")
    def _compute_machine_ids(self):
        for order in self:
            lots = (order.order_line.machine_lot_id
                    | order.order_line.move_ids.move_line_ids.lot_id.filtered("est_machine"))
            order.machine_ids = lots
            order.nb_machines = len(lots)

    def action_fiches_machines(self):
        """Une machine : sa fiche. Plusieurs : la liste des machines de la commande."""
        self.ensure_one()
        if len(self.machine_ids) == 1:
            return {"type": "ir.actions.act_window", "name": self.machine_ids.display_name,
                    "res_model": "stock.lot", "res_id": self.machine_ids.id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Machines de %s", self.name),
            "res_model": "stock.lot",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", self.machine_ids.ids)],
            "target": "current",
        }

    @api.model
    def _default_type_commande(self):
        # Commande creee depuis l'application Location (Enterprise) : toujours une location
        ctx = self.env.context
        return "location" if ctx.get("in_rental_app") or ctx.get("default_is_rental_order") else "vente"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("is_rental_order"):
                vals["type_commande"] = "location"
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("is_rental_order"):
            vals = dict(vals, type_commande="location")
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

    def action_fiche_machine(self):
        """Ouvre la fiche de la machine (n° de serie) dans Suivi des machines."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.machine_lot_id.display_name,
            "res_model": "stock.lot",
            "res_id": self.machine_lot_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

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
                # la re-reservation est faite par StockMove.write
                moves.filtered(lambda m: m.sale_line_id == line).machine_lot_id = line.machine_lot_id
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

    machine_lot_id = fields.Many2one(
        "stock.lot", "N° de série", copy=False,
        domain="[('product_id', '=', product_id), ('location_id.usage', '=', 'internal')]",
        help="Machine précise à livrer (choisie sur le bon de vente ou au moment de la livraison) : "
             "elle est réservée à la place de celle choisie automatiquement.")
    est_machine = fields.Boolean(related="product_id.categ_id.suivi_machine")

    @api.constrains("machine_lot_id", "product_id")
    def _check_machine_lot_move(self):
        for move in self.filtered("machine_lot_id"):
            if move.machine_lot_id.product_id != move.product_id:
                raise ValidationError(self.env._(
                    "Le n° de série %(lot)s n'appartient pas au produit %(prod)s.",
                    lot=move.machine_lot_id.name, prod=move.product_id.display_name))

    def _prepare_merge_moves_distinct_fields(self):
        # Deux machines differentes (n° de serie choisis) ne sont jamais fusionnees
        return super()._prepare_merge_moves_distinct_fields() + ["machine_lot_id"]

    def write(self, vals):
        if "machine_lot_id" not in vals:
            return super().write(vals)
        # Nouveau n° de serie sur une livraison en cours : liberer l'ancien, reserver le nouveau
        a_reserver = self.filtered(lambda m: m.state in ("confirmed", "partially_available", "assigned", "waiting")
                                   and m.machine_lot_id.id != vals["machine_lot_id"])
        a_reserver._do_unreserve()
        res = super().write(vals)
        a_reserver._action_assign()
        return res

    def _update_reserved_quantity_vals(self, need, location_id, lot_id=None, package_id=None,
                                       owner_id=None, strict=True):
        # Reserver uniquement le n° de serie choisi sur la soumission
        if self.machine_lot_id and not lot_id:
            lot_id = self.machine_lot_id
        return super()._update_reserved_quantity_vals(need, location_id, lot_id, package_id,
                                                       owner_id, strict)
