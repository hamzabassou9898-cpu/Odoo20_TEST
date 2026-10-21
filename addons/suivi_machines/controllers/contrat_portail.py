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

    @http.route()
    def portal_quote_accept(self, order_id, access_token=None, name=None, signature=None):
        """Contrat signe en ligne : le PDF signe est range dans le dossier du client, en arriere-plan (le client
        n'attend pas). Deja signe (double clic, Entree, autre onglet) : la page se recharge au lieu d'une
        erreur (le bouton de signature d'Odoo reste bloque apres une erreur)."""
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            order_sudo = self._contrat_du_client(order_id, access_token)
        except (AccessError, MissingError):
            order_sudo = None
        if order_sudo and order_sudo.signature and not order_sudo._has_to_be_signed():
            return {"force_refresh": True, "redirect_url": order_sudo.get_portal_url()}
        request.update_context(contrat_archivage_differe=True)
        resultat = super().portal_quote_accept(order_id, access_token=access_token, name=name, signature=signature)
        if order_sudo and isinstance(resultat, dict) and not resultat.get("error"):
            order_sudo._archiver_plus_tard()
        return resultat
