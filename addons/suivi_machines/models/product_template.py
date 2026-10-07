# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    est_categorie_machine = fields.Boolean(related="categ_id.suivi_machine")
    machine_total = fields.Integer("Machines", compute="_compute_machines")
    machine_client = fields.Integer("En location", compute="_compute_machines")
    machine_vendue = fields.Integer("Vendues", compute="_compute_machines")
    machine_entrepot = fields.Integer("En entrepôt", compute="_compute_machines")
    machine_probleme = fields.Integer("Réparation / à remplacer", compute="_compute_machines")
    machine_retard = fields.Integer("Entretien en retard", compute="_compute_machines")

    def _compute_machines(self):
        today = fields.Date.context_today(self)
        Lot = self.env["stock.lot"]
        par_tmpl = {}
        for lot in Lot.search_fetch([("product_id.product_tmpl_id", "in", self.ids)],
                                    ["product_id", "machine_statut", "date_prochain_entretien"]):
            par_tmpl.setdefault(lot.product_id.product_tmpl_id.id, Lot)
            par_tmpl[lot.product_id.product_tmpl_id.id] |= lot
        for tmpl in self:
            lots = par_tmpl.get(tmpl.id, Lot)
            # En entrepot = quantite en stock de l'Inventaire (avec ou sans n° de serie) ;
            # chez les clients = n° de serie livres (hors stock de l'entrepot)
            tmpl.machine_entrepot = int(tmpl.qty_available)
            tmpl.machine_client = len(lots.filtered(lambda l: l.machine_statut == "chez_client"))
            tmpl.machine_vendue = len(lots.filtered(lambda l: l.machine_statut == "vendue"))
            tmpl.machine_total = tmpl.machine_entrepot + tmpl.machine_client
            tmpl.machine_probleme = len(lots.filtered(
                lambda l: l.machine_statut in ("en_reparation", "a_remplacer", "hors_service")))
            tmpl.machine_retard = len(lots.filtered(
                lambda l: l.date_prochain_entretien and l.date_prochain_entretien < today))

    def action_voir_machines(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("suivi_machines.action_machines")
        action.update(name=self.name, display_name=self.name,
                      domain=[("product_id.product_tmpl_id", "=", self.id)],
                      context={"default_product_id": self.product_variant_id.id})
        return action
