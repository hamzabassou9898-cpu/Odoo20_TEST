# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSuiviMachines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock = cls.env.ref("stock.warehouse0").lot_stock_id
        cls.client = cls.env["res.partner"].create({"name": "Client machines"})
        cls.categ = cls.env["product.category"].create(
            {"name": "Machines test", "suivi_machine": True})
        cls.produit = cls.env["product.product"].create({
            "name": "Machine test", "is_storable": True, "tracking": "serial",
            "categ_id": cls.categ.id,
        })
        cls.lot_a, cls.lot_b = cls.env["stock.lot"].create([
            {"name": "SN-A", "product_id": cls.produit.id},
            {"name": "SN-B", "product_id": cls.produit.id},
        ])
        for lot in (cls.lot_a, cls.lot_b):
            cls.env["stock.quant"]._update_available_quantity(cls.produit, cls.stock, 1, lot_id=lot)

    def _commande(self, lot, type_commande="vente"):
        commande = self.env["sale.order"].create({
            "partner_id": self.client.id,
            "type_commande": type_commande,
            "order_line": [fields.Command.create({
                "product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id,
            })],
        })
        commande.action_confirm()
        return commande

    def _livrer(self, commande):
        picking = commande.picking_ids
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def test_lot_en_entrepot(self):
        self.assertTrue(self.lot_a.est_machine)
        self.assertEqual(self.lot_a.machine_statut, "entrepot")
        self.assertFalse(self.lot_a.machine_client_id)

    def test_intervention_entretien(self):
        intervention = self.env["machine.intervention"].create(
            {"lot_id": self.lot_a.id, "type": "entretien"})
        self.assertNotEqual(intervention.name, "Nouveau")
        self.assertEqual(self.lot_a.nb_interventions, 1)
        self.assertFalse(self.lot_a.date_dernier_entretien)
        intervention.action_fait()
        self.assertEqual(self.lot_a.date_dernier_entretien, intervention.date.date())
        self.assertTrue(self.lot_a.date_prochain_entretien > self.lot_a.date_dernier_entretien)
        intervention.action_annuler()
        self.assertEqual(self.lot_a.nb_interventions, 0)

    def test_installation_par_intervention(self):
        intervention = self.env["machine.intervention"].create({
            "lot_id": self.lot_a.id, "type": "installation", "partner_id": self.client.id,
            "date": fields.Datetime.now() - timedelta(days=40),
        })
        intervention.action_fait()
        self.assertEqual(self.lot_a.machine_client_id, self.client)
        self.assertEqual(self.lot_a.machine_statut, "chez_client")
        self.assertTrue(self.lot_a.age_machine)

    def test_etat_machine_prioritaire(self):
        self.lot_a.machine_etat = "en_reparation"
        self.assertEqual(self.lot_a.machine_statut, "en_reparation")

    def test_vente_reserve_le_bon_numero(self):
        commande = self._commande(self.lot_b)
        self.assertEqual(commande.picking_ids.move_ids.machine_lot_id, self.lot_b)
        self.assertEqual(commande.picking_ids.move_line_ids.lot_id, self.lot_b)
        self._livrer(commande)
        self.assertEqual(self.lot_b.machine_statut, "vendue")
        self.assertEqual(self.lot_b.machine_client_id, self.client)
        self.assertEqual(self.lot_b.commande_count, 1)
        self.assertEqual(self.lot_a.machine_statut, "entrepot")

    def test_location_puis_changement_de_type(self):
        commande = self._commande(self.lot_a, "location")
        self._livrer(commande)
        self.assertEqual(self.lot_a.machine_statut, "chez_client")
        commande.type_commande = "vente"
        self.assertEqual(self.lot_a.machine_statut, "vendue")

    def test_changer_numero_apres_confirmation(self):
        commande = self._commande(self.lot_a)
        commande.order_line.machine_lot_id = self.lot_b
        self.assertEqual(commande.picking_ids.move_line_ids.lot_id, self.lot_b)

    def test_contraintes_ligne(self):
        autre_produit = self.env["product.product"].create(
            {"name": "Autre", "is_storable": True, "tracking": "serial"})
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({
                "partner_id": self.client.id,
                "order_line": [fields.Command.create({
                    "product_id": autre_produit.id, "machine_lot_id": self.lot_a.id})],
            })
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({
                "partner_id": self.client.id,
                "order_line": [fields.Command.create({
                    "product_id": self.produit.id, "product_uom_qty": 2,
                    "machine_lot_id": self.lot_a.id})],
            })

    def test_historique_et_compteurs_produit(self):
        self._livrer(self._commande(self.lot_a, "location"))
        self.env["machine.intervention"].create({"lot_id": self.lot_b.id, "type": "bris"})
        self.env.flush_all()
        historique = self.env["machine.historique"].search(
            [("lot_id", "in", (self.lot_a | self.lot_b).ids)])
        self.assertIn("mouvement", historique.mapped("type"))
        self.assertIn("bris", historique.mapped("type"))
        self.assertEqual(self.lot_b.nb_bris, 1)
        tmpl = self.produit.product_tmpl_id
        tmpl.invalidate_recordset()
        self.assertEqual(tmpl.machine_client, 1)
        self.assertEqual(tmpl.machine_entrepot, 1)
        self.assertEqual(tmpl.machine_total, 2)

    def test_boutons_et_formulaire(self):
        for methode in ("action_voir_interventions", "action_voir_bris", "action_voir_historique",
                        "action_voir_commandes", "action_voir_factures",
                        "action_nouvelle_intervention"):
            self.assertEqual(getattr(self.lot_a, methode)()["type"], "ir.actions.act_window")
        self.assertEqual(self.produit.product_tmpl_id.action_voir_machines()["domain"],
                         [("product_id.product_tmpl_id", "=", self.produit.product_tmpl_id.id)])
        with Form(self.env["machine.intervention"]) as form:
            form.lot_id = self.lot_a
            form.type = "reparation"
        self.assertEqual(form.record.product_id, self.produit)
