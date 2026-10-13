# -*- coding: utf-8 -*-
"""Reparation, machine a remplacer, entretien : l'intervention se planifie toute seule.

Ticket enregistre avec une date prevue et une machine (entretien : et un technicien, car Odoo met deja une
date prevue aux tickets d'entretien qu'il cree) -> intervention « Planifiee » (meme date, meme technicien,
meme machine), visible dans la liste des interventions planifiees et dans la journee du technicien.
Le bouton « Marquer comme fait » termine l'intervention et resout le ticket (entretien : validation avec
le prochain entretien).
"""
from markupsafe import Markup

from odoo import api, models
from odoo.exceptions import UserError

# Type de ticket -> type d'intervention creee automatiquement
TYPES_INTERVENTION_AUTO = {"reparation": "reparation", "remplacement": "remplacement", "entretien": "entretien"}
CHAMPS_DECLENCHEURS = {"type_demande", "type_reparation", "date_planifiee", "lot_id", "user_id", "stage_id"}


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _valeurs_intervention_auto(self):
        self.ensure_one()
        description = self.name
        if self.type_reparation:
            probleme = dict(self._fields["type_reparation"]._description_selection(self.env))[self.type_reparation]
            description = "%s : %s" % (probleme, self.name)
        return {
            "ticket_id": self.id,
            "type": TYPES_INTERVENTION_AUTO[self.type_demande],
            "lot_id": self.lot_id.id,
            "partner_id": (self.commerce_id or self.partner_id).id,
            "date": self.date_planifiee,
            # Jamais l'utilisateur connecte par defaut : seulement le technicien du ticket
            "user_id": self._technicien_ticket().id,
            "description": description,
        }

    def _pret_a_planifier(self):
        """Date prevue et machine ; pour un entretien, aussi le technicien (la date seule vient d'Odoo)."""
        self.ensure_one()
        if not (self.date_planifiee and self.lot_id):
            return False
        return self.type_demande != "entretien" or bool(self._technicien_assigne())

    def _planifier_intervention_auto(self):
        """Cree (ou met a jour) l'intervention planifiee des reparations datees ; annule celle d'un ticket
        qui n'est plus une reparation."""
        Interv = self.env["machine.intervention"].sudo().with_context(synchro_intervention=True)
        for ticket in self:
            interventions = ticket.sudo().intervention_ticket_ids.filtered(lambda i: i.state != "annule")
            planifiees = interventions.filtered(lambda i: i.state == "planifie")
            if ticket.type_demande not in TYPES_INTERVENTION_AUTO:
                # Plus une reparation : l'intervention automatique n'a plus lieu d'etre
                planifiees.filtered(lambda i: i.type in TYPES_INTERVENTION_AUTO.values()).with_context(
                    synchro_intervention=True).action_annuler()
                continue
            if ticket._est_ferme():
                # Ticket ferme (bon signe, glisse dans Resolu...) : l'intervention se termine avec lui
                auto = planifiees.filtered(lambda i: i.type in TYPES_INTERVENTION_AUTO.values()).with_context(
                    synchro_intervention=True)
                if "annul" in (ticket.stage_id.name or "").lower():
                    auto.action_annuler()
                else:
                    auto.action_fait()
                continue
            if not ticket._pret_a_planifier():
                continue
            if not interventions:
                Interv.create(ticket._valeurs_intervention_auto())
            elif planifiees:
                valeurs = ticket._valeurs_intervention_auto()
                del valeurs["ticket_id"]
                if not valeurs["user_id"]:
                    del valeurs["user_id"]
                planifiees.with_context(synchro_intervention=True).write(valeurs)

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        tickets._planifier_intervention_auto()
        return tickets

    def write(self, vals):
        res = super().write(vals)
        if CHAMPS_DECLENCHEURS & set(vals) and not self.env.context.get("synchro_intervention"):
            self._planifier_intervention_auto()
        return res

    def action_marquer_fait(self):
        """Reparation faite : interventions planifiees faites, ticket resolu (le bon signe reste dans le fil).
        Entretien : la fenetre « Valider l'entretien » (date, frequence, prochain entretien)."""
        if len(self) == 1 and self.est_entretien:
            return self.action_valider_entretien()
        for ticket in self:
            ticket.sudo().intervention_ticket_ids.filtered(lambda i: i.state == "planifie").with_context(
                synchro_intervention=True).action_fait()
            if not ticket._est_ferme():
                resolu = ticket._etape_contenant("résolu", ticket.team_id if "team_id" in ticket._fields else None)
                if not resolu:
                    raise UserError(self.env._("Aucune étape « Résolu » : créez-la dans la configuration "
                                               "de l'assistance."))
                ticket.stage_id = resolu
            ticket.message_post(
                body=Markup("<p>%s</p>") % self.env._("Réparation marquée comme faite par %s.", self.env.user.name),
                message_type="comment", subtype_xmlid="mail.mt_note")
        return True
