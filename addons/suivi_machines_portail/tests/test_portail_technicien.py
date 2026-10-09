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
            "technicien_terrain_id": cls.tech_a.id, "date_planifiee": fields.Datetime.now(),
            "description": "<p>Le client entend un bruit</p>"})
        cls.autre = env["helpdesk.ticket"].create({
            "name": "Ticket d'un autre technicien", "partner_id": cls.client.id,
            "technicien_terrain_id": cls.tech_b.id, "date_planifiee": fields.Datetime.now()})

    def _tache(self, ticket):
        return self.env["portail.tache"].search([("ticket_id", "=", ticket.id)])

    def test_tache_du_technicien_portail(self):
        tache = self._tache(self.ticket)
        self.assertEqual(tache.technicien_id, self.tech_a, "le technicien terrain passe avant l'assigné")
        # Glisser vers un technicien interne : le ticket lui est assigné, le terrain est vidé
        tache.write({"technicien_id": self.env.ref("base.user_admin").id})
        self.assertEqual((self.ticket.user_id, self.ticket.technicien_terrain_id),
                         (self.env.ref("base.user_admin"), self.env["res.users"]))
        tache = self._tache(self.ticket)
        tache.write({"technicien_id": self.tech_a.id})
        self.assertEqual(self.ticket.technicien_terrain_id, self.tech_a)

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


    def test_generateur_assigne_le_technicien_portail(self):
        categ = self.env["product.category"].create({"name": "Mach gen", "suivi_machine": True})
        prod = self.env["product.product"].create({"name": "F gen", "categ_id": categ.id, "is_storable": True,
                                                   "tracking": "serial"})
        self.env["sale.order"].create({"partner_id": self.client.id})
        self.env["stock.lot"].create({"name": "GEN-1", "product_id": prod.id})
        wiz = self.env["pilotage.donnees.test"].create({"nb_entretiens": 2, "nb_reparations": 2})
        self.assertIn(self.tech_a, wiz._techniciens())
        wiz.action_generer()
        test = self.env.ref("suivi_machines_pilotage.tag_donnees_test")
        tickets = self.env["helpdesk.ticket"].search([("tag_ids", "in", test.ids)])
        portail = tickets.filtered(lambda t: t.technicien_terrain_id)
        self.assertTrue(portail, "les techniciens portail reçoivent des tickets")
        self.assertFalse(portail.user_id.filtered("share"), "jamais un utilisateur portail en « Assigné à »")


    def test_remplacer_techniciens(self):
        Users = self.env["res.users"]
        interne = Users.create({"name": "Technicien Z", "login": "tech_z_interne",
                                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        ouvert = self.env["helpdesk.ticket"].create({"name": "Ouvert", "partner_id": self.client.id,
                                                     "user_id": interne.id})
        ferme = self.env["helpdesk.ticket"].create({"name": "Fermé", "partner_id": self.client.id,
                                                    "user_id": interne.id,
                                                    "stage_id": self.env["helpdesk.stage"].create({"name": "Résolu"}).id})
        categ = self.env["product.category"].create({"name": "Mach remp", "suivi_machine": True})
        prod = self.env["product.product"].create({"name": "F remp", "categ_id": categ.id, "is_storable": True,
                                                   "tracking": "serial"})
        lot = self.env["stock.lot"].create({"name": "REMP-1", "product_id": prod.id})
        planifiee = self.env["machine.intervention"].create({"type": "reparation", "partner_id": self.client.id,
                                                             "user_id": interne.id, "lot_id": lot.id})
        faite = self.env["machine.intervention"].create({"type": "reparation", "partner_id": self.client.id,
                                                         "user_id": interne.id, "state": "fait", "lot_id": lot.id})
        wiz = self.env["suivi.remplacer.techniciens"].create({})
        ligne = wiz.ligne_ids.filtered(lambda l: l.ancien_id == interne)
        self.assertTrue(ligne, "l'ancien compte avec des tâches est proposé")
        self.assertEqual(ligne.nb_taches, 2)
        self.assertEqual(ligne.nouveau_id, self.tech_a, "proposé dans l'ordre des techniciens portail")
        ligne.nouveau_id = self.tech_b
        wiz.action_remplacer()
        self.assertEqual((ouvert.technicien_terrain_id, ouvert.user_id), (self.tech_b, Users))
        self.assertEqual(ferme.user_id, interne, "l'historique ne bouge pas")
        self.assertEqual((planifiee.user_id, faite.user_id), (self.tech_b, interne))
        self.env["portail.tache"].invalidate_model()
        self.assertEqual(self._tache(ouvert).technicien_id, self.tech_b)


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
        self.assertFalse(self.ticket.message_ids.filtered(lambda m: m.author_id == self.tech_a.partner_id),
                         "rien dans la discussion")
        # Visible par le bureau sur la fiche du ticket (onglet)
        arch = self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("note_technicien_ids", arch)
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
        arch = self.env["stock.picking"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("note_technicien_ids", arch)
