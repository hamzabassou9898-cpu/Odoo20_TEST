# -*- coding: utf-8 -*-
"""Page du client (lien du devis) : il complete lui-meme son contrat et la caution signe en ligne."""
from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from odoo.addons.sale.controllers.portal import CustomerPortal


class ContratPortail(CustomerPortal):

    def _contrat_du_client(self, order_id, access_token):
        return self._document_check_access("sale.order", order_id, access_token=access_token)

    @http.route(["/my/orders/<int:order_id>/contrat"], type="http", auth="public", methods=["POST"], website=True)
    def contrat_completer(self, order_id, access_token=None, **valeurs):
        try:
            order_sudo = self._contrat_du_client(order_id, access_token)
            order_sudo._contrat_completer_par_client(valeurs)
        except (AccessError, MissingError):
            return request.redirect("/my")
        except UserError:
            pass
        return request.redirect(order_sudo.get_portal_url(anchor="contrat_monroy"))

    @http.route(["/my/orders/<int:order_id>/caution/signer"], type="jsonrpc", auth="public", website=True)
    def caution_signer(self, order_id, access_token=None, name=None, signature=None):
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            order_sudo = self._contrat_du_client(order_id, access_token)
        except (AccessError, MissingError):
            return {"error": request.env._("Contrat introuvable.")}
        try:
            order_sudo._signer_caution(name, signature)
        except UserError as erreur:
            return {"error": str(erreur)}
        return {"force_refresh": True, "redirect_url": order_sudo.get_portal_url(anchor="contrat_monroy")}
