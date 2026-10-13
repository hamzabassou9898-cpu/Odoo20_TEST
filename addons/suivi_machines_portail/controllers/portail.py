# -*- coding: utf-8 -*-
"""Phase 2 : « Ma journée » des techniciens sur le portail web (/my/journee)."""
import binascii
from datetime import date, datetime, time, timedelta

import pytz

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.web import Home
from odoo.http import request

from ..models.bon_intervention import PROPRETES, TYPES_BON, texte_engagement, type_bon_de
from odoo.tools.image import image_data_uri
from odoo.tools.misc import format_date

# Pieces jointes envoyees depuis le portail
MAX_FICHIERS = 10
MAX_TAILLE = 20 * 1024 * 1024  # 20 Mo par fichier

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

    def _ma_tache(self, tache_id):
        """La tache du technicien connecte, sinon rien (un technicien ne voit que ses propres taches)."""
        tache = request.env["portail.tache"].with_context(tz=self._fuseau().zone).sudo().browse(tache_id).exists()
        if not _est_technicien() or not tache or tache.technicien_id != request.env.user:
            return None
        return tache

    @http.route(["/my/journee/tache/<int:tache_id>"], type="http", auth="user", website=True)
    def ma_tache(self, tache_id, envoye=None, erreur=None, **kw):
        tache = self._ma_tache(tache_id)
        if not tache:
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
            "mes_notes": self._mes_notes(tache),
            "envoye": envoye,
            "erreur": erreur,
            "max_fichiers": MAX_FICHIERS,
            "bon": tache._source().sudo().bon_intervention_ids[:1],
            "image_data_uri": image_data_uri,
            **self._valeurs_formulaire(tache),
        })
        return request.render("suivi_machines_portail.portal_ma_tache", values)

    def _valeurs_formulaire(self, tache):
        """Section du formulaire Monroy a signer (livraison, entretien/reparation, reprise)."""
        type_bon = type_bon_de(tache.type_tache)
        source = tache._source().sudo()
        reprise = type_bon == "reprise"
        return {
            "type_bon": type_bon,
            "titre_bon": dict(TYPES_BON)[type_bon],
            "texte_bon": texte_engagement(request.env, type_bon, tache.type_tache),
            "reprise": source if reprise else False,
            "proprietes": PROPRETES,
            # Reprise : l'etat (propre / moyen / sale...) est coche avant la signature
            "peut_signer": not reprise or bool(source.reprise_proprete),
        }

    @http.route(["/my/journee/tache/<int:tache_id>/reprise"], type="http", auth="user", website=True,
                methods=["POST"])
    def ma_tache_reprise(self, tache_id, proprete=None, pleine=None, en_fonction=None, **kw):
        """Etat des equipements a la reprise (cases du formulaire papier), avant la signature du client."""
        tache = self._ma_tache(tache_id)
        if not tache:
            return request.redirect("/my/journee")
        source = tache._source().sudo()
        if type_bon_de(tache.type_tache) == "reprise" and proprete in dict(PROPRETES):
            source.write({"reprise_proprete": proprete, "reprise_pleine": bool(pleine),
                          "reprise_en_fonction": bool(en_fonction)})
        return request.redirect("/my/journee/tache/%s#bon_intervention" % tache_id)

    def _mes_notes(self, tache):
        """Notes deja envoyees par ce technicien sur le document de la tache (plus recentes d'abord)."""
        return tache._source().sudo().note_technicien_ids.filtered(
            lambda n: n.technicien_id == request.env.user)

    @http.route(["/my/journee/tache/<int:tache_id>/note"], type="http", auth="user", website=True,
                methods=["POST"])
    def ma_tache_note(self, tache_id, note="", **kw):
        """Note du technicien (+ pieces jointes) : onglet « Notes du technicien » du ticket / transfert / intervention."""
        tache = self._ma_tache(tache_id)
        if not tache:
            return request.redirect("/my/journee")
        url = "/my/journee/tache/%s" % tache_id
        fichiers = [f for f in request.httprequest.files.getlist("pieces_jointes") if f and f.filename]
        if len(fichiers) > MAX_FICHIERS:
            return request.redirect(url + "?erreur=nombre")
        pieces = []
        for fichier in fichiers:
            contenu = fichier.read()
            if len(contenu) > MAX_TAILLE:
                return request.redirect(url + "?erreur=taille")
            pieces.append((fichier.filename, contenu))
        note = (note or "").replace("\r\n", "\n").strip()
        if not note and not pieces:
            return request.redirect(url + "?erreur=vide")
        # Pas de message dans la discussion : la note va dans l'onglet du document (aucun courriel)
        request.env["suivi.note.technicien"]._creer(tache._source().sudo(), request.env.user, note, pieces)
        return request.redirect(url + "?envoye=1")


    @http.route(["/my/journee/tache/<int:tache_id>/signer"], type="jsonrpc", auth="user", website=True)
    def ma_tache_signer(self, tache_id, name=None, signature=None, **kw):
        """Signature du client (formulaire de signature du portail) : bon d'intervention + tache terminee."""
        tache = self._ma_tache(tache_id)
        if not tache:
            return {"error": request.env._("Tâche introuvable.")}
        if not tache.a_faire:
            return {"error": request.env._("Cette tâche est déjà terminée.")}
        if not signature:
            return {"error": request.env._("La signature est vide.")}
        try:
            request.env["suivi.bon.intervention"]._creer_depuis_tache(tache, name, signature)
        except (UserError, ValueError, binascii.Error) as erreur:
            return {"error": str(erreur)}
        return {"force_refresh": True, "redirect_url": "/my/journee/tache/%s#bon_intervention" % tache_id}

    @http.route(["/my/journee/tache/<int:tache_id>/signer_technicien"], type="jsonrpc", auth="user", website=True)
    def ma_tache_signer_technicien(self, tache_id, name=None, signature=None, **kw):
        """Signature du technicien sur le bon deja signe par le client (entretien / reparation)."""
        tache = self._ma_tache(tache_id)
        bon = tache and tache._source().sudo().bon_intervention_ids[:1]
        if not bon:
            return {"error": request.env._("Le client doit d'abord signer le bon.")}
        if bon.technicien_id != request.env.user:
            return {"error": request.env._("Seul le technicien du bon peut le signer.")}
        try:
            bon._signer_technicien(signature)
        except (UserError, ValueError, binascii.Error) as erreur:
            return {"error": str(erreur)}
        return {"force_refresh": True, "redirect_url": "/my/journee/tache/%s#bon_intervention" % tache_id}

    @http.route(["/my/journee/tache/<int:tache_id>/bon"], type="http", auth="user", website=True)
    def ma_tache_bon(self, tache_id, **kw):
        """PDF du bon signe (le technicien de la tache seulement)."""
        tache = self._ma_tache(tache_id)
        bon = tache and tache._source().sudo().bon_intervention_ids[:1]
        if not bon or not bon.pdf_id:
            return request.redirect("/my/journee")
        # Envoi standard d'Odoo (le contenu d'une piece jointe est un fichier, pas des octets)
        stream = request.env["ir.binary"].sudo()._get_stream_from(bon.pdf_id.sudo())
        return stream.get_response(as_attachment=False)


class HomeTechnicien(Home):

    def _login_redirect(self, uid, redirect=None):
        # Le technicien arrive directement sur sa journee
        if not redirect and request.env["res.users"].sudo().browse(uid).est_technicien:
            redirect = "/my/journee"
        return super()._login_redirect(uid, redirect=redirect)
