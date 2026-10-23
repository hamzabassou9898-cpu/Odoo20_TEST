# -*- coding: utf-8 -*-
import re

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestPortailTechnicien(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        portail = env.ref("base.group_portal")

        def technicien(nom, login):
            user = env["res.users"].create({"name": nom, "login": login, "password": login + "_mdp_123",
                                            "tz": "America/Toronto", "group_ids": [(6, 0, [portail.id])]})
            user.partner_id.est_technicien = True
            return user

        cls.tech_a = technicien("Tech portail A", "tech_portail_a")
        cls.tech_b = technicien("Tech portail B", "tech_portail_b")
        cls.client = env["res.partner"].create({"name": "Camping Portail", "street": "12 rue du Lac",
                                                "city": "Lac-Beauport", "phone": "418 555 0101"})
        cls.ticket = env["helpdesk.ticket"].create({
            "name": "Machine ne refroidit pas", "partner_id": cls.client.id,
            "user_id": cls.tech_a.id, "date_planifiee": fields.Datetime.now(),
            "description": "<p>Le client entend un bruit</p>", "type_demande": "reparation",
            "type_reparation": "bruit"})
        cls.autre = env["helpdesk.ticket"].create({
            "name": "Ticket d'un autre technicien", "partner_id": cls.client.id,
            "user_id": cls.tech_b.id, "date_planifiee": fields.Datetime.now()})

    def _tache(self, ticket):
        return self.env["portail.tache"].search([("ticket_id", "=", ticket.id)])

    def test_tache_du_technicien_portail(self):
        tache = self._tache(self.ticket)
        self.assertEqual(tache.technicien_id, self.tech_a, "« Assigné à » (technicien portail)")
        # Glisser vers un technicien interne puis portail : toujours le champ natif « Assigné à »
        tache.write({"technicien_id": self.env.ref("base.user_admin").id})
        self.assertEqual(self.ticket.user_id, self.env.ref("base.user_admin"))
        self._tache(self.ticket).write({"technicien_id": self.tech_a.id})
        self.assertEqual(self.ticket.user_id, self.tech_a)
        self.assertFalse(self.ticket.technicien_terrain_id)

    def test_case_technicien_absente_des_fiches_clients(self):
        from lxml import etree
        arch = etree.fromstring(self.env["res.partner"].get_views([(False, "form")])["views"]["form"]["arch"])
        champ = arch.xpath("//field[@name='est_technicien']")[0]
        self.assertEqual(champ.get("invisible"), "not a_acces_portail and not est_technicien")
        self.assertFalse(self.client.a_acces_portail, "fiche client : case cachée")
        self.assertTrue(self.tech_a.partner_id.a_acces_portail, "technicien portail : case visible")

    def test_un_seul_champ_assigne_a(self):
        """Fiche du ticket : plus de « Technicien terrain » ; « Assigné à » propose les techniciens portail."""
        arch = self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertNotIn('name="technicien_terrain_id"', arch)
        self.assertIn("partner_id.est_technicien", arch)
        # Migration : l'ancien « Technicien terrain » passe dans « Assigné à »
        import importlib.util, os
        chemin = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations", "20.0.1.5.0", "post-migrate.py")
        spec = importlib.util.spec_from_file_location("migration_un_champ", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ancien = self.env["helpdesk.ticket"].create({"name": "Ancien", "partner_id": self.client.id,
                                                     "technicien_terrain_id": self.tech_b.id})
        entretien = self.env["helpdesk.ticket"].create({"name": "Entretien ancien", "partner_id": self.client.id,
                                                        "est_entretien": True,
                                                        "technicien_terrain_id": self.tech_b.id})
        self.assertEqual(entretien.statut_entretien, "a_planifier")
        self.env.flush_all()
        module.migrate(self.env.cr, "20.0.1.4.0")
        self.env.invalidate_all()
        self.assertEqual((ancien.user_id, ancien.technicien_terrain_id), (self.tech_b, self.env["res.users"]))
        self.assertEqual((entretien.user_id, entretien.statut_entretien), (self.tech_b, "planifie"),
                         "entretien déjà assigné : planifié")

    def test_page_ma_journee(self):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        page = self.url_open("/my/journee")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Machine ne refroidit pas", page.text)
        self.assertIn("12 rue du Lac", page.text)
        self.assertNotIn("Ticket d'un autre technicien", page.text)
        # Detail de sa tache : oui ; celle d'un autre : retour a sa journee
        detail = self.url_open("/my/journee/tache/%s" % self._tache(self.ticket).id)
        self.assertIn("Le client entend un bruit", detail.text)
        self.assertIn("Type de réparation", detail.text)
        self.assertIn("Fait du bruit", detail.text)
        self.assertIn("tel:418 555 0101", detail.text)
        refus = self.url_open("/my/journee/tache/%s" % self._tache(self.autre).id)
        self.assertNotIn("Ticket d'un autre technicien", refus.text)
        # Carte « Ma journee » sur l'accueil du portail
        accueil = self.url_open("/my")
        self.assertIn("/my/journee", accueil.text)

    def test_non_technicien(self):
        self.tech_b.partner_id.est_technicien = False
        self.authenticate("tech_portail_b", "tech_portail_b_mdp_123")
        page = self.url_open("/my/journee")
        self.assertNotIn("Ticket d'un autre technicien", page.text)
        accueil = self.url_open("/my")
        self.assertFalse(accueil.url.endswith("/my/journee"), "un autre utilisateur portail garde Mon compte")

    def test_technicien_seulement_sa_journee(self):
        """Le technicien n'a que « Ma journée » : Mon compte l'y amène, une seule carte."""
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        for url in ("/my", "/my/home"):
            self.assertTrue(self.url_open(url).url.endswith("/my/journee"), url)
        cartes = self.env["portal.entry"].search([]).with_user(self.tech_a)._filter_visible_portal_cards()
        self.assertEqual(cartes, self.env.ref("suivi_machines_portail.portal_entry_ma_journee"))


    # ------------------------------------------------------------ note + pieces jointes depuis le portail
    def _csrf(self, url):
        page = self.url_open(url)
        return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    def test_note_et_pieces_jointes(self):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        tache = self._tache(self.ticket)
        url = "/my/journee/tache/%s" % tache.id
        self.assertIn("Ajouter une note", self.url_open(url).text)
        rep = self.url_open(url + "/note", data={"csrf_token": self._csrf(url),
                                                 "note": "Joint remplacé.\nClient satisfait."},
                            files=[("pieces_jointes", ("photo.jpg", b"\xff\xd8\xff photo", "image/jpeg")),
                                   ("pieces_jointes", ("rapport.pdf", b"%PDF-1.4 rapport", "application/pdf"))])
        self.assertEqual(rep.status_code, 200)
        self.assertIn("Note envoyée", rep.text)
        msg = self.ticket.note_technicien_ids
        self.assertEqual(len(msg), 1)
        self.assertEqual(msg.technicien_id, self.tech_a)
        self.assertEqual(msg.note, "Joint remplacé.\nClient satisfait.")
        self.assertEqual(sorted(msg.attachment_ids.mapped("name")), ["photo.jpg", "rapport.pdf"])
        self.assertEqual(set(msg.attachment_ids.mapped("res_model")), {"helpdesk.ticket"})
        self.assertEqual(set(msg.attachment_ids.mapped("res_id")), {self.ticket.id})
        # Aussi en « Note » interne dans le fil du ticket, au nom du technicien, avec les fichiers
        msg_fil = self.ticket.message_ids.filtered(lambda m: m.author_id == self.tech_a.partner_id)
        self.assertEqual(len(msg_fil), 1)
        self.assertIn("Joint remplacé.", msg_fil.body)
        self.assertTrue(msg_fil.subtype_id.internal, "note interne : pas de courriel au client")
        self.assertEqual(sorted(msg_fil.attachment_ids.mapped("name")), ["photo.jpg", "rapport.pdf"])
        # Sur la fiche : seulement dans le fil de discussion a droite (plus d'onglet)
        for model in ("helpdesk.ticket", "stock.picking", "machine.intervention"):
            arch = self.env[model].get_views([(False, "form")])["views"]["form"]["arch"]
            self.assertNotIn("note_technicien_ids", arch, model)
        # La note apparait dans « Mes notes envoyées »
        self.assertIn("rapport.pdf", self.url_open(url).text)

    def test_note_vide_ou_autre_technicien(self):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        tache = self._tache(self.ticket)
        url = "/my/journee/tache/%s" % tache.id
        rep = self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "  "})
        self.assertIn("Écrivez une note", rep.text)
        self.assertFalse(self.ticket.note_technicien_ids)
        # Tache d'un autre technicien : refus, rien n'est ecrit
        autre = self._tache(self.autre)
        rep = self.url_open("/my/journee/tache/%s/note" % autre.id,
                            data={"csrf_token": self._csrf(url), "note": "intrusion"})
        self.assertTrue(rep.url.endswith("/my/journee"))
        self.assertFalse(self.autre.note_technicien_ids)
        # Sans jeton CSRF : refuse
        with self.assertLogs("odoo.http", "WARNING"):     # refus attendu, journalise par Odoo
            rep = self.url_open(url + "/note", data={"note": "sans jeton"})
        self.assertNotEqual(rep.status_code, 200)


    def test_note_limites_fichiers(self):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % self._tache(self.ticket).id
        # 11 fichiers : refuse, rien n'est enregistre
        onze = [("pieces_jointes", ("f%s.txt" % i, b"x", "text/plain")) for i in range(11)]
        rep = self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "trop"}, files=onze)
        self.assertIn("fichiers au plus", rep.text)
        self.assertFalse(self.ticket.note_technicien_ids)
        # Fichier de plus de 20 Mo : refuse
        gros = [("pieces_jointes", ("gros.jpg", b"0" * (20 * 1024 * 1024 + 1), "image/jpeg"))]
        rep = self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "gros"}, files=gros,
                            timeout=60)
        self.assertIn("dépasse 20 Mo", rep.text)
        self.assertFalse(self.ticket.note_technicien_ids)
        # Photo seule, sans texte : acceptee ; 10 fichiers : acceptes
        dix = [("pieces_jointes", ("p%s.jpg" % i, b"\xff\xd8 photo", "image/jpeg")) for i in range(10)]
        rep = self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": ""}, files=dix)
        self.assertIn("Note envoyée", rep.text)
        self.assertEqual(len(self.ticket.note_technicien_ids.attachment_ids), 10)

    def test_bureau_telecharge_la_piece_jointe(self):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % self._tache(self.ticket).id
        self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "photo"},
                      files=[("pieces_jointes", ("photo.jpg", b"\xff\xd8\xff contenu-photo", "image/jpeg"))])
        piece = self.ticket.note_technicien_ids.attachment_ids
        self.assertEqual(len(piece), 1)
        # Le technicien (portail) ne peut pas telecharger les fichiers du ticket directement
        self.assertNotEqual(self.url_open("/web/content/%s?download=true" % piece.id).content,
                            b"\xff\xd8\xff contenu-photo")
        # Le bureau (interne) telecharge la photo depuis le ticket
        self.authenticate("admin", "admin")
        rep = self.url_open("/web/content/%s?download=true" % piece.id)
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(rep.content, b"\xff\xd8\xff contenu-photo")

    def test_note_sur_bon_de_livraison(self):
        type_out = self.env.ref("stock.picking_type_out")
        categ = self.env["product.category"].create({"name": "Mach note", "suivi_machine": True})
        prod = self.env["product.product"].create({"name": "F note", "categ_id": categ.id, "is_storable": True})
        picking = self.env["stock.picking"].create({
            "name": "TEST/NOTE/1", "partner_id": self.client.id, "picking_type_id": type_out.id,
            "location_id": type_out.default_location_src_id.id,
            "location_dest_id": self.env.ref("stock.stock_location_customers").id,
            "livreur_id": self.tech_a.id, "scheduled_date": fields.Datetime.now(),
            "move_ids": [(0, 0, {"product_id": prod.id, "product_uom_qty": 1,
                                 "location_id": type_out.default_location_src_id.id,
                                 "location_dest_id": self.env.ref("stock.stock_location_customers").id})]})
        tache = self.env["portail.tache"].search([("picking_id", "=", picking.id)])
        self.assertEqual(tache.technicien_id, self.tech_a)
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % tache.id
        self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "Client absent, laissé au voisin"})
        self.assertEqual(picking.note_technicien_ids.note, "Client absent, laissé au voisin")
        self.assertIn("Client absent", picking.message_ids[:1].body, "dans le fil de la livraison")


    # ------------------------------------------------------------ l'admin est prevenu et fait le suivi
    def _envoyer_note(self, texte="Pièce à commander", fichiers=None):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % self._tache(self.ticket).id
        self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": texte}, files=fichiers)
        self.env.invalidate_all()
        return self.ticket.note_technicien_ids[:1]

    def test_admin_prevenu_par_une_activite(self):
        admin = self.env.ref("base.user_admin")
        # Base avec des donnees (staging) : on compte a partir des notes deja a lire
        self.notes_a_lire_avant = self.env.ref("suivi_machines_portail.indicateur_notes_a_lire").valeur
        note = self._envoyer_note(fichiers=[("pieces_jointes", ("p.jpg", b"\xff\xd8", "image/jpeg"))])
        self.assertFalse(note.lu)
        activite = note.activity_id
        self.assertTrue(activite, "une activité est créée")
        self.assertEqual(activite.user_id, admin, "pour le responsable (l'administrateur par défaut)")
        self.assertEqual((activite.res_model, activite.res_id), ("helpdesk.ticket", self.ticket.id))
        self.assertIn("Tech portail A", activite.summary)
        self.assertIn(activite, self.ticket.activity_ids)
        # Carte du tableau de bord
        ind = self.env.ref("suivi_machines_portail.indicateur_notes_a_lire")
        ind.invalidate_recordset()
        self.assertEqual(ind.valeur, self.notes_a_lire_avant + 1)
        self.assertEqual(ind.action_ouvrir()["res_model"], "suivi.note.technicien")
        # L'admin marque l'activite « Fait » (horloge) : la note devient « Lue »
        activite.with_user(admin).action_done()
        self.assertTrue(note.lu)
        ind.invalidate_recordset()
        self.assertEqual(ind.valeur, self.notes_a_lire_avant)

    def test_marquer_lue_ferme_l_activite(self):
        note = self._envoyer_note("Client absent")
        activite = note.activity_id
        note.with_user(self.env.ref("base.user_admin")).action_marquer_lu()
        self.assertTrue(note.lu)
        self.assertFalse(activite.active, "activité terminée")
        self.assertFalse(self.ticket.activity_ids.filtered(lambda a: a == activite))

    def test_activite_supprimee_note_lue(self):
        note = self._envoyer_note("Rappel lundi")
        note.activity_id.unlink()
        self.assertTrue(note.lu)

    def test_responsable_configure(self):
        interne = self.env["res.users"].create({"name": "Jose", "login": "josef_test",
                                                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        self.env["ir.config_parameter"].sudo().set_int("suivi_machines_helpdesk.responsable_reprise_id", interne.id)
        note = self._envoyer_note("Pour Jose")
        self.assertEqual(note.activity_id.user_id, interne)
        self.assertEqual(note.responsable_id, interne)


    # ------------------------------------------------------------ parcours entretien complet (synchronisation)
    def test_entretien_planifie_journee_et_pilotage(self):
        if not self.env["helpdesk.ticket"]._etape_contenant("résolu"):
            self.env["helpdesk.stage"].create({"name": "Résolu"})
        categ = self.env["product.category"].create({"name": "Mach entretien", "suivi_machine": True})
        prod = self.env["product.product"].create({"name": "F ent", "categ_id": categ.id, "is_storable": True,
                                                   "tracking": "serial"})
        lot = self.env["stock.lot"].create({"name": "ENT-1", "ref": "F777", "product_id": prod.id})
        ticket = self.env["helpdesk.ticket"].create({"name": "ENTRETIEN - F777", "partner_id": self.client.id,
                                                     "lot_id": lot.id, "est_entretien": True})
        ind = self.env.ref("suivi_machines_pilotage.indicateur_entretiens_ouverts")
        self.assertEqual(ind.section, "entretiens", "carte dans la section Entretiens")
        # Le bureau planifie l'entretien pour le technicien portail (Nouvelle intervention)
        quand = fields.Datetime.now()
        interv = self.env["machine.intervention"].create({
            "ticket_id": ticket.id, "lot_id": lot.id, "type": "entretien", "state": "planifie",
            "user_id": self.tech_a.id, "date": quand})
        self.assertEqual(ticket.user_id, self.tech_a, "technicien portail dans « Assigné à »")
        self.assertEqual(ticket.date_planifiee, quand)
        self.env.invalidate_all()
        tache = self.env["portail.tache"].search([("ticket_id", "=", ticket.id)])
        self.assertEqual((tache.technicien_id, tache.type_tache), (self.tech_a, "entretien"))
        model, domaine = self.env["pilotage.indicateur"]._domaines()["entretiens_ouverts"]
        self.assertIn(ticket, self.env[model].search(domaine))
        # Visible dans la journee du technicien
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        self.assertIn("ENTRETIEN - F777", self.url_open("/my/journee").text)
        # Validation de l'entretien : l'intervention planifiee devient faite, le ticket est resolu
        wiz = self.env["suivi.machines.valider.entretien"].with_context(default_ticket_id=ticket.id).create({})
        self.assertEqual(wiz.technicien_id, self.tech_a)
        wiz.action_valider()
        self.assertEqual(interv.state, "fait")
        self.assertEqual(len(ticket.intervention_ticket_ids), 1)
        equipe = ticket.team_id if "team_id" in ticket._fields else None
        self.assertEqual(ticket.stage_id, ticket._etape_contenant("résolu", equipe), "ticket résolu")
        self.assertNotIn(ticket, self.env[model].search(domaine), "plus dans les entretiens à faire")
        self.env.invalidate_all()
        self.assertEqual(self.env["portail.tache"].search([("ticket_id", "=", ticket.id)]).etat_suivi, "fait")

    # ------------------------------------------------------------ bon d'intervention signe
    SIGNATURE = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

    def test_bon_signe_par_le_client(self):
        resolu = self.env["helpdesk.stage"].search([("name", "=ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        tache = self._tache(self.ticket)
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % tache.id
        page = self.url_open(url)
        self.assertIn("Terminer : signature du client", page.text)
        self.assertIn("Entretien sur les équipements", page.text, "titre du formulaire papier")
        self.assertIn("Je confirme que", page.text, "le client lit ce qu'il signe")
        self.assertIn("portal.signature_form", page.text, "formulaire de signature du portail")
        # Note du jour = « travail fait » du bon
        self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": "Joint remplacé."})
        # Signature vide : refusee
        self.assertIn("error", self.make_jsonrpc_request(url + "/signer", {"name": "M. Tremblay", "signature": ""}))
        rep = self.make_jsonrpc_request(url + "/signer", {"name": "M. Tremblay", "signature": self.SIGNATURE})
        self.assertTrue(rep.get("force_refresh"), rep)
        bon = self.ticket.bon_intervention_ids
        self.assertEqual(len(bon), 1)
        self.assertTrue(bon.name.startswith("BON/"))
        self.assertEqual((bon.signe_par, bon.technicien_id, bon.partner_id), ("M. Tremblay", self.tech_a, self.client))
        self.assertEqual(bon.travail, "Joint remplacé.")
        # Formulaire Monroy : section « Entretien sur les equipements » (reparation)
        self.assertEqual(bon.type_bon, "entretien")
        self.assertIn("a effectué une réparation sur les équipements en place", bon.texte)
        self.assertTrue(bon.signature)
        self.assertEqual(self.ticket.stage_id, resolu, "tâche terminée : ticket résolu")
        self.assertTrue(self.ticket.message_ids.filtered(lambda m: "signé" in (m.body or "")), "dans le fil du ticket")
        # Apres le client : date de l'entretien, signature du client, puis signature du technicien
        page = self.url_open(url).text
        self.assertIn("Date de l'entretien", page)
        self.assertIn('alt="Signature du client"', page)
        self.assertIn("/signer_technicien", page, "le technicien signe à son tour")
        self.assertTrue(bon.doit_signer_technicien)
        self.assertIn("error", self.make_jsonrpc_request(url + "/signer_technicien", {"name": "T", "signature": ""}))
        # Comme sur Odoo.sh : l'admin est prevenu par courriel (base neutralisee = aucun courriel envoye)
        self.env.ref("base.user_admin").notification_type = "email"
        admin = self.env.ref("base.user_admin").partner_id
        notif = lambda: self.env["mail.message"].search([("partner_ids", "in", admin.ids),
                                                        ("subject", "=", "Bon %s signé" % bon.name)])
        self.assertFalse(notif(), "pas encore : le technicien doit signer")
        rep = self.make_jsonrpc_request(url + "/signer_technicien", {"name": "Tech", "signature": self.SIGNATURE})
        self.assertTrue(rep.get("force_refresh"), rep)
        self.env.invalidate_all()
        message = notif()
        self.assertEqual(len(message), 1, "Jose (responsable) est prévenu quand le bon est complet")
        self.assertNotIn(self.client.id, message.partner_ids.ids, "le client n'est pas prévenu")
        # ... et il le voit DANS Odoo quand meme : une activite a faire sur le ticket
        activite = self.ticket.activity_ids.filtered(lambda a: a.summary == "Bon %s signé" % bon.name)
        self.assertEqual(activite.user_id, self.env.ref("base.user_admin"), "activité pour Jose dans Odoo")
        self.env.invalidate_all()
        self.assertTrue(bon.signature_technicien)
        self.assertFalse(bon.doit_signer_technicien)
        page = self.url_open(url).text
        self.assertIn('alt="Signature du technicien"', page)
        self.assertNotIn("/signer_technicien", page)
        signe_le = bon.technicien_signe_le
        # Une seule fois : un 2e envoi (double clic) recharge la page, sans erreur ni bouton bloque
        encore = self.make_jsonrpc_request(url + "/signer_technicien", {"name": "Tech", "signature": self.SIGNATURE})
        self.assertEqual((encore.get("force_refresh"), encore.get("error")), (True, None))
        self.assertEqual(bon.technicien_signe_le, signe_le, "signature inchangée")
        # Deuxieme signature du client : la tache est deja terminee -> la page se recharge, aucun 2e bon
        Bon = self.env["suivi.bon.intervention"]
        avant = Bon.search_count([])
        encore = self.make_jsonrpc_request(url + "/signer", {"name": "X", "signature": self.SIGNATURE})
        self.assertEqual((encore.get("force_refresh"), encore.get("error")), (True, None))
        self.assertEqual(Bon.search_count([]), avant, "pas de deuxième bon")
        self.assertIn(bon.name, self.url_open(url).text)
        # « Voir le bon (PDF) » : le fichier est bien envoye (pas de page blanche)
        self.assertTrue(bon.pdf_id, "PDF joint au ticket")
        fichier = self.url_open(url + "/bon")
        self.assertEqual(fichier.status_code, 200)
        self.assertGreater(len(fichier.content), 100, "le fichier complet est envoyé")
        # Un autre technicien ne peut pas signer la tache
        tache_b = self._tache(self.autre)
        self.assertIn("error", self.make_jsonrpc_request("/my/journee/tache/%s/signer" % tache_b.id,
                                                         {"name": "X", "signature": self.SIGNATURE}))
        self.assertFalse(self.autre.bon_intervention_ids)
        # Le bureau voit les bons signes
        self.env["suivi.bon.intervention"].get_views([(False, "list"), (False, "form")])
        # ... depuis la carte du tableau de bord (plus de menu, pour gagner de la place)
        carte = self.env.ref("suivi_machines_portail.indicateur_bons_signes_mois")
        carte.invalidate_recordset()
        self.assertGreaterEqual(carte.valeur, 1)
        action = carte.action_ouvrir()
        self.assertEqual(action["res_model"], "suivi.bon.intervention")
        self.assertEqual(self.env["suivi.bon.intervention"].search_count(action["domain"]), carte.valeur)
        # ... et dans « À traiter maintenant » de la vue d'ensemble
        alertes = self.env["pilotage.indicateur"].donnees_tableau_moderne("jour")["alertes"]
        self.assertIn("bons_signes_mois", [a["code"] for a in alertes])
        self.assertFalse(self.env.ref("suivi_machines_portail.menu_bons_intervention", raise_if_not_found=False))
        self.assertFalse(self.env.ref("suivi_machines_portail.menu_notes_technicien", raise_if_not_found=False))

    def test_reparation_auto_signee_au_portail(self):
        """Réparation datée : intervention planifiée toute seule ; la signature du client la termine et
        le bon signé (PDF) est dans le fil du ticket, à droite."""
        self.env["helpdesk.stage"].search([("name", "=ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        categ = self.env["product.category"].create({"name": "Machines (auto)", "suivi_machine": True})
        produit = self.env["product.product"].create({"name": "Machine auto", "categ_id": categ.id,
                                                      "is_storable": True, "tracking": "serial"})
        lot = self.env["stock.lot"].create({"name": "AUTO-1", "product_id": produit.id})
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Coule", "partner_id": self.client.id, "type_demande": "reparation", "type_reparation": "coule",
            "lot_id": lot.id, "user_id": self.tech_a.id, "date_planifiee": fields.Datetime.now()})
        interv = ticket.intervention_ticket_ids
        self.assertEqual((interv.state, interv.user_id), ("planifie", self.tech_a))
        self.assertEqual(len(self.env["portail.tache"].search([("partner_id", "=", self.client.id),
                                                                ("lot_id", "=", lot.id)])), 1,
                         "une seule tâche au portail (le ticket), pas de doublon")
        tache = self._tache(ticket)
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % tache.id
        self.url_open(url)
        rep = self.make_jsonrpc_request(url + "/signer", {"name": "Mme Roy", "signature": self.SIGNATURE})
        self.assertTrue(rep.get("force_refresh"), rep)
        self.env.invalidate_all()
        self.assertEqual(interv.state, "fait", "intervention terminée avec la signature")
        self.assertEqual(ticket.statut_entretien, "fait")
        bon = ticket.bon_intervention_ids
        message = ticket.message_ids.filtered(lambda m: bon.name in (m.body or ""))
        self.assertTrue(message, "bon signé dans le fil du ticket")
        self.assertEqual(message.attachment_ids, bon.pdf_id, "avec le PDF")

    def test_bon_signe_intervention_et_transfert(self):
        lot_produit = self.env["product.product"].create({"name": "Machine bon", "is_storable": True})
        lot = self.env["stock.lot"].create({"name": "BON-1", "product_id": lot_produit.id})
        interv = self.env["machine.intervention"].create({
            "lot_id": lot.id, "type": "reparation", "user_id": self.tech_a.id, "partner_id": self.client.id,
            "date": fields.Datetime.now()})
        tache = self.env["portail.tache"].search([("intervention_id", "=", interv.id)])
        bon = self.env["suivi.bon.intervention"]._creer_depuis_tache(tache, "Client", self.SIGNATURE)
        self.assertEqual(interv.state, "fait", "intervention faite")
        self.assertEqual(bon.intervention_id, interv)
        if bon.doit_signer_technicien:
            bon._signer_technicien(self.SIGNATURE)
        self.assertFalse(interv.activity_ids, "pas d'activité sur une intervention (pas claire pour le bureau)")
        # Intervention sans ticket, mais un ticket ouvert sur la meme machine (ticket d'origine) :
        # le bon et son PDF vont dans les deux, et le bureau a son activite sur le ticket
        ticket = self.env["helpdesk.ticket"].create({"name": "Machine à remplacer", "partner_id": self.client.id,
                                                     "lot_id": lot.id})
        interv2 = self.env["machine.intervention"].create({
            "lot_id": lot.id, "type": "remplacement", "user_id": self.tech_a.id, "partner_id": self.client.id,
            "date": fields.Datetime.now()})
        tache2 = self.env["portail.tache"].search([("intervention_id", "=", interv2.id)])
        bon2 = self.env["suivi.bon.intervention"]._creer_depuis_tache(tache2, "Client", self.SIGNATURE)
        self.assertEqual(bon2._dossier_bureau(), ticket)
        if bon2.doit_signer_technicien:
            bon2._signer_technicien(self.SIGNATURE)
        for document in (interv2, ticket):
            messages = document.message_ids.filtered(lambda m: bon2.name in (m.body or ""))
            self.assertTrue(messages, "bon dans %s" % document._name)
            if bon2.pdf_id:
                self.assertIn(bon2.pdf_id, messages.attachment_ids, "PDF dans %s" % document._name)
        self.assertTrue(ticket.activity_ids.filtered(lambda a: bon2.name in (a.summary or "")), "activité du bureau")
        self.assertFalse(interv2.activity_ids, "rien sur l'intervention")
        # Note du technicien sur une intervention : activite sur le ticket d'origine, pas sur l'intervention
        note = self.env["suivi.note.technicien"].sudo().create({
            "technicien_id": self.tech_a.id, "note": "Joint changé", "intervention_id": interv2.id})
        note._prevenir_responsable()
        self.assertEqual((note.activity_id.res_model, note.activity_id.res_id), ("helpdesk.ticket", ticket.id))
        self.assertFalse(interv2.activity_ids)
        type_out = self.env.ref("stock.picking_type_out")
        picking = self.env["stock.picking"].create({
            "picking_type_id": type_out.id, "partner_id": self.client.id, "livreur_id": self.tech_a.id,
            "move_ids": [(0, 0, {"product_id": lot_produit.id, "product_uom_qty": 1,
                                 "location_id": type_out.default_location_src_id.id,
                                 "location_dest_id": self.env.ref("stock.stock_location_customers").id})]})
        picking.action_confirm()
        tache = self.env["portail.tache"].search([("picking_id", "=", picking.id)])
        if tache:
            bon = self.env["suivi.bon.intervention"]._creer_depuis_tache(tache, "Client", self.SIGNATURE)
            self.assertNotEqual(picking.state, "done", "le stock se valide au bureau")
            self.assertTrue(picking.activity_ids, "le bureau est prévenu")
            self.assertEqual(bon.type_bon, "livraison")
            self.assertIn("J'ai reçu en bon état", bon.texte)
            self.assertIn("SES FRAIS", bon.texte)

    def test_bon_de_reprise_avec_etat(self):
        """Reprise : le technicien coche l'etat (tres propre / moyen / sale, pleine, en fonction), puis signature."""
        produit = self.env["product.product"].create({"name": "Machine reprise", "is_storable": True})
        type_in = self.env.ref("stock.picking_type_in")
        retour = self.env["stock.picking"].create({
            "picking_type_id": type_in.id, "partner_id": self.client.id, "livreur_id": self.tech_a.id,
            "location_id": self.env.ref("stock.stock_location_customers").id,
            "location_dest_id": self.env.ref("stock.stock_location_stock").id,
            "scheduled_date": fields.Datetime.now(),
            "move_ids": [(0, 0, {"product_id": produit.id, "product_uom_qty": 1,
                                 "location_id": self.env.ref("stock.stock_location_customers").id,
                                 "location_dest_id": self.env.ref("stock.stock_location_stock").id})]})
        retour.action_confirm()
        tache = self.env["portail.tache"].search([("picking_id", "=", retour.id)])
        if not tache or tache.type_tache != "ramassage":
            self.skipTest("transfert non reconnu comme ramassage dans ce stock de test")
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % tache.id
        page = self.url_open(url)
        self.assertIn("Reprise des équipements", page.text)
        self.assertIn("Cochez d'abord l'état", page.text, "pas de signature avant l'état")
        self.assertNotIn("portal.signature_form", page.text)
        self.url_open(url + "/reprise", data={"csrf_token": self._csrf(url), "proprete": "moyen", "pleine": "1"})
        self.assertEqual((retour.reprise_proprete, retour.reprise_pleine, retour.reprise_en_fonction),
                         ("moyen", True, False))
        self.assertIn("portal.signature_form", self.url_open(url).text)
        self.make_jsonrpc_request(url + "/signer", {"name": "Commis Gagnon", "signature": self.SIGNATURE})
        bon = retour.bon_intervention_ids
        self.assertEqual((bon.type_bon, bon.proprete, bon.pleine, bon.en_fonction, bon.signe_par),
                         ("reprise", "moyen", True, False, "Commis Gagnon"))

    def test_planning_montre_les_techniciens_portail(self):
        donnees = self.env["portail.tache"].donnees_planning(False)
        noms = [ligne["nom"] for ligne in donnees["lignes"]]
        self.assertIn("Tech portail A", noms)
        self.assertIn("Tech portail B", noms)
        self.assertEqual(noms[0], "Sans technicien", "en haut, comme les postes ouverts du Planning")

    def test_planning_seulement_techniciens_portail(self):
        """Planning : ni ligne ni tâche pour un utilisateur interne (Administrator, API...)."""
        admin = self.env.ref("base.user_admin")
        interne = self.env["helpdesk.ticket"].create({
            "name": "Ticket de l'admin au planning", "partner_id": self.client.id, "user_id": admin.id,
            "date_planifiee": fields.Datetime.now()})
        donnees = self.env["portail.tache"].donnees_planning(False)
        self.assertNotIn(admin.id, [ligne["id"] for ligne in donnees["lignes"]])
        titres = [carte["titre"] for carte in donnees["cartes"]]
        self.assertNotIn(interne.name, titres)
        self.assertIn(self.ticket.name, titres, "tâche du technicien portail")
        self.assertNotIn(admin.id, [t["id"] for t in donnees["filtres"]["techniciens"]])


    def test_portail_techniciens_seulement_techniciens(self):
        """Pilotage > Portail techniciens : colonnes des techniciens portail seulement."""
        action = self.env.ref("suivi_machines_pilotage.action_portail_techniciens")
        domaine = eval(action.domain)  # noqa: S307 - domaine statique du module
        Tache = self.env["portail.tache"]
        interne = self.env["helpdesk.ticket"].create({
            "name": "Ticket de l'admin", "partner_id": self.client.id, "user_id": self.env.ref("base.user_admin").id,
            "date_planifiee": fields.Datetime.now()})
        visibles = Tache.search(domaine)
        self.assertIn(self._tache(self.ticket), visibles)
        self.assertNotIn(self._tache(interne), visibles, "tâche d'un utilisateur interne : pas ici")
        groupes = Tache.with_context(read_group_expand=True).formatted_read_group(domaine, ["technicien_id"], ["__count"])
        colonnes = {g["technicien_id"][0] for g in groupes if g["technicien_id"]}
        self.assertIn(self.tech_a.id, colonnes)
        self.assertIn(self.tech_b.id, colonnes)
        self.assertNotIn(self.env.ref("base.user_admin").id, colonnes)

    def test_reprise_depuis_un_ticket(self):
        """Ramassage venant d'un ticket : cases Très propre / Moyen / Sale / Pleine / En fonction avec la
        phrase du formulaire papier, puis dans le bon signé (PDF)."""
        self.env["helpdesk.stage"].search([("name", "=ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Reprendre la machine", "partner_id": self.client.id, "type_demande": "ramassage",
            "user_id": self.tech_a.id, "date_planifiee": fields.Datetime.now()})
        tache = self._tache(ticket)
        self.assertEqual(tache.type_tache, "ramassage")
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % tache.id
        page = self.url_open(url).text
        self.assertIn("La propreté du congélateur et des accessoires", page)
        for case in ("Très propre", "Moyen", "Sale", "PLEINE", "EN FONCTION"):
            self.assertIn(case, page)
        self.assertIn("Cochez d", page, "signature après les cases")
        self.url_open(url + "/reprise", data={"csrf_token": self._csrf(url), "proprete": "moyen", "pleine": "1"})
        self.env.invalidate_all()
        self.assertEqual((ticket.reprise_proprete, ticket.reprise_pleine, ticket.reprise_en_fonction),
                         ("moyen", True, False))
        rep = self.make_jsonrpc_request(url + "/signer", {"name": "Client", "signature": self.SIGNATURE})
        self.assertTrue(rep.get("force_refresh"), rep)
        bon = ticket.bon_intervention_ids
        self.assertEqual((bon.type_bon, bon.proprete, bon.pleine, bon.en_fonction), ("reprise", "moyen", True, False))
        self.assertIn("La propreté du congélateur", bon.texte)
        page = self.url_open(url).text
        self.assertIn("Moyen ☒", page)
        html = self.env["ir.actions.report"]._render_qweb_html(
            "suivi_machines_portail.rapport_bon_intervention", bon.ids)[0].decode()
        self.assertIn("REPRISE DES ÉQUIPEMENTS", html.upper())
        self.assertIn("☒", html)
