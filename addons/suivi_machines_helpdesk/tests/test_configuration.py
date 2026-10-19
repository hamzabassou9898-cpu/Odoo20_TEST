# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestConfigurationMonroy(TransactionCase):
    """Reglages de Monroy repris dans le module : presents, jamais en double, jamais retouches."""

    def _nb(self, modele, nom):
        return self.env[modele].with_context(active_test=False).search_count([("name", "=", nom)])

    def test_etape_et_etiquette_presentes(self):
        etape = self.env["helpdesk.stage"].search([("name", "=", "Machine à remplacer")])
        self.assertEqual(len(etape), 1)
        self.assertEqual(self._nb("helpdesk.tag", "Machine à remplacer"), 1)

    def test_relance_sans_doublon(self):
        """Chaque mise a jour du module relance la configuration : rien n'est cree une 2e fois."""
        self.env["helpdesk.ticket"]._configuration_monroy()
        self.env["helpdesk.ticket"]._configuration_monroy()
        self.assertEqual(self._nb("helpdesk.stage", "Machine à remplacer"), 1)
        self.assertEqual(self._nb("helpdesk.tag", "Machine à remplacer"), 1)

    def test_reglage_fait_a_la_main_garde(self):
        """Base ou l'etape a ete creee a la main (ex. Monroy_test) : on la garde telle quelle, sans doublon."""
        self.env.ref("suivi_machines_helpdesk.etape_machine_a_remplacer").unlink()
        self.env.ref("suivi_machines_helpdesk.tag_machine_a_remplacer").unlink()
        Etape = self.env["helpdesk.stage"]
        archivable, ordonnable = "active" in Etape._fields, "sequence" in Etape._fields
        valeurs = {"name": "Machine à remplacer"}
        if archivable:
            valeurs["active"] = False
        if ordonnable:
            valeurs["sequence"] = 9
        a_la_main = Etape.create(valeurs)
        self.env["helpdesk.ticket"]._configuration_monroy()
        self.assertEqual(self._nb("helpdesk.stage", "Machine à remplacer"), 1)
        if archivable:
            self.assertFalse(a_la_main.active, "un reglage archive a la main reste archive")
        if ordonnable:
            self.assertEqual(a_la_main.sequence, 9)
        self.assertEqual(self._nb("helpdesk.tag", "Machine à remplacer"), 1, "l'etiquette manquante est recreee")
