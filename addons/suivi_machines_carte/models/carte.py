# -*- coding: utf-8 -*-
"""Adresses liees a Google Maps : lien, apercu de carte et itineraire (sans cle d'API)."""
from urllib.parse import quote, urlencode

from markupsafe import Markup, escape

from odoo import fields, models
from odoo.exceptions import UserError

URL_RECHERCHE = "https://www.google.com/maps/search/?"
URL_ITINERAIRE = "https://www.google.com/maps/dir/?"
URL_APERCU = "https://maps.google.com/maps?"
# Limite des liens Google Maps : 1 destination + 9 etapes
MAX_ARRETS = 10


def adresse_propre(texte):
    """Adresse sur une ligne, sans ligne vide (« 12 rue X, Montréal QC H2X 1Y4, Canada »)."""
    morceaux = [m.strip() for m in (texte or "").replace("\n", ",").split(",")]
    return ", ".join(m for m in morceaux if m) or False


def adresse_partenaire(partner):
    """Adresse du commerce d'un contact (une personne rattachee prend celle de son commerce)."""
    if not partner:
        return False
    commerce = partner.parent_id if partner.parent_id and partner.type == "contact" else partner
    if not (commerce.street or commerce.city or commerce.zip):
        return False
    return adresse_propre(commerce._display_address(without_name=True, separator=", "))


def url_recherche(adresse):
    return URL_RECHERCHE + urlencode({"api": 1, "query": adresse}, quote_via=quote)


def url_itineraire(arrets):
    """Itineraire depuis la position du telephone (ou de l'ordinateur), arrets dans l'ordre."""
    params = {"api": 1, "destination": arrets[-1], "travelmode": "driving"}
    if len(arrets) > 1:
        params["waypoints"] = "|".join(arrets[:-1])
    return URL_ITINERAIRE + urlencode(params, quote_via=quote)


def apercu_carte(adresse):
    src = URL_APERCU + urlencode({"q": adresse, "output": "embed", "hl": "fr", "z": 15}, quote_via=quote)
    return Markup(
        '<div class="o_suivi_carte">'
        '<iframe src="%s" title="%s" loading="lazy" allowfullscreen="allowfullscreen" '
        'referrerpolicy="no-referrer-when-downgrade" '
        'style="width: 100%%; height: 380px; border: 0; border-radius: 8px;"></iframe>'
        '</div>') % (src, escape(adresse))


class SuiviCarteMixin(models.AbstractModel):
    _name = "suivi.carte.mixin"
    _description = "Adresse liée à Google Maps"
    # Champ date qui ordonne les arrets d'un itineraire
    _champ_date_carte = None

    adresse_carte = fields.Char("Adresse (carte)", compute="_compute_carte")
    lien_google_maps = fields.Char("Google Maps", compute="_compute_carte")
    lien_itineraire = fields.Char("Itinéraire", compute="_compute_carte")
    carte_google = fields.Html("Carte", compute="_compute_carte", sanitize=False)

    def _adresse_pour_carte(self):
        """Adresse a situer sur la carte (a definir dans chaque modele)."""
        return False

    def _compute_carte(self):
        for record in self:
            adresse = record._adresse_pour_carte()
            record.adresse_carte = adresse
            record.lien_google_maps = url_recherche(adresse) if adresse else False
            record.lien_itineraire = url_itineraire([adresse]) if adresse else False
            record.carte_google = apercu_carte(adresse) if adresse else False

    def _ouvrir_url(self, url):
        if not url:
            raise UserError(self.env._("Aucune adresse à afficher : complétez l'adresse du client."))
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_ouvrir_google_maps(self):
        self.ensure_one()
        return self._ouvrir_url(self.lien_google_maps)

    def action_itineraire_google_maps(self):
        self.ensure_one()
        return self._ouvrir_url(self.lien_itineraire)

    def action_itineraire_tournee(self):
        """Un seul itineraire Google Maps pour les arrets choisis, dans l'ordre des dates."""
        champ = self._champ_date_carte
        arrets = []
        for record in self.sorted(lambda r: (r[champ] or fields.Datetime.now(), r.id) if champ else r.id):
            adresse = record.adresse_carte
            if adresse and (not arrets or arrets[-1] != adresse):
                arrets.append(adresse)
        if not arrets:
            raise UserError(self.env._("Aucune adresse dans les tâches choisies."))
        if len(arrets) > MAX_ARRETS:
            raise UserError(self.env._(
                "Google Maps accepte au plus %(max)s arrêts par itinéraire (%(nb)s ici) : "
                "choisissez moins de tâches.", max=MAX_ARRETS, nb=len(arrets)))
        return self._ouvrir_url(url_itineraire(arrets))


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "suivi.carte.mixin"]
    _champ_date_carte = "scheduled_date"

    def _adresse_pour_carte(self):
        return adresse_propre(self.route) or adresse_partenaire(self.partner_id)


class MachineIntervention(models.Model):
    _name = "machine.intervention"
    _inherit = ["machine.intervention", "suivi.carte.mixin"]

    def _adresse_pour_carte(self):
        return adresse_propre(self.route) or adresse_partenaire(self.partner_id)


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _inherit = ["helpdesk.ticket", "suivi.carte.mixin"]

    def _adresse_pour_carte(self):
        return adresse_partenaire(self.commerce_id or self.partner_id)


class StockLot(models.Model):
    _name = "stock.lot"
    _inherit = ["stock.lot", "suivi.carte.mixin"]

    def _adresse_pour_carte(self):
        return adresse_partenaire(self.machine_client_id)


class PortailTache(models.Model):
    _name = "portail.tache"
    _inherit = ["portail.tache", "suivi.carte.mixin"]
    _champ_date_carte = "date"

    def _adresse_pour_carte(self):
        return adresse_propre(self.route) or adresse_partenaire(self.partner_id)
