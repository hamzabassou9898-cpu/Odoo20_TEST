# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

from odoo.addons.suivi_machines_helpdesk.models.configuration import creer_si_absent

MODULE = "suivi_machines_helpdesk"


@tagged("post_install", "-at_install")
class TestConfigurationMonroy(TransactionCase):
    """Reglages de Monroy repris dans le module : presents, jamais en double, jamais retouches.
    Les tests fonctionnent sur une base neuve comme sur une base ou les reglages ont ete faits a la main."""

    def _nb(self, modele, nom):
        return self.env[modele].with_context(active_test=False).search_count([("name", "=", nom)])

    def test_etape_et_etiquette_presentes(self):
        self.assertTrue(self._nb("helpdesk.stage", "Machine à remplacer"))
        self.assertTrue(self._nb("helpdesk.tag", "Machine à remplacer"))

    def test_relance_sans_doublon(self):
        """Chaque mise a jour du module relance la configuration : rien n'est cree une 2e fois."""
        avant = (self._nb("helpdesk.stage", "Machine à remplacer"), self._nb("helpdesk.tag", "Machine à remplacer"))
        self.env["helpdesk.ticket"]._configuration_monroy()
        self.env["helpdesk.ticket"]._configuration_monroy()
        self.assertEqual((self._nb("helpdesk.stage", "Machine à remplacer"),
                          self._nb("helpdesk.tag", "Machine à remplacer")), avant)

    def test_creer_si_absent(self):
        """Absent -> cree une seule fois (xmlid pose) ; deja fait a la main -> garde tel quel, sans xmlid."""
        nom = "Réglage de test Monroy"
        tag, cree = creer_si_absent(self.env, MODULE, "tag_test_configuration", "helpdesk.tag", nom)
        self.assertTrue(cree)
        self.assertEqual(self.env.ref(MODULE + ".tag_test_configuration"), tag)
        encore, cree = creer_si_absent(self.env, MODULE, "tag_test_configuration", "helpdesk.tag", nom)
        self.assertEqual((encore, cree), (tag, False))
        a_la_main = self.env["helpdesk.tag"].create({"name": "Réglage fait à la main"})
        trouve, cree = creer_si_absent(self.env, MODULE, "tag_test_main", "helpdesk.tag", "Réglage fait à la main",
                                       {"champ_inexistant": 1})
        self.assertEqual((trouve, cree), (a_la_main, False))
        self.assertFalse(self.env.ref(MODULE + ".tag_test_main", raise_if_not_found=False))
        self.assertEqual(self._nb("helpdesk.tag", "Réglage fait à la main"), 1)
