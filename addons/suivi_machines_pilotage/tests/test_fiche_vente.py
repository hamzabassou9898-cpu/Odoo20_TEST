# -*- coding: utf-8 -*-
from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFicheVente(TransactionCase):
    """Opportunite : fiche de vente Monroy (sections du formulaire de vente interne du site)."""

    def test_formulaire_web_donne_le_support(self):
        Lead = self.env["crm.lead"]
        web = Lead.create({"name": "Dépanneur web", "via_formulaire_web": True, "nom_representant": "Jean Vendeur", "type_clientele": "commercant",
                           "type_commerce": "depanneur", "region_desservie": "portneuf",
                           "equipement_souhaite": "barbotine_2", "potentiel_emplacement": "bon"})
        self.assertEqual(web.medium_id.name, "Formulaire web")
        self.assertEqual(web.nom_representant, "Jean Vendeur")
        autre = Lead.create({"name": "Saisie au bureau"})
        self.assertNotEqual(autre.medium_id.name, "Formulaire web", "seulement le formulaire du site")
        # Un seul support « Formulaire web », reutilise
        Lead.create({"name": "Deuxième", "via_formulaire_web": True})
        self.assertEqual(self.env["utm.medium"].search_count([("name", "=ilike", "Formulaire web")]), 1)

    def test_type_de_contrat_envisage(self):
        lead = self.env["crm.lead"].create({"name": "Contrat"})
        lead.type_contrat_envisage_id = self.env.ref("suivi_machines.type_contrat_location")
        self.assertTrue(lead.est_location_envisagee)
        self.assertFalse(lead.est_proprietaire)
        lead.type_contrat_envisage_id = self.env.ref("suivi_machines.type_contrat_proprietaire")
        self.assertTrue(lead.est_proprietaire, "note : pas de réservation de machine")
        self.assertFalse(lead.est_location_envisagee, "durée et début de location cachés")

    def test_cases_permises_au_formulaire_du_site(self):
        champs = self.env["ir.model.fields"]
        if "website_form_blacklisted" not in champs._fields:
            self.skipTest("module Site Web absent")
        permis = champs.search([("model", "=", "crm.lead"), ("website_form_blacklisted", "=", False)]).mapped("name")
        for nom in ("nom_representant", "type_clientele", "region_desservie", "equipement_souhaite", "type_contrat_envisage_id",
                    "telephone_contact", "street", "via_formulaire_web"):
            self.assertIn(nom, permis)

    def test_vues(self):
        form = etree.fromstring(self.env["crm.lead"].get_views([(False, "form")])["views"]["form"]["arch"])
        page = form.xpath("//page[@name='fiche_vente']")[0]
        self.assertEqual(form.xpath("//notebook/page")[0], page, "onglet en premier")
        self.assertTrue(page.xpath(".//field[@name='nom_representant']"), "représentant écrit librement")
        for section in ("1. Informations générales", "2. Contact du projet", "3. Besoin & qualification",
                        "4. Type de contrat envisagé"):
            self.assertTrue(page.xpath(".//group[@string=$s]", s=section), section)
        kanban = self.env["crm.lead"].get_views([(self.env.ref("crm.crm_case_kanban_view_leads").id, "kanban")])
        self.assertIn("record.nom_representant.value", kanban["views"]["kanban"]["arch"], "représentant en étiquette")
