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
