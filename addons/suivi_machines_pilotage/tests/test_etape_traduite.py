# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEtapeTraduite(TransactionCase):
    """Etape copiee d'une etape native : nom francais « Entretien & Réparation », mais traduction anglaise
    restee « Solved ». Le ticket est ouvert : il ne doit jamais passer pour « fait » (planning, portail)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.etape = cls.env["helpdesk.stage"].with_context(lang="en_US").create({"name": "Solved"})
        cls.etape.with_context(lang="fr_FR").name = "Entretien & Réparation"
        cls.client = cls.env["res.partner"].create({"name": "Accommodation test"})
        cls.ticket = cls.env["helpdesk.ticket"].create({
            "name": "Machine est brisée", "partner_id": cls.client.id, "stage_id": cls.etape.id,
            "user_id": cls.env.uid, "date_planifiee": fields.Datetime.now()})

    def test_ticket_ouvert_dans_le_planning(self):
        self.assertEqual(self.etape.with_context(lang="en_US").name, "Solved")
        self.env.flush_all()
        tache = self.env["portail.tache"].search([("ticket_id", "=", self.ticket.id)])
        self.assertTrue(tache.a_faire, "ouvert : à faire, pas « fait »")
        self.assertNotEqual(tache.etat_suivi, "fait")

    def test_ticket_ouvert_meme_lu_en_anglais(self):
        """Les taches planifiees tournent en anglais : le ticket reste ouvert pour elles aussi."""
        self.assertFalse(self.ticket.with_context(lang="en_US")._est_ferme())
        resolu = self.env["helpdesk.stage"].with_context(lang="fr_FR").create({"name": "Résolu"})
        self.ticket.stage_id = resolu
        self.assertTrue(self.ticket.with_context(lang="en_US")._est_ferme())

    def test_appels_de_service_rechargeable(self):
        """Recharger la page « Appels de service » relance le menu, pas l'action de l'equipe (active_id)."""
        menu = self.env.ref("suivi_machines_pilotage.action_pilotage_appels_assistance")
        self.assertEqual(menu.path, "appels-de-service")
        action = self.env["pilotage.indicateur"].action_appels_de_service()
        self.assertNotIn("active_id", str(action.get("context", "")))
        if action.get("res_model") == "helpdesk.ticket" and "path" in action:
            self.assertFalse(action["path"])
