# -*- coding: utf-8 -*-
"""Phase 2 : « Ma journée » des techniciens sur le portail web (/my/journee)."""
from datetime import date, datetime, time, timedelta

import pytz

from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.web import Home
from odoo.http import request
from odoo.tools.misc import format_date

COULEURS = {"livraison": "success", "ramassage": "warning", "entretien": "info",
            "reparation": "danger", "installation": "primary", "autre": "secondary"}


def _est_technicien():
    user = request.env.user
    return not user._is_public() and user.est_technicien


class PortailTechnicien(CustomerPortal):

    def _fuseau(self):
        return pytz.timezone(request.env.user.tz or "America/Toronto")

    def _jour(self, jour):
        try:
            return date.fromisoformat(jour) if jour else None
        except ValueError:
            return None

    def _taches_du_jour(self, jour):
        """Taches du technicien connecte pour une journee (retards inclus aujourd'hui), en sudo."""
        fuseau = self._fuseau()
        debut = fuseau.localize(datetime.combine(jour, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        journee = ["&", ("date", ">=", debut), ("date", "<", debut + timedelta(days=1))]
        if jour == datetime.now(fuseau).date():
            journee = ["|", *journee, ("etat_suivi", "=", "en_retard")]
        domaine = [("technicien_id", "=", request.env.user.id), *journee]
        return request.env["portail.tache"].with_context(tz=self._fuseau().zone).sudo().search(domaine, order="date, id")

    @http.route(["/my/journee"], type="http", auth="user", website=True)
    def ma_journee(self, jour=None, **kw):
        if not _est_technicien():
            return request.redirect("/my")
        aujourdhui = datetime.now(self._fuseau()).date()
        jour = self._jour(jour) or aujourdhui
        taches = self._taches_du_jour(jour)
        a_faire = taches.filtered("a_faire")
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "ma_journee",
            "taches": taches,
            "jour": jour,
            "aujourdhui": aujourdhui,
            "titre_jour": format_date(request.env, jour, date_format="EEEE d MMMM").capitalize(),
            "veille": (jour - timedelta(days=1)).isoformat(),
            "lendemain": (jour + timedelta(days=1)).isoformat(),
            "nb_faites": len(taches) - len(a_faire),
            "nb_retard": len(taches.filtered(lambda t: t.etat_suivi == "en_retard")),
            "couleurs": COULEURS,
        })
        return request.render("suivi_machines_portail.portal_ma_journee", values)

    @http.route(["/my/journee/tache/<int:tache_id>"], type="http", auth="user", website=True)
    def ma_tache(self, tache_id, **kw):
        tache = request.env["portail.tache"].with_context(tz=self._fuseau().zone).sudo().browse(tache_id).exists()
        # Un technicien ne voit que ses propres taches
        if not _est_technicien() or not tache or tache.technicien_id != request.env.user:
            return request.redirect("/my/journee")
        jour = fields.Datetime.context_timestamp(tache.with_context(tz=self._fuseau().zone), tache.date).date() \
            if tache.date else None
        ticket = tache.ticket_id
        client = ticket.partner_id or tache.partner_id
        values = self._prepare_portal_layout_values()
        values.update({
            "page_name": "ma_tache",
            "tache": tache,
            "ticket": ticket,
            "telephone": (ticket.partner_phone if ticket else False) or client.phone or client.commercial_partner_id.phone,
            "retour": "/my/journee" + ("?jour=%s" % jour.isoformat() if jour else ""),
            "couleurs": COULEURS,
        })
        return request.render("suivi_machines_portail.portal_ma_tache", values)


class HomeTechnicien(Home):

    def _login_redirect(self, uid, redirect=None):
        # Le technicien arrive directement sur sa journee
        if not redirect and request.env["res.users"].sudo().browse(uid).est_technicien:
            redirect = "/my/journee"
        return super()._login_redirect(uid, redirect=redirect)
