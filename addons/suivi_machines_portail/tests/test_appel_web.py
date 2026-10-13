# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestAppelWeb(HttpCase):
    """Formulaire public « Appel de service » : le ticket est cree automatiquement."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.client = env["res.partner"].create({"name": "Café Web", "ref": "WEB100", "street": "5 rue du Web",
                                                "city": "Québec", "phone": "418 555 0199"})
        cls.sans_machine = env["res.partner"].create({"name": "Client sans machine", "ref": "WEB200"})
        categ = env["product.category"].create({"name": "Machines (web)", "suivi_machine": True})
        produit = env["product.product"].create({"name": "Machine web", "categ_id": categ.id,
                                                 "is_storable": True, "tracking": "serial"})
        cls.lot = env["stock.lot"].create({"name": "WEB-1", "product_id": produit.id, "ref": "W1"})
        env["machine.intervention"].create({"lot_id": cls.lot.id, "type": "installation", "state": "fait",
                                            "partner_id": cls.client.id})

    def _post(self, **valeurs):
        base = {"prenom": "Julie", "nom": "Tremblay", "courriel": "julie@exemple.ca", "entreprise": "Café Web",
                "telephone": "418 555 0123", "adresse": "5 rue du Web", "ville": "Québec"}
        base.update(valeurs)
        return base

    def _envoyer(self, **valeurs):
        page = self.url_open("/appel-de-service")
        jeton = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        return self.url_open("/appel-de-service", data=dict(self._post(**valeurs), csrf_token=jeton))

    def _tickets_web(self):
        return self.env["helpdesk.ticket"].search([("recu_par_web", "=", True)])

    def test_page_publique(self):
        page = self.url_open("/appel-de-service")
        self.assertEqual(page.status_code, 200)
        for texte in ("Appel de service", "Code client", "Type de demande", "Type de réparation", "Ne gèle pas",
                      "Envoyer"):
            self.assertIn(texte, page.text)
        types = re.findall(r'name="type_demande"[^>]*value="(\w+)"', page.text)
        self.assertEqual(types, ["reparation", "ramassage", "entretien", "remplacement"], "4 types sur le site")
        self.assertRegex(page.text, r'<input type="radio" name="type_demande"[^>]*value="reparation"')
        self.assertIn('<textarea id="appel_message" name="message"', page.text)
        # Code client juste apres Entreprise
        ordre = [page.text.index('name="%s"' % nom) for nom in ("entreprise", "code_client", "telephone")]
        self.assertEqual(ordre, sorted(ordre))

    def test_reparation_avec_code_client(self):
        reponse = self._envoyer(code_client="web100", type_demande="reparation", type_reparation="ne_gele_pas",
                                message="Plus de slush depuis ce matin")
        self.assertIn("/appel-de-service/merci", reponse.url)
        self.assertIn("Merci", reponse.text)
        ticket = self._tickets_web()
        self.assertEqual(len(ticket), 1)
        self.assertIn(ticket._reference_web(), reponse.text)
        # Le code client remplit le dossier ; la seule machine du client est choisie
        self.assertEqual((ticket.partner_id, ticket.code_client, ticket.lot_id), (self.client, "WEB100", self.lot))
        self.assertEqual((ticket.type_demande, ticket.type_reparation, ticket.statut_entretien),
                         ("reparation", "ne_gele_pas", "a_planifier"))
        self.assertEqual(ticket.name, "Réparation : Ne gèle pas — Café Web")
        self.assertEqual(ticket.partner_phone, "418 555 0199", "téléphone du dossier Odoo (code client)")
        self.assertEqual(ticket.partner_email, "julie@exemple.ca", "client sans courriel dans Odoo : celui tapé")
        self.assertIn("418 555 0123", ticket.description, "ce qui a été tapé reste dans la description")
        self.assertIn("Plus de slush depuis ce matin", ticket.description)
        self.assertIn("Julie", ticket.description)

    def test_entretien_sans_code_client(self):
        self._envoyer(type_demande="entretien", type_reparation="coule")
        ticket = self._tickets_web()
        self.assertEqual(len(ticket), 1)
        self.assertFalse(ticket.partner_id, "Josef choisira le client")
        self.assertTrue(ticket.est_entretien)
        self.assertFalse(ticket.type_reparation, "type de réparation ignoré hors réparation")

    def test_code_inconnu_garde_dans_la_description(self):
        self._envoyer(code_client="XYZ999", type_demande="entretien")
        ticket = self._tickets_web()
        self.assertFalse(ticket.partner_id)
        self.assertFalse(ticket.code_client)
        self.assertIn("XYZ999", ticket.description)

    def test_refus_sans_ticket(self):
        cas = [
            ({"type_demande": "reparation"}, "type de réparation"),
            ({"type_demande": "reparation", "type_reparation": "autre"}, "section Message"),
            ({"type_demande": "inconnu"}, "type de demande"),
            ({"type_demande": "commande"}, "type de demande"),
            ({"type_demande": "entretien", "courriel": "pas-un-courriel"}, "courriel"),
            ({"type_demande": "entretien", "ville": ""}, "Ville"),
            ({"type_demande": "remplacement", "code_client": "WEB200"}, "Aucune machine"),
        ]
        for valeurs, message in cas:
            with self.subTest(valeurs=valeurs):
                reponse = self._envoyer(**valeurs)
                self.assertEqual(reponse.status_code, 200)
                self.assertIn(message, reponse.text)
                self.assertIn("alert-danger", reponse.text)
                # Ce qui a ete saisi reste dans le formulaire
                self.assertIn('value="Tremblay"', reponse.text)
                if valeurs.get("type_reparation") == "autre":
                    self.assertRegex(reponse.text, r'<option[^>]*selected[^>]*value="autre"|<option[^>]*value="autre"[^>]*selected')
        self.assertFalse(self._tickets_web())

    def test_robot(self):
        reponse = self._envoyer(type_demande="entretien", site_web="http://spam.example")
        self.assertIn("/appel-de-service/merci", reponse.url)
        self.assertFalse(self._tickets_web())

    def test_texte_echappe(self):
        Ticket = self.env["helpdesk.ticket"]
        ticket = Ticket._creer_depuis_formulaire_web(
            self._post(type_demande="entretien", entreprise="<b>Café</b>", message="<script>x</script>"))
        self.assertNotIn("<script>", ticket.description)
        self.assertNotIn("<b>Café</b>", ticket.description)
        with self.assertRaises(UserError):
            Ticket._creer_depuis_formulaire_web({"type_demande": "entretien"})

    def test_bandeau_dans_le_ticket(self):
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        bandeau = arch.xpath("//div[contains(@class, 'alert-info')][contains(., 'formulaire web')]")
        self.assertEqual(bandeau[0].get("invisible"), "not recu_par_web")

    def test_code_client_suffit(self):
        """Notre base : le code client. Avec un code valide, entreprise / adresse / ville viennent d'Odoo."""
        page = self.url_open("/appel-de-service")
        self.assertRegex(page.text, r'<input[^>]*name="adresse"[^>]*>')
        self.assertNotRegex(page.text, r'<input[^>]*name="adresse"[^>]*required')
        self.assertRegex(page.text, r'<input[^>]*name="prenom"[^>]*required')
        self._envoyer(code_client="WEB100", type_demande="entretien", entreprise="", adresse="", ville="")
        ticket = self._tickets_web()
        self.assertEqual(len(ticket), 1)
        self.assertEqual(ticket.partner_id, self.client)
        self.assertEqual(ticket.name, "Entretien — Café Web", "nom de l'entreprise pris dans Odoo")
        self.assertIn("5 rue du Web", ticket.adresse_commerce, "adresse du dossier Odoo")
        # Sans code valide : entreprise, adresse et ville obligatoires
        reponse = self._envoyer(code_client="INCONNU", type_demande="entretien", adresse="", ville="")
        self.assertIn("Adresse, Ville", reponse.text)
        self.assertEqual(len(self._tickets_web()), 1)
