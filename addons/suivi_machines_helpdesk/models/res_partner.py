# -*- coding: utf-8 -*-
"""Fiche client : contrat de location actuel (choisi automatiquement) et historique d'achat."""
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    contrat_location_id = fields.Many2one(
        "sale.order", "Contrat de location actuel", compute="_compute_contrats_client",
        groups="sales_team.group_sale_salesman",
        help="Choisi automatiquement : le contrat confirmé dont des machines sont chez le client, "
             "sinon le plus récent.")
    contrat_location_type = fields.Selection(related="contrat_location_id.type_commande", string="Type de contrat")
    contrat_location_debut = fields.Datetime(related="contrat_location_id.date_debut_location",
                                             string="Début du contrat")
    contrat_location_fin = fields.Datetime(related="contrat_location_id.date_fin_location", string="Fin du contrat")
    historique_achat_ids = fields.Many2many(
        "sale.order", string="Historique d'achat", compute="_compute_contrats_client",
        groups="sales_team.group_sale_salesman")

    def _compute_contrats_client(self):
        Commande = self.env["sale.order"]
        for partner in self:
            client = partner.commercial_partner_id
            if not client.id:
                partner.contrat_location_id = partner.historique_achat_ids = False
                continue
            commandes = Commande.search([("partner_id", "child_of", client.id), ("state", "=", "sale")],
                                        order="date_order desc, id desc")
            partner.historique_achat_ids = commandes
            locations = commandes.filtered(lambda c: c.type_commande == "location")
            # Contrat actuel : machines encore chez le client, sinon le plus recent
            partner.contrat_location_id = (locations.filtered(lambda c: c._machines_a_reprendre())[:1]
                                           or locations[:1])


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    # Contrat du client, affiche des que le client est choisi
    contrat_client_id = fields.Many2one("sale.order", "Contrat de location", compute="_compute_contrat_client",
                                        groups="sales_team.group_sale_salesman")
    contrat_client_type = fields.Selection(related="contrat_client_id.type_commande", string="Type de contrat")
    contrat_client_debut = fields.Datetime(related="contrat_client_id.date_debut_location",
                                           string="Début du contrat")
    contrat_client_fin = fields.Datetime(related="contrat_client_id.date_fin_location", string="Fin du contrat")

    @api.depends("partner_id")
    def _compute_contrat_client(self):
        for ticket in self:
            client = ticket.commerce_id or ticket.partner_id
            ticket.contrat_client_id = client.contrat_location_id if client else False
