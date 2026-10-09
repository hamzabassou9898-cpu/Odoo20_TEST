# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPilotage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, skip_sms=True))
        cls.client = cls.env["res.partner"].create({"name": "Client pilotage", "ref": "PIL1"})
        categ = cls.env["product.category"].create({"name": "Machines (pilotage)", "suivi_machine": True})
        cls.produit = cls.env["product.product"].create({
            "name": "Machine pilotage", "categ_id": categ.id, "is_storable": True, "tracking": "serial"})
        cls.lot = cls.env["stock.lot"].create({"name": "PIL-1", "product_id": cls.produit.id})
        Interv = cls.env["machine.intervention"]
        Interv.create({"lot_id": cls.lot.id, "type": "installation", "state": "fait", "partner_id": cls.client.id})
        Interv.create({"lot_id": cls.lot.id, "type": "entretien", "state": "fait", "partner_id": cls.client.id,
                       "date": fields.Datetime.now() - relativedelta(months=13)})
        Interv.create({"lot_id": cls.lot.id, "type": "bris", "partner_id": cls.client.id,
                       "frais_ids": [(0, 0, {"product_id": cls.produit.id, "prix_unitaire": 80})]})

    def _ind(self, code):
        return self.env.ref("suivi_machines_pilotage.indicateur_" + code)

    def test_compteurs(self):
        self.assertGreaterEqual(self._ind("entretien_retard").valeur, 1)
        self.assertGreaterEqual(self._ind("bris_mois").valeur, 1)
        facturer = self._ind("a_facturer")
        self.assertGreaterEqual(facturer.valeur, 1)
        self.assertIn("Total", facturer.sous_titre)

    def test_appels_ouverts(self):
        avant = self._ind("appels_ouverts").valeur
        self.env["helpdesk.ticket"].create({"name": "Ne gèle pas", "code_client": "PIL1"})
        self._ind("appels_ouverts").invalidate_recordset()
        self.assertEqual(self._ind("appels_ouverts").valeur, avant + 1, "un appel sans étape est ouvert")

    def test_toutes_les_cartes_et_vues(self):
        indicateurs = self.env["pilotage.indicateur"].search([])
        self.assertGreaterEqual(len(indicateurs), 18)
        indicateurs.mapped("valeur")
        for ind in indicateurs:
            action = ind.action_ouvrir()
            self.assertEqual(action["type"], "ir.actions.act_window", ind.code)
            Model = self.env[action["res_model"]]
            Model.search_count(eval(action["domain"]) if isinstance(action["domain"], str) else action["domain"] or [])
            vues = [(v, m) for v, m in action["views"]]
            Model.get_views(vues + [(action.get("search_view_id") and action["search_view_id"][0], "search")])
        self.env["pilotage.indicateur"].get_views([(False, "kanban")])

    def test_menu_reserve_au_groupe(self):
        menu = self.env.ref("suivi_machines_pilotage.menu_pilotage_root")
        groupe = self.env.ref("suivi_machines_pilotage.group_pilotage")
        self.assertIn(groupe, menu.group_ids)
        self.assertIn(self.env.ref("base.user_admin"), groupe.user_ids)


@tagged("post_install", "-at_install")
class TestPortailLivreurs(TransactionCase):

    def test_portail(self):
        env = self.env(context=dict(self.env.context, tracking_disable=True, skip_sms=True))
        client = env["res.partner"].create({"name": "Camping test", "street": "1 rue", "city": "Québec"})
        categ = env["product.category"].create({"name": "Mach portail", "suivi_machine": True})
        prod = env["product.product"].create({"name": "F100 p", "categ_id": categ.id, "is_storable": True,
                                              "tracking": "serial"})
        pompe = env["product.product"].create({"name": "Pompe p", "is_storable": True})
        stock = env.ref("stock.stock_location_stock")
        lot = env["stock.lot"].create({"name": "P-1", "ref": "F900", "product_id": prod.id})
        env["stock.quant"]._update_available_quantity(prod, stock, 1, lot_id=lot)
        env["stock.quant"]._update_available_quantity(pompe, stock, 5)
        livreur_a = env["res.users"].create({"name": "Livreur A", "login": "livreur_a_test"})
        so = env["sale.order"].create({"partner_id": client.id, "type_commande": "location", "order_line": [
            (0, 0, {"product_id": prod.id, "product_uom_qty": 1, "machine_lot_id": lot.id}),
            (0, 0, {"product_id": pompe.id, "product_uom_qty": 2})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.livreur_id = livreur_a
        self.assertEqual(pk.type_tournee, "livraison")
        self.assertIn("F900 (P-1)", pk.machines_tournee)
        self.assertIn("2 × Pompe p", pk.accessoires_tournee)
        self.assertTrue(pk.date_tournee)
        action = env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_portail_livreurs")
        domaine = eval(action["domain"])
        self.assertIn(pk, env["stock.picking"].search(domaine))
        env["stock.picking"].get_views([(False, "kanban"), (False, "search")] if False else
                                       [(env.ref("suivi_machines_pilotage.view_portail_livreurs_kanban").id, "kanban"),
                                        (env.ref("suivi_machines_pilotage.view_portail_livreurs_search").id, "search")])

        # Portail techniciens : livraison + ticket + intervention planifiee, dans une seule vue
        Tache = env["portail.tache"]
        tache_pk = Tache.search([("picking_id", "=", pk.id)])
        self.assertEqual((tache_pk.type_tache, tache_pk.technicien_id), ("livraison", livreur_a))
        self.assertIn("F900 (P-1)", tache_pk.machines)
        ticket = env["helpdesk.ticket"].create({"name": "Ne refroidit pas", "partner_id": client.id,
                                                "lot_id": lot.id, "user_id": livreur_a.id})
        interv = env["machine.intervention"].create({"lot_id": lot.id, "type": "reparation",
                                                     "partner_id": client.id, "user_id": livreur_a.id})
        taches = Tache.search([("technicien_id", "=", livreur_a.id)])
        self.assertEqual(set(taches.mapped("type_tache")), {"livraison", "reparation"})
        self.assertEqual(len(taches), 3)
        tache_ticket = taches.filtered(lambda t: t.ticket_id == ticket)
        self.assertIn("1 rue", tache_ticket.route)
        etiquette = env["helpdesk.tag"].create({"name": "Ne refroidit pas", "color": 1})
        ticket.tag_ids = etiquette
        Tache.invalidate_model()
        self.assertEqual(tache_ticket.tag_ids, etiquette)
        self.assertEqual(tache_ticket.action_ouvrir()["res_model"], "helpdesk.ticket")
        # Glisser vers un autre technicien : le document d'origine change
        tech_b = env["res.users"].create({"name": "Tech B", "login": "tech_b_test"})
        taches.write({"technicien_id": tech_b.id})
        self.assertEqual((pk.livreur_id, ticket.user_id, interv.user_id), (tech_b, tech_b, tech_b))
        self.assertEqual(len(Tache.search([("technicien_id", "=", tech_b.id)])), 3)
        # Intervention faite / ticket rattache : plus de doublon dans le portail
        interv.ticket_id = ticket
        self.assertFalse(Tache.search([("intervention_id", "=", interv.id)]))
        Tache.get_views([(False, "kanban"), (False, "list"), (False, "calendar"), (False, "form"), (False, "search")])

        # Suivi de Josef : en retard / fait
        tache_ticket = Tache.search([("ticket_id", "=", ticket.id)])
        self.assertEqual(tache_ticket.etat_suivi, "a_faire")
        ticket.date_planifiee = fields.Datetime.now() - relativedelta(days=2)
        Tache.invalidate_model()
        self.assertEqual(Tache.search([("ticket_id", "=", ticket.id)]).etat_suivi, "en_retard")
        etape = env["helpdesk.stage"].create({"name": "Résolu"})
        ticket.stage_id = etape
        Tache.invalidate_model()
        tache_ticket = Tache.search([("ticket_id", "=", ticket.id)])
        self.assertEqual((tache_ticket.etat_suivi, tache_ticket.a_faire), ("fait", False),
                         "ticket résolu : reste visible pour le suivi, en vert")

        # Ma journee : le technicien voit ses taches, sans pouvoir les reassigner
        tech_b.group_ids = [(4, env.ref("suivi_machines_pilotage.group_technicien").id)]
        taches_b = Tache.with_user(tech_b).search([("technicien_id", "=", tech_b.id)])
        self.assertEqual(len(taches_b), 2, "transfert + ticket (l'intervention est rattachée au ticket)")
        self.assertTrue(taches_b.mapped("route"), "adresse lue même sans droits sur les documents")
        with self.assertRaises(UserError):
            taches_b.write({"technicien_id": livreur_a.id})
        action = env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_ma_journee")
        self.assertIn("uid", action["domain"])
