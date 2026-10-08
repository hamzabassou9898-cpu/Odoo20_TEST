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
    adresse_commerce = fields.Text("Adresse commerciale", compute="_compute_client")

    # ------------------------------------------------------------ machines
    lot_id = fields.Many2one("stock.lot", "Numéro de série", index="btree_not_null", tracking=True)
    machines_client_ids = fields.Many2many("stock.lot", string="Machines chez le client",
                                           compute="_compute_machines_client")
    nb_machines_client = fields.Integer("Inventaire chez le client", compute="_compute_machines_client")
    machine_modele_id = fields.Many2one(related="lot_id.product_id", string="Modèle")
    machine_emplacement_id = fields.Many2one(related="lot_id.location_id", string="Emplacement")
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

    # ------------------------------------------------------------ suites du ticket
    intervention_ticket_ids = fields.One2many("machine.intervention", "ticket_id", "Interventions du ticket")
    vente_ids = fields.One2many("sale.order", "ticket_assistance_id", "Bons de vente")
    livraison_ids = fields.One2many("stock.picking", "ticket_assistance_id", "Livraisons")
    nb_interventions_ticket = fields.Integer("Nb interventions du ticket", compute="_compute_suites")
    nb_ventes = fields.Integer("Nb bons de vente", compute="_compute_suites")
    nb_livraisons = fields.Integer("Nb livraisons", compute="_compute_suites")
    technicien_id = fields.Many2one(
        "res.users", "Technicien", compute="_compute_technicien", store=True, index="btree_not_null",
        help="Technicien de la dernière intervention du ticket (choisi dans « Nouvelle intervention »).")

    # ------------------------------------------------------------ code client <-> client
    @api.model
    def _client_par_code(self, code):
        code = (code or "").strip()
        if not code:
            return self.env["res.partner"]
        # Comparaison exacte (sans tenir compte des majuscules) : « _ » et « % » ne sont pas des jokers
        clients = self.env["res.partner"].search([("ref", "ilike", code)]).filtered(
            lambda p: (p.ref or "").strip().upper() == code.upper())
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

    def _remplir_telephone(self):
        """Telephone natif du ticket : celui du commerce s'il est vide."""
        if "partner_phone" in self._fields and not self.partner_phone:
            self.partner_phone = self.commerce_id.phone or self.partner_id.phone

    def _choisir_machine(self):
        """Garde la machine si elle est chez ce client ; s'il n'en a qu'une, la choisit."""
        self._remplir_telephone()
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
    @api.depends("partner_id.parent_id", "partner_id.type", "partner_id.contact_address",
                 "partner_id.parent_id.contact_address")
    def _compute_client(self):
        for ticket in self:
            p = ticket.partner_id
            commerce = p.parent_id if p.parent_id and p.type == "contact" else p
            ticket.commerce_id = commerce
            ticket.adresse_commerce = commerce._display_address(without_name=True) if commerce else False

    @api.depends("partner_id")
    def _compute_machines_client(self):
        Lot = self.env["stock.lot"].sudo()
        for ticket in self:
            commerce = ticket.commerce_id
            lots = Lot.search([("est_machine", "=", True), ("machine_client_id", "child_of", commerce._origin.id)],
                              order="name") if commerce else Lot
            ticket.machines_client_ids = lots.sudo(False)
            ticket.nb_machines_client = len(lots)

    @api.depends("partner_id", "lot_id")
    def _compute_tickets_precedents(self):
        for ticket in self:
            domaine = []
            if ticket.commerce_id:
                domaine = [("partner_id", "child_of", ticket.commerce_id._origin.id)]
            if ticket.lot_id:
                domaine = ["|", ("lot_id", "=", ticket.lot_id._origin.id)] + (
                    domaine or [("id", "=", 0)])
            autres = self.search([("id", "!=", ticket._origin.id)] + domaine,
                                 order="create_date desc") if domaine else self.browse()
            ticket.tickets_precedents_ids = autres
            ticket.nb_tickets_precedents = len(autres)

    @api.depends("intervention_ticket_ids.user_id", "intervention_ticket_ids.state",
                 "intervention_ticket_ids.date")
    def _compute_technicien(self):
        for ticket in self:
            actives = ticket.sudo().intervention_ticket_ids.filtered(lambda i: i.state != "annule")
            ticket.technicien_id = actives.sorted(lambda i: (i.date, i.id))[-1:].user_id

    @api.depends("intervention_ticket_ids", "vente_ids.picking_ids", "livraison_ids")
    def _compute_suites(self):
        for ticket in self:
            # sudo : un agent sans droits Ventes/Inventaire voit quand meme les compteurs
            t = ticket.sudo()
            ticket.nb_interventions_ticket = len(t.intervention_ticket_ids)
            ticket.nb_ventes = len(t.vente_ids)
            ticket.nb_livraisons = len(t._livraisons())

    def _livraisons(self):
        """Livraisons directes du ticket + livraisons de ses bons de vente."""
        return self.livraison_ids | self.vente_ids.picking_ids

    # ------------------------------------------------------------ boutons
    def action_fiche_machine(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.lot_id.display_name,
                "res_model": "stock.lot", "res_id": self.lot_id.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def _action_liste(self, model, nom, records, context):
        action = {"type": "ir.actions.act_window", "name": nom, "res_model": model,
                  "context": context, "target": "current"}
        if len(records) == 1:
            action.update(res_id=records.id, view_mode="form", views=[(False, "form")])
        else:
            action.update(domain=[("id", "in", records.ids)], view_mode="list,form",
                          views=[(False, "list"), (False, "form")])
        return action

    def action_nouvelle_intervention(self):
        """Intervention liee au ticket : machine, client et probleme deja remplis."""
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Nouvelle intervention"),
                "res_model": "machine.intervention", "view_mode": "form",
                "views": [(False, "form")], "target": "new",
                "context": {"default_ticket_id": self.id,
                            "default_lot_id": self.lot_id.id,
                            "default_partner_id": self.commerce_id.id or self.partner_id.id,
                            "default_type": "reparation",
                            "default_description": self.name}}

    def action_voir_interventions_ticket(self):
        self.ensure_one()
        return self._action_liste("machine.intervention", self.env._("Interventions - %s", self.name),
                                  self.intervention_ticket_ids,
                                  {"default_ticket_id": self.id, "default_lot_id": self.lot_id.id,
                                   "default_partner_id": self.commerce_id.id})

    def action_creer_vente(self):
        """Bon de vente (pieces, accessoires, machine) pour le client du ticket."""
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Bon de vente"),
                "res_model": "sale.order", "view_mode": "form", "views": [(False, "form")],
                "target": "current",
                "context": {"default_partner_id": self.commerce_id.id or self.partner_id.id,
                            "default_ticket_assistance_id": self.id,
                            "default_origin": self.name,
                            "default_type_commande": "vente"}}

    def action_voir_ventes(self):
        self.ensure_one()
        return self._action_liste("sale.order", self.env._("Bons de vente - %s", self.name),
                                  self.vente_ids, {"default_ticket_assistance_id": self.id,
                                                   "default_partner_id": self.commerce_id.id})

    def action_creer_livraison(self):
        """Livraison directe (sans bon de vente) vers le commerce du client."""
        self.ensure_one()
        entrepot = self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1)
        return {"type": "ir.actions.act_window", "name": self.env._("Livraison"),
                "res_model": "stock.picking", "view_mode": "form", "views": [(False, "form")],
                "target": "current",
                "context": {"default_picking_type_id": entrepot.out_type_id.id,
                            "default_partner_id": self.commerce_id.id or self.partner_id.id,
                            "default_ticket_assistance_id": self.id,
                            "default_origin": self.name}}

    def action_voir_livraisons(self):
        self.ensure_one()
        return self._action_liste("stock.picking", self.env._("Livraisons - %s", self.name),
                                  self._livraisons(), {"default_ticket_assistance_id": self.id})


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket d'assistance", index="btree_not_null",
                                tracking=True, copy=False)

    def action_creer_bon_commande(self):
        # Bon de commande des frais : rattache aussi au ticket d'origine
        action = super().action_creer_bon_commande()
        for interv in self.filtered(lambda i: i.ticket_id and i.sale_order_id
                                    and not i.sale_order_id.ticket_assistance_id):
            interv.sale_order_id.ticket_assistance_id = interv.ticket_id
        return action


class SaleOrder(models.Model):
    _inherit = "sale.order"

    ticket_assistance_id = fields.Many2one("helpdesk.ticket", "Ticket d'assistance",
                                           index="btree_not_null", copy=False)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    ticket_assistance_id = fields.Many2one("helpdesk.ticket", "Ticket d'assistance",
                                           index="btree_not_null", copy=False)
    technicien_id = fields.Many2one(related="ticket_assistance_id.technicien_id", store=True,
                                    string="Technicien")
    route = fields.Char("Route", compute="_compute_route", store=True,
                        help="Adresse de livraison du client, pour planifier la tournée.")

    @api.depends("partner_id.type", "partner_id.parent_id", "partner_id.street", "partner_id.street2",
                 "partner_id.city", "partner_id.zip", "partner_id.state_id",
                 "partner_id.parent_id.street", "partner_id.parent_id.city", "partner_id.parent_id.zip")
    def _compute_route(self):
        for picking in self:
            p = picking.partner_id
            commerce = p.parent_id if p.parent_id and p.type == "contact" else p
            picking.route = commerce._display_address(without_name=True, separator=", ") if commerce else False


class StockMove(models.Model):
    _inherit = "stock.move"

    def _vals_intervention_retour(self, ml, picking):
        vals = super()._vals_intervention_retour(ml, picking)
        ticket = picking.ticket_assistance_id
        if ticket and ticket.lot_id and ticket.lot_id != ml.lot_id \
                and ml.lot_id not in ticket.machines_reprise_ids:
            # Retour de plusieurs machines : le ticket de reprise de cette machine-ci
            autre = self.env["helpdesk.ticket"].search(
                ["|", ("lot_id", "=", ml.lot_id.id), ("machines_reprise_ids", "in", ml.lot_id.ids),
                 ("commande_reprise_id", "!=", False),
                 ("commande_reprise_id", "=", ticket.commande_reprise_id.id)], order="id desc", limit=1)
            ticket = autre or ticket
        if ticket:
            vals["ticket_id"] = ticket.id
        return vals

    def _get_new_picking_values(self):
        # Livraison creee depuis un bon de vente du ticket : garde le lien vers le ticket
        vals = super()._get_new_picking_values()
        ticket = self.sale_line_id.order_id.ticket_assistance_id[:1]
        if ticket:
            vals["ticket_assistance_id"] = ticket.id
        return vals


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
