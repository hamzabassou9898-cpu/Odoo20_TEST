# -*- coding: utf-8 -*-
"""Guides de l'utilisation dans l'application Connaissances.

Chaque guide est un article sous « Guide de l'utilisation ». Le texte et les captures viennent du module
(static/guides : base de demonstration, aucune vraie donnee). Les exemples ecrits dans le texte ({{banniere}},
{{code}}...) sont pris dans la base au moment de l'installation ou de la mise a jour du module : les vraies
donnees des clients ne sont jamais dans le code."""
import re
from collections import Counter

from markupsafe import escape

from odoo import api, models
from odoo.tools import file_open

MODULE = "guide_dutilisation_monroy"
NOM_APPLICATION = "Guide de l'utilisation"
RACINE = ("guide_racine", "Guide de l'utilisation", "📘")
# (xmlid, dossier dans static/guides, titre, icone) : l'ordre est celui du menu des guides
GUIDES = [
    ("guide_contacts", "contacts", "Contacts", "👥"),
    ("guide_contrat_location", "contrat_location", "Contrat de location", "📝"),
    ("guide_appels_service", "appels_service", "Appels de service", "📞"),
    ("guide_portail_technicien", "portail_technicien", "Portail technicien", "📱"),
    ("guide_planning", "planning", "Planning", "🗓️"),
]
# Exemples de la base de demonstration (si la base n'a pas de banniere avec des commerces)
EXEMPLES_DEMO = {"banniere": "Dépanneurs Bonjour", "nb": "4", "commerces": "ses commerces",
                 "commerce": "Dépanneur Bonjour Sainte-Foy", "code": "MON502", "ville": "Québec",
                 "types_contrat": "Location / entreprise, Convention slush, Convention popcorn, Propriétaire",
                 "contrat": "LOC00077", "contrat_client": "Dépanneur Bonjour Limoilou"}


class KnowledgeArticle(models.Model):
    _inherit = "knowledge.article"

    @api.model
    def _monroy_installer_guides(self):
        valeurs = self._monroy_exemples()
        racine = self._monroy_article(*RACINE)
        guides = self.browse()
        for sequence, (xmlid, dossier, titre, icone) in enumerate(GUIDES, start=1):
            article = self._monroy_article(xmlid, titre, icone, racine, sequence)
            corps = self._monroy_lire("%s/article.html" % dossier)
            article.body = self._monroy_remplir(corps, valeurs, dossier)
            guides |= article
        liste = "".join('<li style="margin:6px 0;font-size:17px;"><a href="/knowledge/article/%s">%s %s</a></li>'
                        % (article.id, escape(article.icon or ""), escape(article.name)) for article in guides)
        racine.body = self._monroy_lire("accueil.html").replace("{{guides}}", liste)
        self._monroy_renommer_application()
        return racine

    # ------------------------------------------------------------ exemples reels de la base
    @api.model
    def _monroy_exemples(self):
        """La banniere qui a le plus de commerces (adresses de livraison avec un code client) et un de ses
        commerces ; sinon les exemples de la demonstration. Valeurs echappees (HTML)."""
        Partner = self.env["res.partner"].sudo()
        valeurs = dict(EXEMPLES_DEMO)
        commerces = Partner.search([("parent_id", "!=", False), ("type", "=", "delivery"), ("ref", "!=", False)])
        nombres = Counter(commerce.parent_id.id for commerce in commerces)
        if nombres:
            banniere = Partner.browse(nombres.most_common(1)[0][0])
            siens = commerces.filtered(lambda c: c.parent_id == banniere).sorted("name")
            exemple = siens[:1]
            reste = len(siens) - 4
            valeurs.update({
                "banniere": banniere.name, "nb": str(len(siens)),
                "commerces": ", ".join(siens[:4].mapped("name")) + (" et %d autres" % reste if reste > 0 else ""),
                "commerce": exemple.name, "code": exemple.ref, "ville": exemple.city or ""})
        valeurs.update(self._monroy_exemples_contrats())
        return {cle: str(escape(valeur)) for cle, valeur in valeurs.items()}

    @api.model
    def _monroy_exemples_contrats(self):
        """Types de contrat de la base et le contrat de location confirme le plus recent (hors demonstration)."""
        valeurs = {}
        if "suivi.type.contrat" in self.env:
            types = self.env["suivi.type.contrat"].sudo().search([])
            if types:
                valeurs["types_contrat"] = ", ".join(types.mapped("name"))
        Commande = self.env["sale.order"].sudo() if "sale.order" in self.env else None
        if Commande is not None and "type_commande" in Commande._fields:
            contrats = Commande.search([("type_commande", "=", "location"), ("state", "=", "sale")],
                                       order="date_order desc, id desc", limit=20)
            contrat = contrats.filtered(lambda c: (c.client_order_ref or "").upper() != "DEMO")[:1] or contrats[:1]
            if contrat:
                valeurs.update({"contrat": contrat.name, "contrat_client": contrat.partner_id.name})
        return valeurs

    # ------------------------------------------------------------ articles
    @api.model
    def _monroy_article(self, xmlid, nom, icone, parent=None, sequence=0):
        """Article du module (retrouve par son xmlid, meme renomme), cree s'il n'existe pas encore."""
        article = self.env.ref("%s.%s" % (MODULE, xmlid), raise_if_not_found=False)
        champs = self._fields
        valeurs = {"name": nom, "icon": icone, "sequence": sequence, "parent_id": parent.id if parent else False}
        if not parent and "internal_permission" in champs:
            valeurs["internal_permission"] = "write"   # espace de travail : visible et modifiable par le bureau
        if "full_width" in champs:
            valeurs["full_width"] = True
        valeurs = {cle: valeur for cle, valeur in valeurs.items() if cle in champs}
        if article:
            article.sudo().write(valeurs)
            return article
        article = self.sudo().create(valeurs)
        self.env["ir.model.data"].sudo().create({"module": MODULE, "name": xmlid, "model": self._name,
                                                 "res_id": article.id, "noupdate": True})
        return article

    @api.model
    def _monroy_lire(self, chemin):
        with file_open("%s/static/guides/%s" % (MODULE, chemin), "rb") as fichier:
            return fichier.read().decode("utf-8")

    @api.model
    def _monroy_remplir(self, corps, valeurs, dossier):
        """{{img:nom}} -> capture du module ; {{cle}} -> exemple de la base."""
        corps = re.sub(r"\{\{img:([^}]+)\}\}",
                       lambda m: "/%s/static/guides/%s/img/%s" % (MODULE, dossier, m.group(1)), corps)
        return re.sub(r"\{\{(\w+)\}\}", lambda m: valeurs.get(m.group(1), m.group(0)), corps)

    @api.model
    def _monroy_renommer_application(self):
        """L'application Connaissances s'appelle « Guide de l'utilisation », dans toutes les langues."""
        menu = self.env.ref("knowledge.knowledge_menu_root", raise_if_not_found=False) or \
            self.env["ir.ui.menu"].sudo().search([("parent_id", "=", False), ("web_icon", "=like", "knowledge,%")],
                                                 limit=1)
        for code, _nom in self.env["res.lang"].get_installed():
            menu.sudo().with_context(lang=code).name = NOM_APPLICATION
        return menu
