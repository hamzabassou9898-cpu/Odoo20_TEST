# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, freeze_time, tagged


# Periode de location obligatoire pour confirmer un contrat de location
PERIODE_TEST = (fields.Datetime.to_datetime("2026-01-01 12:00:00"), fields.Datetime.to_datetime("2027-12-31 12:00:00"))


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
        f.type_reparation = "ne_gele_pas"
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
        f = Form(self.env["machine.intervention"].with_context(**ticket._contexte_intervention()))
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

    def test_entretien_valide_deux_fois_sans_doublon(self):
        """Meme machine validee deux fois le meme jour (deux tickets) : un seul entretien fait ; la visite
        planifiee du 2e ticket est annulee."""
        tech = self._tech("tech_doublon_e")
        aujourdhui = fields.Date.context_today(self.env.user)
        tickets = self.env["helpdesk.ticket"].create([{
            "name": "Entretien %s" % i, "partner_id": self.commerce.id, "lot_id": self.lots[0].id,
            "type_demande": "entretien", "user_id": tech.id,
            "date_planifiee": fields.Datetime.now()} for i in (1, 2)])
        Intervention = self.env["machine.intervention"]
        domaine = [("lot_id", "=", self.lots[0].id), ("type", "=", "entretien"), ("state", "=", "fait")]
        avant = Intervention.search_count(domaine)
        for ticket in tickets:
            action = ticket.action_valider_entretien()
            f = Form(self.env[action["res_model"]].with_context(**action["context"]))
            f.date_entretien = aujourdhui
            f.save().action_valider()
        self.assertEqual(Intervention.search_count(domaine), avant + 1, "un seul entretien fait")
        self.assertFalse(tickets.intervention_ticket_ids.filtered(lambda i: i.state == "planifie"))

    def test_intervention_client_par_defaut(self):
        """Client de l'intervention : celui chez qui est la machine, sinon le client du ticket."""
        Intervention = self.env["machine.intervention"]
        lot = self.lots[0]
        self.assertTrue(lot.machine_client_id)
        self.assertEqual(Intervention.create({"lot_id": lot.id}).partner_id, lot.machine_client_id)
        entrepot = self.env["stock.lot"].create({"name": "SANS-CLIENT-1", "product_id": lot.product_id.id})
        ticket = self.env["helpdesk.ticket"].create({"name": "Sans client", "partner_id": self.commerce.id})
        self.assertFalse(entrepot.machine_client_id)
        interv = Intervention.create({"lot_id": entrepot.id, "ticket_id": ticket.id})
        self.assertEqual(interv.partner_id, self.commerce)
        self.assertTrue(interv.route, "la route suit le client")

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
        # Avertissement attendu (« Code client inconnu ») : capture pour ne pas salir le journal des tests
        with self.assertLogs("odoo.tests.form.onchange", "WARNING"):
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
        self.assertEqual(t._contexte_intervention()["default_lot_id"], self.lots[0].id)

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
        f = Form(self.env["machine.intervention"].with_context(**t._contexte_intervention()))
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
        f = Form(self.env["machine.intervention"].with_context(**t._contexte_intervention()))
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
        vieux = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
                                               "order_line": [(0, 0, {"product_id": self.produit.id})]})
        actuel = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        devis = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1]})
        actuel.action_confirm()
        pk = actuel.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
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

    def test_sante_du_client(self):
        Ticket = self.env["helpdesk.ticket"]
        client = self.commerce
        client.invalidate_recordset()
        self.assertEqual(client.sante_niveau, "fidele")
        self.assertGreaterEqual(client.sante_nb_machines, 2, "machines chez lui")
        for i in range(3):
            Ticket.create({"name": "Appel %s" % i, "partner_id": client.id})
        client.invalidate_recordset()
        self.assertEqual(client.sante_niveau, "surveiller")
        self.assertIn("3 appels", client.sante_raison)
        for i in range(3):
            Ticket.create({"name": "Encore %s" % i, "partner_id": client.id})
        client.invalidate_recordset()
        self.assertEqual(client.sante_niveau, "risque", "plus de 5 appels en 3 mois")
        self.assertEqual(client.sante_nb_appels, 6)
        self.assertEqual(client.sante_impayes, 0)
        contact = self.env["res.partner"].create({"name": "Personne", "parent_id": client.id})
        self.assertEqual(contact.sante_niveau, "risque", "même santé que la société")
        arch = self.env["res.partner"].get_views([(False, "form")])["views"]["form"]["arch"]
        for champ in ("sante_niveau", "sante_nb_machines", "sante_impayes", "sante_chiffre"):
            self.assertIn(champ, arch)

    def test_ajuster_un_contrat(self):
        so = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
                                            "order_line": [(0, 0, {"product_id": self.produit.id})]})
        ticket = self.env["helpdesk.ticket"].create({"name": "Ajouter 2 machines", "partner_id": self.commerce.id,
                                                     "type_demande": "ajustement"})
        with self.assertRaises(UserError):
            ticket.action_ajuster_contrat()          # devis pas encore confirme : pas un contrat
        so.action_confirm()
        action = ticket.action_ajuster_contrat()
        self.assertEqual((action["res_model"], action["res_id"], action["view_mode"]), ("sale.order", so.id, "form"))
        so2 = self.env["sale.order"].create({"partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
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
        with self.assertRaises(AssertionError):
            f.save()                       # type de reparation obligatoire pour une reparation
        f.type_reparation = "coule"
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
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": l.id})
                           for l in lots]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
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
        self.assertEqual(ticket.name, "Ne refroidit pas", "le titre écrit par Jose est gardé")
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
        autre.type_reparation = "coule"
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
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
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
        so.copy({"date_fin_location": fields.Datetime.now() + relativedelta(days=2)})
        self.assertFalse(SO._cron_tickets_reprise(), "machine pas encore livrée / délai 0 : rien")
        self.env.ref("suivi_machines_helpdesk.cron_tickets_reprise").method_direct_trigger()

    def test_bouton_creer_ticket_reprise(self):
        stock = self.env.ref("stock.stock_location_stock")
        lot = self.env["stock.lot"].create({"name": "REP-2", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
        so = self.env["sale.order"].create({
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        with self.assertRaises(UserError) as err:
            so.action_creer_tickets_reprise()
        self.assertIn("REP-2", str(err.exception), "le message explique la situation de la machine")
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
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
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0],
            "date_fin_location": fields.Datetime.now() + relativedelta(days=1),
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
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
        retour.livreur_id = retour.livreur_id or self.env.user  # technicien obligatoire pour valider
        retour.prochain_entretien = retour.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        retour.frequence_entretien = retour.frequence_entretien or "12"
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
            "partner_id": self.commerce.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0],
            "date_fin_location": fields.Datetime.now() + relativedelta(days=1),
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2}),
                           (0, 0, {"product_id": frosty.id, "product_uom_qty": 1}),
                           (0, 0, {"product_id": pompe.id, "product_uom_qty": 3})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
        pk.with_context(skip_sms=True).button_validate()
        self.assertEqual(set(lots.mapped("machine_statut")), {"chez_client"})
        ticket = self.env["sale.order"]._cron_tickets_reprise()
        self.assertEqual(len(ticket), 1, "un seul ticket pour le contrat")
        self.assertEqual(ticket.machines_reprise_ids, lots, "toutes les machines regroupées")
        self.assertIn("MULTI-A", ticket.description)
        self.assertFalse(self.env["sale.order"]._cron_tickets_reprise(), "pas de doublon")
        etape = self.env["helpdesk.stage"].search([("name", "ilike", "reprise")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Reprise de machine"})
        tech = self._tech("chauffeur_reprise_test")
        ticket.user_id = tech
        retour = self.env["stock.picking"].browse(ticket.action_ramassage()["res_id"])
        self.assertEqual(retour.livreur_id, tech, "le technicien du ticket fait le ramassage")
        self.assertEqual(ticket.stage_id, etape)
        self.assertEqual(retour.move_ids.move_line_ids.lot_id, lots, "un seul retour, chaque machine avec SON n°")
        machines = retour.move_ids.filtered("machine_lot_id")
        self.assertEqual(sorted(machines.move_line_ids.mapped("quantity")), [1, 1, 1])
        mv_pompe = retour.move_ids.filtered(lambda m: m.product_id == pompe)
        self.assertEqual((mv_pompe.product_uom_qty, mv_pompe.quantity), (3, 3), "les 3 pompes sont reprises")
        self.assertEqual(ticket.action_ramassage()["res_id"], retour.id, "même bon de retour")
        retour.move_ids.picked = True
        retour.livreur_id = retour.livreur_id or self.env.user  # technicien obligatoire pour valider
        retour.prochain_entretien = retour.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        retour.frequence_entretien = retour.frequence_entretien or "12"
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
        f = Form(Interv.with_context(**t0._contexte_intervention()))
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
        self.assertFalse(tickets, "machine en entrepôt : pas de ticket d'entretien (seulement chez un client)")
        # Ancien ticket automatique d'une machine revenue en entrepot, pas planifie : ferme
        annule = self.env["helpdesk.stage"].create({"name": "Annulé"})
        vieux = self.env["helpdesk.ticket"].create({
            "name": "Entretien - S1", "lot_id": lot.id, "est_entretien": True, "origine_auto": "entretien",
            "date_entretien_prevu": lot.date_prochain_entretien})
        planifie = self.env["helpdesk.ticket"].create({
            "name": "Entretien - S1 planifié", "lot_id": lot.id, "est_entretien": True, "origine_auto": "entretien",
            "user_id": self.env.user.id})
        self.env["helpdesk.ticket"]._cron_tickets_entretien()
        self.assertEqual(vieux.stage_id, annule)
        self.assertNotEqual(planifie.stage_id, annule, "déjà planifié par Jose : on n'y touche pas")
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
        self.assertEqual(noms[noms.index("adresse_commerce"):noms.index("contrat_client_fin") + 1],
                         ["adresse_commerce", "contrat_client_id", "contrat_client_modele_id", "contrat_client_type",
                          "contrat_client_debut",
                          "contrat_client_fin"], "puis le contrat du client, son type et ses dates")
        self.assertNotIn("commerce_id", visibles, "client affiché une seule fois (champ natif)")
        boutons = [b.get("name") for b in arch.iter("button") if b.getparent().tag == "header"]
        self.assertNotIn("action_nouvelle_intervention", boutons, "intervention planifiée toute seule")
        self.assertIn("action_marquer_fait", boutons)
        vente = arch.xpath("//header/button[@name='action_creer_vente']")
        self.assertEqual([b.get("invisible") for b in vente], ["type_demande != 'commande' or not partner_id"],
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

    def test_type_de_reparation(self):
        """Ticket de reparation : choix a cocher (Coule, Ne gele pas...) obligatoire dans le formulaire,
        efface si le ticket change de type."""
        from lxml import etree
        self.assertEqual([v for v, _l in self.env["helpdesk.ticket"]._fields["type_reparation"].selection],
                         ["coule", "ne_gele_pas", "ne_tourne_pas", "bruit", "gele_trop", "autre"])
        f = self._form()
        f.code_client = "TST100"
        f.type_reparation = False
        with self.assertRaises(AssertionError):
            f.save()                       # obligatoire pour une reparation
        f.type_reparation = "bruit"
        ticket = f.save()
        self.assertEqual(ticket.type_reparation, "bruit")
        # Autre type : le choix disparait du formulaire et n'est plus obligatoire
        f = Form(ticket)
        f.type_demande = "commande"
        self.assertFalse(f.type_reparation)
        f.save()
        self.assertFalse(ticket.type_reparation)
        ticket.write({"type_demande": "reparation", "type_reparation": "gele_trop"})
        ticket.type_demande = "entretien"
        self.assertFalse(ticket.type_reparation, "effacé quand le ticket n'est plus une réparation")
        # Boutons radio, visibles seulement pour une reparation
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        champ = arch.xpath("//field[@name='type_reparation']")[0]
        self.assertEqual((champ.get("widget"), champ.get("invisible")), ("radio", "type_demande != 'reparation'"))
        # Ticket sans formulaire (cree par Odoo, formulaire web) : accepte sans type de reparation
        self.env["helpdesk.ticket"].create({"name": "Web", "type_demande": "reparation"})

    def test_reparation_planifiee_toute_seule(self):
        """Réparation avec date prévue et machine : l'intervention planifiée est créée à l'enregistrement,
        suit le ticket, et « Marquer comme fait » termine tout."""
        Interv = self.env["machine.intervention"]
        tech = self.env["res.users"].create({"name": "Tech auto", "login": "tech_auto"})
        resolu = self.env["helpdesk.stage"].search([("name", "ilike", "résolu")], limit=1) or \
            self.env["helpdesk.stage"].create({"name": "Résolu"})
        f = self._form()
        f.code_client = "TST100"
        f.lot_id = self.lots[0]
        ticket = f.save()
        self.assertFalse(ticket.intervention_ticket_ids, "sans date : rien à planifier")
        self.assertEqual(ticket.statut_entretien, "a_planifier")
        quand = fields.Datetime.now() + relativedelta(days=2)
        ticket.date_planifiee = quand
        interv = ticket.intervention_ticket_ids
        self.assertEqual(len(interv), 1)
        self.assertEqual((interv.state, interv.type, interv.lot_id, interv.date, interv.partner_id),
                         ("planifie", "reparation", self.lots[0], quand, self.commerce))
        self.assertFalse(interv.user_id, "pas l'utilisateur connecté par défaut")
        self.assertIn("Ne gèle pas", interv.description)
        self.assertEqual(ticket.statut_entretien, "planifie")
        self.assertIn(interv, Interv.search([("state", "=", "planifie")]), "dans la liste des interventions planifiées")
        # Le ticket change : l'intervention suit (une seule)
        ticket.write({"user_id": tech.id, "date_planifiee": quand + relativedelta(days=1), "lot_id": self.lots[1].id})
        self.assertEqual(ticket.intervention_ticket_ids, interv)
        self.assertEqual((interv.user_id, interv.date, interv.lot_id), (tech, quand + relativedelta(days=1), self.lots[1]))
        self.assertEqual(ticket.user_id, tech, "le ticket garde son technicien")
        # Marquer comme fait
        ticket.action_marquer_fait()
        self.assertEqual((interv.state, ticket.stage_id, ticket.statut_entretien), ("fait", resolu, "fait"))
        self.assertEqual(len(ticket.intervention_ticket_ids), 1, "pas de nouvelle intervention")
        # Ticket glisse dans Resolu (ou bon signe au portail) : l'intervention est faite aussi
        autre = self.env["helpdesk.ticket"].create({
            "name": "Bruit", "partner_id": self.commerce.id, "type_demande": "reparation",
            "type_reparation": "bruit", "lot_id": self.lots[0].id, "date_planifiee": quand})
        autre.stage_id = resolu
        self.assertEqual(autre.intervention_ticket_ids.state, "fait")
        annule = self.env["helpdesk.stage"].create({"name": "Annulé"})
        dernier = self.env["helpdesk.ticket"].create({
            "name": "Annulé ensuite", "partner_id": self.commerce.id, "type_demande": "reparation",
            "type_reparation": "bruit", "lot_id": self.lots[1].id, "date_planifiee": quand})
        dernier.stage_id = annule
        self.assertEqual(dernier.intervention_ticket_ids.state, "annule")

    def test_reparation_auto_annulee_si_le_type_change(self):
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Fuite", "partner_id": self.commerce.id, "type_demande": "reparation",
            "type_reparation": "coule", "lot_id": self.lots[0].id, "date_planifiee": fields.Datetime.now()})
        interv = ticket.intervention_ticket_ids
        self.assertEqual((len(interv), interv.state), (1, "planifie"), "créée dès la création du ticket")
        ticket.type_demande = "commande"
        self.assertEqual(interv.state, "annule")
        ticket.type_demande = "remplacement"
        self.assertEqual(len(ticket.intervention_ticket_ids.filtered(lambda i: i.state == "planifie")), 1)
        self.assertEqual(ticket.intervention_ticket_ids.filtered(lambda i: i.state == "planifie").type,
                         "remplacement")
        # Sans machine : pas d'intervention (machine obligatoire), le bandeau le dit
        sans = self.env["helpdesk.ticket"].create({
            "name": "Sans machine", "partner_id": self.commerce.id, "type_demande": "reparation",
            "type_reparation": "bruit", "date_planifiee": fields.Datetime.now()})
        if not sans.lot_id:
            self.assertFalse(sans.intervention_ticket_ids)
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        self.assertTrue(arch.xpath("//div[contains(@class, 'alert-warning')][contains(., 'Date prévue')]"))

    def test_entretien_planifie_tout_seul(self):
        """Entretien : technicien + date prévue + machine -> intervention d'entretien planifiée à
        l'enregistrement ; « Marquer comme fait » ouvre la validation (prochain entretien)."""
        tech = self.env["res.users"].create({"name": "Tech entretien", "login": "tech_entretien"})
        quand = fields.Datetime.now() + relativedelta(days=1)
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Entretien M0", "partner_id": self.commerce.id, "type_demande": "entretien",
            "lot_id": self.lots[0].id, "date_planifiee": quand})
        self.assertTrue(ticket.est_entretien)
        self.assertFalse(ticket.intervention_ticket_ids, "date d'Odoo seule, sans technicien : pas encore planifié")
        ticket.user_id = tech
        interv = ticket.intervention_ticket_ids
        self.assertEqual((len(interv), interv.state, interv.type, interv.user_id, interv.date),
                         (1, "planifie", "entretien", tech, quand))
        self.assertEqual(ticket.statut_entretien, "planifie")
        # Marquer comme fait = validation de l'entretien, qui termine l'intervention planifiee (pas de doublon)
        action = ticket.action_marquer_fait()
        self.assertEqual(action["res_model"], "suivi.machines.valider.entretien")
        f = Form(self.env[action["res_model"]].with_context(**action["context"]))
        f.date_entretien = fields.Date.context_today(ticket)
        f.save().action_valider()
        self.assertEqual(ticket.intervention_ticket_ids, interv)
        self.assertEqual(interv.state, "fait")
        self.assertTrue(self.lots[0].date_prochain_entretien)
        # En-tete : un seul bouton de fin pour chaque type, plus « Valider l'entretien »
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        noms = [b.get("name") for b in arch.xpath("//header/button")]
        self.assertNotIn("action_valider_entretien", noms)
        self.assertEqual(noms.count("action_marquer_fait"), 2)
        self.assertTrue(arch.xpath("//div[contains(@class, 'alert-warning')][contains(., 'Pour planifier l')]"))

    def test_fiche_client_machines_et_boutons(self):
        """Fiche client : onglets Machines chez le client, Historique des appels, Historique d'achat
        (comme dans le ticket) ; boutons inutiles masqués."""
        from lxml import etree
        self.assertEqual(self.commerce.machine_client_ids, self.lots[:2], "les machines du commerce seulement")
        self.assertEqual(self.commerce.sante_nb_machines, 2)
        ticket = self.env["helpdesk.ticket"].create({"name": "Appel fiche", "partner_id": self.commerce.id,
                                                     "type_demande": "commande"})
        (self.commerce | self.autre_client).invalidate_recordset(["appel_client_ids"])  # calcul a l'affichage
        self.assertIn(ticket, self.commerce.appel_client_ids)
        self.assertNotIn(ticket, self.autre_client.appel_client_ids)
        arch = etree.fromstring(self.env["res.partner"].get_views([(False, "form")])["views"]["form"]["arch"])
        vue = etree.fromstring(self.env.ref("suivi_machines_helpdesk.view_partner_form_contrat_location").arch_db.encode())
        pages = [p.get("name") for p in vue.xpath("//page")]
        self.assertLess(pages.index("machines_client"), pages.index("appels_client"))
        self.assertLess(pages.index("appels_client"), pages.index("historique_achat"))
        for bouton in arch.xpath("//div[@name='button_box']/button[@name='action_schedule_meeting']"):
            self.assertEqual(bouton.get("invisible"), "1", "réunions masquées")

    def test_activite_un_mois_avant_entretien(self):
        """Entretien dans 3 semaines : ticket + activité « Planifier entretien » pour le bureau (un mois avant),
        sans l'étiquette « cette semaine » ; dans 2 mois : rien encore."""
        lot = self.lots[1]   # installee, pas encore d'entretien
        T = self.env["helpdesk.ticket"]
        lot.prochain_entretien_fixe = fields.Date.today() + relativedelta(weeks=3)
        self.assertEqual(lot.date_prochain_entretien, fields.Date.today() + relativedelta(weeks=3))
        ticket = T._cron_tickets_entretien().filtered(lambda t: t.lot_id == lot)
        self.assertEqual(len(ticket), 1, "créé un mois avant")
        self.assertFalse(ticket.tag_ids & self.env.ref("suivi_machines_helpdesk.tag_entretien_semaine"))
        self.assertTrue(ticket.activity_ids.filtered(lambda a: "entretien" in (a.summary or "").lower()))
        self.assertEqual(ticket.activity_ids[:1].date_deadline, lot.date_prochain_entretien)
        autre = self.lots[2]
        autre.prochain_entretien_fixe = fields.Date.today() + relativedelta(months=2)
        self.assertFalse(T._cron_tickets_entretien().filtered(lambda t: t.lot_id == autre), "trop tôt")

    def test_echanger_la_machine(self):
        """Machine à remplacer : ramassage de l'ancienne + livraison de la nouvelle en une seule opération ;
        l'ancien n° de série revient en inventaire, la nouvelle machine est chez le client (même contrat)."""
        lot, so, _reprise = self._location_livree("ECH-1")
        resolu = self.env["helpdesk.stage"].search([("name", "ilike", "résolu")], limit=1) \
            or self.env["helpdesk.stage"].create({"name": "Résolu"})
        stock = self.env.ref("stock.stock_location_stock")
        nouvelle = self.env["stock.lot"].create({"name": "ECH-2", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=nouvelle)
        # Cas reel : du stock du meme produit SANS n° de serie, et la machine choisie sur une etagere
        etagere = self.env["stock.location"].create({"name": "Étagère A", "location_id": stock.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1)
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, -1, lot_id=nouvelle)
        self.env["stock.quant"]._update_available_quantity(self.produit, etagere, 1, lot_id=nouvelle)
        self.assertEqual((lot.machine_statut, nouvelle.machine_statut), ("chez_client", "entrepot"))
        tech = self.env["res.users"].create({"name": "Tech échange", "login": "tech_echange"})
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Machine à changer", "partner_id": self.commerce.id, "type_demande": "remplacement",
            "lot_id": lot.id, "user_id": tech.id, "date_planifiee": fields.Datetime.now()})
        interv = ticket.intervention_ticket_ids
        self.assertEqual((interv.type, interv.state), ("remplacement", "planifie"))
        with self.assertRaisesRegex(UserError, "machine de remplacement"):
            ticket.action_echanger_machine()
        ticket.lot_remplacement_id = nouvelle
        action = ticket.action_echanger_machine()
        retour, livraison = ticket.echange_retour_id, ticket.echange_livraison_id
        self.assertEqual(action["res_id"], livraison.id)
        self.assertEqual((retour.echange_picking_id, livraison.echange_picking_id), (livraison, retour))
        self.assertEqual((retour.livreur_id, livraison.livreur_id), (tech, tech))
        self.assertEqual(retour.move_ids.move_line_ids.lot_id, lot, "l'ancienne machine revient")
        self.assertEqual(livraison.move_ids.move_line_ids.lot_id, nouvelle, "la nouvelle part")
        self.assertEqual(livraison.move_ids.move_line_ids.location_id, etagere, "prise là où elle est")
        # Echange deja cree, ligne de livraison abimee (sans n° de serie) : reparee a la validation
        livraison.move_ids.move_line_ids.lot_id = False
        self.assertTrue(livraison.prochain_entretien and livraison.frequence_entretien, "entretien repris")
        with self.assertRaises(UserError):
            ticket.action_echanger_machine()   # pas deux fois
        # Une seule operation : valider la livraison valide aussi le ramassage
        for pk in retour | livraison:
            pk.move_ids.picked = True
        livraison.with_context(skip_sms=True).button_validate()
        self.assertEqual((retour.state, livraison.state), ("done", "done"))
        self.assertEqual(lot.machine_statut, "entrepot", "n° de série revenu en inventaire")
        self.assertEqual(nouvelle.machine_statut, "chez_client", "nouvelle machine en location chez le client")
        self.assertEqual(nouvelle.machine_client_id, self.commerce)
        self.assertIn(nouvelle, so.machine_ids, "dans le même contrat")
        self.assertEqual(so.order_line.qty_delivered, 1, "toujours une machine louée")
        self.assertEqual((interv.state, interv.lot_remplacement_id), ("fait", nouvelle))
        self.assertEqual(ticket.stage_id, resolu, "ticket résolu")

    def test_ticket_assigne_va_dans_son_etape(self):
        """Ticket « Nouveau » assigné à quelqu'un (planifié) : il passe dans l'étape de son type."""
        Etape = self.env["helpdesk.stage"]
        nouveau = Etape.create({"name": "Nouveau"})
        entretien_rep = Etape.create({"name": "Entretien & Réparation"})
        remplacer = Etape.create({"name": "Machine à remplacer"})
        reprise = Etape.search([("name", "ilike", "reprise")], limit=1) or \
            Etape.create({"name": "Installation de machine / Reprise de machine"})
        tech = self.env["res.users"].create({"name": "Tech étape", "login": "tech_etape"})
        T = self.env["helpdesk.ticket"]
        cas = [("reparation", entretien_rep), ("entretien", entretien_rep), ("remplacement", remplacer),
               ("ramassage", reprise)]
        for type_demande, etape in cas:
            with self.subTest(type_demande=type_demande):
                ticket = T.create({"name": "Étape %s" % type_demande, "partner_id": self.commerce.id,
                                   "type_demande": type_demande, "stage_id": nouveau.id})
                self.assertEqual(ticket.stage_id, nouveau, "personne assigné : reste dans Nouveau")
                ticket.user_id = tech
                self.assertEqual(ticket.stage_id, etape)
        # Assigne des la creation ; un ticket deja plus loin (ex. Resolu) ne recule pas
        direct = T.create({"name": "Direct", "partner_id": self.commerce.id, "type_demande": "reparation",
                           "stage_id": nouveau.id, "user_id": tech.id})
        self.assertEqual(direct.stage_id, entretien_rep)
        resolu = Etape.search([("name", "ilike", "résolu")], limit=1) or Etape.create({"name": "Résolu"})
        fini = T.create({"name": "Fini", "partner_id": self.commerce.id, "type_demande": "reparation",
                         "stage_id": resolu.id})
        fini.user_id = tech
        self.assertEqual(fini.stage_id, resolu)
        commande = T.create({"name": "Commande", "partner_id": self.commerce.id, "type_demande": "commande",
                             "stage_id": nouveau.id, "user_id": tech.id})
        self.assertEqual(commande.stage_id, nouveau, "pas d'étape propre : on ne touche pas")


    def test_facturer_les_frais_depuis_le_ticket(self):
        """Le bon de vente des frais se fait depuis le ticket (pas depuis l'intervention)."""
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Fuite", "partner_id": self.commerce.id, "type_demande": "reparation",
            "user_id": self.env.user.id, "date_planifiee": fields.Datetime.now()})
        main_oeuvre = self.env.ref("suivi_machines.produit_frais_reparation")
        livraison = self.env.ref("suivi_machines.produit_frais_livraison")
        interv = self.env["machine.intervention"].create({
            "type": "reparation", "partner_id": self.commerce.id, "ticket_id": ticket.id, "lot_id": self.lots[0].id,
            "frais_ids": [(0, 0, {"product_id": main_oeuvre.id, "quantite": 1.5, "prix_unitaire": 85}),
                          (0, 0, {"product_id": livraison.id, "quantite": 1, "prix_unitaire": 45})]})
        action = ticket.action_facturer_frais()
        commande = self.env["sale.order"].browse(action["res_id"])
        self.assertEqual(commande.ticket_assistance_id, ticket)
        self.assertEqual(commande.partner_id, self.commerce)
        self.assertEqual(commande.amount_untaxed, 172.5, "main-d'œuvre 127,50 + livraison 45")
        self.assertEqual(interv.sale_order_id, commande)
        self.assertEqual(interv.etat_facturation, "bon_cree")
        self.assertEqual(ticket.action_facturer_frais()["res_id"], commande.id, "brouillon rouvert, pas de doublon")
        # Sans frais saisis : main-d'oeuvre + livraison proposees, a completer
        autre = self.env["helpdesk.ticket"].create({"name": "Bruit", "partner_id": self.commerce.id,
                                                    "type_demande": "reparation"})
        vide = self.env["sale.order"].browse(autre.action_facturer_frais()["res_id"])
        self.assertEqual(vide.order_line.product_id, main_oeuvre | livraison)
        # L'intervention d'un ticket n'a plus son propre bouton
        arch = self.env["machine.intervention"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("ticket_id", arch)
        arch_ticket = self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("action_facturer_frais", arch_ticket)

    def test_tickets_selon_le_type_de_contrat(self):
        """Convention : réparations couvertes (seul l'appel inutile se facture) ; propriétaire : déplacement
        + taux horaire ; le ticket l'affiche."""
        Commande, Ticket = self.env["sale.order"], self.env["helpdesk.ticket"]
        convention = self.env.ref("suivi_machines.type_contrat_convention")
        proprietaire = self.env.ref("suivi_machines.type_contrat_proprietaire")
        self.assertEqual((convention.couvre_reparations, convention.frais_appel_inutile), (True, 125))
        self.assertEqual((proprietaire.couvre_reparations, proprietaire.frais_deplacement,
                          proprietaire.taux_horaire), (False, 125, 105))
        resultats = {}
        for type_contrat in (convention, proprietaire):
            client = self.env["res.partner"].create({"name": "Client %s" % type_contrat.name,
                                                     "is_company": True})
            Commande.create({"partner_id": client.id, "type_contrat_id": type_contrat.id,
                             "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
                             "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]
                             }).action_confirm()
            ticket = Ticket.create({"name": "Fuite", "partner_id": client.id, "type_demande": "reparation"})
            self.assertEqual(ticket.contrat_client_modele_id, type_contrat)
            commande = Commande.browse(ticket.action_facturer_frais()["res_id"])
            resultats[type_contrat] = (ticket, commande)
        ticket, commande = resultats[convention]
        self.assertEqual(ticket.contrat_couverture, "couvert")
        note = ticket.message_ids.filtered(lambda m: "Contrat du client" in (m.body or ""))
        self.assertEqual(len(note), 1, "note automatique dans le ticket")
        self.assertIn("Convention slush", note.body)
        self.assertIn("couverts par le contrat", ticket.contrat_couverture_texte)
        produits = commande.order_line.filtered(lambda l: not l.display_type)
        self.assertEqual(produits.product_id, self.env.ref("suivi_machines.produit_appel_inutile"))
        self.assertEqual((produits.product_uom_qty, produits.price_unit), (0, 125), "à mettre à 1 s'il s'applique")
        self.assertEqual(commande.amount_untaxed, 0, "réparation couverte : rien à payer")
        ticket, commande = resultats[proprietaire]
        self.assertEqual(ticket.contrat_couverture, "facture")
        self.assertIn("105", ticket.contrat_couverture_texte)
        self.assertEqual(commande.order_line.mapped("price_unit"), [125, 105], "déplacement + 1 h")
        self.assertEqual(commande.amount_untaxed, 230)
        arch = Ticket.get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("contrat_couverture_texte", arch)

    def test_echange_machine_installee_sans_stock(self):
        """Machine installée chez le client sans mouvement de stock (saisie à la main) : l'échange part
        de l'emplacement Clients au lieu de planter sur un emplacement vide."""
        ancienne = self.env["stock.lot"].create({"name": "ECH-MAIN-1", "product_id": self.produit.id})
        self.env["machine.intervention"].create({
            "lot_id": ancienne.id, "type": "installation", "state": "fait", "partner_id": self.commerce.id,
            "date": fields.Datetime.now() - relativedelta(months=2)})
        self.assertEqual((ancienne.machine_client_id, ancienne.location_id), (self.commerce, ancienne.location_id.browse()))
        nouvelle = self.env["stock.lot"].create({"name": "ECH-MAIN-2", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(
            self.produit, self.env.ref("stock.stock_location_stock"), 1, lot_id=nouvelle)
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Échange machine saisie", "partner_id": self.commerce.id, "type_demande": "remplacement",
            "lot_id": ancienne.id, "user_id": self.env.user.id, "lot_remplacement_id": nouvelle.id})
        ticket.action_echanger_machine()
        retour, livraison = ticket.echange_retour_id, ticket.echange_livraison_id
        self.assertEqual(retour.location_id.usage, "customer")
        self.assertEqual(livraison.location_dest_id, retour.location_id)
        for pk in retour | livraison:
            pk.move_ids.picked = True
        livraison.with_context(skip_sms=True).button_validate()
        self.assertEqual((retour.state, livraison.state), ("done", "done"))
        self.assertEqual(ancienne.machine_statut, "entrepot", "revenue en inventaire")
        self.assertEqual(nouvelle.machine_client_id, self.commerce)

    def test_echange_machine_pas_en_stock(self):
        lot, so, _reprise = self._location_livree("ECH-3")
        absente = self.env["stock.lot"].create({"name": "ECH-4", "product_id": self.produit.id})
        ticket = self.env["helpdesk.ticket"].create({
            "name": "Échange impossible", "partner_id": self.commerce.id, "type_demande": "remplacement",
            "lot_id": lot.id, "user_id": self.env.user.id, "lot_remplacement_id": absente.id})
        with self.assertRaisesRegex(UserError, "entrepôt"):
            ticket.action_echanger_machine()
        self.assertFalse(ticket.echange_livraison_id)

    def test_choix_des_machines(self):
        """Ramassage : seulement les machines en location chez le client ; remplacement : même modèle."""
        from lxml import etree
        lot_loue, so, _reprise = self._location_livree("CHX-1")
        vendue = self.lots[0]
        ticket = self.env["helpdesk.ticket"].create({"name": "Reprise", "partner_id": self.commerce.id,
                                                     "type_demande": "reparation"})
        self.assertIn(lot_loue, ticket.machines_choix_ids)
        ticket.type_demande = "ramassage"
        self.assertEqual(ticket.machines_choix_ids.mapped("machine_statut"), ["chez_client"] * len(ticket.machines_choix_ids))
        self.assertIn(lot_loue, ticket.machines_choix_ids)
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        self.assertEqual(arch.xpath("//field[@name='lot_id']")[0].get("domain"), "[('id', 'in', machines_choix_ids)]")
        self.assertIn("('product_id', '=', machine_modele_id)",
                      self.env["helpdesk.ticket"]._fields["lot_remplacement_id"].domain)
        # Autre modele refuse
        autre_produit = self.env["product.product"].create({
            "name": "Autre modèle", "categ_id": self.produit.categ_id.id, "is_storable": True, "tracking": "serial"})
        autre = self.env["stock.lot"].create({"name": "CHX-2", "product_id": autre_produit.id})
        self.env["stock.quant"]._update_available_quantity(autre_produit, self.env.ref("stock.stock_location_stock"),
                                                           1, lot_id=autre)
        remp = self.env["helpdesk.ticket"].create({
            "name": "Remplacer", "partner_id": self.commerce.id, "type_demande": "remplacement",
            "lot_id": lot_loue.id, "user_id": self.env.user.id, "lot_remplacement_id": autre.id})
        with self.assertRaisesRegex(UserError, "même modèle"):
            remp.action_echanger_machine()
        self.assertNotIn(vendue, ticket.machines_choix_ids.filtered(lambda l: l.machine_statut != "chez_client"))

    def test_etiquette_type_dans_le_kanban(self):
        """Kanban de l'Assistance : une étiquette de couleur par type de ticket sous le titre."""
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "kanban")])["views"]["kanban"]["arch"])
        badge = arch.xpath("//templates//field[@name='type_demande'][@widget='badge']")
        self.assertTrue(badge, "étiquette du type sur la carte")
        for decoration in ("decoration-danger", "decoration-info", "decoration-warning"):
            self.assertTrue(badge[0].get(decoration), decoration)

    def test_disposition_client_a_gauche(self):
        """Fiche du ticket : client (code client...) en haut a gauche, puis equipe et planification ;
        type de ticket a droite."""
        from lxml import etree
        arch = etree.fromstring(self.env["helpdesk.ticket"].get_views([(False, "form")])["views"]["form"]["arch"])
        gauche = arch.xpath("//field[@name='code_client']/ancestor::group[1]")[0]
        droite = arch.xpath("//field[@name='type_demande']/ancestor::group[1]")[0]
        self.assertIsNot(gauche, droite)
        self.assertTrue(gauche.xpath(".//field[@name='user_id']"), "assigne et planification sous le client")
        self.assertIs(gauche.getnext(), droite, "client a gauche, type a droite")
        noms = [n.get("name") for n in gauche.iter("field")]
        self.assertLess(noms.index("code_client"), noms.index("user_id"))
