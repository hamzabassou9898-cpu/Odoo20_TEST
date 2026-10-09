# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, freeze_time, tagged


@tagged("post_install", "-at_install")
class TestTicketMachine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, skip_sms=True))
        P = cls.env["res.partner"]
        cls.banniere = P.create({"name": "Bannière Test", "is_company": True, "type": "invoice"})
        cls.commerce = P.create({"name": "Commerce Test", "parent_id": cls.banniere.id, "type": "delivery",
                                 "ref": "TST100", "street": "1 rue Test", "city": "Québec",
                                 "phone": "418 555-0000"})
        cls.personne = P.create({"name": "Personne Test", "parent_id": cls.commerce.id, "type": "contact"})
        cls.autre_client = P.create({"name": "Autre client", "ref": "TST200"})
        categ = cls.env["product.category"].create({"name": "Machines (test)", "suivi_machine": True})
        cls.produit = cls.env["product.product"].create({
            "name": "Congélateur test", "categ_id": categ.id, "is_storable": True, "tracking": "serial"})
        cls.lots = cls.env["stock.lot"].create([
            {"name": f"TST-{i}", "product_id": cls.produit.id, "ref": f"M{i}"} for i in range(3)])
        Interv = cls.env["machine.intervention"]
        # 2 machines chez le commerce, 1 chez l'autre client (installees par intervention)
        for lot, client in zip(cls.lots, (cls.commerce, cls.commerce, cls.autre_client)):
            Interv.create({"lot_id": lot.id, "type": "installation", "state": "fait", "partner_id": client.id})
        Interv.create({"lot_id": cls.lots[0].id, "type": "entretien", "state": "fait",
                       "partner_id": cls.commerce.id})

    def _form(self, **ctx):
        f = Form(self.env["helpdesk.ticket"].with_context(**ctx))
        f.name = "Ne refroidit pas"
        f.type_demande = "reparation"
        return f

    def test_code_client_remplit_le_dossier(self):
        f = self._form()
        f.code_client = "  tst100 "
        self.assertEqual(f.code_client, "TST100")
        self.assertEqual(f.partner_id, self.commerce)
        self.assertEqual(f.commercial_partner_id, self.banniere)
        self.assertEqual(f.adresse_commerce, "1 rue Test\nQuébec", "adresse sur plusieurs lignes")
        self.assertEqual(f.partner_phone, "418 555-0000", "téléphone natif rempli")
        self.assertEqual(f.nb_machines_client, 2)
        self.assertFalse(f.lot_id, "2 machines : l'utilisateur choisit")
        f.lot_id = self.lots[1]
        self.assertEqual(f.machine_modele_id, self.produit)
        self.assertEqual(f.machine_numero, "M1")
        ticket = f.save()
        self.assertEqual(ticket.lot_id, self.lots[1])
        self.assertEqual(ticket.machine_modele_id, self.produit, "le modèle reste après enregistrement")

    def test_code_client_rempli_par_le_client(self):
        """Client choisi sans passer par l'ecran (generateur, courriel...) : le code client se remplit."""
        Ticket = self.env["helpdesk.ticket"]
        self.assertEqual(Ticket.create({"name": "A", "partner_id": self.commerce.id}).code_client, "TST100")
        self.assertEqual(Ticket.create({"name": "B", "partner_id": self.personne.id}).code_client, "TST100",
                         "personne rattachée : code de son commerce")
        # Code seulement sur la banniere (societe mere)
        self.banniere.ref = "BAN1"
        sans_code = self.env["res.partner"].create({"name": "Succursale", "parent_id": self.banniere.id,
                                                    "type": "delivery"})
        self.assertEqual(Ticket.create({"name": "C", "partner_id": sans_code.id}).code_client, "BAN1")
        # Changement de client : le code suit
        ticket = Ticket.create({"name": "D", "partner_id": self.commerce.id})
        ticket.partner_id = self.autre_client
        self.assertEqual(ticket.code_client, "TST200")
        # Client sans aucun code : le code saisi est garde
        inconnu = self.env["res.partner"].create({"name": "Sans code"})
        self.assertEqual(Ticket.create({"name": "E", "partner_id": inconnu.id, "code_client": "XYZ9"}).code_client,
                         "XYZ9")
        # A l'ecran : choisir le client remplit le code
        f = self._form()
        f.partner_id = self.commerce
        self.assertEqual(f.code_client, "TST100")

    # ------------------------------------------------------------ synchronisation ticket <-> intervention
    def _tech(self, login):
        return self.env["res.users"].create({"name": login, "login": login,
                                             "group_ids": [(6, 0, [self.env.ref("base.group_user").id])]})

    def test_nouvelle_intervention_reprend_date_et_technicien(self):
        from datetime import datetime
        tech = self._tech("tech_synchro_1")
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Ne refroidit pas", "partner_id": self.commerce.id, "lot_id": self.lots[0].id,
            "user_id": tech.id, "date_planifiee": datetime(2030, 10, 10, 14, 0)})
        action = ticket.action_nouvelle_intervention()
        f = Form(self.env["machine.intervention"].with_context(**action["context"]))
        interv = f.save()
        self.assertEqual(interv.date, datetime(2030, 10, 10, 14, 0), "date prévue du ticket, pas « maintenant »")
        self.assertEqual(interv.user_id, tech, "technicien du ticket, pas l'utilisateur connecté")
        self.assertEqual(interv.ticket_id, ticket)

    def test_synchro_intervention_vers_ticket_et_retour(self):
        from datetime import datetime
        tech1, tech2 = self._tech("tech_synchro_a"), self._tech("tech_synchro_b")
        ticket = self.env["helpdesk.ticket"].create({"name": "Fuite", "partner_id": self.commerce.id,
                                                     "lot_id": self.lots[0].id})
        interv = self.env["machine.intervention"].create({
            "ticket_id": ticket.id, "lot_id": self.lots[0].id, "type": "reparation", "state": "planifie",
            "user_id": tech1.id, "date": datetime(2030, 11, 3, 9, 0)})
        # Intervention planifiee -> ticket (date prevue + technicien) : le ticket va dans sa journee
        self.assertEqual(ticket.date_planifiee, datetime(2030, 11, 3, 9, 0))
        self.assertEqual(ticket._technicien_ticket(), tech1)
        interv.write({"user_id": tech2.id, "date": datetime(2030, 11, 4, 13, 0)})
        self.assertEqual((ticket._technicien_ticket(), ticket.date_planifiee), (tech2, datetime(2030, 11, 4, 13, 0)))
        # Ticket -> intervention planifiee
        ticket.write({"date_planifiee": datetime(2030, 11, 5, 8, 0), "user_id": tech1.id})
        self.assertEqual((interv.date, interv.user_id), (datetime(2030, 11, 5, 8, 0), tech1))
        # Intervention faite : plus de synchronisation (l'historique ne bouge pas)
        interv.state = "fait"
        ticket.write({"date_planifiee": datetime(2030, 12, 1, 8, 0)})
        self.assertEqual(interv.date, datetime(2030, 11, 5, 8, 0))

    def test_valider_entretien_met_a_jour_l_intervention_planifiee(self):
        from datetime import datetime
        tech = self._tech("tech_synchro_e")
        resolu = self.env["helpdesk.stage"].create({"name": "Résolu"})
        ticket = self.env["helpdesk.ticket"].create({
            "name": "ENTRETIEN - M0", "partner_id": self.commerce.id, "lot_id": self.lots[0].id,
            "est_entretien": True, "user_id": tech.id, "date_planifiee": datetime(2020, 5, 4, 13, 0)})
        planifiee = self.env["machine.intervention"].create({
            "ticket_id": ticket.id, "lot_id": self.lots[0].id, "type": "entretien", "state": "planifie",
            "user_id": tech.id, "date": datetime(2020, 5, 4, 13, 0)})
        avant = len(ticket.intervention_ticket_ids)
        wiz_action = ticket.action_valider_entretien()
        wiz = Form(self.env["suivi.machines.valider.entretien"].with_context(**wiz_action["context"]))
        self.assertEqual(wiz.technicien_id, tech, "technicien du ticket par défaut")
        self.assertEqual(str(wiz.date_entretien), "2020-05-04", "date prévue (passée) par défaut")
        wiz.note = "Nettoyage complet"
        wiz.save().action_valider()
        self.assertEqual(len(ticket.intervention_ticket_ids), avant, "pas de doublon")
        self.assertEqual(planifiee.state, "fait")
        self.assertEqual(planifiee.description, "Nettoyage complet")
        self.assertEqual(ticket.stage_id, resolu, "le ticket ne reste pas ouvert")

    def test_une_seule_machine_choisie_automatiquement(self):
        f = self._form()
        f.code_client = "TST200"
        self.assertEqual(f.nb_machines_client, 1)
        self.assertEqual(f.lot_id, self.lots[2])
        # changement de client : la machine de l'ancien client est retiree
        f.code_client = "TST100"
        self.assertFalse(f.lot_id)

    def test_personne_rattachee(self):
        f = self._form()
        f.partner_id = self.personne
        self.assertEqual(f.code_client, "TST100")
        self.assertEqual(f.commerce_id, self.commerce)
        self.assertEqual(f.nb_machines_client, 2)

    def test_code_inconnu(self):
        f = self._form()
        f.partner_id = self.autre_client
        f.code_client = "INCONNU"
        self.assertEqual(f.partner_id, self.autre_client, "un code inconnu ne change pas le client")

    def test_code_sans_joker(self):
        client_x = self.env["res.partner"].create({"name": "X", "ref": "AB_1"})
        self.env["res.partner"].create({"name": "Y", "ref": "ABC1"})
        self.assertEqual(self.env["helpdesk.ticket"]._client_par_code("ab_1"), client_x)
        self.assertFalse(self.env["helpdesk.ticket"]._client_par_code("AB%"))

    def test_creation_par_code(self):
        t = self.env["helpdesk.ticket"].create({"name": "Par code", "code_client": "TST100"})
        self.assertEqual(t.partner_id, self.commerce)

    def test_dossier_machine(self):
        t = self.env["helpdesk.ticket"].create({"name": "x", "partner_id": self.commerce.id,
                                                "lot_id": self.lots[0].id})
        self.assertTrue(t.machine_dernier_entretien)
        self.assertEqual(len(t.machine_intervention_ids), 2)
        self.env.flush_all()
        self.assertEqual(len(t.machine_historique_ids), 2)
        self.assertEqual(t.action_fiche_machine()["res_id"], self.lots[0].id)
        nouvelle = t.action_nouvelle_intervention()
        self.assertEqual(nouvelle["context"]["default_lot_id"], self.lots[0].id)

    def test_appels_de_service(self):
        T = self.env["helpdesk.ticket"]
        t1 = T.create({"name": "1", "partner_id": self.commerce.id, "lot_id": self.lots[0].id})
        self.assertEqual(t1.nb_tickets_precedents, 0, "le ticket lui-même n'est pas compté")
        t2 = T.create({"name": "2", "partner_id": self.personne.id})
        # meme machine, mais declaree au nom d'un autre client
        t3 = T.create({"name": "3", "partner_id": self.autre_client.id, "lot_id": self.lots[0].id})
        T.create({"name": "4", "partner_id": self.autre_client.id})
        (t1 | t2 | t3).invalidate_recordset()
        self.assertEqual(t1.tickets_precedents_ids, t2 | t3)
        self.assertEqual(t2.tickets_precedents_ids, t1)
        self.assertEqual(self.lots[0].nb_tickets, 2)
        self.assertEqual(self.lots[0].action_voir_tickets()["domain"], [("lot_id", "=", self.lots[0].id)])

    def test_agent_sans_droits_inventaire(self):
        agent = self.env["res.users"].create({
            "name": "Agent", "login": "agent_test_machines",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("helpdesk.group_helpdesk_user").id])]})
        t = self.env["helpdesk.ticket"].create({"name": "x", "partner_id": self.commerce.id,
                                                "lot_id": self.lots[0].id})
        champs = {f: {} for f in ("code_client", "lot_id", "machine_modele_id", "machine_numero",
                                  "machine_dernier_entretien", "nb_machines_client", "adresse_commerce")}
        champs.update({f: {"fields": {"display_name": {}}} for f in (
            "machines_client_ids", "machine_historique_ids", "machine_intervention_ids",
            "tickets_precedents_ids")})
        t.with_user(agent).web_read(champs)
        self.env["helpdesk.ticket"].with_user(agent).get_views([(False, "form")])

    def test_intervention_depuis_ticket(self):
        t = self.env["helpdesk.ticket"].create({"name": "Fuite", "code_client": "TST100",
                                                "lot_id": self.lots[0].id})
        action = t.action_nouvelle_intervention()
        f = Form(self.env["machine.intervention"].with_context(**action["context"]))
        interv = f.save()
        self.assertEqual(interv.ticket_id, t)
        self.assertEqual(interv.lot_id, self.lots[0])
        self.assertEqual(interv.partner_id, self.commerce)
        self.assertEqual(interv.description, "Fuite")
        self.assertEqual(interv.route, "1 rue Test, Québec", "route = adresse du commerce")
        t.invalidate_recordset()
        self.assertEqual(t.nb_interventions_ticket, 1)
        self.assertEqual(t.action_voir_interventions_ticket()["res_id"], interv.id)
        self.assertEqual(self.lots[0].nb_interventions, 3, "visible aussi dans le dossier de la machine")

    def test_frais_intervention_lies_au_ticket(self):
        t = self.env["helpdesk.ticket"].create({"name": "Retour", "code_client": "TST100",
                                                "lot_id": self.lots[1].id})
        interv = self.env["machine.intervention"].create({
            "ticket_id": t.id, "lot_id": self.lots[1].id, "partner_id": self.commerce.id, "type": "ramassage",
            "frais_ids": [(0, 0, {"product_id": self.env.ref("suivi_machines.produit_frais_livraison").id,
                                  "prix_unitaire": 50})]})
        interv.action_creer_bon_commande()
        self.assertEqual(interv.sale_order_id.ticket_assistance_id, t)
        t.invalidate_recordset()
        self.assertEqual(t.nb_ventes, 1)

    def test_technicien_du_ticket(self):
        tech_a = self.env["res.users"].create({"name": "Technicien A", "login": "tech_a_test"})
        tech_b = self.env["res.users"].create({"name": "Technicien B", "login": "tech_b_test"})
        t = self.env["helpdesk.ticket"].create({"name": "Bris", "code_client": "TST100",
                                                "lot_id": self.lots[0].id})
        self.assertFalse(t.technicien_id)
        f = Form(self.env["machine.intervention"].with_context(**t.action_nouvelle_intervention()["context"]))
        f.user_id = tech_a
        i1 = f.save()
        self.assertEqual(t.technicien_id, tech_a, "le technicien choisi apparaît sur le ticket")
        i2 = self.env["machine.intervention"].create({
            "ticket_id": t.id, "lot_id": self.lots[0].id, "user_id": tech_b.id,
            "date": i1.date + relativedelta(days=1)})
        self.assertEqual(t.technicien_id, tech_b, "dernière intervention")
        i2.action_annuler()
        self.assertEqual(t.technicien_id, tech_a, "intervention annulée ignorée")
        i1.user_id = tech_b
        self.assertEqual(t.technicien_id, tech_b, "modifié depuis l'intervention")
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id, "partner_id": self.personne.id,
            "ticket_assistance_id": t.id})
        self.assertEqual(picking.technicien_id, tech_b, "technicien sur la livraison")
        self.assertEqual(picking.route, "1 rue Test, Québec", "route = adresse du commerce")
        self.env["stock.picking"].get_views([(False, "form"), (False, "list")])
        arch = self.env["helpdesk.ticket"].get_views([(False, "kanban")])["views"]["kanban"]["arch"]
        self.assertIn("technicien_id", arch)

    def test_fiche_client_contrat_actuel_et_historique(self):
        stock = self.env.ref("stock.stock_location_stock")
        lot = self.env["stock.lot"].create({"name": "CLI-1", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        vente = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "vente",
                                               "order_line": [(0, 0, {"product_id": self.produit.id})]})
        vieux = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location",
                                               "order_line": [(0, 0, {"product_id": self.produit.id})]})
        actuel = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        devis = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location"})
        actuel.action_confirm()
        pk = actuel.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        (vente | vieux).action_confirm()
        self.commerce.invalidate_recordset()
        self.assertEqual(self.commerce.contrat_location_id, actuel, "celui dont la machine est chez le client")
        self.assertEqual(set(self.commerce.historique_achat_ids.ids), {vente.id, vieux.id, actuel.id},
                         "ventes et locations confirmées (pas les devis)")
        self.assertNotIn(devis, self.commerce.historique_achat_ids)
        # Contact de la societe (ex. Nathacha) : meme contrat
        contact = self.env["res.partner"].create({"name": "Nathacha", "parent_id": self.commerce.id})
        self.assertEqual(contact.contrat_location_id, actuel)
        # Ticket : des que le client est choisi, son contrat, son type et ses dates s'affichent
        f = self._form()
        f.code_client = "TST100"
        self.assertEqual(f.contrat_client_id, actuel)
        self.assertEqual(f.contrat_client_type, "location")
        actuel.date_debut_location = fields.Datetime.now()
        actuel.date_fin_location = fields.Datetime.now() + relativedelta(years=1)
        f.code_client = "TST200"
        f.code_client = "TST100"
        self.assertEqual((f.contrat_client_debut, f.contrat_client_fin),
                         (actuel.date_debut_location, actuel.date_fin_location))
        arch = self.env["res.partner"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("contrat_location_id", arch)
        self.assertEqual(self.commerce.contrat_location_type, "location")
        self.assertIn("Historique d'achat", arch)

    def test_ajuster_un_contrat(self):
        so = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location",
                                            "order_line": [(0, 0, {"product_id": self.produit.id})]})
        ticket = self.env["helpdesk.ticket"].create({"name": "Ajouter 2 machines", "partner_id": self.commerce.id,
                                                     "type_demande": "ajustement"})
        with self.assertRaises(UserError):
            ticket.action_ajuster_contrat()          # devis pas encore confirme : pas un contrat
        so.action_confirm()
        action = ticket.action_ajuster_contrat()
        self.assertEqual((action["res_model"], action["res_id"], action["view_mode"]), ("sale.order", so.id, "form"))
        so2 = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location",
                                             "order_line": [(0, 0, {"product_id": self.produit.id})]})
        so2.action_confirm()
        action = ticket.action_ajuster_contrat()
        self.assertEqual(self.env["sale.order"].search(action["domain"]), so | so2, "plusieurs : la liste")
        self.assertFalse(ticket.statut_entretien, "rien à planifier")
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        bouton = arch.xpath("//header/button[@name='action_ajuster_contrat']")
        self.assertEqual(bouton[0].get("invisible"), "type_demande != 'ajustement' or not partner_id")

    def test_creation_rapide_avec_type(self):
        kanban = self.env["helpdesk.ticket"].get_views([(False, "kanban")])["views"]["kanban"]["arch"]
        self.assertIn('quick_create_view="suivi_machines_helpdesk.helpdesk_ticket_view_form_creation_rapide"', kanban)
        vue = self.env.ref("suivi_machines_helpdesk.helpdesk_ticket_view_form_creation_rapide")
        f = Form(self.env["helpdesk.ticket"], view=vue)
        f.name = "Fuite"
        f.partner_id = self.commerce
        with self.assertRaises(AssertionError):
            f.save()                       # type obligatoire
        f.type_demande = "reparation"
        ticket = f.save()
        self.assertEqual((ticket.type_demande, ticket.code_client), ("reparation", "TST100"),
                         "code client rempli depuis le client")

    def test_remplacement_sans_machine_refuse(self):
        from lxml import etree
        sans = self.env["res.partner"].create({"name": "Client sans machine", "ref": "TST900"})
        f = self._form()
        f.code_client = "TST900"
        f.type_demande = "remplacement"
        self.assertEqual(f.nb_machines_client, 0)
        with self.assertRaises(ValidationError):
            f.save()
        with self.assertRaises(ValidationError):
            self.env["helpdesk.ticket"].create({"name": "X", "partner_id": sans.id, "type_demande": "remplacement"})
        # Bandeau jaune dans le formulaire
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        bandeau = arch.xpath("//div[contains(@class, 'alert-warning')][contains(., '0 machine')]")
        self.assertEqual(bandeau[0].get("invisible"),
                         "type_demande != 'remplacement' or not partner_id or nb_machines_client")
        # Client avec des machines : accepte
        ok = self.env["helpdesk.ticket"].create({"name": "Y", "partner_id": self.commerce.id,
                                                 "type_demande": "remplacement"})
        self.assertGreater(ok.nb_machines_client, 0)

    def test_ramassage_a_la_main(self):
        """Type « Ramassage » : Odoo trouve le contrat de location et les machines louees ;
        le bouton Ramassage ouvre directement le bon de retour."""
        stock = self.env.ref("stock.stock_location_stock")
        lots = self.env["stock.lot"]
        for nom in ("RAM-1", "RAM-2"):
            lot = self.env["stock.lot"].create({"name": nom, "product_id": self.produit.id, "ref": nom})
            self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
            lots |= lot
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": l.id})
                           for l in lots]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        self.assertEqual(set(lots.mapped("machine_statut")), {"chez_client"})
        # Formulaire : code client + type Ramassage -> contrat et machines remplis tout seuls
        f = self._form()
        f.type_demande = "ramassage"
        f.code_client = "TST100"
        self.assertEqual(f.commande_reprise_id, so)
        self.assertEqual(set(f.machines_reprise_ids.ids), set(lots.ids))
        self.assertTrue(f.est_reprise, "boutons Ramassage / Prolonger")
        ticket = f.save()
        self.assertEqual((ticket.commande_reprise_id, ticket.machines_reprise_ids), (so, lots))
        self.assertFalse(ticket.origine_auto, "créé par une personne")
        self.assertEqual(ticket.name, "Ne refroidit pas", "le titre écrit par Josef est gardé")
        # Le cron ne renomme pas ce ticket et ne cree pas de doublon
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=2)
        self.env["sale.order"]._cron_tickets_reprise()
        self.assertEqual(ticket.name, "Ne refroidit pas")
        # Une seule machine choisie : seulement elle revient
        ticket.lot_id = lots[0]
        ticket.machines_reprise_ids = lots[0]
        action = ticket.action_ramassage()
        retour = self.env["stock.picking"].browse(action["res_id"])
        self.assertEqual((action["res_model"], action["target"]), ("stock.picking", "current"),
                         "ouvre directement le bon de retour")
        self.assertEqual(retour.move_ids.machine_lot_id, lots[0])
        self.assertEqual(retour.location_dest_id.usage, "internal")
        self.assertEqual(retour.ticket_assistance_id, ticket)
        self.assertEqual(ticket.action_ramassage()["res_id"], retour.id, "pas de doublon")
        # Plus un ramassage : le contrat est detache
        autre = self._form()
        autre.code_client = "TST100"
        autre.type_demande = "ramassage"
        self.assertEqual(autre.commande_reprise_id, so)
        autre.type_demande = "reparation"
        self.assertFalse(autre.commande_reprise_id)
        self.assertFalse(autre.est_reprise)
        t2 = autre.save()
        t2.type_demande = "ramassage"
        self.assertEqual(t2.commande_reprise_id, so, "rempli aussi par l'ORM (écriture)")
        t2.type_demande = "reparation"
        self.assertFalse(t2.commande_reprise_id)
        # Client sans location : rien a ramasser (bandeau d'alerte)
        sans = self.env["helpdesk.ticket"].create({"name": "Rien", "partner_id": self.autre_client.id,
                                                   "type_demande": "ramassage"})
        self.assertFalse(sans.commande_reprise_id)

    def test_tickets_de_reprise(self):
        stock = self.env.ref("stock.stock_location_stock")
        lot = self.env["stock.lot"].create({"name": "REP-1", "product_id": self.produit.id, "ref": "R1"})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        self.assertEqual(lot.machine_statut, "chez_client")
        SO = self.env["sale.order"]
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=40)
        self.assertFalse(SO._cron_tickets_reprise(), "fin dans 40 jours : rien encore")
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=29)
        self.assertEqual(len(SO._cron_tickets_reprise()), 1, "fin dans 29 jours : ticket (délai 30 jours)")
        so.ticket_reprise_ids.unlink()
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=2)
        etape = self.env["helpdesk.stage"].search([("name", "=ilike", "reprise de machine")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Reprise de machine"})
        tickets = SO._cron_tickets_reprise()
        self.assertEqual(tickets.stage_id, etape, "ticket placé dans l'étape Reprise de machine")
        activite = tickets.activity_ids
        self.assertEqual(len(activite), 1)
        self.assertEqual((activite.summary, activite.user_id, activite.activity_type_id),
                         ("Planifier ramassage de machine", self.env.ref("base.user_admin"),
                          self.env.ref("mail.mail_activity_data_todo")))
        self.assertEqual(activite.date_deadline, so.date_fin_location.date())
        self.assertEqual(len(tickets), 1)
        self.assertEqual((tickets.lot_id, tickets.partner_id, tickets.code_client, tickets.commande_reprise_id),
                         (lot, self.commerce, "TST100", so))
        self.assertEqual((tickets.type_demande, tickets.origine_auto), ("ramassage", "reprise"), "créé par Odoo")
        self.assertIn("Reprise", tickets.name)
        self.assertFalse(SO._cron_tickets_reprise(), "pas de doublon")
        self.assertEqual(so.nb_tickets_reprise, 1)
        icp = self.env["ir.config_parameter"]
        (icp.set_int if hasattr(icp, "set_int") else icp.set_param)("suivi_machines_helpdesk.jours_avant_reprise", 0)
        so2 = so.copy({"date_fin_location": fields.Datetime.now() + relativedelta(days=2)})
        self.assertFalse(SO._cron_tickets_reprise(), "machine pas encore livrée / délai 0 : rien")
        self.env.ref("suivi_machines_helpdesk.cron_tickets_reprise").method_direct_trigger()

    def test_bouton_creer_ticket_reprise(self):
        from odoo.exceptions import UserError, ValidationError
        stock = self.env.ref("stock.stock_location_stock")
        lot = self.env["stock.lot"].create({"name": "REP-2", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        with self.assertRaises(UserError) as err:
            so.action_creer_tickets_reprise()
        self.assertIn("REP-2", str(err.exception), "le message explique la situation de la machine")
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        action = so.action_creer_tickets_reprise()
        ticket = self.env["helpdesk.ticket"].browse(action["res_id"])
        self.assertEqual((ticket.lot_id, ticket.commande_reprise_id), (lot, so),
                         "créé tout de suite, même sans date de fin proche")
        self.assertEqual(so.action_creer_tickets_reprise()["domain"], [("commande_reprise_id", "=", so.id)],
                         "2e clic : ouvre le ticket existant")

    def _location_livree(self, nom):
        stock = self.env.ref("stock.stock_location_stock")
        lot = self.env["stock.lot"].create({"name": nom, "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "date_fin_location": fields.Datetime.now() + relativedelta(days=1),
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        ticket = self.env["helpdesk.ticket"].browse(so.action_creer_tickets_reprise()["res_id"])
        return lot, so, ticket

    def test_ramassage_depuis_ticket(self):
        lot, so, ticket = self._location_livree("RAM-1")
        self.assertTrue(ticket.est_reprise)
        etape = self.env["helpdesk.stage"].search([("name", "ilike", "reprise")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Reprise de machine"})
        nouveau = self.env["helpdesk.stage"].create({"name": "Nouveau test"})
        ticket.stage_id = nouveau
        action = ticket.action_ramassage()
        self.assertEqual(ticket.stage_id, etape, "Ramassage : le ticket glisse vers Reprise de machine")
        retour = self.env["stock.picking"].browse(action["res_id"])
        self.assertEqual(retour.ticket_assistance_id, ticket)
        self.assertEqual(retour.move_ids.move_line_ids.lot_id, lot, "la machine du ticket est indiquée")
        self.assertEqual(ticket.action_ramassage()["res_id"], retour.id, "2e clic : même bon de retour")
        livreur = self.env["res.users"].create({"name": "Livreur R", "login": "livreur_r"})
        retour.livreur_id = livreur
        retour.move_ids.picked = True
        retour.with_context(skip_sms=True).button_validate()
        self.assertEqual(retour.state, "done")
        self.assertEqual(lot.machine_statut, "entrepot")
        interv = lot.intervention_ids.filtered(lambda i: i.type == "ramassage")
        self.assertEqual((interv.ticket_id, interv.user_id), (ticket, livreur), "intervention liée au ticket")

    def test_ramassage_plusieurs_machines(self):
        stock = self.env.ref("stock.stock_location_stock")
        frosty = self.env["product.product"].create({
            "name": "Frosty test", "categ_id": self.produit.categ_id.id, "is_storable": True, "tracking": "serial"})
        lots = self.env["stock.lot"]
        for produit, nom in ((self.produit, "MULTI-A"), (self.produit, "MULTI-B"), (frosty, "MULTI-C")):
            lot = self.env["stock.lot"].create({"name": nom, "product_id": produit.id})
            self.env["stock.quant"]._update_available_quantity(produit, stock, 1, lot_id=lot)
            lots |= lot
        pompe = self.env["product.product"].create({"name": "Pompe test", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(pompe, stock, 10)
        # une ligne de 2 machines (sans n° sur la ligne) + une autre ligne + 3 pompes (accessoire)
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location",
            "date_fin_location": fields.Datetime.now() + relativedelta(days=1),
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2}),
                           (0, 0, {"product_id": frosty.id, "product_uom_qty": 1}),
                           (0, 0, {"product_id": pompe.id, "product_uom_qty": 3})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.with_context(skip_sms=True).button_validate()
        self.assertEqual(set(lots.mapped("machine_statut")), {"chez_client"})
        ticket = self.env["sale.order"]._cron_tickets_reprise()
        self.assertEqual(len(ticket), 1, "un seul ticket pour le contrat")
        self.assertEqual(ticket.machines_reprise_ids, lots, "toutes les machines regroupées")
        self.assertIn("MULTI-A", ticket.description)
        self.assertFalse(self.env["sale.order"]._cron_tickets_reprise(), "pas de doublon")
        etape = self.env["helpdesk.stage"].search([("name", "ilike", "reprise")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Reprise de machine"})
        retour = self.env["stock.picking"].browse(ticket.action_ramassage()["res_id"])
        self.assertEqual(ticket.stage_id, etape)
        self.assertEqual(retour.move_ids.move_line_ids.lot_id, lots, "un seul retour, chaque machine avec SON n°")
        machines = retour.move_ids.filtered("machine_lot_id")
        self.assertEqual(sorted(machines.move_line_ids.mapped("quantity")), [1, 1, 1])
        mv_pompe = retour.move_ids.filtered(lambda m: m.product_id == pompe)
        self.assertEqual((mv_pompe.product_uom_qty, mv_pompe.quantity), (3, 3), "les 3 pompes sont reprises")
        self.assertEqual(ticket.action_ramassage()["res_id"], retour.id, "même bon de retour")
        retour.move_ids.picked = True
        retour.with_context(skip_sms=True).button_validate()
        self.assertEqual(retour.state, "done")
        self.assertEqual(set(lots.mapped("machine_statut")), {"entrepot"})
        for lot in lots:
            interv = lot.intervention_ids.filtered(lambda i: i.type == "ramassage")
            self.assertEqual(interv.ticket_id, ticket, "intervention liée au ticket du contrat")

    def test_actions_planifiees_declenchees(self):
        Trigger = self.env["ir.cron.trigger"]
        reprise = self.env.ref("suivi_machines_helpdesk.cron_tickets_reprise")
        entretien = self.env.ref("suivi_machines_helpdesk.cron_tickets_entretien")
        avant_r = Trigger.search_count([("cron_id", "=", reprise.id)])
        avant_e = Trigger.search_count([("cron_id", "=", entretien.id)])
        self.env["machine.intervention"].create({"lot_id": self.lots[0].id, "type": "entretien", "state": "fait"})
        self.assertGreater(Trigger.search_count([("cron_id", "=", entretien.id)]), avant_e,
                           "intervention : vérification des entretiens relancée")
        lot, so, ticket = self._location_livree("TRIG-1")
        self.assertGreater(Trigger.search_count([("cron_id", "=", reprise.id)]), avant_r,
                           "livraison / date de fin : vérification des reprises relancée")

    def test_prolonger_location(self):
        lot, so, ticket = self._location_livree("PRO-1")
        resolu = self.env["helpdesk.stage"].search([("name", "=ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        ancienne = so.date_fin_location
        f = Form(self.env["suivi.machines.prolonger.location"].with_context(**ticket.action_prolonger_location()["context"]))
        self.assertEqual(f.nouvelle_date_fin, ancienne + relativedelta(months=1), "proposé : +1 mois")
        f.nouvelle_date_fin = ancienne + relativedelta(days=30)
        f.save().action_prolonger()
        self.assertEqual(so.date_fin_location, ancienne + relativedelta(days=30))
        self.assertEqual(ticket.stage_id, resolu)
        self.assertFalse(ticket.activity_ids, "activité Planifier ramassage terminée")
        # a l'approche de la nouvelle date : nouveau ticket de reprise
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=2)
        nouveau = self.env["sale.order"]._cron_tickets_reprise().filtered(lambda t: t.commande_reprise_id == so)
        self.assertEqual(len(nouveau), 1)
        self.assertNotEqual(nouveau, ticket)
        with self.assertRaises(Exception):
            f2 = Form(self.env["suivi.machines.prolonger.location"].with_context(default_ticket_id=nouveau.id))
            f2.nouvelle_date_fin = so.date_fin_location - relativedelta(days=5)
            f2.save().action_prolonger()

    def test_tickets_entretien(self):
        T = self.env["helpdesk.ticket"]
        retard = self.env.ref("suivi_machines_helpdesk.tag_entretien_retard")
        semaine = self.env.ref("suivi_machines_helpdesk.tag_entretien_semaine")
        aujourdhui = fields.Date.context_today(T)
        Interv = self.env["machine.intervention"]
        # lots[0] : dernier entretien il y a 12 mois + 3 jours -> en retard
        Interv.search([("lot_id", "=", self.lots[0].id), ("type", "=", "entretien")]).date = \
            fields.Datetime.now() - relativedelta(months=12, days=3)
        # lots[1] : dernier entretien il y a 12 mois - 4 jours -> du dans 4 jours (cette semaine)
        Interv.create({"lot_id": self.lots[1].id, "type": "entretien", "state": "fait",
                       "date": fields.Datetime.now() - relativedelta(months=12, days=-4)})
        # lots[2] : entretien fait il y a 2 mois -> rien
        Interv.create({"lot_id": self.lots[2].id, "type": "entretien", "state": "fait",
                       "date": fields.Datetime.now() - relativedelta(months=2)})
        action = T._action_verifier_entretiens()
        self.assertIn("2 ticket(s)", action["params"]["message"])
        tickets = T.search([("est_entretien", "=", True)])
        self.assertEqual(set(tickets.lot_id.ids), {self.lots[0].id, self.lots[1].id})
        t0 = tickets.filtered(lambda t: t.lot_id == self.lots[0])
        t1 = tickets.filtered(lambda t: t.lot_id == self.lots[1])
        self.assertEqual(t0.tag_ids, retard)
        self.assertEqual(t1.tag_ids, semaine)
        self.assertEqual((t0.partner_id, t0.code_client), (self.commerce, "TST100"))
        self.assertTrue(t0.est_entretien)
        self.assertEqual((t0.type_demande, t0.origine_auto, t0.statut_entretien),
                         ("entretien", "entretien", "a_planifier"), "créé par Odoo, à planifier")
        self.assertEqual(t0.name, "Entretien - M0 - Commerce Test", "chez le client : nom du client")
        self.assertEqual(t0.activity_ids.summary, "Planifier entretien")
        self.assertFalse(T._cron_tickets_entretien(), "pas de doublon")
        # le temps passe (6 jours) : « cette semaine » devient « en retard »
        with freeze_time(fields.Datetime.now() + relativedelta(days=6)):
            T._cron_tickets_entretien()
        self.assertEqual(t1.tag_ids, retard, "dépassé : étiquette en retard")
        # entretien fait depuis le ticket : etiquettes retirees, nouvelle echeance dans 12 mois
        f = Form(Interv.with_context(**t0.action_nouvelle_intervention()["context"]))
        self.assertEqual(f.type, "entretien")
        f.save().action_fait()
        T._cron_tickets_entretien()
        self.assertFalse(t0.tag_ids & (retard | semaine), "entretien fait : plus d'étiquette")
        self.assertGreater(self.lots[0].date_prochain_entretien, aujourdhui + relativedelta(months=11))

    def test_valider_entretien(self):
        T = self.env["helpdesk.ticket"]
        Interv = self.env["machine.intervention"]
        Interv.search([("lot_id", "=", self.lots[0].id), ("type", "=", "entretien")]).date = \
            fields.Datetime.now() - relativedelta(months=13)
        ticket = T._cron_tickets_entretien().filtered(lambda t: t.lot_id == self.lots[0])
        resolu = self.env["helpdesk.stage"].search([("name", "ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        tech = self.env["res.users"].create({"name": "Tech E", "login": "tech_e"})
        f = Form(self.env["suivi.machines.valider.entretien"].with_context(**ticket.action_valider_entretien()["context"]))
        self.assertEqual(f.frequence, "12", "fréquence actuelle de la machine")
        hier = fields.Date.context_today(T) - relativedelta(days=1)
        f.date_entretien = hier
        f.frequence = "6"
        f.technicien_id = tech
        f.note = "Nettoyage complet"
        f.save().action_valider()
        lot = self.lots[0]
        self.assertEqual(lot.intervalle_entretien, 6)
        self.assertEqual(lot.date_dernier_entretien, hier)
        self.assertEqual(lot.date_prochain_entretien, hier + relativedelta(months=6), "prochain dans 6 mois")
        interv = lot.intervention_ids.filtered(lambda i: i.ticket_id == ticket)
        self.assertEqual((interv.type, interv.state, interv.user_id), ("entretien", "fait", tech))
        self.assertFalse(ticket.tag_ids)
        self.assertEqual(ticket.stage_id, resolu)
        self.assertFalse(ticket.activity_ids)
        self.assertEqual(ticket.technicien_id, tech)
        self.assertFalse(T._cron_tickets_entretien().filtered(lambda t: t.lot_id == lot), "rien avant 6 mois")
        with self.assertRaises(Exception):
            f2 = Form(self.env["suivi.machines.valider.entretien"].with_context(default_ticket_id=ticket.id))
            f2.date_entretien = fields.Date.context_today(T) + relativedelta(days=3)
            f2.save().action_valider()

    def test_entretien_machine_en_entrepot(self):
        lot = self.env["stock.lot"].create({"name": "ENT-STOCK", "product_id": self.produit.id, "ref": "S1"})
        stock = self.env.ref("stock.stock_location_stock")
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        self.env["machine.intervention"].create({
            "lot_id": lot.id, "type": "entretien", "state": "fait",
            "date": fields.Datetime.now() - relativedelta(months=13)})
        self.assertFalse(lot.machine_client_id)
        tickets = self.env["helpdesk.ticket"]._cron_tickets_entretien().filtered(lambda t: t.lot_id == lot)
        self.assertEqual(len(tickets), 1, "machine en entrepôt en retard : ticket aussi")
        self.assertEqual(tickets.name, "Entretien - S1 - En entrepôt (%s)" % stock.display_name)
        self.assertEqual(tickets.machine_emplacement_id, stock)
        self.assertEqual(tickets.tag_ids, self.env.ref("suivi_machines_helpdesk.tag_entretien_retard"))
        hs = self.env["stock.lot"].create({"name": "ENT-HS", "product_id": self.produit.id,
                                           "machine_etat": "hors_service"})
        self.env["machine.intervention"].create({
            "lot_id": hs.id, "type": "entretien", "state": "fait",
            "date": fields.Datetime.now() - relativedelta(months=13)})
        self.assertFalse(self.env["helpdesk.ticket"]._cron_tickets_entretien().filtered(lambda t: t.lot_id == hs),
                         "hors service : pas de ticket")

    def test_route_personne(self):
        interv = self.env["machine.intervention"].create({"lot_id": self.lots[0].id,
                                                          "partner_id": self.personne.id})
        self.assertEqual(interv.route, "1 rue Test, Québec", "personne : adresse de son commerce")
        self.commerce.street = "2 rue Nouvelle"
        self.assertEqual(interv.route, "2 rue Nouvelle, Québec")

    def test_bon_de_vente_et_livraison(self):
        t = self.env["helpdesk.ticket"].create({"name": "Pièce", "code_client": "TST100"})
        piece = self.env["product.product"].create({"name": "Pièce test", "is_storable": True})
        f = Form(self.env["sale.order"].with_context(**t.action_creer_vente()["context"]))
        self.assertEqual(f.partner_id, self.commerce)
        self.assertEqual(f.type_commande, "vente")
        with f.order_line.new() as ligne:
            ligne.product_id = piece
        so = f.save()
        self.assertEqual(so.ticket_assistance_id, t)
        self.assertEqual(so.origin, "Pièce")
        so.action_confirm()
        self.assertEqual(so.picking_ids.ticket_assistance_id, t, "la livraison garde le lien du ticket")
        f = Form(self.env["stock.picking"].with_context(**t.action_creer_livraison()["context"]))
        with f.move_ids.new() as m:
            m.product_id = piece
            m.product_uom_qty = 1
        directe = f.save()
        self.assertEqual(directe.picking_type_id.code, "outgoing")
        self.assertEqual(directe.partner_id, self.commerce)
        t.invalidate_recordset()
        self.assertEqual((t.nb_ventes, t.nb_livraisons), (1, 2))
        self.assertEqual(t.action_voir_ventes()["res_id"], so.id)
        self.assertEqual(set(t.action_voir_livraisons()["domain"][0][2]), set((so.picking_ids | directe).ids))

    def test_vues(self):
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        visibles = [f.get("name") for f in arch.iter("field") if f.get("invisible") not in ("1", "True")
                    and not [p for p in f.iterancestors() if p.tag in ("list", "kanban")]]
        for champ in ("partner_id", "partner_phone", "adresse_commerce", "code_client", "lot_id"):
            self.assertEqual(visibles.count(champ), 1, f"{champ} affiché une seule fois")
        champ_tel = arch.xpath("//field[@name='partner_phone']")[0]
        groupe = next(champ_tel.iterancestors("group"))
        noms = [f.get("name") for f in groupe.xpath("./field") if f.get("invisible") not in ("1", "True")]
        self.assertIn("adresse_commerce", noms, "adresse commerciale : sa propre ligne, dans le groupe du téléphone")
        self.assertEqual(noms[noms.index("adresse_commerce"):],
                         ["adresse_commerce", "contrat_client_id", "contrat_client_type", "contrat_client_debut",
                          "contrat_client_fin"], "puis le contrat du client, son type et ses dates")
        self.assertNotIn("commerce_id", visibles, "client affiché une seule fois (champ natif)")
        boutons = [b.get("name") for b in arch.iter("button") if b.getparent().tag == "header"]
        self.assertIn("action_nouvelle_intervention", boutons)
        vente = arch.xpath("//header/button[@name='action_creer_vente']")
        self.assertEqual(vente[0].get("invisible"), "type_demande != 'commande' or not partner_id",
                         "Bon de vente : seulement pour « Passer une commande »")
        self.assertNotIn("action_creer_livraison", boutons, "bouton Livraison retiré")
        self.env["stock.lot"].get_views([(False, "form")])

    def test_type_de_ticket_obligatoire(self):
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        champ = arch.xpath("//field[@name='type_demande'][not(@invisible='1')]")
        self.assertEqual(len(champ), 1)
        self.assertEqual(champ[0].get("required"), "1", "obligatoire à la création")
        self.assertEqual(arch.xpath("//field[@name='technicien_id'][not(ancestor::list)][not(ancestor::kanban)]"),
                         [], "un seul technicien : « Assigné à »")
        self.assertTrue(arch.xpath("//div[contains(@class, 'alert')][.//field[@name='origine_auto']] "
                                   "| //div[contains(@class, 'alert')][@invisible='not origine_auto']"),
                        "bandeau « créé automatiquement par Odoo »")
        f = Form(self.env["helpdesk.ticket"])
        f.name = "Sans type"
        f.code_client = "TST100"
        with self.assertRaises(AssertionError):
            f.save()
        f.type_demande = "remplacement"
        ticket = f.save()
        self.assertEqual((ticket.type_demande, ticket.est_entretien, ticket.origine_auto, ticket.statut_entretien),
                         ("remplacement", False, False, "a_planifier"), "créé par une personne : pas de bandeau")
        # Type « Entretien » choisi a la main : c'est un ticket d'entretien (bouton Valider, Pilotage)
        ticket.type_demande = "entretien"
        self.assertTrue(ticket.est_entretien)
        self.assertEqual(ticket.statut_entretien, "a_planifier")
        ticket.type_demande = "reparation"
        self.assertFalse(ticket.est_entretien)
        self.assertEqual(ticket.statut_entretien, "a_planifier", "une réparation se planifie aussi")
        ticket.type_demande = "commande"
        self.assertFalse(ticket.statut_entretien, "passer une commande : rien à planifier")
        for valeur in ("reparation", "ramassage", "entretien", "remplacement", "commande"):
            self.assertIn(valeur, dict(self.env["helpdesk.ticket"]._fields["type_demande"].selection))
