# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged

NOMS = ("🥇 1ère proposition", "🥈 2ème proposition", "✅ Livré / Terminé")


@tagged("post_install", "-at_install")
class TestConfigurationCrm(TransactionCase):
    """Etapes du CRM de Monroy reprises dans le module."""

    def _etape(self, nom):
        return self.env["crm.stage"].with_context(active_test=False).search([("name", "=", nom)])

    def test_etapes_dans_l_ordre(self):
        """1re et 2e proposition avant Gagne, Livre / Termine apres."""
        premiere, deuxieme, livre = (self._etape(nom) for nom in NOMS)
        self.assertTrue(premiere and deuxieme and livre)
        gagne = self.env["crm.stage"].search([("is_won", "=", True)], order="sequence, id", limit=1)
        self.assertLess(premiere.sequence, deuxieme.sequence)
        self.assertLess(deuxieme.sequence, gagne.sequence)
        self.assertLess(gagne.sequence, livre.sequence)
        self.assertFalse(livre.is_won)

    def test_relance_sans_doublon_ni_retouche(self):
        """Les etapes deja en place (deplacees a la main) ne sont ni dupliquees ni remises en ordre."""
        for nom in NOMS:
            self._etape(nom).sequence = 50
        gagne = self.env["crm.stage"].search([("is_won", "=", True)], limit=1)
        sequence_gagne = gagne.sequence
        self.env["crm.lead"]._configuration_monroy()
        for nom in NOMS:
            self.assertEqual(len(self._etape(nom)), 1, nom)
            self.assertEqual(self._etape(nom).sequence, 50, nom)
        self.assertEqual(gagne.sequence, sequence_gagne)
