# -*- coding: utf-8 -*-
"""Type de ticket (obligatoire a la creation) et statut des entretiens (a planifier / planifie / fait)."""
from odoo import api, fields, models

TYPES_DEMANDE = [
    ("reparation", "Réparation"),
    ("ramassage", "Ramassage"),
    ("entretien", "Entretien"),
    ("remplacement", "Machine à remplacer"),
    ("commande", "Passer une commande"),
]
# Tickets qui se planifient (technicien a envoyer chez le client)
TYPES_A_PLANIFIER = ("entretien", "reparation", "remplacement")
STATUTS_ENTRETIEN = [("a_planifier", "À planifier"), ("planifie", "Planifié"), ("fait", "Fait")]
# Etapes qui ferment un ticket (Resolu, Cloture, Annule)
MOTS_FERME = ("résolu", "resolu", "clôtur", "clotur", "annul")
# Tickets crees par les actions planifiees d'Odoo (bandeau en haut du ticket)
ORIGINES_AUTO = [("entretien", "Entretien à échéance"), ("reprise", "Fin de location")]


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    type_demande = fields.Selection(
        TYPES_DEMANDE, "Type de ticket", compute="_compute_type_demande", store=True, readonly=False,
        precompute=True, index=True, tracking=True,
        help="Ce qu'il faut faire chez le client : aide à planifier le ticket.")
    statut_entretien = fields.Selection(
        STATUTS_ENTRETIEN, "Planification", compute="_compute_statut_entretien", store=True,
        index=True, help="Entretiens et réparations. À planifier : aucun technicien. Planifié : assigné à un "
                         "technicien (ou intervention planifiée) — il apparaît dans sa journée. Fait : ticket résolu.")

    origine_auto = fields.Selection(
        ORIGINES_AUTO, "Créé automatiquement", readonly=True, copy=False,
        help="Ticket créé par une action planifiée d'Odoo (et non par une personne).")

    @api.depends("est_entretien", "commande_reprise_id")
    def _compute_type_demande(self):
        for ticket in self:
            if ticket.est_entretien:
                ticket.type_demande = "entretien"
            elif ticket.commande_reprise_id:
                ticket.type_demande = "ramassage"
            elif ticket.type_demande == "entretien":
                ticket.type_demande = False
            else:
                ticket.type_demande = ticket.type_demande

    @api.depends("est_entretien", "type_demande", "commande_reprise_id", "user_id", "stage_id",
                 "intervention_ticket_ids.state")
    def _compute_statut_entretien(self):
        for ticket in self:
            if ticket.commande_reprise_id or not (ticket.est_entretien
                                                  or ticket.type_demande in TYPES_A_PLANIFIER):
                ticket.statut_entretien = False
            elif any(mot in (ticket.stage_id.name or "").lower() for mot in MOTS_FERME):
                ticket.statut_entretien = "fait"
            elif ticket.user_id or "planifie" in ticket.sudo().intervention_ticket_ids.mapped("state"):
                ticket.statut_entretien = "planifie"
            else:
                ticket.statut_entretien = "a_planifier"

    # ------------------------------------------------------------ type « Ramassage » choisi a la main
    def _contrat_location_client(self):
        """Contrat de location confirme du client dont des machines sont encore chez lui : celui de la
        machine du ticket, sinon celui qui se termine le plus tot."""
        self.ensure_one()
        client = (self.commerce_id or self.partner_id).commercial_partner_id
        if not client:
            return self.env["sale.order"]
        commandes = self.env["sale.order"].search(
            [("type_commande", "=", "location"), ("state", "=", "sale"), "|",
             ("partner_id", "child_of", client.id), ("partner_shipping_id", "child_of", client.id)])
        commandes = commandes.filtered(lambda c: c._machines_a_reprendre())
        if self.lot_id:
            commandes = commandes.filtered(lambda c: self.lot_id in c._machines_a_reprendre()) or commandes
        return commandes.sorted(lambda c: (not c.date_fin_location, c.date_fin_location or fields.Datetime.now(),
                                           c.id))[:1]

    def _valeurs_ramassage(self, avec_machine=True):
        """Machines louees qui vont revenir : celle du ticket si elle est louee, sinon tout le contrat."""
        self.ensure_one()
        contrat = self._contrat_location_client()
        if not contrat:
            return {}
        machines = contrat._machines_a_reprendre()
        if self.lot_id in machines:
            machines = self.lot_id
        valeurs = {"commande_reprise_id": contrat.id, "date_fin_reprise": contrat.date_fin_location,
                   "machines_reprise_ids": [(6, 0, machines.ids)]}
        if avec_machine and not self.lot_id:
            valeurs["lot_id"] = machines[:1].id
        return valeurs

    def _ramassage_a_remplir(self):
        return self.filtered(lambda t: t.type_demande == "ramassage" and not t.commande_reprise_id
                             and t.partner_id and not t._est_ferme())

    @api.onchange("type_demande", "partner_id", "lot_id")
    def _onchange_type_ramassage(self):
        if self.type_demande != "ramassage":
            if self.commande_reprise_id and self.origine_auto != "reprise":
                self.update({"commande_reprise_id": False, "date_fin_reprise": False,
                             "machines_reprise_ids": [(5, 0, 0)]})
            return
        if self.origine_auto == "reprise":
            return
        # Sans toucher a « Numero de serie » : choisir une machine = ne reprendre qu'elle
        valeurs = self._valeurs_ramassage(avec_machine=False)
        if valeurs or self.commande_reprise_id:
            self.update(valeurs or {"commande_reprise_id": False, "date_fin_reprise": False,
                                    "machines_reprise_ids": [(5, 0, 0)]})

    @api.model
    def _avec_type(self, vals):
        """Type « Entretien » choisi a la main = ticket d'entretien (bouton Valider, Pilotage...)."""
        if "type_demande" in vals and "est_entretien" not in vals:
            vals = dict(vals, est_entretien=vals["type_demande"] == "entretien")
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create([self._avec_type(vals) for vals in vals_list])
        for ticket in tickets._ramassage_a_remplir():
            ticket.write(ticket._valeurs_ramassage())
        return tickets

    def write(self, vals):
        vals = self._avec_type(vals)
        if vals.get("type_demande") and vals["type_demande"] != "ramassage":
            # Plus un ramassage : on detache le contrat (sauf ticket de reprise cree par Odoo)
            manuels = self.filtered(lambda t: t.commande_reprise_id and t.origine_auto != "reprise")
            if manuels:
                super(HelpdeskTicket, manuels).write({"commande_reprise_id": False, "date_fin_reprise": False,
                                                      "machines_reprise_ids": [(5, 0, 0)]})
        res = super().write(vals)
        if {"type_demande", "partner_id", "lot_id"} & set(vals):
            for ticket in self._ramassage_a_remplir():
                valeurs = ticket._valeurs_ramassage()
                if valeurs:
                    super(HelpdeskTicket, ticket).write(valeurs)
        return res

    def action_nouvelle_intervention(self):
        action = super().action_nouvelle_intervention()
        if self.type_demande == "remplacement":
            action["context"]["default_type"] = "remplacement"
        return action
