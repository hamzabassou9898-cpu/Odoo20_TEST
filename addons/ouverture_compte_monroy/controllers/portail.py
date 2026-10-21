# -*- coding: utf-8 -*-
"""Page du client : formulaire d'ouverture de compte ouvert par le lien du courriel (jeton d'acces)."""
from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class OuverturePortail(CustomerPortal):

    def _ouverture(self, ouverture_id, access_token):
        return self._document_check_access("ouverture.compte", ouverture_id, access_token=access_token)

    @http.route(["/ouverture/<int:ouverture_id>"], type="http", auth="public", website=True)
    def ouverture_page(self, ouverture_id, access_token=None, **kw):
        try:
            ouverture = self._ouverture(ouverture_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")
        return request.render("ouverture_compte_monroy.ouverture_page", {
            "doc": ouverture, "editable": ouverture._modifiable_par_client(),
            "access_token": access_token or "", "manquants": ouverture._manquants()})

    @http.route(["/ouverture/<int:ouverture_id>/champ"], type="http", auth="public", methods=["POST"],
                website=True)
    def ouverture_champ(self, ouverture_id, access_token=None, **valeurs):
        """Une case remplie par le client (enregistrement automatique pendant qu'il ecrit)."""
        try:
            ouverture = self._ouverture(ouverture_id, access_token)
            ouverture._completer_par_client(valeurs)
        except (AccessError, MissingError):
            return request.make_response("", status=403)
        except UserError:
            return request.make_response("", status=409)
        return request.make_response("", status=204)

    @http.route(["/ouverture/<int:ouverture_id>/etat"], type="jsonrpc", auth="public", website=True)
    def ouverture_etat(self, ouverture_id, access_token=None, **kw):
        """Onglet reste ouvert : le formulaire est-il encore a remplir ? (sinon la page se met a jour)."""
        try:
            ouverture = self._ouverture(ouverture_id, access_token)
        except (AccessError, MissingError):
            return {"modifiable": False}
        return {"modifiable": ouverture._modifiable_par_client()}

    @http.route(["/ouverture/<int:ouverture_id>/pdf"], type="http", auth="public", website=True)
    def ouverture_pdf(self, ouverture_id, access_token=None, **kw):
        """La demande signee, a telecharger par le client (PDF deja prepare, sinon fait a la demande)."""
        try:
            ouverture = self._ouverture(ouverture_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/my")
        if not ouverture.signature:
            return request.redirect(ouverture.get_portal_url())
        piece = ouverture.sudo()._pdf_pour_client()
        if not piece:
            return request.redirect(ouverture.get_portal_url())
        stream = request.env["ir.binary"]._get_stream_from(piece)
        stream.download_name = ouverture.sudo()._nom_pdf() + ".pdf"
        return stream.get_response(as_attachment=True)

    @http.route(["/ouverture/<int:ouverture_id>/signer"], type="jsonrpc", auth="public", website=True)
    def ouverture_signer(self, ouverture_id, access_token=None, name=None, signature=None):
        access_token = access_token or request.httprequest.args.get("access_token")
        try:
            ouverture = self._ouverture(ouverture_id, access_token)
        except (AccessError, MissingError):
            return {"error": request.env._("Formulaire introuvable.")}
        if not ouverture._modifiable_par_client():
            # Deja signe (autre onglet, double clic) ou retire : la page se recharge et montre ou il en est
            return {"force_refresh": True, "redirect_url": ouverture.get_portal_url()}
        try:
            ouverture._signer(name, signature)
        except UserError as erreur:
            return {"error": str(erreur)}
        return {"force_refresh": True, "redirect_url": ouverture.get_portal_url()}
