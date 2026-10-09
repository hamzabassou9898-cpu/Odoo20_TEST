# -*- coding: utf-8 -*-
"""Planifier le ramassage depuis une livraison terminee : bon de retour pret, en un clic."""
from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _est_livraison_client(self):
        self.ensure_one()
        return self.state == "done" and self.picking_type_code == "outgoing" \
            and self.location_dest_id.usage != "internal"

    def _retours_en_cours(self):
        """Bons de retour deja crees depuis cette livraison et pas encore faits."""
        self.ensure_one()
        retours = self.return_ids if "return_ids" in self._fields else self.browse()
        return retours.filtered(lambda r: r.state not in ("done", "cancel"))

    def action_planifier_ramassage(self):
        self.ensure_one()
        if not self._est_livraison_client():
            raise UserError(self.env._("Le ramassage se planifie depuis une livraison terminée."))
        encours = self._retours_en_cours()[:1]
        if encours:
            return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": encours.id,
                    "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "name": self.env._("Planifier le ramassage"),
                "res_model": "suivi.machines.planifier.ramassage", "view_mode": "form",
                "views": [(False, "form")], "target": "new", "context": {"default_picking_id": self.id}}


class PlanifierRamassage(models.TransientModel):
    _name = "suivi.machines.planifier.ramassage"
    _description = "Planifier le ramassage"

    picking_id = fields.Many2one("stock.picking", "Livraison", required=True, readonly=True)
    partner_id = fields.Many2one(related="picking_id.partner_id", string="Client")
    machines_livrees_ids = fields.Many2many("stock.lot", "suivi_ramassage_livrees_rel", string="Machines livrées",
                                            compute="_compute_machines_livrees")
    lot_ids = fields.Many2many("stock.lot", "suivi_ramassage_lot_rel", string="Machines à reprendre",
                               domain="[('id', 'in', machines_livrees_ids)]")
    avec_accessoires = fields.Boolean("Reprendre aussi les accessoires", default=True,
                                      help="Pompes, etc. livrées avec les machines (même quantité).")
    accessoires = fields.Char("Accessoires", compute="_compute_machines_livrees")
    date = fields.Datetime("Date du ramassage", required=True, default=lambda s: s._default_date())
    livreur_id = fields.Many2one("res.users", "Technicien assigné",
                                 default=lambda s: s._picking_contexte().livreur_id)

    def _picking_contexte(self):
        return self.env["stock.picking"].browse(self.env.context.get("default_picking_id"))

    def _default_date(self):
        # Demain, 9 h (heure de l'utilisateur)
        demain = fields.Datetime.context_timestamp(self, fields.Datetime.now()).replace(
            hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return demain.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        picking = self._picking_contexte()
        if "lot_ids" in fields_list and picking:
            res["lot_ids"] = [(6, 0, self._machines_chez_client(picking).ids)]
        return res

    @api.model
    def _machines_livrees(self, picking):
        return picking.move_line_ids.lot_id.filtered("est_machine")

    @api.model
    def _machines_chez_client(self, picking):
        """Machines de la livraison qui ne sont pas revenues en stock depuis."""
        return self._machines_livrees(picking).filtered(
            lambda l: not any(q.quantity > 0 and q.location_id.usage == "internal" for q in l.quant_ids))

    @api.model
    def _accessoires_livres(self, picking):
        return [(m.product_id, m.quantity, m.uom_id) for m in picking.move_ids
                if m.state == "done" and m.quantity > 0 and not m.product_id.categ_id.suivi_machine
                and m.product_id.is_storable]

    @api.depends("picking_id")
    def _compute_machines_livrees(self):
        for wiz in self:
            wiz.machines_livrees_ids = self._machines_livrees(wiz.picking_id)
            wiz.accessoires = ", ".join("%g × %s" % (qte, produit.display_name)
                                        for produit, qte, _uom in self._accessoires_livres(wiz.picking_id)) or False

    def action_planifier(self):
        self.ensure_one()
        livraison = self.picking_id
        accessoires = self._accessoires_livres(livraison) if self.avec_accessoires else []
        if not self.lot_ids and not accessoires:
            raise UserError(self.env._("Choisissez au moins une machine ou un accessoire à reprendre."))
        retour = livraison._create_return()
        source, destination = retour.location_id, retour.location_dest_id
        retour.move_ids.unlink()
        Move = self.env["stock.move"]
        commun = {"picking_id": retour.id, "location_id": source.id, "location_dest_id": destination.id,
                  "partner_id": retour.partner_id.id}
        for lot in self.lot_ids:
            Move.create(dict(commun, product_id=lot.product_id.id, product_uom_qty=1,
                             uom_id=lot.product_id.uom_id.id, machine_lot_id=lot.id))
        for produit, qte, uom in accessoires:
            Move.create(dict(commun, product_id=produit.id, product_uom_qty=qte, uom_id=uom.id))
        retour.write({"scheduled_date": self.date, "livreur_id": self.livreur_id.id,
                      "origin": self.env._("Retour de %s", livraison.name)})
        retour.action_confirm()
        retour.action_assign()
        # Retour depuis le client (pas de reservation) : chaque ligne = la machine de son mouvement
        for move in retour.move_ids:
            if move.machine_lot_id:
                vals = {"lot_id": move.machine_lot_id.id, "quantity": 1}
            elif move.has_tracking in ("lot", "serial"):
                continue   # accessoire suivi par lot : numero a indiquer dans « Details »
            else:
                vals = {"quantity": move.product_uom_qty}
            if move.move_line_ids:
                move.move_line_ids[:1].write(vals)
                move.move_line_ids[1:].unlink()
            else:
                self.env["stock.move.line"].create(dict(vals, move_id=move.id, picking_id=retour.id,
                                                        product_id=move.product_id.id,
                                                        location_id=source.id, location_dest_id=destination.id))
        retour.write({"scheduled_date": self.date})
        livraison.message_post(body=self.env._("Ramassage planifié : %s", retour._get_html_link()))
        return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": retour.id,
                "views": [(False, "form")], "target": "current"}
