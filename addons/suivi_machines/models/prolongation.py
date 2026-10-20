# -*- coding: utf-8 -*-
"""Prolonger un contrat de location : nouvelle date de fin, choisie par duree (1 an, 6 mois, 3 mois) ou
directement. La date native de l'application Location suit (voir _dates_vers_location)."""
from datetime import datetime, time

import pytz
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

DUREES = [("12", "1 an"), ("6", "6 mois"), ("3", "3 mois")]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _prolongeable(self):
        self.ensure_one()
        return self.type_commande == "location" and self.state == "sale"

    def action_prolonger_contrat(self):
        self.ensure_one()
        if not self._prolongeable():
            raise UserError(self.env._("Seul un contrat de location confirmé peut être prolongé."))
        return {"type": "ir.actions.act_window", "name": self.env._("Prolonger le contrat %s", self.name),
                "res_model": "suivi.machines.prolonger.contrat", "view_mode": "form",
                "views": [(False, "form")], "target": "new", "context": {"default_order_id": self.id}}

    def _prolonger(self, nouvelle_fin):
        """Nouvelle date de fin du contrat (plus tard que l'actuelle), notee dans son fil."""
        self.ensure_one()
        if not self._prolongeable():
            raise UserError(self.env._("Seul un contrat de location confirmé peut être prolongé."))
        ancienne_fin = self.date_fin_location
        if ancienne_fin and nouvelle_fin <= ancienne_fin:
            raise ValidationError(self.env._("La nouvelle fin doit être après la fin actuelle (%s).",
                                             self._date_courte(ancienne_fin)))
        self.date_fin_location = nouvelle_fin
        self.message_post(body=Markup(self.env._("Contrat <b>prolongé</b> : fin le <b>%(nouvelle)s</b> "
                                                 "(avant : %(ancienne)s).")) % {
            "nouvelle": self._date_courte(nouvelle_fin),
            "ancienne": self._date_courte(ancienne_fin) if ancienne_fin else "—"})
        return ancienne_fin

    def _date_courte(self, moment):
        return fields.Datetime.context_timestamp(self, moment).strftime("%d/%m/%Y")


class ProlongerContrat(models.TransientModel):
    _name = "suivi.machines.prolonger.contrat"
    _description = "Prolonger un contrat de location"

    order_id = fields.Many2one("sale.order", "Contrat", required=True, readonly=True)
    partner_id = fields.Many2one(related="order_id.partner_id", string="Client")
    fin_actuelle = fields.Datetime(related="order_id.date_fin_location", string="Fin actuelle")
    mode = fields.Selection([("duree", "Prolonger d'une durée"), ("date", "Choisir la date de fin")],
                            "Prolongation", default="duree", required=True)
    duree = fields.Selection(DUREES, "Durée", default="12")
    nouvelle_date = fields.Date("Nouvelle fin", compute="_compute_nouvelle_date", store=True, readonly=False,
                                precompute=True, required=True)

    @api.depends("mode", "duree", "fin_actuelle")
    def _compute_nouvelle_date(self):
        for wiz in self:
            if wiz.mode == "duree" and wiz.duree:
                depart = wiz._fin_locale() or fields.Date.context_today(wiz)
                wiz.nouvelle_date = depart + relativedelta(months=int(wiz.duree))
            elif not wiz.nouvelle_date:
                wiz.nouvelle_date = wiz._fin_locale()

    def _fin_locale(self):
        return self.fin_actuelle and fields.Datetime.context_timestamp(self, self.fin_actuelle).date()

    def _nouvelle_fin(self):
        """Nouvelle fin a la meme heure que la fin actuelle (midi sinon), dans le fuseau de l'utilisateur."""
        fuseau = pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "UTC")
        heure = fields.Datetime.context_timestamp(self, self.fin_actuelle).time() if self.fin_actuelle else time(12)
        locale = fuseau.localize(datetime.combine(self.nouvelle_date, heure))
        return locale.astimezone(pytz.UTC).replace(tzinfo=None)

    def action_prolonger(self):
        self.ensure_one()
        self.order_id._prolonger(self._nouvelle_fin())
        return {"type": "ir.actions.act_window_close"}
