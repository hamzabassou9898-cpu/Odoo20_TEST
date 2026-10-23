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

    def test_sens_etape_selon_nom_francais(self):
        """Fermee / nouvelle : lu dans le nom francais, quelle que soit la langue de l'utilisateur."""
        Etape = self.env["helpdesk.stage"]
        for langue in ("en_US", "fr_FR"):
            etape = self.etape.with_context(lang=langue)
            self.assertFalse(etape.etape_fermee, langue)
            self.assertNotIn(self.etape, Etape.with_context(lang=langue).search([("etape_fermee", "=", True)]))
            self.assertIn(self.etape, Etape.with_context(lang=langue).search([("etape_fermee", "=", False)]))

    def test_resolu_trouve_la_bonne_etape(self):
        """Bon signe, echange termine, reparation faite : le ticket va dans « Résolu », jamais dans l'etape
        renommee qui s'appelle encore « Solved » en anglais (taches planifiees, portail en anglais)."""
        resolu = self.env["helpdesk.stage"].with_context(lang="fr_FR").create({"name": "Résolu"})
        for langue in ("en_US", "fr_FR"):
            trouvee = self.env["helpdesk.ticket"].with_context(lang=langue)._etape_contenant("résolu")
            self.assertEqual(trouvee, resolu, langue)
        self.ticket.with_context(lang="en_US").action_marquer_fait()
        self.assertEqual(self.ticket.stage_id, resolu)

    def test_menus_et_filtres_ouverts(self):
        """Tableau de bord et filtre « Ouverts » : le ticket de l'etape renommee est compte ouvert."""
        Ticket = self.env["helpdesk.ticket"].with_context(lang="en_US")
        domaine = self.env["pilotage.indicateur"].with_context(lang="en_US")._domaines()["appels_ouverts"][1]
        self.assertIn(self.ticket, Ticket.search(domaine))
        filtre = ["|", ("stage_id", "=", False), "!", ("stage_id.etape_fermee", "=", True)]
        self.assertIn(self.ticket, Ticket.search(filtre))
        sans_etape = Ticket.create({"name": "Sans étape", "partner_id": self.client.id})
        sans_etape.stage_id = False
        self.assertIn(sans_etape, Ticket.search(filtre))
        self.assertIn(sans_etape, Ticket.search(domaine))
        resolu = self.env["helpdesk.stage"].with_context(lang="fr_FR").create({"name": "Résolu"})
        sans_etape.stage_id = resolu
        self.assertNotIn(sans_etape, Ticket.search(filtre))
        self.assertNotIn(sans_etape, Ticket.search(domaine))

    def test_renommer_une_etape_recalcule_les_tickets(self):
        """Renommer l'etape en « Résolu » ferme ses tickets ; la renommer a nouveau les rouvre."""
        self.ticket.type_demande = "reparation"
        self.assertEqual(self.ticket.statut_entretien, "planifie")
        self.etape.with_context(lang="fr_FR").name = "Résolu"
        self.assertEqual(self.ticket.statut_entretien, "fait")
        self.etape.with_context(lang="fr_FR").name = "Entretien & Réparation"
        self.assertEqual(self.ticket.statut_entretien, "planifie")

    def test_garde_fou_nom_brut_des_etapes(self):
        """Garde-fou : aucun module ne decide d'apres le nom brut d'une etape (toutes langues melangees ou
        langue de l'utilisateur). Tout passe par nom_etape() / etape_fermee / etape_nouvelle."""
        import os
        import re
        racine = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        modules = ("suivi_machines", "suivi_machines_helpdesk", "suivi_sage", "suivi_machines_pilotage",
                   "suivi_machines_portail", "guide_dutilisation_monroy", "ouverture_compte_monroy")
        interdit = re.compile(r"stage_id\.name|stage\.name|etape\.name\b|s\.name::text")
        fautes = []
        for module in modules:
            for dossier, _sous, fichiers in os.walk(os.path.join(racine, module)):
                if "tests" in dossier.split(os.sep) or "i18n" in dossier:
                    continue
                for fichier in fichiers:
                    if not fichier.endswith((".py", ".xml", ".js")) or fichier == "etapes.py":
                        continue
                    chemin = os.path.join(dossier, fichier)
                    with open(chemin, encoding="utf-8") as f:
                        for numero, ligne in enumerate(f, 1):
                            if interdit.search(ligne) and "@api.depends" not in ligne and "nom non traduit" not in ligne:
                                fautes.append("%s:%s: %s" % (os.path.relpath(chemin, racine), numero, ligne.strip()))
        self.assertFalse(fautes, "Nom d'étape lu sans nom_etape() :\n" + "\n".join(fautes))
