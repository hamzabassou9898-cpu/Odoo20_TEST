# -*- coding: utf-8 -*-
from odoo import api, fields, models

TYPES = [
    ("installation", "Installation"),
    ("entretien", "Entretien"),
    ("bris", "Bris"),
    ("reparation", "Réparation"),
    ("remplacement", "Remplacement"),
    ("ramassage", "Ramassage"),
    ("autre", "Autre"),
]


class MachineIntervention(models.Model):
    _name = "machine.intervention"
    _description = "Intervention sur une machine"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char("Numéro", readonly=True, copy=False, default="Nouveau")
    lot_id = fields.Many2one(
        "stock.lot", "Machine (n° de série)", required=True, index=True, tracking=True,
        domain="[('est_machine', '=', True)]")
    product_id = fields.Many2one(related="lot_id.product_id", store=True, string="Produit")
    machine_ref = fields.Char(related="lot_id.ref", string="# machine")
    type = fields.Selection(TYPES, "Type", required=True, default="entretien", tracking=True)
    date = fields.Datetime("Date", required=True, default=fields.Datetime.now, tracking=True)
    state = fields.Selection(
        [("planifie", "Planifiée"), ("fait", "Faite"), ("annule", "Annulée")],
        "Statut", default="planifie", required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", "Client", tracking=True)
    user_id = fields.Many2one("res.users", "Technicien", default=lambda self: self.env.user,
                              tracking=True)
    lot_remplacement_id = fields.Many2one(
        "stock.lot", "Machine de remplacement", domain="[('est_machine', '=', True)]",
        help="Machine installée à la place de celle-ci.")
    description = fields.Text("Description")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Nouveau") == "Nouveau":
                vals["name"] = self.env["ir.sequence"].next_by_code("machine.intervention") or "Nouveau"
        return super().create(vals_list)

    @api.onchange("lot_id")
    def _onchange_lot_id(self):
        if self.lot_id and not self.partner_id:
            self.partner_id = self.lot_id.machine_client_id

    def action_fait(self):
        self.write({"state": "fait"})

    def action_annuler(self):
        self.write({"state": "annule"})

    def action_planifier(self):
        self.write({"state": "planifie"})
