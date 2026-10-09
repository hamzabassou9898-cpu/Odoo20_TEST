# -*- coding: utf-8 -*-
"""Synchronisation ticket <-> intervention planifiee : meme date, meme technicien, des deux cotes."""
from odoo import api, models

CHAMPS_TICKET = {"date_planifiee", "user_id"}
CHAMPS_INTERVENTION = {"date", "user_id", "ticket_id", "state"}


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _technicien_assigne(self):
        """Technicien assigne au ticket : le champ natif « Assigne a » (interne ou technicien portail)."""
        self.ensure_one()
        return self.user_id

    def _technicien_ticket(self):
        """Technicien qui se deplace : l'assigne, sinon celui de la derniere intervention."""
        self.ensure_one()
        return self._technicien_assigne() or self.technicien_id

    def _valeurs_technicien(self, user):
        """Valeurs du ticket pour ce technicien : un seul champ, « Assigne a »."""
        return {"user_id": user.id}

    def write(self, vals):
        res = super().write(vals)
        if CHAMPS_TICKET & set(vals) and not self.env.context.get("synchro_intervention"):
            for ticket in self:
                planifiees = ticket.intervention_ticket_ids.filtered(lambda i: i.state == "planifie")
                if not planifiees:
                    continue
                valeurs = {}
                if "date_planifiee" in vals and ticket.date_planifiee:
                    valeurs["date"] = ticket.date_planifiee
                if (CHAMPS_TICKET - {"date_planifiee"}) & set(vals) and ticket._technicien_ticket():
                    valeurs["user_id"] = ticket._technicien_ticket().id
                if valeurs:
                    planifiees.with_context(synchro_intervention=True).write(valeurs)
        return res


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._rattacher_ticket_entretien(vals) for vals in vals_list]
        interventions = super().create(vals_list)
        if not self.env.context.get("synchro_intervention"):
            interventions._synchroniser_ticket()
        return interventions

    @api.model
    def _rattacher_ticket_entretien(self, vals):
        """Entretien planifie depuis Interventions : il rejoint le ticket d'entretien ouvert de la machine
        (le ticket passe « Planifie » et va dans la journee du technicien)."""
        if (vals.get("ticket_id") or not vals.get("lot_id") or vals.get("type", "entretien") != "entretien"
                or vals.get("state", "planifie") != "planifie"):
            return vals
        ticket = self.env["helpdesk.ticket"].sudo().search(
            [("est_entretien", "=", True), ("lot_id", "=", vals["lot_id"]),
             ("statut_entretien", "in", ("a_planifier", "planifie"))], order="id desc", limit=1)
        return dict(vals, ticket_id=ticket.id) if ticket else vals

    def write(self, vals):
        res = super().write(vals)
        if CHAMPS_INTERVENTION & set(vals) and not self.env.context.get("synchro_intervention"):
            self._synchroniser_ticket()
        return res

    def _synchroniser_ticket(self):
        """Intervention planifiee : le ticket prend sa date et son technicien (portail des techniciens)."""
        for interv in self.filtered(lambda i: i.ticket_id and i.state == "planifie"):
            ticket = interv.ticket_id
            valeurs = {}
            if interv.date and ticket.date_planifiee != interv.date:
                valeurs["date_planifiee"] = interv.date
            if interv.user_id and ticket._technicien_assigne() != interv.user_id:
                valeurs.update(ticket._valeurs_technicien(interv.user_id))
            if valeurs:
                ticket.with_context(synchro_intervention=True).write(valeurs)
