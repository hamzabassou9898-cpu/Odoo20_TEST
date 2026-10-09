# -*- coding: utf-8 -*-
"""Ajuster un contrat de location : ajouter des machines, des accessoires, renouveler.
Un seul contrat par client : les ajouts deviennent des lignes du meme contrat (nouvelle livraison)."""
from odoo import api, fields, models
from odoo.exceptions import UserError


class AjusterContrat(models.TransientModel):
    _name = "suivi.ajuster.contrat"
    _description = "Ajuster un contrat de location"

    contrat_id = fields.Many2one(
        "sale.order", "Contrat de location", required=True,
        domain="[('type_commande', '=', 'location'), ('state', '=', 'sale')]")
    partner_id = fields.Many2one(related="contrat_id.partner_id", string="Client")
    date_fin_actuelle = fields.Datetime(related="contrat_id.date_fin_location", string="Fin actuelle")
    machines_actuelles_ids = fields.Many2many("stock.lot", string="Machines chez le client",
                                              compute="_compute_machines_actuelles")
    # 1. Machines en plus (disponibles en entrepot)
    machine_ids = fields.Many2many("stock.lot", string="Machines à ajouter",
                                   domain="[('est_machine', '=', True), ('machine_statut', '=', 'entrepot')]")
    # 2. Accessoires en plus
    accessoire_ids = fields.One2many("suivi.ajuster.contrat.ligne", "assistant_id", "Accessoires à ajouter")
    # 3. Renouvellement (meme contrat, nouvelle date de fin)
    renouveler = fields.Boolean("Renouveler le contrat")
    nouvelle_date_fin = fields.Datetime("Nouvelle fin de location")
    note = fields.Text("Note (visible dans le contrat)")

    @api.depends("contrat_id")
    def _compute_machines_actuelles(self):
        for assistant in self:
            assistant.machines_actuelles_ids = (assistant.contrat_id._machines_a_reprendre()
                                                if assistant.contrat_id else False)

    @api.onchange("renouveler", "contrat_id")
    def _onchange_renouveler(self):
        if self.renouveler and not self.nouvelle_date_fin:
            self.nouvelle_date_fin = fields.Datetime.add(self.date_fin_actuelle or fields.Datetime.now(), years=1)

    def _contexte_lignes(self):
        # Application Location (Enterprise) : les nouvelles lignes sont des lignes de location
        return {"in_rental_app": True} if "is_rental_order" in self.contrat_id._fields \
            and self.contrat_id.is_rental_order else {}

    def action_appliquer(self):
        self.ensure_one()
        contrat = self.contrat_id
        accessoires = self.accessoire_ids.filtered(lambda l: l.product_id and l.quantite > 0)
        if not (self.machine_ids or accessoires or self.renouveler):
            raise UserError(self.env._("Choisissez au moins une machine, un accessoire ou le renouvellement."))
        deja_louees = self.machine_ids.filtered(lambda l: l.machine_statut != "entrepot")
        if deja_louees:
            raise UserError(self.env._("Ces machines ne sont plus en entrepôt : %s",
                                       ", ".join(deja_louees.mapped("name"))))
        if self.renouveler and not self.nouvelle_date_fin:
            raise UserError(self.env._("Indiquez la nouvelle date de fin de location."))
        lignes = [(0, 0, {"product_id": lot.product_id.id, "product_uom_qty": 1, "machine_lot_id": lot.id})
                  for lot in self.machine_ids]
        lignes += [(0, 0, {"product_id": l.product_id.id, "product_uom_qty": l.quantite}) for l in accessoires]
        livraisons_avant = contrat.picking_ids
        resume = []
        if lignes:
            verrouille = "locked" in contrat._fields and contrat.locked
            if verrouille:
                contrat.action_unlock()
            contrat.with_context(**self._contexte_lignes()).write({"order_line": lignes})
            if verrouille:
                contrat.action_lock()
            if self.machine_ids:
                resume.append(self.env._("machine(s) ajoutée(s) : %s", ", ".join(self.machine_ids.mapped("name"))))
            if accessoires:
                resume.append(self.env._("accessoire(s) ajouté(s) : %s", ", ".join(
                    "%s × %s" % (l.quantite, l.product_id.display_name) for l in accessoires)))
        if self.renouveler:
            resume.append(contrat._prolonger_location(self.nouvelle_date_fin))
        if lignes:
            contrat.message_post(body=self.env._("Contrat ajusté — %s", " ; ".join(resume)) +
                                 (" — %s" % self.note if self.note else ""))
        elif self.note:
            contrat.message_post(body=self.note)
        # Nouvelle livraison (machines / accessoires en plus) : on l'ouvre pour la planifier
        nouvelles = contrat.picking_ids - livraisons_avant
        if len(nouvelles) == 1:
            return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": nouvelles.id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "res_model": "sale.order", "res_id": contrat.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}


class AjusterContratLigne(models.TransientModel):
    _name = "suivi.ajuster.contrat.ligne"
    _description = "Accessoire à ajouter au contrat"

    assistant_id = fields.Many2one("suivi.ajuster.contrat", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", "Accessoire", required=True,
                                 domain="[('sale_ok', '=', True), ('categ_id.suivi_machine', '=', False)]")
    quantite = fields.Float("Quantité", default=1.0)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_ajuster_contrat(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Ajuster le contrat"),
                "res_model": "suivi.ajuster.contrat", "view_mode": "form", "views": [(False, "form")],
                "target": "new", "context": {"default_contrat_id": self.id}}
