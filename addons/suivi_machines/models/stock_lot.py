# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

STATUTS = [
    ("entrepot", "En entrepôt"),
    ("chez_client", "En location (chez un client)"),
    ("en_reparation", "En réparation"),
    ("a_remplacer", "À remplacer"),
    ("hors_service", "Hors service"),
    ("sans_emplacement", "Sans emplacement"),
]


class StockLot(models.Model):
    _inherit = "stock.lot"

    est_machine = fields.Boolean(related="product_id.categ_id.suivi_machine", store=True,
                                 string="Est une machine")
    intervention_ids = fields.One2many("machine.intervention", "lot_id", "Interventions")
    historique_ids = fields.One2many("machine.historique", "lot_id", "Historique")

    machine_etat = fields.Selection(
        [("actif", "Normal"), ("en_reparation", "En réparation"),
         ("a_remplacer", "À remplacer"), ("hors_service", "Hors service")],
        "État de la machine", default="actif", required=True, tracking=True)
    machine_statut = fields.Selection(
        STATUTS, "Statut", compute="_compute_machine", store=True,
        group_expand="_expand_statuts")
    machine_client_id = fields.Many2one("res.partner", "Client actuel",
                                        compute="_compute_machine", store=True)
    date_installation = fields.Date("Date d'installation", compute="_compute_machine", store=True)
    date_dernier_entretien = fields.Date("Dernier entretien", compute="_compute_machine", store=True)
    intervalle_entretien = fields.Integer("Entretien aux (mois)", default=12)
    date_prochain_entretien = fields.Date("Prochain entretien", compute="_compute_machine", store=True)
    nb_interventions = fields.Integer("Nb interventions", compute="_compute_machine", store=True)
    nb_bris = fields.Integer("Bris", compute="_compute_machine", store=True)
    date_mise_service = fields.Date("Mise en service",
                                    help="Date d'achat ou de première mise en service.")
    age_machine = fields.Char("Âge", compute="_compute_age")
    commande_count = fields.Integer("Commandes", compute="_compute_ventes")
    facture_count = fields.Integer("Factures", compute="_compute_ventes")

    def _expand_statuts(self, statuts, domain):
        return [k for k, _ in STATUTS if k != "sans_emplacement"]

    @api.depends("location_id", "machine_etat", "intervalle_entretien",
                 "intervention_ids.state", "intervention_ids.type",
                 "intervention_ids.date", "intervention_ids.partner_id")
    def _compute_machine(self):
        MoveLine = self.env["stock.move.line"]
        for lot in self:
            faites = lot.intervention_ids.filtered(lambda i: i.state == "fait").sorted("date")
            installs = faites.filtered(lambda i: i.type == "installation")
            entretiens = faites.filtered(lambda i: i.type == "entretien")
            lot.nb_interventions = len(lot.intervention_ids.filtered(lambda i: i.state != "annule"))
            lot.nb_bris = len(lot.intervention_ids.filtered(
                lambda i: i.type == "bris" and i.state != "annule"))
            lot.date_dernier_entretien = entretiens[-1:].date.date() if entretiens else False

            # Client actuel + date d'installation : tires de l'INVENTAIRE (dernier
            # bon de livraison valide vers le client). Sans livraison dans Odoo,
            # on se rabat sur la derniere installation / ramassage saisi en intervention.
            client = self.env["res.partner"]
            installation = False
            if lot.location_id.usage == "customer":
                ml = MoveLine.search([("lot_id", "=", lot._origin.id), ("state", "=", "done"),
                                      ("location_dest_id", "=", lot.location_id.id)],
                                     order="date desc", limit=1)
                client = ml.picking_id.partner_id or ml.move_id.partner_id
                installation = ml.date.date() if ml else False
            else:
                derniere = faites.filtered(lambda i: i.type in ("installation", "ramassage"))[-1:]
                if derniere.type == "installation":
                    client = derniere.partner_id
                    installation = derniere.date.date()
            lot.machine_client_id = client
            lot.date_installation = installation or (installs[-1:].date.date() if installs else False)
            depart = lot.date_dernier_entretien or lot.date_installation
            lot.date_prochain_entretien = (
                depart + relativedelta(months=lot.intervalle_entretien or 12) if depart else False)

            if lot.machine_etat != "actif":
                lot.machine_statut = lot.machine_etat
            elif client:
                lot.machine_statut = "chez_client"
            elif lot.location_id.usage == "internal":
                lot.machine_statut = "entrepot"
            else:
                lot.machine_statut = "sans_emplacement"

    @api.depends("date_mise_service", "intervention_ids.date", "intervention_ids.type")
    def _compute_age(self):
        """Mise en service, sinon 1re installation, sinon 1re entree dans l'inventaire."""
        today = fields.Date.context_today(self)
        for lot in self:
            installs = lot.intervention_ids.filtered(lambda i: i.type == "installation")
            premier_mvt = self.env["stock.move.line"].search(
                [("lot_id", "=", lot._origin.id), ("state", "=", "done")], order="date", limit=1)
            debut = (lot.date_mise_service
                     or (min(installs.mapped("date")).date() if installs else False)
                     or (premier_mvt.date.date() if premier_mvt else False))
            if not debut:
                lot.age_machine = False
                continue
            d = relativedelta(today, debut)
            lot.age_machine = f"{d.years} an(s) {d.months} mois" if d.years else f"{d.months} mois"

    def _machine_lignes_vente(self):
        mls = self.env["stock.move.line"].search([("lot_id", "in", self.ids), ("state", "=", "done")])
        return mls.move_id.sale_line_id

    def _compute_ventes(self):
        for lot in self:
            lignes = lot._machine_lignes_vente() if lot.id else self.env["sale.order.line"]
            lot.commande_count = len(lignes.order_id)
            lot.facture_count = len(lignes.invoice_lines.move_id)

    # ------------------------------------------------------------ boutons
    def _action(self, model, nom, domaine, context=None, vues="list,form"):
        return {"type": "ir.actions.act_window", "name": nom, "res_model": model,
                "view_mode": vues, "domain": domaine, "context": context or {}}

    def action_voir_interventions(self):
        return self._action("machine.intervention", f"Interventions - {self.name}",
                            [("lot_id", "=", self.id)],
                            {"default_lot_id": self.id, "default_partner_id": self.machine_client_id.id},
                            "list,form,calendar")

    def action_voir_bris(self):
        action = self.action_voir_interventions()
        action.update(name=f"Bris - {self.name}",
                      domain=[("lot_id", "=", self.id), ("type", "=", "bris")])
        action["context"]["default_type"] = "bris"
        return action

    def action_voir_historique(self):
        return self._action("machine.historique", f"Historique - {self.name}",
                            [("lot_id", "=", self.id)], vues="list")

    def action_voir_commandes(self):
        commandes = self._machine_lignes_vente().order_id
        return self._action("sale.order", f"Commandes - {self.name}", [("id", "in", commandes.ids)])

    def action_voir_factures(self):
        factures = self._machine_lignes_vente().invoice_lines.move_id
        return self._action("account.move", f"Factures - {self.name}", [("id", "in", factures.ids)])

    def action_nouvelle_intervention(self):
        return {"type": "ir.actions.act_window", "res_model": "machine.intervention",
                "view_mode": "form", "target": "new",
                "context": {"default_lot_id": self.id,
                            "default_partner_id": self.machine_client_id.id}}
