# -*- coding: utf-8 -*-
"""Prolonger un contrat de location : nouvelle date de fin, choisie par duree (1 an, 6 mois, 3 mois) ou
directement. La date native de l'application Location suit (voir _dates_vers_location)."""
from datetime import datetime, time

import pytz
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round
from odoo.tools.misc import format_date

DUREES = [("12", "1 an"), ("6", "6 mois"), ("3", "3 mois")]
AJUSTEMENTS = [("pourcentage", "Pourcentage"), ("prix", "Nouveau prix")]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    forfait_prix_ajuste = fields.Float(
        "Prochain forfait (ajusté)", digits="Product Price", copy=False, readonly=True,
        help="Prix par machine choisi à la prolongation : proposé au prochain renouvellement du forfait annuel.")

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

    def _ajuster_forfait(self, ancien, nouveau):
        """Prolongation : nouveau forfait / machine, propose au prochain renouvellement (rien n'est facture)."""
        self.ensure_one()
        if nouveau < 0:
            raise ValidationError(self.env._("Le forfait ne peut pas être négatif."))
        if float_compare(nouveau, ancien, precision_digits=2) == 0:
            return False
        self.write({"forfait_montant": nouveau, "forfait_prix_ajuste": nouveau})
        devise = self.currency_id or self.env.company.currency_id
        quand = self.forfait_prochaine_date and self.forfait_prochaine_date.strftime("%d/%m/%Y")
        self.message_post(body=Markup(self.env._(
            "Forfait annuel <b>ajusté</b> : %(ancien)s → <b>%(nouveau)s</b> par machine (%(ecart)s), "
            "à partir du prochain forfait%(quand)s.")) % {
            "ancien": devise.format(ancien), "nouveau": devise.format(nouveau),
            "ecart": "%+.2f %%" % (100 * (nouveau - ancien) / ancien) if ancien else "—",
            "quand": " (%s)" % quand if quand else ""})
        return True

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
    # Ajustement des frais : forfait annuel / machine, applique au prochain forfait
    avec_forfait = fields.Boolean(compute="_compute_forfait_actuel")
    forfait_actuel = fields.Float("Forfait actuel / machine", digits="Product Price",
                                  compute="_compute_forfait_actuel")
    nombre_machines = fields.Integer("Nombre de machines", compute="_compute_forfait_actuel")
    ajustement = fields.Selection(AJUSTEMENTS, "Ajustement", default="pourcentage", required=True)
    hausse = fields.Float("Hausse (%)", digits=(5, 2), default=0.0,
                          help="Pourcentage appliqué au forfait actuel (négatif pour une baisse). 0 : inchangé.")
    nouveau_forfait = fields.Float("Nouveau forfait / machine", digits="Product Price",
                                   compute="_compute_nouveau_forfait", store=True, readonly=False, precompute=True)
    currency_id = fields.Many2one(related="order_id.currency_id")
    calcul_forfait = fields.Char("Machines", compute="_compute_calcul_forfait")
    application_forfait = fields.Char("S'applique", compute="_compute_calcul_forfait")

    @api.depends("mode", "duree", "fin_actuelle")
    def _compute_nouvelle_date(self):
        for wiz in self:
            if wiz.mode == "duree" and wiz.duree:
                depart = wiz._fin_locale() or fields.Date.context_today(wiz)
                wiz.nouvelle_date = depart + relativedelta(months=int(wiz.duree))
            elif not wiz.nouvelle_date:
                wiz.nouvelle_date = wiz._fin_locale()

    @api.depends("order_id")
    def _compute_forfait_actuel(self):
        for wiz in self:
            order = wiz.order_id
            wiz.forfait_actuel = (order.forfait_prix_ajuste or order._forfait_prix_precedent()) if order else 0.0
            wiz.avec_forfait = bool(order) and (order.forfait_montant > 0 or wiz.forfait_actuel > 0)
            wiz.nombre_machines = order._machines_forfait()[0] if order else 0

    @api.depends("ajustement", "hausse", "forfait_actuel")
    def _compute_nouveau_forfait(self):
        for wiz in self:
            if wiz.ajustement == "pourcentage":
                wiz.nouveau_forfait = float_round(wiz.forfait_actuel * (1 + wiz.hausse / 100), precision_digits=2)
            elif not wiz.nouveau_forfait:
                wiz.nouveau_forfait = wiz.forfait_actuel

    @api.depends("nouveau_forfait", "nombre_machines")
    def _compute_calcul_forfait(self):
        for wiz in self:
            devise = wiz.order_id.currency_id or self.env.company.currency_id
            wiz.calcul_forfait = self.env._("%(nb)s × %(prix)s = %(total)s / an", nb=wiz.nombre_machines,
                                            prix=devise.format(wiz.nouveau_forfait),
                                            total=devise.format(wiz.nouveau_forfait * wiz.nombre_machines))
            prochaine = wiz.order_id.forfait_prochaine_date
            wiz.application_forfait = self.env._("au prochain forfait annuel (%s)",
                                                 format_date(self.env, prochaine, date_format="d MMM y")) \
                if prochaine else self.env._("au prochain forfait annuel")

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
        if self.avec_forfait:
            self.order_id._ajuster_forfait(self.forfait_actuel, self.nouveau_forfait)
        return {"type": "ir.actions.act_window_close"}
