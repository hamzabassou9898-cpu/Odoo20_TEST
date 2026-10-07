# -*- coding: utf-8 -*-
"""Ticket d'assistance : le code client ramene tout le dossier du client et de sa machine."""
from odoo import api, fields, models


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    code_client = fields.Char("Code client", index="btree_not_null", tracking=True,
                              help="Numéro de client (ex. MON134) : remplit le client et ses machines.")

    # ------------------------------------------------------------ client
    # Natifs utilises : partner_id, commercial_partner_id (banniere), partner_phone, partner_email,
    # priority, tag_ids, description
    commercial_partner_id = fields.Many2one(related="partner_id.commercial_partner_id")
    commerce_id = fields.Many2one("res.partner", "Commerce", compute="_compute_client")
    adresse_commerce = fields.Char("Adresse du commerce", compute="_compute_client")
    telephone_commerce = fields.Char("Téléphone", compute="_compute_client")

    # ------------------------------------------------------------ machines
    lot_id = fields.Many2one("stock.lot", "Numéro de série", index="btree_not_null", tracking=True)
    machines_client_ids = fields.Many2many("stock.lot", string="Machines chez le client",
                                           compute="_compute_machines_client")
    nb_machines_client = fields.Integer("Inventaire chez le client", compute="_compute_machines_client")
    machine_modele_id = fields.Many2one(related="lot_id.product_id", string="Modèle")
    machine_numero = fields.Char(related="lot_id.ref", string="Machine actuelle")
    machine_statut = fields.Selection(related="lot_id.machine_statut")
    machine_date_installation = fields.Date(related="lot_id.date_installation")
    machine_dernier_entretien = fields.Date(related="lot_id.date_dernier_entretien")
    machine_prochain_entretien = fields.Date(related="lot_id.date_prochain_entretien")

    # ------------------------------------------------------------ historiques
    machine_historique_ids = fields.One2many(related="lot_id.historique_ids",
                                             string="Historique de la machine")
    machine_intervention_ids = fields.One2many(related="lot_id.intervention_ids",
                                               string="Interventions")
    tickets_precedents_ids = fields.Many2many(
        "helpdesk.ticket", "helpdesk_ticket_precedent_rel", "ticket_id", "precedent_id",
        string="Appels de service", compute="_compute_tickets_precedents")
    nb_tickets_precedents = fields.Integer("Nb appels de service", compute="_compute_tickets_precedents")
    diagnostic_initial = fields.Html("Notes internes - Diagnostic initial")

    # ------------------------------------------------------------ code client <-> client
    @api.model
    def _client_par_code(self, code):
        code = (code or "").strip()
        if not code:
            return self.env["res.partner"]
        clients = self.env["res.partner"].search([("ref", "=ilike", code)])
        # Le commerce (ou la societe) plutot qu'une personne rattachee
        return clients.filtered(lambda p: not (p.parent_id and p.type == "contact"))[:1] or clients[:1]

    @staticmethod
    def _code_du_client(partner):
        commerce = partner.parent_id if partner.parent_id and partner.type == "contact" else partner
        return commerce.ref or partner.ref or False

    @api.onchange("code_client")
    def _onchange_code_client(self):
        if not self.code_client:
            return
        self.code_client = self.code_client.strip().upper()
        client = self._client_par_code(self.code_client)
        if not client:
            return {"warning": {"title": self.env._("Code client inconnu"),
                                "message": self.env._("Aucun client n'a le code %s.", self.code_client)}}
        if self.commerce_id != client:
            self.partner_id = client
        self._choisir_machine()

    @api.onchange("partner_id")
    def _onchange_partner_code_client(self):
        if self.partner_id:
            code = self._code_du_client(self.partner_id)
            if code and code.upper() != (self.code_client or "").upper():
                self.code_client = code
        self._choisir_machine()

    def _choisir_machine(self):
        """Garde la machine si elle est chez ce client ; s'il n'en a qu'une, la choisit."""
        if self.lot_id and self.lot_id not in self.machines_client_ids:
            self.lot_id = False
        if not self.lot_id and len(self.machines_client_ids) == 1:
            self.lot_id = self.machines_client_ids

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code_client") and not vals.get("partner_id"):
                client = self._client_par_code(vals["code_client"])
                if client:
                    vals["partner_id"] = client.id
        return super().create(vals_list)

    # ------------------------------------------------------------ calculs
    @api.depends("partner_id.parent_id", "partner_id.type", "partner_id.phone", "partner_id.contact_address",
                 "partner_id.parent_id.phone", "partner_id.parent_id.contact_address")
    def _compute_client(self):
        for ticket in self:
            p = ticket.partner_id
            commerce = p.parent_id if p.parent_id and p.type == "contact" else p
            ticket.commerce_id = commerce
            ticket.adresse_commerce = commerce._display_address(without_name=True, separator=", ") if commerce else False
            ticket.telephone_commerce = commerce.phone

    @api.depends("partner_id")
    def _compute_machines_client(self):
        Lot = self.env["stock.lot"].sudo()
        for ticket in self:
            commerce = ticket.commerce_id
            lots = Lot.search([("est_machine", "=", True), ("machine_client_id", "child_of", commerce.id)],
                              order="name") if commerce else Lot
            ticket.machines_client_ids = lots.sudo(False)
            ticket.nb_machines_client = len(lots)

    @api.depends("partner_id", "lot_id")
    def _compute_tickets_precedents(self):
        for ticket in self:
            domaine = []
            if ticket.commerce_id:
                domaine = [("partner_id", "child_of", ticket.commerce_id.id)]
            if ticket.lot_id:
                domaine = ["|", ("lot_id", "=", ticket.lot_id.id)] + (
                    domaine or [("id", "=", 0)])
            autres = self.search([("id", "!=", ticket._origin.id)] + domaine,
                                 order="create_date desc") if domaine else self.browse()
            ticket.tickets_precedents_ids = autres
            ticket.nb_tickets_precedents = len(autres)

    # ------------------------------------------------------------ boutons
    def action_fiche_machine(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.lot_id.display_name,
                "res_model": "stock.lot", "res_id": self.lot_id.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def action_nouvelle_intervention(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Nouvelle intervention"),
                "res_model": "machine.intervention", "view_mode": "form",
                "views": [(False, "form")], "target": "new",
                "context": {"default_lot_id": self.lot_id.id,
                            "default_partner_id": self.commerce_id.id,
                            "default_type": "bris",
                            "default_description": self.name}}


class StockLot(models.Model):
    _inherit = "stock.lot"

    ticket_ids = fields.One2many("helpdesk.ticket", "lot_id", "Appels de service")  # lot natif du ticket
    nb_tickets = fields.Integer("Nb appels de service", compute="_compute_nb_tickets")

    def _compute_nb_tickets(self):
        for lot in self:
            lot.nb_tickets = len(lot.ticket_ids)

    def action_voir_tickets(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Appels de service - %s", self.name),
                "res_model": "helpdesk.ticket", "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")],
                "domain": [("lot_id", "=", self.id)],
                "context": {"default_lot_id": self.id,
                            "default_partner_id": self.machine_client_id.id}}
