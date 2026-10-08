# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import Form, TransactionCase, tagged


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
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=10)
        self.assertFalse(SO._cron_tickets_reprise(), "fin dans 10 jours : rien encore")
        so.date_fin_location = fields.Datetime.now() + relativedelta(days=2)
        tickets = SO._cron_tickets_reprise()
        self.assertEqual(len(tickets), 1)
        self.assertEqual((tickets.lot_id, tickets.partner_id, tickets.code_client, tickets.commande_reprise_id),
                         (lot, self.commerce, "TST100", so))
        self.assertIn("Reprise", tickets.name)
        self.assertFalse(SO._cron_tickets_reprise(), "pas de doublon")
        self.assertEqual(so.nb_tickets_reprise, 1)
        icp = self.env["ir.config_parameter"]
        (icp.set_int if hasattr(icp, "set_int") else icp.set_param)("suivi_machines_helpdesk.jours_avant_reprise", 0)
        so2 = so.copy({"date_fin_location": fields.Datetime.now() + relativedelta(days=2)})
        self.assertFalse(SO._cron_tickets_reprise(), "machine pas encore livrée / délai 0 : rien")
        self.env.ref("suivi_machines_helpdesk.cron_tickets_reprise").method_direct_trigger()

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
        self.assertEqual(groupe.xpath("./field")[-1].get("name"), "adresse_commerce",
                         "adresse commerciale : sa propre ligne, dans le groupe du téléphone")
        self.assertNotIn("commerce_id", visibles, "client affiché une seule fois (champ natif)")
        self.env["stock.lot"].get_views([(False, "form")])
