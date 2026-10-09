# -*- coding: utf-8 -*-
"""Synchronisation ticket <-> intervention planifiee : meme date, meme technicien, des deux cotes."""
from odoo import api, models

CHAMPS_TICKET = {"date_planifiee", "user_id", "technicien_terrain_id"}
CHAMPS_INTERVENTION = {"date", "user_id", "ticket_id", "state"}


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _technicien_assigne(self):
        """Technicien assigne au ticket : technicien terrain (portail), sinon « Assigne a »."""
        self.ensure_one()
        terrain = self["technicien_terrain_id"] if "technicien_terrain_id" in self._fields else False
        return terrain or self.user_id

    def _technicien_ticket(self):
        """Technicien qui se deplace : l'assigne, sinon celui de la derniere intervention."""
        self.ensure_one()
        return self._technicien_assigne() or self.technicien_id

    def _valeurs_technicien(self, user):
        """Valeurs du ticket pour ce technicien (portail : technicien terrain ; interne : assigne)."""
        if "technicien_terrain_id" not in self._fields:
            return {"user_id": user.id}
        if user.share:
            return {"technicien_terrain_id": user.id}
        return {"user_id": user.id, "technicien_terrain_id": False}

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
        interventions = super().create(vals_list)
        if not self.env.context.get("synchro_intervention"):
            interventions._synchroniser_ticket()
        return interventions

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
