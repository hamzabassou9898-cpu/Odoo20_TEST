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

    @api.constrains("state", "type_commande", "date_debut_location", "date_fin_location")
    def _check_periode_location(self):
        """Contrat de location confirme : la periode de location (debut et fin) est obligatoire."""
        for order in self:
            if order.type_commande == "location" and order.state == "sale" and not (
                    order.date_debut_location and order.date_fin_location):
                raise ValidationError(self.env._(
                    "%s : indiquez la période de location (début et fin) avant de confirmer.", order.name))

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        """Periode de location obligatoire a l'ecran (application Location si installee)."""
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "form":
            for node in arch.xpath("//field[@name='rental_start_date' or @name='rental_return_date' "
                                   "or @name='date_debut_location' or @name='date_fin_location']"):
                node.set("required", "type_commande == 'location'")
        return arch, view

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

    nb_livraisons_a_faire = fields.Integer("Livraisons à faire", compute="_compute_nb_livraisons_a_faire")

    @api.depends("picking_ids.state")
    def _compute_nb_livraisons_a_faire(self):
        for order in self:
            order.nb_livraisons_a_faire = len(order._livraisons_a_faire())

    def _livraisons_a_faire(self):
        self.ensure_one()
        return self.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")
                                         and p.picking_type_code == "outgoing")

    def action_ajuster_contrat(self):
        """Ajuster le contrat de location : machines ou accessoires en plus, nouvelle date de fin."""
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Ajuster le contrat %s", self.name),
                "res_model": "suivi.machines.ajuster.contrat", "view_mode": "form", "views": [(False, "form")],
                "target": "new", "context": {"default_commande_id": self.id}}

    def action_livraison_a_faire(self):
        """Ajustement du contrat (machine ou accessoire ajouté) : la livraison des ajouts, prête à planifier."""
        self.ensure_one()
        pickings = self._livraisons_a_faire()
        action = {"type": "ir.actions.act_window", "name": self.env._("Livraison à faire - %s", self.name),
                  "res_model": "stock.picking", "target": "current"}
        if len(pickings) == 1:
            return dict(action, res_id=pickings.id, view_mode="form", views=[(False, "form")])
        return dict(action, domain=[("id", "in", pickings.ids)], view_mode="list,form",
                    views=[(False, "list"), (False, "form")])

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
        nouveau = self.env._("New")
        for vals in vals_list:
            if vals.get("is_rental_order"):
                vals["type_commande"] = "location"
            location = (vals.get("type_commande") or self._default_type_commande()) == "location"
            # Contrat de location : son propre numero (LOC00001), pas celui des ventes
            if location and vals.get("name", nouveau) == nouveau:
                vals["name"] = self._numero_contrat(vals.get("company_id")) or nouveau
        return super().create(vals_list)

    @api.model
    def _numero_contrat(self, company_id=None):
        return self.env["ir.sequence"].with_company(company_id or self.env.company.id).next_by_code(
            "suivi_machines.contrat_location")

    def _renumeroter_selon_type(self):
        """Soumission (pas encore confirmee) passee de Vente a Location ou l'inverse : bon numero."""
        for order in self.filtered(lambda o: o.state in ("draft", "sent")):
            est_contrat = (order.name or "").startswith("LOC")
            if order.type_commande == "location" and not est_contrat:
                numero = order._numero_contrat(order.company_id.id)
            elif order.type_commande == "vente" and est_contrat:
                numero = self.env["ir.sequence"].with_company(order.company_id).next_by_code("sale.order")
            else:
                continue
            if numero:
                order.name = numero

    def write(self, vals):
        if vals.get("is_rental_order"):
            vals = dict(vals, type_commande="location")
        res = super().write(vals)
        if "type_commande" in vals and "name" not in vals:
            self._renumeroter_selon_type()
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

    @api.model_create_multi
    def create(self, vals_list):
        lignes = super().create(vals_list)
        # Ajustement d'un contrat deja confirme : trace dans le contrat, avec la livraison creee par Odoo
        ajouts = lignes.filtered(lambda l: l.order_id.state == "sale" and not l.display_type)
        for commande in ajouts.order_id:
            noms = ", ".join("%s × %s" % (l.product_uom_qty, l.product_id.display_name)
                             for l in ajouts.filtered(lambda l: l.order_id == commande))
            livraisons = ajouts.filtered(lambda l: l.order_id == commande).move_ids.picking_id
            message = self.env._("Contrat ajusté : ajout de %s.", noms)
            if livraisons:
                message += " " + self.env._("Livraison à faire : %s.", ", ".join(livraisons.mapped("name")))
            commande.message_post(body=message)
        return lignes

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

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        moves._reporter_numero_serie_vente()
        return moves

    def _reporter_numero_serie_vente(self):
        """N° de serie choisi a la livraison (pas au bon de vente) : repris sur la ligne du bon de vente,
        et note dans le bon de vente."""
        livrees = self.filtered(lambda m: m.state == "done" and m.sale_line_id and m.est_machine
                                and m._vers_client())
        for move in livrees:
            lots = move.move_line_ids.lot_id
            ligne = move.sale_line_id
            if len(lots) == 1 and ligne.product_uom_qty == 1 and ligne.machine_lot_id != lots:
                ligne.machine_lot_id = lots
        for commande in livrees.sale_line_id.order_id:
            lots = livrees.filtered(lambda m: m.sale_line_id.order_id == commande).move_line_ids.lot_id
            if lots:
                commande.message_post(body=self.env._(
                    "N° de série livrés : %s.", ", ".join(lots.mapped("display_name"))))

    def _vers_client(self):
        """Livraison chez le client (vente) ou vers l'emplacement de location."""
        self.ensure_one()
        societe = self.company_id or self.env.company
        loc_location = societe.rental_loc_id if "rental_loc_id" in societe._fields else False
        return self.location_dest_id.usage == "customer" or bool(loc_location and self.location_dest_id == loc_location)

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
        self._reporter_numero_serie_choisi()
        return res

    def _reporter_numero_serie_choisi(self):
        """N° de serie choisi sur la livraison (des l'enregistrement) : repris sur la ligne du bon de vente
        ou du contrat de location (une machine par ligne)."""
        for move in self.filtered(lambda m: m.machine_lot_id and m.sale_line_id and m.state != "cancel"):
            ligne = move.sale_line_id
            if ligne.product_uom_qty == 1 and ligne.machine_lot_id != move.machine_lot_id:
                ligne.machine_lot_id = move.machine_lot_id

    def _update_reserved_quantity_vals(self, need, location_id, lot_id=None, package_id=None,
                                       owner_id=None, strict=True):
        # Reserver uniquement le n° de serie choisi sur la soumission
        if self.machine_lot_id and not lot_id:
            lot_id = self.machine_lot_id
        return super()._update_reserved_quantity_vals(need, location_id, lot_id, package_id,
                                                       owner_id, strict)
