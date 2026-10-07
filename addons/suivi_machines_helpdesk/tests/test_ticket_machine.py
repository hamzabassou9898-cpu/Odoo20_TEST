# -*- coding: utf-8 -*-
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
        self.assertEqual(f.adresse_commerce, "1 rue Test, Québec")
        self.assertEqual(f.telephone_commerce, "418 555-0000")
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

    def test_vues(self):
        self.env["helpdesk.ticket"].get_views([(False, "form")])
        self.env["stock.lot"].get_views([(False, "form")])
