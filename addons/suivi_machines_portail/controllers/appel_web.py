# -*- coding: utf-8 -*-
"""Page publique « Appel de service » : formulaire du client -> ticket cree automatiquement."""
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..models.appel_web import CHAMPS_FORMULAIRE


class AppelDeServiceWeb(http.Controller):

    def _page(self, valeurs=None, erreur=None):
        Ticket = request.env["helpdesk.ticket"].sudo()
        return request.render("suivi_machines_portail.appel_de_service_page", {
            "champs": CHAMPS_FORMULAIRE,
            "types_demande": Ticket._fields["type_demande"]._description_selection(request.env),
            "types_reparation": Ticket._fields["type_reparation"]._description_selection(request.env),
            "valeurs": valeurs or {},
            "erreur": erreur,
        })

    @http.route("/appel-de-service", type="http", auth="public", methods=["GET", "POST"], website=True)
    def appel_de_service(self, **post):
        if request.httprequest.method != "POST":
            return self._page()
        if post.get("site_web"):
            # Champ cache rempli : robot. On fait comme si tout allait bien.
            return request.redirect("/appel-de-service/merci")
        try:
            # Point de sauvegarde : un ticket refuse (contrainte) n'est jamais enregistre a moitie
            with request.env.cr.savepoint():
                ticket = request.env["helpdesk.ticket"].sudo()._creer_depuis_formulaire_web(post)
        except (UserError, ValidationError) as erreur:
            return self._page(post, erreur.args[0])
        return request.redirect("/appel-de-service/merci?%s" % urlencode({"n": ticket._reference_web()}))

    @http.route("/appel-de-service/merci", type="http", auth="public", website=True)
    def appel_de_service_merci(self, n=None, **kw):
        return request.render("suivi_machines_portail.appel_de_service_merci", {"numero": (n or "")[:20]})
