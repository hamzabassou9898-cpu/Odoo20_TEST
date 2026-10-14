# -*- coding: utf-8 -*-
"""Portail livreurs : informations d'affichage des tournees (livraisons et ramassages)."""
from odoo import api, fields, models
from odoo.tools.misc import format_datetime


class StockPicking(models.Model):
    _inherit = "stock.picking"

    type_tournee = fields.Selection(
        [("livraison", "Livraison"), ("ramassage", "Ramassage"), ("autre", "Autre")],
        "Type de tournée", compute="_compute_type_tournee", store=True, index=True)
    date_tournee = fields.Char("Date de la tournée", compute="_compute_affichage_tournee")
    machines_tournee = fields.Char("Machines", compute="_compute_affichage_tournee")
    accessoires_tournee = fields.Char("Accessoires", compute="_compute_affichage_tournee")

    @api.depends("location_id.usage", "location_dest_id.usage", "company_id")
    def _compute_type_tournee(self):
        for picking in self:
            # Chez le client : emplacement Clients, ou l'emplacement interne « Location » (machines louees)
            societe = picking.company_id or self.env.company
            location = societe.rental_loc_id if "rental_loc_id" in societe._fields else self.env["stock.location"]

            def chez_client(emplacement):
                return emplacement.usage == "customer" or (location and emplacement == location)

            if chez_client(picking.location_dest_id) and not chez_client(picking.location_id):
                picking.type_tournee = "livraison"
            elif chez_client(picking.location_id) and not chez_client(picking.location_dest_id):
                picking.type_tournee = "ramassage"
            else:
                picking.type_tournee = "autre"

    @api.depends("scheduled_date", "move_ids.machine_lot_id", "move_ids.move_line_ids.lot_id",
                 "move_ids.product_uom_qty")
    def _compute_affichage_tournee(self):
        for picking in self:
            date = format_datetime(self.env, picking.scheduled_date, dt_format="EEE d MMM '·' HH 'h' mm") \
                if picking.scheduled_date else ""
            picking.date_tournee = date[:1].upper() + date[1:]
            lots = (picking.move_ids.machine_lot_id | picking.move_ids.move_line_ids.lot_id).filtered("est_machine")
            machines = ["%s (%s)" % (l.ref, l.name) if l.ref else l.name for l in lots]
            # Machines sans numero encore choisi (ex. retour cree depuis Location)
            sans_numero = picking.move_ids.filtered(
                lambda m: m.product_id.categ_id.suivi_machine and m.product_uom_qty > 0
                and not (m.machine_lot_id | m.move_line_ids.lot_id))
            machines += [self.env._("%(qte)g × %(produit)s (n° à préciser)", qte=m.product_uom_qty,
                                    produit=m.product_id.name) for m in sans_numero]
            picking.machines_tournee = ", ".join(machines) or False
            autres = picking.move_ids.filtered(
                lambda m: not m.product_id.categ_id.suivi_machine and m.product_uom_qty > 0)
            picking.accessoires_tournee = ", ".join(
                "%g × %s" % (m.product_uom_qty, m.product_id.name) for m in autres) or False
