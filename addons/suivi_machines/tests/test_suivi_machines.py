# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSuiviMachines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, skip_sms=True))
        cls.client = cls.env["res.partner"].create({"name": "Dépanneur Test", "ref": "TST001"})
        cls.categ = cls.env["product.category"].create({"name": "Machines (test)", "suivi_machine": True})
        cls.produit = cls.env["product.product"].create({
            "name": "Congélateur test", "categ_id": cls.categ.id, "is_storable": True,
            "tracking": "serial", "list_price": 100})
        cls.stock = cls.env.ref("stock.stock_location_stock")
        cls.clients_loc = cls.env.ref("stock.stock_location_customers")
        cls.lot_a, cls.lot_b = cls.env["stock.lot"].create([
            {"name": "TST-A", "product_id": cls.produit.id, "ref": "M-A"},
            {"name": "TST-B", "product_id": cls.produit.id, "ref": "M-B"}])
        for lot in cls.lot_a | cls.lot_b:
            cls.env["stock.quant"]._update_available_quantity(cls.produit, cls.stock, 1, lot_id=lot)

    # ------------------------------------------------------------ outils
    def _valider(self, picking, lot=None):
        picking.action_assign()
        if lot:
            picking.move_ids.move_line_ids.unlink()
            picking.move_ids.write({"move_line_ids": [(0, 0, {
                "product_id": self.produit.id, "lot_id": lot.id, "quantity": 1,
                "location_id": picking.location_id.id, "location_dest_id": picking.location_dest_id.id})]})
        picking.move_ids.picked = True
        res = picking.button_validate()
        self.assertTrue(res is True or isinstance(res, dict) and picking.state == "done", res)
        self.assertEqual(picking.state, "done")

    def _livrer_sans_commande(self, lot):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id, "partner_id": self.client.id,
            "location_id": self.stock.id, "location_dest_id": self.clients_loc.id,
            "move_ids": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1,
                                 "location_id": self.stock.id, "location_dest_id": self.clients_loc.id})]})
        picking.action_confirm()
        self._valider(picking, lot)
        return picking

    def _commande(self, lot, type_commande="vente"):
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": type_commande,
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1,
                                   "machine_lot_id": lot.id})]})
        so.action_confirm()
        return so

    def _retour(self, picking, lot):
        retour = picking._create_return()
        retour.action_confirm()
        self._valider(retour, lot)
        return retour

    # ------------------------------------------------------------ statuts
    def test_entrepot(self):
        self.assertTrue(self.lot_a.est_machine)
        self.assertEqual(self.lot_a.machine_statut, "entrepot")
        self.assertFalse(self.lot_a.machine_client_id)

    def test_vente(self):
        so = self._commande(self.lot_a, "vente")
        picking = so.picking_ids
        self.assertEqual(picking.move_ids.move_line_ids.lot_id, self.lot_a, "le n° choisi est réservé")
        self._valider(picking)
        self.assertEqual(self.lot_a.machine_statut, "vendue")
        self.assertEqual(self.lot_a.machine_client_id, self.client)
        self.assertEqual(self.lot_a.date_installation, fields.Date.today())
        self.assertEqual(self.lot_b.machine_statut, "entrepot", "l'autre machine reste en stock")

    def test_location_et_changement_de_type(self):
        so = self._commande(self.lot_b, "location")
        self._valider(so.picking_ids)
        self.assertEqual(self.lot_b.machine_statut, "chez_client")
        so.type_commande = "vente"
        self.assertEqual(self.lot_b.machine_statut, "vendue", "le statut suit le type de la commande")

    def test_livraison_sans_commande(self):
        self._livrer_sans_commande(self.lot_a)
        self.assertEqual(self.lot_a.machine_statut, "livree")
        self.assertEqual(self.lot_a.machine_client_id, self.client)

    def test_retour_en_entrepot(self):
        picking = self._livrer_sans_commande(self.lot_a)
        self.env["machine.intervention"].create({
            "lot_id": self.lot_a.id, "type": "installation", "state": "fait", "partner_id": self.client.id,
            "date": fields.Datetime.now() - relativedelta(days=1)})
        self._retour(picking, self.lot_a)
        self.assertEqual(self.lot_a.machine_statut, "entrepot",
                         "revenue en stock : une ancienne installation ne la remet pas chez le client")
        self.assertFalse(self.lot_a.machine_client_id)

    def test_installation_par_intervention(self):
        # Machine sans livraison dans Odoo, installee chez le client par une intervention
        self.env["machine.intervention"].create({
            "lot_id": self.lot_b.id, "type": "installation", "state": "fait", "partner_id": self.client.id})
        self.assertEqual(self.lot_b.machine_statut, "chez_client")
        self.assertEqual(self.lot_b.machine_client_id, self.client)
        self.env["machine.intervention"].create({
            "lot_id": self.lot_b.id, "type": "ramassage", "state": "fait", "partner_id": self.client.id,
            "date": fields.Datetime.now() + relativedelta(minutes=5)})
        self.assertEqual(self.lot_b.machine_statut, "entrepot")

    def test_etat_manuel(self):
        self.lot_a.machine_etat = "hors_service"
        self.assertEqual(self.lot_a.machine_statut, "hors_service")
        self.lot_a.machine_etat = "actif"
        self.assertEqual(self.lot_a.machine_statut, "entrepot")

    # ------------------------------------------------------------ sante / interventions
    def test_entretien_et_bris(self):
        Interv = self.env["machine.intervention"]
        il_y_a_2_mois = fields.Datetime.now() - relativedelta(months=2)
        e = Interv.create({"lot_id": self.lot_a.id, "type": "entretien", "date": il_y_a_2_mois})
        self.assertTrue(e.name.startswith("INT/"))
        self.assertFalse(self.lot_a.date_dernier_entretien, "planifiée : pas encore un entretien fait")
        e.action_fait()
        self.assertEqual(self.lot_a.date_dernier_entretien, il_y_a_2_mois.date())
        self.assertEqual(self.lot_a.date_prochain_entretien, il_y_a_2_mois.date() + relativedelta(months=12))
        self.lot_a.intervalle_entretien = 6
        self.assertEqual(self.lot_a.date_prochain_entretien, il_y_a_2_mois.date() + relativedelta(months=6))
        b1 = Interv.create({"lot_id": self.lot_a.id, "type": "bris"})
        Interv.create({"lot_id": self.lot_a.id, "type": "bris"})
        self.assertEqual(self.lot_a.nb_bris, 2)
        self.assertEqual(self.lot_a.nb_interventions, 3)
        b1.action_annuler()
        self.assertEqual(self.lot_a.nb_bris, 1)
        self.assertEqual(self.lot_a.nb_interventions, 2)
        self.assertTrue(self.lot_a.age_machine)

    def test_historique(self):
        self._livrer_sans_commande(self.lot_a)
        self.env["machine.intervention"].create({"lot_id": self.lot_a.id, "type": "bris"})
        self.env.flush_all()
        types = set(self.lot_a.historique_ids.mapped("type"))
        self.assertEqual(types, {"mouvement", "bris"})

    # ------------------------------------------------------------ vente avec n° de serie
    def test_ligne_controles(self):
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({"partner_id": self.client.id, "order_line": [(0, 0, {
                "product_id": self.produit.id, "product_uom_qty": 2, "machine_lot_id": self.lot_a.id})]})
        autre = self.env["product.product"].create({"name": "Autre", "is_storable": True})
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({"partner_id": self.client.id, "order_line": [(0, 0, {
                "product_id": autre.id, "product_uom_qty": 1, "machine_lot_id": self.lot_a.id})]})
        with self.assertRaises(ValidationError):
            self.env["sale.order"].create({"partner_id": self.client.id, "order_line": [
                (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_a.id}),
                (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_a.id})]})

    def test_formulaire_commande(self):
        f = Form(self.env["sale.order"])
        f.partner_id = self.client
        self.assertEqual(f.type_commande, "vente")
        with f.order_line.new() as ligne:
            ligne.product_id = self.produit
            ligne.product_uom_qty = 3
            ligne.machine_lot_id = self.lot_b
            self.assertEqual(ligne.product_uom_qty, 1, "un n° de série = quantité 1")
        so = f.save()
        self.assertEqual(so.nb_machines, 1)
        self.assertEqual(so.action_fiches_machines()["res_id"], self.lot_b.id)
        loc = Form(self.env["sale.order"].with_context(in_rental_app=True))
        self.assertEqual(loc.type_commande, "location", "application Location : location par défaut")

    def test_changer_lot_apres_confirmation(self):
        so = self._commande(self.lot_a)
        so.order_line.machine_lot_id = self.lot_b
        self.assertEqual(so.picking_ids.move_ids.move_line_ids.lot_id, self.lot_b)

    # ------------------------------------------------------------ vue d'ensemble produit
    def test_vue_ensemble_produit(self):
        tmpl = self.produit.product_tmpl_id
        self.assertEqual((tmpl.machine_entrepot, tmpl.machine_client, tmpl.machine_vendue), (2, 0, 0))
        self._valider(self._commande(self.lot_a, "location").picking_ids)
        self._valider(self._commande(self.lot_b, "vente").picking_ids)
        tmpl.invalidate_recordset()
        self.assertEqual((tmpl.machine_entrepot, tmpl.machine_client, tmpl.machine_vendue), (0, 1, 1))
        self.assertEqual(tmpl.machine_total, 1, "en entrepôt + en location")
        self.assertEqual(tmpl.action_voir_machines()["domain"], [("product_id.product_tmpl_id", "=", tmpl.id)])

    def test_vues(self):
        for model, vues in (("stock.lot", ["form", "list", "kanban", "pivot", "graph", "search"]),
                            ("machine.intervention", ["form", "list", "calendar", "search"]),
                            ("machine.historique", ["list", "search"]),
                            ("sale.order", ["form"]), ("product.template", ["form", "kanban"]),
                            ("stock.picking", ["form", "list", "search"])):
            self.env[model].get_views([(False, v) for v in vues])

    # ------------------------------------------------------------ frais -> bon de commande -> Sage
    def test_frais_et_bon_de_commande(self):
        interv = self.env["machine.intervention"].create({
            "lot_id": self.lot_a.id, "type": "ramassage", "partner_id": self.client.id})
        self.assertEqual(interv.etat_facturation, "aucun")
        with self.assertRaises(Exception):
            interv.action_creer_bon_commande()
        depl = self.env.ref("suivi_machines.produit_frais_deplacement")
        f = Form(interv)
        with f.frais_ids.new() as ligne:
            ligne.product_id = depl
            self.assertEqual(ligne.name, depl.display_name)
            ligne.prix_unitaire = 75
        with f.frais_ids.new() as ligne:
            ligne.product_id = self.env.ref("suivi_machines.produit_frais_reparation")
            ligne.quantite = 2
            ligne.prix_unitaire = 60
        f.save()
        self.assertEqual(interv.montant_frais, 195)
        self.assertEqual(interv.etat_facturation, "a_facturer")
        action = interv.action_creer_bon_commande()
        so = interv.sale_order_id
        self.assertEqual(action["res_id"], so.id)
        self.assertEqual((so.partner_id, so.origin, so.type_commande), (self.client, interv.name, "vente"))
        self.assertEqual(so.amount_untaxed, 195)
        self.assertEqual(interv.etat_facturation, "bon_cree")
        interv.action_creer_bon_commande()
        self.assertEqual(interv.sale_order_id, so, "pas de deuxième bon de commande")
        interv.action_facture_sage()
        self.assertEqual(interv.etat_facturation, "facture")

    # ------------------------------------------------------------ livraison : n° de serie + livreur
    def test_numero_serie_choisi_a_la_livraison(self):
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "order_line": [(0, 0, {"product_id": self.produit.id,
                                                                 "product_uom_qty": 1})]})
        so.action_confirm()
        picking = so.picking_ids
        livreur = self.env["res.users"].create({"name": "Livreur test", "login": "livreur_test"})
        f = Form(picking)
        f.livreur_id = livreur
        with f.move_ids.edit(0) as ligne:
            ligne.machine_lot_id = self.lot_b
        f.save()
        self.assertEqual(picking.move_ids.move_line_ids.lot_id, self.lot_b, "la machine choisie est réservée")
        # changement d'avis : l'autre machine
        picking.move_ids.machine_lot_id = self.lot_a
        self.assertEqual(picking.move_ids.move_line_ids.lot_id, self.lot_a)
        self._valider(picking)
        self.assertEqual(picking.livreur_id, livreur)
        self.assertEqual(self.lot_a.machine_statut, "vendue")
        self.assertEqual(self.lot_b.machine_statut, "entrepot")

    def test_numero_serie_mauvais_produit_livraison(self):
        autre = self.env["product.product"].create({"name": "Autre", "is_storable": True, "tracking": "serial"})
        lot_autre = self.env["stock.lot"].create({"name": "AUTRE-1", "product_id": autre.id})
        so = self._commande(self.lot_a)
        with self.assertRaises(ValidationError):
            so.picking_ids.move_ids.machine_lot_id = lot_autre
