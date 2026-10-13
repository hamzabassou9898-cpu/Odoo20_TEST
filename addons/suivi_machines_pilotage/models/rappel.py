# -*- coding: utf-8 -*-
"""Rappel automatique au client la veille du passage du technicien (courriel)."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

from .portail_tache import FUSEAU

PARAM_ACTIF = "suivi_machines_pilotage.rappel_veille_actif"


class RappelVeille(models.AbstractModel):
    """Champ « rappel envoye le » commun aux documents qui portent une visite."""
    _name = "suivi.rappel.veille.mixin"
    _description = "Rappel la veille de la visite"

    rappel_veille_le = fields.Date("Rappel envoyé le", readonly=True, copy=False,
                                   help="Courriel de rappel envoyé au client la veille de la visite.")


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _inherit = ["helpdesk.ticket", "suivi.rappel.veille.mixin"]


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "suivi.rappel.veille.mixin"]


class MachineIntervention(models.Model):
    _name = "machine.intervention"
    _inherit = ["machine.intervention", "suivi.rappel.veille.mixin"]


class PortailTache(models.Model):
    _inherit = "portail.tache"

    @api.model
    def _taches_de_demain(self):
        """Visites de demain (journee de Quebec), a faire, avec un technicien et un client joignable."""
        fuseau = pytz.timezone(FUSEAU)
        demain = datetime.now(fuseau).date() + timedelta(days=1)
        debut = fuseau.localize(datetime.combine(demain, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        taches = self.sudo().search([("date", ">=", debut), ("date", "<", debut + timedelta(days=1)),
                                     ("a_faire", "=", True), ("technicien_id", "!=", False),
                                     ("partner_id", "!=", False)], order="date, id")
        return taches.filtered(lambda t: t._email_client())

    def _email_client(self):
        self.ensure_one()
        client = self.partner_id
        return client.email or client.commercial_partner_id.email

    @api.model
    def _cron_rappel_veille(self):
        """Chaque jour : un courriel de rappel par visite de demain (une seule fois par document)."""
        if not self.env["ir.config_parameter"].sudo().get_bool(PARAM_ACTIF, True):
            return self.browse()
        modele = self.env.ref("suivi_machines_pilotage.mail_rappel_veille", raise_if_not_found=False)
        if not modele:
            return self.browse()
        aujourdhui = fields.Date.context_today(self)
        envoyees = self.browse()
        for tache in self._taches_de_demain():
            source = tache._source().sudo()
            if source.rappel_veille_le == aujourdhui:
                continue
            destinataire = tache.partner_id if tache.partner_id.email else tache.partner_id.commercial_partner_id
            modele.sudo().send_mail(tache.id, email_values={"recipient_ids": [(6, 0, destinataire.ids)],
                                                            "model": source._name, "res_id": source.id})
            source.rappel_veille_le = aujourdhui
            source.message_post(body=self.env._(
                "Rappel envoyé à %(client)s (%(courriel)s) pour la visite de demain.",
                client=destinataire.display_name, courriel=destinataire.email))
            envoyees |= tache
        return envoyees
