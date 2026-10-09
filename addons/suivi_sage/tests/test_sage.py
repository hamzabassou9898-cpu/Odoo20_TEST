# -*- coding: utf-8 -*-
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.client = cls.env["res.partner"].create({"name": "Client Sage"})
        cls.fournisseur = cls.env["res.partner"].create({"name": "Fournisseur Sage"})
        cls.service = cls.env["product.product"].create({"name": "Service Sage", "type": "service",
                                                         "list_price": 100, "standard_price": 40})

    def _piece(self, move_type, partenaire):
        return self.env["account.move"].create({
            "move_type": move_type, "partner_id": partenaire.id,
            "invoice_line_ids": [(0, 0, {"product_id": self.service.id, "quantity": 1, "price_unit": 100})]})

    def test_statut_sage_clients_et_fournisseurs(self):
        for move_type, partenaire in (("out_invoice", self.client), ("out_refund", self.client),
                                      ("in_invoice", self.fournisseur), ("in_refund", self.fournisseur)):
            piece = self._piece(move_type, partenaire)
            if move_type.startswith("in_"):
                piece.invoice_date = piece.date
            self.assertEqual(piece.statut_sage, "non_concerne", "brouillon : pas encore à transférer")
            piece.action_post()
            self.assertEqual(piece.statut_sage, "a_transferer", move_type)
            piece.sage_reference = "SAGE-001"
            piece.action_transfere_sage()
            self.assertEqual(piece.statut_sage, "transfere")
            self.assertTrue(piece.sage_date)
            piece.action_annuler_transfert_sage()
            self.assertEqual(piece.statut_sage, "a_transferer")

    def test_case_a_cocher_liste(self):
        piece = self._piece("in_invoice", self.fournisseur)
        piece.invoice_date = piece.date
        piece.action_post()
        piece.write({"sage_transfere": True})   # clic dans la colonne de la liste
        self.assertEqual((piece.statut_sage, piece.sage_date), ("transfere", piece.sage_date))
        self.assertTrue(piece.sage_date)
        piece.write({"sage_transfere": False})
        self.assertFalse(piece.sage_date)
        arch = self.env["account.move"].get_views(
            [(self.env.ref("account.view_in_invoice_tree").id, "list")])["views"]["list"]["arch"]
        self.assertIn('name="sage_transfere"', arch, "colonne présente dans les factures fournisseurs")
        arch = self.env["account.move"].get_views(
            [(self.env.ref("account.view_out_invoice_tree").id, "list")])["views"]["list"]["arch"]
        self.assertIn('name="sage_transfere"', arch, "colonne présente dans les factures clients")

    def test_action_de_groupe(self):
        pieces = self._piece("out_invoice", self.client) | self._piece("out_invoice", self.client)
        pieces.action_post()
        self.env.ref("suivi_sage.action_server_transfere_sage").with_context(
            active_model="account.move", active_ids=pieces.ids).run()
        self.assertEqual(set(pieces.mapped("statut_sage")), {"transfere"})

    def test_intervention_facturee_quand_facture_transferee(self):
        categ = self.env["product.category"].create({"name": "Machines Sage", "suivi_machine": True})
        produit = self.env["product.product"].create({"name": "Machine Sage", "categ_id": categ.id,
                                                      "is_storable": True, "tracking": "serial"})
        lot = self.env["stock.lot"].create({"name": "SAGE-1", "product_id": produit.id})
        interv = self.env["machine.intervention"].create({
            "lot_id": lot.id, "type": "reparation", "partner_id": self.client.id,
            "frais_ids": [(0, 0, {"product_id": self.service.id, "prix_unitaire": 120})]})
        interv.action_creer_bon_commande()
        so = interv.sale_order_id
        so.action_confirm()
        facture = so._create_invoices()
        facture.action_post()
        self.assertEqual(interv.etat_facturation, "bon_cree")
        facture.action_transfere_sage()
        self.assertEqual(interv.etat_facturation, "facture", "facture transférée dans Sage : intervention facturée")

    def test_vues(self):
        self.env["account.move"].get_views([(False, "form"), (False, "list"), (False, "search")])
        self.env["account.move"].with_context(default_move_type="in_invoice").get_views(
            [(self.env.ref("account.view_in_invoice_tree").id, "list")])
