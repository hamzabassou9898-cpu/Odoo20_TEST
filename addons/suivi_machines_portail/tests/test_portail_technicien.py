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
            "description": "<p>Le client entend un bruit</p>"})
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
        self.assertTrue(tickets.filtered(lambda t: t.user_id.share), "les techniciens portail reçoivent des tickets")


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
        self.assertEqual(ouvert.user_id, self.tech_b)
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
        # Aussi en « Note » interne dans le fil du ticket, au nom du technicien, avec les fichiers
        msg_fil = self.ticket.message_ids.filtered(lambda m: m.author_id == self.tech_a.partner_id)
        self.assertEqual(len(msg_fil), 1)
        self.assertIn("Joint remplacé.", msg_fil.body)
        self.assertTrue(msg_fil.subtype_id.internal, "note interne : pas de courriel au client")
        self.assertEqual(sorted(msg_fil.attachment_ids.mapped("name")), ["photo.jpg", "rapport.pdf"])
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


    # ------------------------------------------------------------ l'admin est prevenu et fait le suivi
    def _envoyer_note(self, texte="Pièce à commander", fichiers=None):
        self.authenticate("tech_portail_a", "tech_portail_a_mdp_123")
        url = "/my/journee/tache/%s" % self._tache(self.ticket).id
        self.url_open(url + "/note", data={"csrf_token": self._csrf(url), "note": texte}, files=fichiers)
        self.env.invalidate_all()
        return self.ticket.note_technicien_ids[:1]

    def test_admin_prevenu_par_une_activite(self):
        admin = self.env.ref("base.user_admin")
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
        self.assertEqual(ind.valeur, 1)
        self.assertEqual(ind.action_ouvrir()["res_model"], "suivi.note.technicien")
        # L'admin marque l'activite « Fait » (horloge) : la note devient « Lue »
        activite.with_user(admin).action_done()
        self.assertTrue(note.lu)
        ind.invalidate_recordset()
        self.assertEqual(ind.valeur, 0)

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
        interne = self.env["res.users"].create({"name": "Josef", "login": "josef_test",
                                                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})
        self.env["ir.config_parameter"].sudo().set_int("suivi_machines_helpdesk.responsable_reprise_id", interne.id)
        note = self._envoyer_note("Pour Josef")
        self.assertEqual(note.activity_id.user_id, interne)
        self.assertEqual(note.responsable_id, interne)


    # ------------------------------------------------------------ parcours entretien complet (synchronisation)
    def test_entretien_planifie_journee_et_pilotage(self):
        resolu = self.env["helpdesk.stage"].create({"name": "Résolu"})
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
        self.assertEqual(ticket.stage_id, resolu)
        self.assertNotIn(ticket, self.env[model].search(domaine), "plus dans les entretiens à faire")
        self.env.invalidate_all()
        self.assertEqual(self.env["portail.tache"].search([("ticket_id", "=", ticket.id)]).etat_suivi, "fait")
