# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

# Petite image PNG (1 x 1) : signature de test
SIGNATURE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@tagged("post_install", "-at_install")
class TestOuvertureCompte(TransactionCase):
    """Ouverture de compte : Jose envoie, le client remplit et signe, Jose approuve avec un code client."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.Ouverture = cls.env["ouverture.compte"]

    def _ouverture_envoyee(self, **valeurs):
        ouverture = self.Ouverture.create(dict({"entreprise_nom": "Glaces Test inc.", "courriel": "glaces@exemple.test",
                                                "contact_nom": "Lise Test"}, **valeurs))
        ouverture._envoyer()
        return ouverture

    def _remplir(self, ouverture, **extra):
        valeurs = {"rue": "1 rue Test", "ville": "Québec", "code_postal": "G1A 1A1", "telephone": "418 555-0000",
                   "nom_majuscules": "LISE TEST", "forme": "inc", "paiement": "ppa", "terme": "30",
                   "approvisionnement": "livraison", "banque_compte": "12345", "actionnaire1_naissance": "1980-01-01",
                   "banque_nom": "Caisse Test", "banque_adresse": "2 rue Banque", "signe_a": "Québec",
                   "caution_noms": "Lise Test"}
        valeurs.update(extra)
        return ouverture._completer_par_client(valeurs)

    def test_numero_envoi_et_courriel(self):
        ouverture = self._ouverture_envoyee()
        self.assertTrue(ouverture.name.startswith("OUV"))
        self.assertEqual(ouverture.state, "envoye")
        self.assertTrue(ouverture.access_token)
        self.assertEqual(ouverture.access_url, "/ouverture/%s" % ouverture.id)
        courriel = self.env["mail.mail"].search([("model", "=", "ouverture.compte"), ("res_id", "=", ouverture.id)])
        self.assertEqual(courriel.email_to, "glaces@exemple.test")
        self.assertIn(ouverture.get_portal_url(), courriel.body_html, "bouton Remplir et signer")
        self.assertFalse(courriel.recipient_ids)
        self.assertFalse(self.env["res.partner"].search_count([("email", "=", "glaces@exemple.test")]),
                         "pas de contact avant l'approbation")
        sans_courriel = self.Ouverture.create({"entreprise_nom": "Sans courriel"})
        with self.assertRaises(UserError):
            sans_courriel.action_envoyer()

    def test_fenetre_courriel_modifiable(self):
        """Envoyer ouvre le courriel pret a relire ; Jose change l'adresse, l'objet, le texte, ajoute une piece."""
        ouverture = self.Ouverture.create({"entreprise_nom": "Courriel Test", "courriel": "avant@exemple.test"})
        action = ouverture.action_envoyer()
        self.assertEqual((action["res_model"], action["target"]), ("ouverture.compte.envoyer", "new"))
        fenetre = self.env["ouverture.compte.envoyer"].with_context(action["context"]).create({})
        self.assertEqual(fenetre.courriel, "avant@exemple.test")
        self.assertIn(ouverture.name, fenetre.sujet)
        self.assertIn(ouverture.get_portal_url(), fenetre.corps, "lien Remplir et signer dans le texte")
        piece = self.env["ir.attachment"].create({"name": "tarifs.pdf", "raw": b"%PDF-1.4"})
        fenetre.write({"courriel": " apres@exemple.test ", "sujet": "Votre compte Monroy",
                       "corps": fenetre.corps + "<p>Texte ajouté par Jose</p>", "piece_ids": [(6, 0, piece.ids)]})
        fenetre.action_envoyer()
        courriel = self.env["mail.mail"].search([("model", "=", "ouverture.compte"), ("res_id", "=", ouverture.id)])
        self.assertEqual((courriel.email_to, courriel.subject), ("apres@exemple.test", "Votre compte Monroy"))
        self.assertIn("Texte ajouté par Jose", courriel.body_html)
        self.assertEqual(courriel.attachment_ids.mapped("name"), ["tarifs.pdf"])
        self.assertEqual((ouverture.courriel, ouverture.state), ("apres@exemple.test", "envoye"))

    def test_client_remplit_seulement_ses_cases(self):
        ouverture = self._ouverture_envoyee()
        self._remplir(ouverture)
        ecrit = ouverture._completer_par_client({"state": "approuve", "partner_id": 1, "forme": "inconnue",
                                                 "ville": "  Lévis  ", "autres_noms": "x" * 300})
        self.assertNotIn("state", ecrit)
        self.assertNotIn("partner_id", ecrit)
        self.assertEqual((ouverture.state, ouverture.ville, len(ouverture.autres_noms)), ("envoye", "Lévis", 150))
        self.assertEqual(ouverture.forme, "inc", "choix inconnu ignoré, le précédent reste")
        self.assertEqual(ouverture.sudo().banque_compte, "12345")

    def test_cases_obligatoires_choisies_par_monroy(self):
        """Les cases marquees par Monroy sont obligatoires ; les autres sections restent facultatives."""
        ouverture = self._ouverture_envoyee(contact_nom=False)
        manquants = ouverture._manquants()
        for libelle in ("Adresse", "Ville", "Contact", "Mode de paiement", "Institution financière", "Signé à",
                        "Nom en lettres majuscules", "Caution(s)", "Terme (jours)", "Forme"):
            self.assertIn(libelle, manquants)
        for libelle in ("Télécopieur", "Autre(s) nom(s) utilisé(s)"):
            self.assertNotIn(libelle, manquants, "facultatif")
        with self.assertRaises(UserError):
            ouverture._signer("Lise Test", SIGNATURE)
        self._remplir(ouverture, contact_nom="Lise Test")
        self.assertEqual(ouverture._manquants(), [])
        ouverture.entreprise_nom = False   # Jose le retire apres coup : l'approbation reste possible
        ouverture.contact_nom = False
        ouverture.sudo().signature = SIGNATURE
        ouverture.state = "signe"
        # Approuvee sans nom d'entreprise : la fiche porte le code client (Jose la renomme au besoin)
        assistant = self.env["ouverture.compte.approuver"].create({"ouverture_id": ouverture.id,
                                                                   "code_client": "VIDE001"})
        assistant.action_approuver()
        self.assertEqual((ouverture.state, ouverture.partner_id.name, ouverture.partner_id.ref),
                         ("approuve", "VIDE001", "VIDE001"))

    def test_signature_complete_obligatoire(self):
        """Si des cases deviennent obligatoires : signer attend qu'elles soient remplies."""
        from unittest.mock import patch
        ouverture = self._ouverture_envoyee()
        Ouverture = type(self.env["ouverture.compte"])
        with patch.object(Ouverture, "_champs_obligatoires", lambda self: ("rue", "ville")):
            self.assertEqual(ouverture._manquants(), ["Adresse", "Ville"])
            with self.assertRaises(UserError):
                ouverture._signer("Lise Test", SIGNATURE)
            self._remplir(ouverture)
            self.assertEqual(ouverture._manquants(), [])
        with self.assertRaises(UserError):
            ouverture._signer("Lise Test", False)
        ouverture.user_id = self.env.user
        ouverture._signer("Lise Test", SIGNATURE)
        self.assertEqual((ouverture.state, ouverture.signe_par), ("signe", "Lise Test"))
        self.assertTrue(ouverture.signe_le)
        self.assertTrue(ouverture.activity_ids, "Jose doit évaluer la demande")
        # PDF prepare en arriere-plan (le client n'attend pas)
        self.assertTrue(ouverture.pdf_a_preparer)
        self.Ouverture._cron_pdf_signes()
        self.assertFalse(ouverture.pdf_a_preparer)
        # Le client recoit la confirmation (avec la demande signee), une seule fois
        self.assertTrue(ouverture.confirmation_envoyee)
        courriel = self.env["mail.mail"].search([("model", "=", "ouverture.compte"), ("res_id", "=", ouverture.id),
                                                 ("subject", "ilike", "bien reçu")])
        self.assertEqual(len(courriel), 1)
        self.assertEqual(courriel.email_to, ouverture.courriel)
        self.assertIn("en attente d'approbation", courriel.body_html)
        self.assertEqual(courriel.attachment_ids, ouverture.pdf_signe_id)
        ouverture._envoyer_confirmation_signature()
        self.assertEqual(len(self.env["mail.mail"].search([("model", "=", "ouverture.compte"),
                                                          ("res_id", "=", ouverture.id),
                                                          ("subject", "ilike", "bien reçu")])), 1, "une seule fois")
        with self.assertRaises(UserError):
            ouverture._completer_par_client({"ville": "Autre"})

    def test_approuver_cree_le_client(self):
        ouverture = self._ouverture_envoyee()
        self._remplir(ouverture, autres_noms="Glacier Test Limoilou", livraison_rue="2 rue Livraison",
                      livraison_ville="Québec")
        ouverture._signer("Lise Test", SIGNATURE)
        assistant = self.env["ouverture.compte.approuver"].create({"ouverture_id": ouverture.id,
                                                                   "code_client": " MONT999 "})
        action = assistant.action_approuver()
        client = ouverture.partner_id
        self.assertEqual((client.name, client.ref, client.parent_id),
                         ("Glacier Test Limoilou", "MONT999", self.env["res.partner"]))
        self.assertEqual((client.x_nom_legal, client.city, client.email),
                         ("Glaces Test inc. Inc.", "Québec", "glaces@exemple.test"))
        self.assertEqual(client.child_ids.filtered(lambda c: c.type == "delivery").street, "2 rue Livraison")
        self.assertEqual(client.child_ids.filtered(lambda c: c.type == "contact").name, "Lise Test")
        self.assertEqual((ouverture.state, ouverture.approuve_par_id), ("approuve", self.env.user))
        self.assertFalse(ouverture.activity_ids, "activité d'évaluation terminée")
        self.assertEqual(action["res_id"], client.id)
        self.assertEqual(action["effect"]["type"], "rainbow_man")
        self.assertIn("Félicitations", action["effect"]["message"])
        self.assertEqual(client.ouverture_compte_id, ouverture)
        self.assertEqual(client.ouverture_compte_etat, "approuve")
        if ouverture.pdf_signe_id:
            self.assertEqual((ouverture.pdf_signe_id.res_model, ouverture.pdf_signe_id.res_id), ("res.partner", client.id))

    def test_code_client_unique_et_obligatoire(self):
        self.env["res.partner"].create({"name": "Déjà client", "ref": "MONT100"})
        ouverture = self._ouverture_envoyee()
        self._remplir(ouverture)
        ouverture._signer("Lise Test", SIGNATURE)
        with self.assertRaises(ValidationError):
            ouverture._approuver("mont100")
        with self.assertRaises(ValidationError):
            ouverture._approuver("  ")
        self.assertEqual(ouverture.state, "signe")
        brouillon = self.Ouverture.create({"entreprise_nom": "Pas signé", "courriel": "a@exemple.test"})
        with self.assertRaises(UserError):
            brouillon.action_approuver()

    def test_client_existant_mis_a_jour(self):
        existant = self.env["res.partner"].create({"name": "Client connu", "city": "Lévis",
                                                   "email": "connu@exemple.test"})
        action = existant.action_ouverture_compte()
        ouverture = self.Ouverture.browse(action["res_id"])
        self.assertEqual((ouverture.partner_id, ouverture.courriel, ouverture.ville),
                         (existant, "connu@exemple.test", "Lévis"))
        self.assertEqual(existant.action_ouverture_compte()["res_id"], ouverture.id, "même demande en cours")
        ouverture._envoyer()
        self._remplir(ouverture, ville="Québec")
        ouverture._signer("Lise Test", SIGNATURE)
        client = ouverture._approuver("MONT555")
        self.assertEqual(client, existant, "pas de doublon")
        self.assertEqual((client.ref, client.city), ("MONT555", "Lévis"), "ce qui était rempli est gardé")

    def test_menus_contacts_et_pilotage(self):
        """Ouvertures de compte : dans Contacts et dans Pilotage > Contacts (avec la liste des contacts)."""
        action = self.env.ref("ouverture_compte_monroy.action_ouverture_compte")
        for xmlid in ("menu_ouverture_compte", "menu_pilotage_ouverture_compte"):
            self.assertEqual(self.env.ref("ouverture_compte_monroy." + xmlid).action, action)
        pilotage = self.env.ref("suivi_machines_pilotage.menu_pilotage_contacts")
        self.assertEqual(pilotage.child_id.mapped("name"), ["Contacts", "Ouvertures de compte"])
        self.assertEqual(self.env.ref("ouverture_compte_monroy.menu_pilotage_contacts_liste").action,
                         self.env.ref("contacts.action_contacts"))

    def test_refus_et_renseignements_proteges(self):
        ouverture = self._ouverture_envoyee()
        ouverture.action_refuser()
        self.assertEqual(ouverture.state, "refuse")
        ouverture.action_brouillon()
        self.assertEqual(ouverture.state, "brouillon")
        for champ in ("banque_compte", "actionnaire1_naissance", "actionnaire2_adresse"):
            self.assertEqual(self.Ouverture._fields[champ].groups, "sales_team.group_sale_manager", champ)


@tagged("post_install", "-at_install")
class TestOuverturePortail(HttpCase):
    """Page du client : ouverte avec le jeton du courriel, cases enregistrees, signature."""

    def test_page_cases_et_signature(self):
        ouverture = self.env["ouverture.compte"].create({"entreprise_nom": "Page Test inc.",
                                                         "courriel": "page@exemple.test"})
        ouverture._envoyer()
        url = "/ouverture/%s" % ouverture.id
        reponse = self.url_open(url + "?access_token=%s" % ouverture.access_token)
        self.assertNotIn("Internal Server Error", reponse.text)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("OUVERTURE COMPTE CLIENT", reponse.text)
        self.assertIn("ÉLECTION DE DOMICILE", reponse.text, "conditions du formulaire")
        self.assertIn('name="banque_compte"', reponse.text)
        self.assertNotIn("OUVERTURE COMPTE CLIENT", self.url_open(url + "?access_token=faux").text,
                         "sans le bon jeton : pas de formulaire")
        jeton_csrf = re.search(r'name="csrf_token" value="([^"]+)"', reponse.text).group(1)
        enregistre = self.url_open(url + "/champ", data={"access_token": ouverture.access_token, "ville": "Québec",
                                                         "csrf_token": jeton_csrf})
        self.assertEqual(enregistre.status_code, 204)
        refus = self.url_open(url + "/champ", data={"access_token": "faux", "ville": "Ailleurs",
                                                    "csrf_token": jeton_csrf})
        self.assertNotEqual(refus.status_code, 204)
        ouverture.invalidate_recordset()
        self.assertEqual(ouverture.ville, "Québec")

    def test_page_apres_signature_et_etat_sur_la_fiche(self):
        """Apres la signature : la page du client affiche le formulaire signe (date), la fiche suit l'etat."""
        client = self.env["res.partner"].create({"name": "Fiche suivie", "email": "suivie@exemple.test"})
        ouverture = self.env["ouverture.compte"].browse(client.action_ouverture_compte()["res_id"])
        self.assertEqual(client.ouverture_compte_etat, "brouillon")
        ouverture._envoyer()
        self.assertEqual(client.ouverture_compte_etat, "envoye")
        ouverture._completer_par_client({"rue": "1 rue", "ville": "Québec", "code_postal": "G1A 1A1",
                                         "telephone": "418", "nom_majuscules": "X", "entreprise_nom": "Fiche suivie",
                                         "forme": "inc", "contact_nom": "X", "banque_nom": "B", "banque_adresse": "B",
                                         "banque_compte": "1", "approvisionnement": "bureau", "paiement": "cheque",
                                         "terme": "30", "signe_a": "Québec", "caution_noms": "X"})
        ouverture._signer("X", "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
        self.assertEqual(client.ouverture_compte_etat, "signe")
        reponse = self.url_open("/ouverture/%s?access_token=%s" % (ouverture.id, ouverture.access_token))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(ouverture._date_texte(ouverture.signe_le), reponse.text)
        # Confirmation claire pour le client : signee, en attente d'approbation, PDF a telecharger
        self.assertIn('id="ouverture_confirmation"', reponse.text)
        self.assertIn("en attente d'approbation", reponse.text)
        self.assertNotIn('name="ville"', reponse.text, "plus de cases à remplir")
        lien = "/ouverture/%s/pdf?access_token=%s" % (ouverture.id, ouverture.access_token)
        self.assertIn(lien.replace("&", "&amp;") if "&" in lien else lien, reponse.text)
        pdf = self.url_open(lien)
        if ouverture._rendre_pdf():   # moteur PDF present (Odoo.sh) : le fichier est envoye
            self.assertEqual(pdf.headers.get("Content-Type"), "application/pdf")
            self.assertIn("attachment", pdf.headers.get("Content-Disposition", ""))
            self.assertTrue(pdf.content, "le fichier est envoyé (en test, Odoo rend le rapport en HTML)")
            self.assertFalse(ouverture.pdf_a_preparer, "prepare une seule fois")
        refuse = self.url_open("/ouverture/%s/pdf?access_token=faux" % ouverture.id)
        self.assertNotIn("attachment", refuse.headers.get("Content-Disposition", ""), "jamais sans le bon lien")
        client.ouverture_compte_etat  # lu avant l'approbation, comme sur la fiche ouverte
        ouverture._approuver("MONT321")
        self.assertEqual(client.ouverture_compte_etat, "approuve")
