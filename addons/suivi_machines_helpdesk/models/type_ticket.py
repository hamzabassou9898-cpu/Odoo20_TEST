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
        STATUTS_ENTRETIEN, "Statut de l'entretien", compute="_compute_statut_entretien", store=True,
        index=True, help="À planifier : aucun technicien. Planifié : assigné à un technicien "
                         "(ou intervention planifiée) — il apparaît dans sa journée. Fait : ticket résolu.")

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

    @api.depends("est_entretien", "user_id", "stage_id", "intervention_ticket_ids.state")
    def _compute_statut_entretien(self):
        for ticket in self:
            if not ticket.est_entretien:
                ticket.statut_entretien = False
            elif any(mot in (ticket.stage_id.name or "").lower() for mot in MOTS_FERME):
                ticket.statut_entretien = "fait"
            elif ticket.user_id or "planifie" in ticket.sudo().intervention_ticket_ids.mapped("state"):
                ticket.statut_entretien = "planifie"
            else:
                ticket.statut_entretien = "a_planifier"

    @api.model
    def _avec_type(self, vals):
        """Type « Entretien » choisi a la main = ticket d'entretien (bouton Valider, Pilotage...)."""
        if "type_demande" in vals and "est_entretien" not in vals:
            vals = dict(vals, est_entretien=vals["type_demande"] == "entretien")
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._avec_type(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._avec_type(vals))
