# -*- coding: utf-8 -*-
"""Itineraire Google Maps d'un technicien pour une journee (toutes ses taches)."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError


class SuiviCarteItineraire(models.TransientModel):
    _name = "suivi.carte.itineraire"
    _description = "Itinéraire Google Maps d'un technicien"

    livreur_id = fields.Many2one("res.users", "Technicien", required=True, default=lambda self: self._default_livreur())
    date = fields.Date("Journée", required=True, default=fields.Date.context_today)
    inclure_faits = fields.Boolean("Inclure les arrêts déjà faits")
    arret_ids = fields.Many2many("portail.tache", string="Arrêts", compute="_compute_arret_ids")
    nb_arrets = fields.Integer("Nombre d'arrêts", compute="_compute_arret_ids")

    @api.model
    def _default_livreur(self):
        """L'utilisateur lui-meme s'il a des taches (technicien sur son telephone)."""
        user = self.env.user
        return user if self.env["portail.tache"].search_count([("technicien_id", "=", user.id)], limit=1) else False

    def _bornes_journee(self):
        """Debut et fin de la journee choisie, dans le fuseau de l'utilisateur, en UTC."""
        tz = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "America/Toronto")
        debut = tz.localize(datetime.combine(self.date, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        return debut, debut + timedelta(days=1)

    @api.depends("livreur_id", "date", "inclure_faits")
    def _compute_arret_ids(self):
        for wiz in self:
            if not (wiz.livreur_id and wiz.date):
                wiz.arret_ids = False
                wiz.nb_arrets = 0
                continue
            debut, fin = wiz._bornes_journee()
            domaine = [("technicien_id", "=", wiz.livreur_id.id), ("date", ">=", debut), ("date", "<", fin)]
            if not wiz.inclure_faits:
                domaine.append(("a_faire", "=", True))
            arrets = self.env["portail.tache"].search(domaine, order="date, id")
            wiz.arret_ids = arrets
            wiz.nb_arrets = len(arrets)

    def action_ouvrir_itineraire(self):
        self.ensure_one()
        if not self.arret_ids:
            raise UserError(self.env._("Aucun arrêt pour %(livreur)s ce jour-là.", livreur=self.livreur_id.name))
        return self.arret_ids.action_itineraire_tournee()
