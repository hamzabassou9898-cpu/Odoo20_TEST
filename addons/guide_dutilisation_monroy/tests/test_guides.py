# -*- coding: utf-8 -*-
import re

from odoo.tests import TransactionCase, tagged
from odoo.tools import file_open

from odoo.addons.guide_dutilisation_monroy.models.guides import GUIDES, MODULE, NOM_APPLICATION


@tagged("post_install", "-at_install")
class TestGuides(TransactionCase):
    """Guides de l'utilisation dans Connaissances : articles, captures, exemples pris dans la base."""

    def _racine(self):
        return self.env.ref(MODULE + ".guide_racine")

    def test_articles_et_application(self):
        racine = self._racine()
        self.assertEqual(racine.name, "Guide de l'utilisation")
        for xmlid, _dossier, titre, _icone in GUIDES:
            article = self.env.ref("%s.%s" % (MODULE, xmlid))
            self.assertEqual((article.name, article.parent_id), (titre, racine))
            self.assertIn("/knowledge/article/%s" % article.id, racine.body, "lien depuis l'accueil")
        menu = self.env["knowledge.article"]._monroy_renommer_application()
        self.assertEqual(menu.name, NOM_APPLICATION)

    def test_captures_et_exemples_remplis(self):
        """Plus aucun {{...}} dans les guides ; chaque capture citee existe dans le module."""
        for xmlid, dossier, _titre, _icone in GUIDES:
            corps = self.env.ref("%s.%s" % (MODULE, xmlid)).body or ""
            self.assertFalse(re.findall(r"\{\{\w+(?::[^}]*)?\}\}", corps), xmlid)
            images = re.findall(r'src="(/%s/static/guides/%s/img/[^"]+)"' % (MODULE, dossier), corps)
            self.assertTrue(images, xmlid)
            for chemin in images:
                with file_open(chemin.lstrip("/"), "rb") as fichier:
                    self.assertTrue(fichier.read(4))

    def test_exemple_de_la_base(self):
        """La banniere qui a le plus de commerces (avec code client) sert d'exemple dans le texte."""
        Partner = self.env["res.partner"]
        banniere = Partner.create({"name": "Bannière test guides", "is_company": True})
        for i in range(12):
            Partner.create({"name": "Commerce test guides %02d" % i, "parent_id": banniere.id, "type": "delivery",
                            "ref": "TG%02d" % i, "city": "Lévis"})
        valeurs = self.env["knowledge.article"]._monroy_exemples()
        self.assertEqual((valeurs["banniere"], valeurs["nb"]), ("Bannière test guides", "12"))
        self.assertEqual((valeurs["commerce"], valeurs["code"], valeurs["ville"]),
                         ("Commerce test guides 00", "TG00", "Lévis"))
        self.assertIn("et 8 autres", valeurs["commerces"])
        # Valeurs echappees : un nom avec du HTML ne casse pas l'article
        banniere.name = "<b>Chaîne</b>"
        self.assertNotIn("<b>", self.env["knowledge.article"]._monroy_exemples()["banniere"])

    def test_relance_sans_doublon(self):
        """Chaque mise a jour du module refait les guides : memes articles, aucun doublon."""
        Article = self.env["knowledge.article"].with_context(active_test=False)
        avant = Article.search_count([])
        self._racine().name = "Guides renommés par Jose"
        self.env["knowledge.article"]._monroy_installer_guides()
        self.assertEqual(Article.search_count([]), avant)
        self.assertEqual(self._racine().name, "Guide de l'utilisation")

    def test_exemple_de_contrat(self):
        """Le contrat de location confirme le plus recent sert d'exemple (sauf ceux de demonstration)."""
        valeurs = self.env["knowledge.article"]._monroy_exemples()
        self.assertTrue(valeurs["types_contrat"])
        if "type_commande" not in self.env["sale.order"]._fields:
            return
        client = self.env["res.partner"].create({"name": "Client contrat guides"})
        commande = self.env["sale.order"].create({
            "partner_id": client.id, "type_commande": "location",
            "date_debut_location": "2026-01-01 12:00:00", "date_fin_location": "2027-01-01 12:00:00"})
        commande.write({"state": "sale"})
        valeurs = self.env["knowledge.article"]._monroy_exemples()
        self.assertEqual((valeurs["contrat"], valeurs["contrat_client"]), (commande.name, "Client contrat guides"))

    def test_guides_tickets_portail_planning(self):
        """Un chapitre par type de ticket ; portail technicien et planning ont leur guide."""
        self.env["knowledge.article"]._monroy_installer_guides()
        appels = self.env.ref(MODULE + ".guide_appels_service")
        for type_ticket in ("Réparation", "Entretien", "Ramassage", "Machine à remplacer"):
            self.assertIn(type_ticket, appels.body)
        self.assertNotIn("Ajuster un contrat", appels.body, "type retiré")
        self.assertIn("Ma journée", self.env.ref(MODULE + ".guide_portail_technicien").body)
        self.assertIn("Glisser", self.env.ref(MODULE + ".guide_planning").body)
        self.assertEqual([g[0] for g in GUIDES][-3:],
                         ["guide_appels_service", "guide_portail_technicien", "guide_planning"])
