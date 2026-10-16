# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, tagged


# Periode de location obligatoire pour confirmer un contrat de location
PERIODE_TEST = (fields.Datetime.to_datetime("2026-01-01 12:00:00"), fields.Datetime.to_datetime("2027-12-31 12:00:00"))


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
        picking.livreur_id = picking.livreur_id or self.env.user  # technicien obligatoire pour valider
        picking.prochain_entretien = picking.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        picking.frequence_entretien = picking.frequence_entretien or "12"
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
        periode = {"date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1]} \
            if type_commande == "location" else {}
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": type_commande, **periode,
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

    def test_deux_lignes_meme_modele(self):
        so = self.env["sale.order"].create({"partner_id": self.client.id, "order_line": [
            (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_a.id}),
            (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_b.id})]})
        so.action_confirm()
        self.assertEqual(len(so.picking_ids.move_ids), 2, "pas de fusion des deux machines")
        self.assertEqual(so.picking_ids.move_ids.move_line_ids.lot_id, self.lot_a | self.lot_b)

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
        self.assertEqual(so.order_line.machine_lot_id, self.lot_b, "repris sur le bon de vente dès l'enregistrement")
        # changement d'avis : l'autre machine
        picking.move_ids.machine_lot_id = self.lot_a
        self.assertEqual(picking.move_ids.move_line_ids.lot_id, self.lot_a)
        self.assertEqual(so.order_line.machine_lot_id, self.lot_a, "changement d'avis : suivi sur le bon de vente")
        self._valider(picking)
        self.assertEqual(picking.livreur_id, livreur)
        self.assertEqual(so.order_line.machine_lot_id, self.lot_a, "n° de série livré repris sur le bon de vente")
        self.assertTrue(so.message_ids.filtered(lambda m: "TST-A" in (m.body or "")), "noté dans le bon de vente")
        self.assertEqual(self.lot_a.machine_statut, "vendue")
        self.assertEqual(self.lot_b.machine_statut, "entrepot")

    def test_numero_serie_mauvais_produit_livraison(self):
        autre = self.env["product.product"].create({"name": "Autre", "is_storable": True, "tracking": "serial"})
        lot_autre = self.env["stock.lot"].create({"name": "AUTRE-1", "product_id": autre.id})
        so = self._commande(self.lot_a)
        with self.assertRaises(ValidationError):
            so.picking_ids.move_ids.machine_lot_id = lot_autre

    # ------------------------------------------------------------ retour de location
    def test_retour_cree_intervention_ramassage(self):
        frais = self.env.ref("suivi_machines.produit_frais_livraison")
        frais.lst_price = 40
        livreur = self.env["res.users"].create({"name": "Livreur retour", "login": "livreur_retour"})
        so = self._commande(self.lot_a, "location")
        self._valider(so.picking_ids)
        self.assertEqual(self.lot_a.machine_statut, "chez_client")
        self.assertFalse(self.lot_a.intervention_ids, "la livraison ne crée pas d'intervention")
        retour = so.picking_ids._create_return()
        retour.livreur_id = livreur
        retour.action_confirm()
        self._valider(retour, self.lot_a)
        self.assertEqual(self.lot_a.machine_statut, "entrepot")
        interv = self.lot_a.intervention_ids
        self.assertEqual(len(interv), 1)
        self.assertEqual((interv.type, interv.state, interv.user_id, interv.partner_id),
                         ("ramassage", "fait", livreur, self.client))
        self.assertEqual(interv.montant_frais, 40, "frais de reprise ajoutés")
        self.assertEqual(interv.etat_facturation, "a_facturer")

    # ------------------------------------------------------------ planifier le ramassage depuis la livraison
    def _livraison_2_machines_et_pompes(self):
        pompe = self.env["product.product"].create({"name": "Pompe test", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(pompe, self.stock, 10)
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1], "order_line": [
                (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_a.id}),
                (0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_b.id}),
                (0, 0, {"product_id": pompe.id, "product_uom_qty": 3})]})
        so.action_confirm()
        livraison = so.picking_ids
        livraison.action_assign()
        livraison.move_ids.picked = True
        livraison.livreur_id = livraison.livreur_id or self.env.user  # technicien obligatoire pour valider
        livraison.prochain_entretien = livraison.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        livraison.frequence_entretien = livraison.frequence_entretien or "12"
        livraison.button_validate()
        self.assertEqual(livraison.state, "done")
        return livraison, pompe

    def test_planifier_ramassage_depuis_livraison(self):
        from odoo.tests import Form
        technicien = self.env["res.users"].create({"name": "Tech ramassage", "login": "tech_ramassage"})
        livraison, pompe = self._livraison_2_machines_et_pompes()
        action = livraison.action_planifier_ramassage()
        self.assertEqual(action["res_model"], "suivi.machines.planifier.ramassage")
        f = Form(self.env[action["res_model"]].with_context(**action["context"]))
        self.assertEqual(set(f.lot_ids.ids), {self.lot_a.id, self.lot_b.id}, "machines chez le client cochées")
        f.livreur_id = technicien
        wiz = f.save()
        self.assertIn("3 × Pompe test", wiz.accessoires)
        retour = self.env["stock.picking"].browse(wiz.action_planifier()["res_id"])
        # Bon de retour pret : une ligne par machine avec SON numero, les pompes, le technicien, la date
        self.assertEqual(retour.location_id, livraison.location_dest_id)
        self.assertEqual(retour.location_dest_id.usage, "internal")
        self.assertEqual(retour.livreur_id, technicien)
        self.assertEqual(retour.scheduled_date, wiz.date)
        self.assertEqual(retour.return_id, livraison)
        self.assertEqual(set(retour.move_ids.machine_lot_id.ids), {self.lot_a.id, self.lot_b.id})
        self.assertEqual(set(retour.move_line_ids.lot_id.ids), {self.lot_a.id, self.lot_b.id})
        self.assertEqual(sum(retour.move_ids.filtered(lambda m: m.product_id == pompe).mapped("product_uom_qty")), 3)
        # Deuxieme clic : on retrouve le meme bon de retour (pas de doublon)
        self.assertEqual(livraison.action_planifier_ramassage()["res_id"], retour.id)
        # Validation du retour : machines en entrepot + interventions de ramassage avec le technicien
        retour.move_ids.picked = True
        retour.livreur_id = retour.livreur_id or self.env.user  # technicien obligatoire pour valider
        retour.prochain_entretien = retour.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        retour.frequence_entretien = retour.frequence_entretien or "12"
        retour.button_validate()
        self.assertEqual(retour.state, "done")
        self.assertEqual((self.lot_a.machine_statut, self.lot_b.machine_statut), ("entrepot", "entrepot"))
        interv = (self.lot_a | self.lot_b).intervention_ids.filtered(lambda i: i.type == "ramassage")
        self.assertEqual(len(interv), 2)
        self.assertEqual(interv.user_id, technicien)
        # Plus rien chez le client : le formulaire ne propose plus de machine
        f2 = Form(self.env["suivi.machines.planifier.ramassage"].with_context(default_picking_id=livraison.id))
        self.assertFalse(f2.lot_ids)

    def test_planifier_ramassage_une_seule_machine_sans_pompes(self):
        livraison, pompe = self._livraison_2_machines_et_pompes()
        wiz = self.env["suivi.machines.planifier.ramassage"].with_context(default_picking_id=livraison.id).create({})
        wiz.write({"lot_ids": [(6, 0, self.lot_a.ids)], "avec_accessoires": False})
        retour = self.env["stock.picking"].browse(wiz.action_planifier()["res_id"])
        self.assertEqual(retour.move_ids.machine_lot_id, self.lot_a)
        self.assertFalse(retour.move_ids.filtered(lambda m: m.product_id == pompe))

    def test_planifier_ramassage_refuse_si_pas_terminee(self):
        from odoo.exceptions import UserError
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id, "partner_id": self.client.id,
            "location_id": self.stock.id, "location_dest_id": self.clients_loc.id})
        with self.assertRaises(UserError):
            picking.action_planifier_ramassage()
        livraison, _pompe = self._livraison_2_machines_et_pompes()
        wiz = self.env["suivi.machines.planifier.ramassage"].with_context(default_picking_id=livraison.id).create({})
        wiz.write({"lot_ids": [(5, 0, 0)], "avec_accessoires": False})
        with self.assertRaises(UserError):
            wiz.action_planifier()

    def test_date_fin_location_saisie(self):
        so = self._commande(self.lot_b, "location")
        fin = fields.Datetime.now() + relativedelta(days=10)
        so.date_fin_location = fin
        self.assertEqual(so.date_fin_location, fin.replace(microsecond=0))

    def test_numero_contrat_de_location(self):
        """Contrat de location : numero propre LOC00001 ; une vente garde S00001."""
        location = self._commande(self.lot_b, "location")
        vente = self._commande(self.lot_b, "vente")
        self.assertTrue(location.name.startswith("LOC"), location.name)
        self.assertFalse(vente.name.startswith("LOC"), vente.name)
        suivant = self._commande(self.lot_b, "location")
        self.assertGreater(suivant.name, location.name, "numéros qui se suivent")
        # Soumission (brouillon) passee de Vente a Location (et retour) : le numero suit le type
        soumission = self.env["sale.order"].create({"partner_id": self.client.id, "type_commande": "vente"})
        self.assertFalse(soumission.name.startswith("LOC"))
        soumission.type_commande = "location"
        self.assertTrue(soumission.name.startswith("LOC"))
        soumission.type_commande = "vente"
        self.assertFalse(soumission.name.startswith("LOC"))
        # Application Location (Enterprise) : commande creee depuis l'application
        depuis_app = self.env["sale.order"].with_context(in_rental_app=True).create({"partner_id": self.client.id})
        self.assertEqual(depuis_app.type_commande, "location")
        self.assertTrue(depuis_app.name.startswith("LOC"))
        # Contrat confirme : son numero ne change plus
        nom = location.name
        location.type_commande = "vente"
        self.assertEqual(location.name, nom)

    def test_frise_de_la_machine(self):
        so = self._commande(self.lot_b, "location")
        pk = so.picking_ids
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
        pk.with_context(skip_sms=True).button_validate()
        self.env["machine.intervention"].create({"lot_id": self.lot_b.id, "type": "entretien", "state": "fait",
                                                 "partner_id": self.client.id})
        self.env["machine.intervention"].create({"lot_id": self.lot_b.id, "type": "bris", "state": "fait",
                                                 "description": "Joint usé"})
        self.lot_b.invalidate_recordset()
        frise = str(self.lot_b.frise_html)
        self.assertIn("Livrée", frise)
        self.assertIn(self.client.name, frise)
        self.assertIn("Entretien", frise)
        self.assertIn("Joint usé", frise)
        # Resume cliquable sous la frise : clients, entretiens, bris / reparations
        self.assertEqual(self.lot_b.frise_nb_clients, 1)
        self.assertEqual(self.lot_b.frise_nb_entretiens, 1)
        self.assertGreaterEqual(self.lot_b.frise_nb_bris, 1)
        self.assertEqual(self.env["res.partner"].search(self.lot_b.action_frise_clients()["domain"]), self.client)
        entretiens = self.env["machine.intervention"].search(self.lot_b.action_frise_entretiens()["domain"])
        self.assertEqual(set(entretiens.mapped("type")), {"entretien"})
        bris = self.env["machine.intervention"].search(self.lot_b.action_frise_bris()["domain"])
        self.assertTrue(bris and set(bris.mapped("type")) <= {"bris", "reparation"})
        self.assertLess(frise.index("Livrée"), frise.index("Joint usé"), "du plus ancien au plus récent")
        # Bon de livraison : la fiche de la machine en haut (n° de serie choisi)
        self.assertEqual(pk.machine_fiche_ids, self.lot_b)
        self.assertEqual(pk.machine_fiche_label, self.lot_b.ref or self.lot_b.name)
        self.assertEqual(pk.action_fiche_machines()["res_id"], self.lot_b.id)
        arch_pk = self.env["stock.picking"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("action_fiche_machines", arch_pk)
        # Machine installee sans bon de livraison (saisie a la main) : son client compte aussi
        saisie = self.env["stock.lot"].create({"name": "SAISIE-1", "product_id": self.produit.id})
        self.env["machine.intervention"].create({"lot_id": saisie.id, "type": "installation", "state": "fait",
                                                 "partner_id": self.client.id})
        self.assertEqual(saisie.frise_nb_clients, 1)
        # Machine sans evenement : message simple
        neuve = self.env["stock.lot"].create({"name": "NEUVE-1", "product_id": self.produit.id})
        self.assertIn("Aucun événement", str(neuve.frise_html))
        arch = self.env["stock.lot"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("frise_html", arch)
        for bouton in ("action_frise_clients", "action_frise_entretiens", "action_frise_bris"):
            self.assertIn(bouton, arch)


    def test_technicien_obligatoire_pour_valider(self):
        """Livraison chez le client : pas de validation sans technicien assigné (bandeau rouge)."""
        from lxml import etree
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id, "partner_id": self.client.id,
            "location_id": self.stock.id, "location_dest_id": self.clients_loc.id,
            "move_ids": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1,
                                 "location_id": self.stock.id, "location_dest_id": self.clients_loc.id})]})
        picking.action_confirm()
        picking.action_assign()
        picking.move_ids.picked = True
        self.assertTrue(picking.technicien_requis)
        with self.assertRaisesRegex(UserError, "technicien assigné"):
            picking.button_validate()
        self.assertNotEqual(picking.state, "done")
        picking.livreur_id = self.env.user
        picking.write({"prochain_entretien": fields.Date.today() + relativedelta(months=12),
                       "frequence_entretien": "12"})
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertFalse(picking.technicien_requis)
        # Transfert interne : pas concerne
        interne = self.env["stock.picking"].new({"location_id": self.stock.id, "location_dest_id": self.stock.id})
        self.assertFalse(interne._est_tournee_client())
        arch = etree.fromstring(self.env["stock.picking"].get_views([(False, "form")])["views"]["form"]["arch"])
        bandeau = arch.xpath("//div[contains(@class, 'alert-danger')][contains(., 'Technicien assigné')]")
        self.assertEqual(bandeau[0].get("invisible"), "not technicien_requis or livreur_id")

    def test_periode_de_location_obligatoire(self):
        """Contrat de location : la période (début et fin) est obligatoire, à l'écran et à la confirmation."""
        from lxml import etree
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": "location",
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        with self.assertRaisesRegex(ValidationError, "période de location"):
            so.action_confirm()
        so.write({"date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1]})
        so.action_confirm()
        self.assertEqual(so.state, "sale")
        vente = self._commande(self.lot_a)
        self.assertEqual(vente.state, "sale", "une vente n'a pas de période")
        arch = etree.fromstring(self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"])
        for nom in ("date_debut_location", "date_fin_location"):
            self.assertEqual(arch.xpath("//field[@name='%s']" % nom)[0].get("required"), "type_commande == 'location'")

    def test_ajout_au_contrat_de_location(self):
        """Upgrade : une machine (ou un accessoire) ajoutée au contrat déjà livré part en livraison ;
        son n° de série est choisi à la livraison et revient sur la ligne du contrat."""
        contrat = self._commande(self.lot_a, "location")
        self.assertFalse(contrat.nb_livraisons_a_faire, "livraison normale du contrat : pas « Livraison à faire »")
        self._valider(contrat.picking_ids)
        self.assertEqual(self.lot_a.machine_statut, "chez_client")
        # Jose ajoute une deuxieme machine au meme contrat
        ligne = self.env["sale.order.line"].create({"order_id": contrat.id, "product_id": self.produit.id,
                                                    "product_uom_qty": 1, "price_unit": 50})
        a_livrer = contrat.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
        self.assertEqual(len(a_livrer), 1, "livraison du nouveau composant créée")
        contrat.invalidate_recordset(["nb_livraisons_a_faire"])
        self.assertEqual(contrat.nb_livraisons_a_faire, 1, "ajout : « Livraison à faire » apparaît")
        self.assertEqual(a_livrer.move_ids.product_id, self.produit)
        self.assertEqual(a_livrer.move_ids.sale_line_id, ligne)
        self.assertEqual(contrat.action_livraison_a_faire()["res_id"], a_livrer.id)
        self.assertTrue(contrat.message_ids.filtered(lambda m: a_livrer.name in (m.body or "")),
                        "ajout noté dans le contrat avec sa livraison")
        a_livrer.move_ids.machine_lot_id = self.lot_b
        self._valider(a_livrer)
        self.assertEqual(ligne.machine_lot_id, self.lot_b)
        self.assertEqual(self.lot_b.machine_statut, "chez_client")
        self.assertEqual(contrat.machine_ids, self.lot_a | self.lot_b, "les deux machines dans le même contrat")

    def test_entretien_choisi_a_la_livraison(self):
        """Livraison de machines chez le client : prochain entretien et fréquence obligatoires,
        gardés sur la fiche de la machine ; ensuite : dernier entretien + fréquence."""
        so = self._commande(self.lot_a, "location")
        picking = so.picking_ids
        picking.action_assign()
        picking.move_ids.picked = True
        picking.livreur_id = self.env.user
        self.assertTrue(picking.livre_machines)
        with self.assertRaisesRegex(UserError, "prochain entretien"):
            picking.button_validate()
        dans_3_mois = fields.Date.today() + relativedelta(months=3)
        picking.write({"prochain_entretien": dans_3_mois, "frequence_entretien": "6"})
        picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual((self.lot_a.date_prochain_entretien, self.lot_a.intervalle_entretien), (dans_3_mois, 6))
        # Entretien fait : le suivant = dernier entretien + 6 mois
        self.env["machine.intervention"].create({"lot_id": self.lot_a.id, "type": "entretien", "state": "fait",
                                                 "date": fields.Datetime.now() + relativedelta(days=1)})
        self.assertEqual(self.lot_a.date_prochain_entretien,
                         fields.Date.today() + relativedelta(days=1) + relativedelta(months=6))
        # Transfert sans machine vers le client : pas concerné
        self.assertFalse(self.env["stock.picking"].new({"location_id": self.stock.id,
                                                        "location_dest_id": self.stock.id}).livre_machines)

    # ------------------------------------------------------------ types de contrat et forfait annuel
    def test_types_de_contrat(self):
        """4 types Monroy ; le type regle vente / location (proprietaire = machine au client)."""
        types = {t: self.env.ref("suivi_machines.type_contrat_" + t)
                 for t in ("location", "convention", "popcorn", "proprietaire")}
        self.assertEqual([types[t].type_commande for t in types], ["location", "location", "location", "vente"])
        self.assertEqual((types["convention"].forfait_montant, types["popcorn"].forfait_montant,
                          types["location"].forfait_montant), (359.99, 279.5, 0))
        so = self.env["sale.order"].create({"partner_id": self.client.id, "type_contrat_id": types["proprietaire"].id})
        self.assertEqual(so.type_commande, "vente")
        so.write({"type_contrat_id": types["convention"].id, "date_debut_location": PERIODE_TEST[0],
                  "date_fin_location": PERIODE_TEST[1]})
        self.assertEqual(so.type_commande, "location")
        arch = self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("type_contrat_id", arch)
        self.assertIn("forfait_montant", arch)

    def test_forfait_annuel_selon_le_contrat(self):
        """Convention : le forfait est une ligne DU CONTRAT (signee avec lui), prix modifiable ; chaque
        annee, la ligne de l'annee suivante est ajoutee au meme contrat (tache planifiee)."""
        from dateutil.relativedelta import relativedelta
        convention = self.env.ref("suivi_machines.type_contrat_convention")
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_contrat_id": convention.id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2})]})
        forfait = so.order_line.filtered("est_forfait")
        self.assertEqual((forfait.product_uom_qty, forfait.price_unit), (2, 359.99), "ligne du contrat dès la soumission")
        self.assertEqual(forfait.product_id, self.env.ref("suivi_machines.produit_forfait_entretien"))
        # Une machine de plus : la ligne suit ; prix negocie sur le contrat : la ligne suit
        so.write({"order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        self.assertEqual(forfait.product_uom_qty, 3)
        so.forfait_montant = 300
        self.assertEqual(forfait.price_unit, 300, "prix modifiable sur le contrat")
        # Prix change a la main sur la ligne : garde
        forfait.price_unit = 290
        so.write({"order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        self.assertEqual((forfait.product_uom_qty, forfait.price_unit), (4, 290))
        so.action_confirm()
        aujourdhui = fields.Date.context_today(so)
        self.assertEqual(so.forfait_prochaine_date, aujourdhui + relativedelta(months=12))
        self.assertEqual(len(so.order_line.filtered("est_forfait")), 1)
        # Pas encore l'anniversaire : rien
        self.env["sale.order"]._cron_forfaits_annuels()
        self.assertEqual(len(so.order_line.filtered("est_forfait")), 1)
        # Un an plus tard : rappel au bureau, rien d'ajoute tout seul (le prix est a ajuster)
        so.forfait_prochaine_date = aujourdhui
        self.env["sale.order"]._cron_forfaits_annuels()
        self.assertTrue(so.forfait_a_renouveler)
        self.assertEqual(len(so.order_line.filtered("est_forfait")), 1, "pas de ligne automatique")
        self.assertEqual(len(so._activites_forfait()), 1)
        self.env["sale.order"]._cron_forfaits_annuels()
        self.assertEqual(len(so._activites_forfait()), 1, "un seul rappel")
        # Jose renouvelle : prix de l'an dernier propose, ajuste a 310
        action = so.action_renouveler_forfait()
        assistant = Form(self.env[action["res_model"]].with_context(action["context"]))
        self.assertEqual((assistant.prix_precedent, assistant.prix, assistant.nombre), (290, 290, 4))
        assistant.prix = 310
        assistant.save().action_renouveler()
        lignes = so.order_line.filtered("est_forfait").sorted("id")
        self.assertEqual(len(lignes), 2)
        self.assertEqual((lignes[-1].product_uom_qty, lignes[-1].price_unit), (4, 310))
        self.assertIn("Frais annuels", lignes[-1].name)
        self.assertFalse(so.forfait_a_renouveler)
        self.assertFalse(so._activites_forfait(), "rappel termine")
        self.assertEqual(so.forfait_prochaine_date, aujourdhui + relativedelta(months=12))
        # Location (0 $) et proprietaire : jamais de forfait
        for xmlid in ("type_contrat_location", "type_contrat_proprietaire"):
            autre = self.env["sale.order"].create({
                "partner_id": self.client.id, "type_contrat_id": self.env.ref("suivi_machines." + xmlid).id,
                "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
                "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
            autre.action_confirm()
            self.assertFalse(autre.order_line.filtered("est_forfait"), xmlid)
            self.assertFalse(autre.forfait_prochaine_date)
        # Changer de type sur une soumission : la ligne suit (supprimee si plus de forfait)
        brouillon = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_contrat_id": convention.id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        brouillon.type_contrat_id = self.env.ref("suivi_machines.type_contrat_popcorn")
        self.assertEqual(brouillon.order_line.filtered("est_forfait").price_unit, 279.5)
        brouillon.type_contrat_id = self.env.ref("suivi_machines.type_contrat_location")
        self.assertFalse(brouillon.order_line.filtered("est_forfait"))

    def test_numero_de_serie_obligatoire_a_la_livraison(self):
        """Jose choisit le n° de série de chaque machine sur le bon de livraison : obligatoire pour valider."""
        so = self.env["sale.order"].create({
            "partner_id": self.client.id,
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2})]})
        so.action_confirm()
        livraison = so.picking_ids
        livraison.write({"livreur_id": self.env.user.id, "frequence_entretien": "12",
                         "prochain_entretien": fields.Date.today() + relativedelta(months=12)})
        livraison.move_ids.move_line_ids.unlink()
        self.assertTrue(livraison.machines_sans_serie, "bandeau rouge sur le bon de livraison")
        with self.assertRaisesRegex(UserError, "n° de série de chaque machine"):
            livraison.button_validate()
        moves = livraison.move_ids.filtered("est_machine")
        moves[0].machine_lot_id = self.lot_a
        self.assertTrue(livraison.machines_sans_serie, "une machine sur deux : pas encore")
        moves[1].machine_lot_id = self.lot_b
        self.assertFalse(livraison.machines_sans_serie)
        arch = self.env["stock.picking"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("machines_sans_serie", arch)

    def test_numero_de_serie_saisi_dans_le_bon_puis_enregistre(self):
        """Comme Jose dans l'écran : choisir le n° de série de chaque machine, Enregistrer, puis Valider."""
        so = self.env["sale.order"].create({
            "partner_id": self.client.id,
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2})]})
        so.action_confirm()
        livraison = so.picking_ids
        livraison.move_ids.move_line_ids.unlink()
        self.assertTrue(all(livraison.move_ids.filtered("est_machine").mapped("serie_requise")),
                        "n° de série obligatoire dans l'écran")
        arch = self.env["stock.picking"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('required="serie_requise"', arch, "case rouge obligatoire dans la ligne")
        with Form(livraison) as f:
            f.livreur_id = self.env.user
            f.frequence_entretien = "12"
            f.prochain_entretien = fields.Date.today() + relativedelta(months=12)
            for i, lot in enumerate((self.lot_a, self.lot_b)):
                with f.move_ids.edit(i) as ligne:
                    ligne.machine_lot_id = lot
        self.assertEqual(set(livraison.move_ids.machine_lot_id.ids), {self.lot_a.id, self.lot_b.id}, "enregistré")
        self.assertEqual(livraison.move_ids.move_line_ids.lot_id, self.lot_a | self.lot_b, "réservé")
        self.assertFalse(livraison.machines_sans_serie)
        livraison.button_validate()
        self.assertEqual(livraison.state, "done")
        self.assertEqual(livraison.move_ids.move_line_ids.lot_id, self.lot_a | self.lot_b)

    def test_bon_de_vente_confirme_dans_le_profil_du_client(self):
        """Profil du client : une vente confirmée y va, signée ou non (un contrat, seulement une fois signé)."""
        so = self._commande(self.lot_a)
        pieces = self.env["ir.attachment"].search([("res_model", "=", "res.partner"),
                                                   ("res_id", "=", self.client.commercial_partner_id.id)])
        self.assertTrue(pieces.filtered(lambda a: a.name == "Bon de vente %s.pdf" % so.name), "vente non signée")
        signee = self.env["sale.order"].create({
            "partner_id": self.client.id, "signature": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
            "signed_by": "Client", "signed_on": fields.Datetime.now(),
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": self.lot_b.id})]})
        signee.action_confirm()
        so = signee
        pieces = self.env["ir.attachment"].search([("res_model", "=", "res.partner"),
                                                   ("res_id", "=", self.client.commercial_partner_id.id)])
        self.assertTrue(pieces.filtered(lambda a: a.name == "Bon de vente %s.pdf" % so.name))
        if "documents.document" in self.env:
            self.assertTrue(self.env["documents.document"].search(
                [("partner_id", "=", self.client.commercial_partner_id.id), ("name", "=", "Bon de vente %s.pdf" % so.name)]))

    def test_une_ligne_par_machine(self):
        """« Machine x 2 » : 2 lignes d'une machine, pour choisir le n° de serie de chacune."""
        so = self.env["sale.order"].create({
            "partner_id": self.client.id,
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2, "price_unit": 50})]})
        machines = so.order_line.filtered("est_machine")
        self.assertEqual(machines.mapped("product_uom_qty"), [1, 1])
        self.assertEqual(machines.mapped("price_unit"), [50, 50], "même prix")
        so.write({"order_line": [(1, machines[0].id, {"product_uom_qty": 3})]})
        self.assertEqual(len(so.order_line.filtered("est_machine")), 4)
        self.assertEqual(sum(so.order_line.mapped("product_uom_qty")), 4)

    def test_action_ranger_pdf_client(self):
        """Action manuelle (menu Action, ventes seulement) : refait le PDF dans le profil du client, sans
        doublon."""
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_location").id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        for _essai in range(2):
            resultat = so.action_ranger_pdf_client()
            self.assertEqual(resultat["params"]["type"], "success")
        # Échec (ex. rapport impossible) : la raison s'affiche dans le message, la vente n'est pas bloquée
        from unittest.mock import patch
        with patch.object(type(so), "_ranger_pdf_client", side_effect=ValueError("Rapport impossible")):
            resultat = so.action_ranger_pdf_client()
        self.assertEqual(resultat["params"]["type"], "warning")
        self.assertIn("Rapport impossible", resultat["params"]["message"])
        self.assertIn(so.name, resultat["params"]["message"])
        pieces = self.env["ir.attachment"].search([("res_model", "=", "res.partner"), ("res_id", "=", self.client.id),
                                                   ("name", "ilike", so.name)])
        self.assertEqual(len(pieces), 1, "remplacé, pas de doublon")
        # Rangé par un client du portail dans une autre langue : même nom de document (pas de doublon)
        for lang, nom in (("en_US", "Rental EN"), ("fr_CA", "Location FR")):
            self.env["res.lang"]._activate_lang(lang)
            so.type_contrat_id.with_context(lang=lang).name = nom
        self.assertEqual(so.with_context(lang="en_US")._nom_document_client(),
                         so.with_context(lang="fr_CA")._nom_document_client())
        action = self.env.ref("suivi_machines.action_serveur_ranger_pdf_client")
        self.assertEqual(action.binding_model_id.model, "sale.order")
        self.assertIn(self.env.ref("sales_team.group_sale_salesman"), action.group_ids, "ventes seulement")

    def test_libelles_uniques(self):
        """Odoo avertit (Test: Warning sur Odoo.sh) quand deux champs d'un modele ont le meme libelle :
        aucun doublon cree par nos modules."""
        doublons = []
        for nom_modele, modele in self.env.registry.items():
            libelles = {}
            for champ in modele._fields.values():
                libelles.setdefault(champ.string, []).append(champ)
            for libelle, champs in libelles.items():
                if len(champs) > 1 and any((c._module or "").startswith("suivi_") for c in champs):
                    doublons.append("%s : %s (%s)" % (nom_modele, libelle, ", ".join(c.name for c in champs)))
        self.assertFalse(doublons, "\n".join(doublons))

    def test_contrat_qweb_rempli_et_signe_en_ligne(self):
        """Le contrat du type (QWeb) suit le devis : PDF et page du client, rempli depuis Odoo, signé en ligne."""
        self.client.write({"ref": "MON777", "street": "12 rue du Port", "city": "Québec", "zip": "G1K 1A1",
                           "phone": "418-555-0100", "is_company": True})
        lot = self.env["stock.lot"].create({"name": "SER-CONTRAT", "product_id": self.produit.id, "ref": "F999"})
        rapport = self.env["ir.actions.report"]
        # Texte original des formulaires (montants ecrits compris), seuls les blancs sont remplis
        attendus = {
            "type_contrat_location": ["CONTRAT DE LOCATION / ENTREPRISE", "louera au client", "0.00 $",
                                      "QUATRE MILLE DOLLARS (4000$", "frais de 125$", "Rév. 01/13", "de le présent contrat"],
            "type_contrat_convention": ["CONVENTION", "permettra au client d’utiliser", "359.99$", "frais de 125$",
                                        "Rév. 01/13", "V2 ELMECO"],
            "type_contrat_popcorn": ["POPCORN", "HARLAN’S", "279.50 $", "frais de 70$",
                                     "DEUX MILLE CINQ CENTS DOLLARS (2500$", "Rév. 10/2016"],
            "type_contrat_proprietaire": ["CONTRAT PROPRIÉTAIRE", "DISTRIBUTEUR", "125.00$ plus un taux horaire de 105,00 $",
                                          "Rév. 12/09"],
        }
        for xmlid, textes in attendus.items():
            so = self.env["sale.order"].create({
                "partner_id": self.client.id, "type_contrat_id": self.env.ref("suivi_machines." + xmlid).id,
                "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1], "saison": "ete",
                "prix_detail_353": 2.5,
                "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1, "machine_lot_id": lot.id})]})
            self.assertTrue(so.require_signature, "le client signe le contrat en ligne")
            html = rapport._render_qweb_html("sale.action_report_saleorder", so.ids)[0].decode()
            with self.subTest(type=xmlid):
                for texte in textes + ["Client", "MON777", "Dépanneur Test", "1 janvier 2026", "31 décembre 2027",
                                       "CLAUSE PÉNALE", "Initiales"] + (["F999 (SER-CONTRAT)"] if "popcorn" not in xmlid else []):
                    self.assertIn(texte, html)
        # N° de serie choisi a la livraison (comme d'habitude) : a la signature « attribue a la livraison »,
        # puis le contrat montre les n° de serie choisis sur le bon de livraison (une ligne par machine)
        lot2 = self.env["stock.lot"].create({"name": "SER-LIVRE-2", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, self.stock, 1, lot_id=lot2)
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_convention").id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 2})]})
        html = rapport._render_qweb_html("sale.action_report_saleorder", so.ids)[0].decode()
        self.assertIn("numéro de série ______________", html, "blanc avant la livraison, comme le formulaire")
        so.action_confirm()
        livraison = so.picking_ids
        moves = livraison.move_ids.filtered("est_machine")
        self.assertEqual(len(moves), 2, "une ligne de livraison par machine, chacune avec son n° de série")
        moves[0].machine_lot_id = self.lot_a
        moves[1].machine_lot_id = lot2
        self.assertEqual(set(so.order_line.filtered("est_machine").mapped("machine_lot_id.name")),
                         {self.lot_a.name, "SER-LIVRE-2"}, "reportés sur les lignes du contrat")
        html = rapport._render_qweb_html("sale.action_report_saleorder", so.ids)[0].decode()
        self.assertIn("SER-LIVRE-2", html)
        self.assertIn(self.lot_a.name, html)
        # Sans type de contrat : devis normal, pas de contrat
        simple = self.env["sale.order"].create({"partner_id": self.client.id})
        self.assertNotIn("CLAUSE PÉNALE", rapport._render_qweb_html("sale.action_report_saleorder", simple.ids)[0].decode())
        # Page du client : le contrat est affiché avant les adresses
        from lxml import etree
        arch = etree.tostring(self.env.ref("sale.sale_order_portal_content")._get_combined_arch(), encoding="unicode")
        self.assertIn("contrat_monroy", arch)

    def test_dates_de_location_toujours_visibles(self):
        """Nouveau contrat de location : début et fin toujours à l'écran (même avec l'application Location),
        et la date saisie est gardée à l'enregistrement."""
        arch = self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        if "rental_start_date" in self.env["sale.order"]._fields:
            # Application Location : sa « Période de location » native, sous Expiration
            self.assertIn('widget="daterange"', arch)
            self.assertIn("rental_return_date", arch)
        else:
            self.assertIn('name="date_debut_location"', arch)
            self.assertNotIn("date_fin_auto\"", arch.split('name="date_debut_location"')[1].split("/>")[0])
        vals = self.env["sale.order"]._dates_vers_location({"date_debut_location": PERIODE_TEST[0]})
        if "rental_start_date" in self.env["sale.order"]._fields:
            self.assertEqual(vals["rental_start_date"], PERIODE_TEST[0])
        so = self.env["sale.order"].create({"partner_id": self.client.id, "type_commande": "location",
                                            "date_debut_location": PERIODE_TEST[0],
                                            "date_fin_location": PERIODE_TEST[1]})
        so.write({"date_fin_location": PERIODE_TEST[1] + relativedelta(months=1)})
        self.assertEqual(so.date_debut_location, PERIODE_TEST[0])
        self.assertEqual(so.date_fin_location, PERIODE_TEST[1] + relativedelta(months=1))

    def test_prix_de_detail_visibles_sur_un_nouveau_contrat(self):
        """Contrat original : saison et prix de détail affichés dès que c'est une location, même avant de
        choisir le type de contrat (cachés seulement pour le popcorn)."""
        arch = self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        for champ in ("prix_detail_353", "prix_detail_510", "prix_detail_775", "saison"):
            self.assertIn('name="%s"' % champ, arch)
        self.assertIn("type_commande != 'location'", arch.split('name="saison"')[1].split("/>")[0])

    def test_fiche_contact_monroy(self):
        """Fiche contact : nom légal, autres numéros, code client de la société sur un contact rattaché,
        cadre « Code client » et onglet « Autres informations »."""
        societe = self.env["res.partner"].create({"name": "Société Test", "ref": "SOC01",
                                                  "x_nom_legal": "SOCIETE TEST INC.", "x_autres_numeros": "418 555-0001"})
        contact = self.env["res.partner"].create({"name": "Personne", "parent_id": societe.id, "type": "contact"})
        self.assertEqual(contact.x_code_societe, "SOC01")
        self.assertEqual(societe.x_nom_legal, "SOCIETE TEST INC.")
        arch = self.env["res.partner"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertEqual(arch.count('name="autres_informations"'), 1)
        for champ in ("x_nom_legal", "x_autres_numeros", "x_code_societe"):
            self.assertIn('name="%s"' % champ, arch)

    def test_bouton_envoyer_ne_range_rien(self):
        """Comme Jose : bouton « Envoyer » puis « Envoyer » dans la fenêtre du courriel -> rien n'est rangé dans
        le profil du client : seul le contrat signé y va (voir test_contrat_signe_range_dans_le_dossier_du_client)."""
        client = self.env["res.partner"].create({"name": "Client Envoyer", "email": "envoyer@exemple.ca"})
        so = self.env["sale.order"].create({
            "partner_id": client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_convention").id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        action = so.action_quotation_send()
        composer = self.env["mail.compose.message"].with_context(**action["context"]).create({})
        composer.action_send_mail()
        self.assertEqual(so.state, "sent")
        pieces = self.env["ir.attachment"].search([("res_model", "=", "res.partner"), ("res_id", "=", client.id)])
        self.assertFalse(pieces.filtered(lambda a: so.name in a.name), "pas encore signé : rien dans le profil")
        if "documents.document" in self.env:
            self.assertFalse(self.env["documents.document"].search([("partner_id", "=", client.id)]))

    def test_courriel_contrat_a_signer(self):
        """« Envoyer » un contrat de location : courriel Monroy en français avec le lien sécurisé du client
        dans le texte ; une vente garde le courriel standard."""
        modele = self.env.ref("suivi_machines.mail_template_contrat_location")
        so = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": "location",
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1})]})
        self.assertEqual(so._find_mail_template(), modele)
        corps = modele._render_field("body_html", so.ids)[so.id]
        self.assertIn("Lire et signer mon contrat", corps)
        self.assertIn(so.get_portal_url(), corps, "lien sécurisé du client (avec son jeton)")
        self.assertIn("access_token=", corps)
        self.assertIn(so.name, modele._render_field("subject", so.ids)[so.id])
        vente = self.env["sale.order"].create({"partner_id": self.client.id, "type_commande": "vente"})
        self.assertNotEqual(vente._find_mail_template(), modele)
        so.state = "sale"
        self.assertNotEqual(so._find_mail_template(), modele, "contrat signé : courriel de confirmation")


@tagged("post_install", "-at_install")
class TestContratEnLigne(HttpCase):
    """La page envoyée au client (lien du devis) affiche le contrat à signer."""

    def test_page_du_client_affiche_le_contrat(self):
        client = self.env["res.partner"].create({"name": "Client en ligne", "ref": "MON888", "email": "c@exemple.ca"})
        categ = self.env["product.category"].create({"name": "Machines (en ligne)", "suivi_machine": True})
        produit = self.env["product.product"].create({"name": "Machine en ligne", "categ_id": categ.id,
                                                      "is_storable": True, "tracking": "serial"})
        so = self.env["sale.order"].create({
            "partner_id": client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_popcorn").id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": produit.id, "product_uom_qty": 1})]})
        so.write({"require_signature": True, "prepayment_percent": 0})
        so.action_quotation_sent()
        reponse = self.url_open(so.get_portal_url())
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("CLAUSE PÉNALE", reponse.text)
        self.assertIn("HARLAN’S", reponse.text)
        self.assertIn("MON888", reponse.text)
        # Le client complete lui-meme le contrat : cases DANS le texte du contrat, enregistrees toutes seules
        for champ in ("contrat_initiales", "caution_nom", "caution_ville", "proprietaire_immeuble", "contrat_compagnie"):
            self.assertIn('name="%s"' % champ, reponse.text)
        self.assertIn('id="contrat_client_form"', reponse.text)
        import re
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', reponse.text).group(1)
        self.url_open("/my/orders/%s/contrat" % so.id, data={
            "csrf_token": csrf, "access_token": so.access_token, "contrat_initiales": "M.G.",
            "contrat_compagnie": "oui", "caution_nom": "Marie Gagnon", "caution_numero": "12",
            "caution_rue": "des Érables", "caution_ville": "Québec", "caution_province": "Québec",
            "proprietaire_immeuble": "Immeubles du Port inc., 1 rue du Quai"})
        so.invalidate_recordset()
        self.assertEqual((so.contrat_initiales, so.contrat_compagnie, so.caution_nom), ("M.G.", "oui", "Marie Gagnon"))
        # Enregistrement d'une seule case (sauvegarde automatique) : les autres restent
        self.url_open("/my/orders/%s/contrat" % so.id, data={
            "csrf_token": csrf, "access_token": so.access_token, "caution_ville": "Lévis"})
        so.invalidate_recordset()
        self.assertEqual((so.caution_ville, so.caution_nom), ("Lévis", "Marie Gagnon"))
        # Le client signe (une seule signature) : compagnie = la caution est signee avec
        signature = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        so.write({"signature": signature, "signed_by": "Marie Gagnon"})
        html = " ".join(self.env["ir.actions.report"]._render_qweb_html(
            "sale.action_report_saleorder", so.ids)[0].decode().split())
        for texte in ("Initiales : <strong>M.G.</strong>", "Je, soussigné <strong>Marie Gagnon</strong>",
                      "rue <strong>des Érables</strong>", "Immeubles du Port inc."):
            self.assertIn(texte, html)
        self.assertGreaterEqual(html.count("data:image/png;base64"), 2, "signature du client ET de la caution")
        page = self.url_open(so.get_portal_url()).text
        self.assertIn("data:image/png;base64", page, "la signature apparaît dans le contrat sur la page")
        self.assertNotIn('id="contrat_client_form"', self.url_open(so.get_portal_url()).text, "plus modifiable")
        with self.assertRaises(UserError):
            so._contrat_completer_par_client({"caution_nom": "Autre"})

    def test_contrat_signe_range_dans_le_dossier_du_client(self):
        """Le client signe en ligne : le contrat signé (PDF) va dans sa fiche, et dans Documents si installé."""
        client = self.env["res.partner"].create({"name": "Café Signature", "is_company": True,
                                                 "email": "cafe@exemple.ca", "ref": "MON999"})
        categ = self.env["product.category"].create({"name": "Machines (signature)", "suivi_machine": True})
        produit = self.env["product.product"].create({"name": "Machine signature", "categ_id": categ.id,
                                                      "is_storable": True, "tracking": "serial"})
        so = self.env["sale.order"].create({
            "partner_id": client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_convention").id,
            "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1],
            "order_line": [(0, 0, {"product_id": produit.id, "product_uom_qty": 1, "price_unit": 100})]})
        # Selon la base (Odoo.sh), un paiement en ligne peut etre exige apres la signature : pas ici
        so.write({"require_signature": True, "prepayment_percent": 0})
        so.action_quotation_sent()
        envoye = self.env["ir.attachment"].search([("res_model", "=", "res.partner"), ("res_id", "=", client.id)])
        self.assertFalse(envoye.filtered(lambda a: so.name in a.name), "devis envoyé : rien tant qu'il n'est pas signé")
        jeton = so._portal_ensure_token()
        signature = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        resultat = self.make_jsonrpc_request("/my/orders/%s/accept?access_token=%s" % (so.id, jeton),
                                             {"name": "Richard Filion", "signature": signature})
        self.assertFalse(resultat.get("error"), resultat)
        so.invalidate_recordset()
        self.assertEqual(so.state, "sale", "contrat signé = confirmé")
        pieces = self.env["ir.attachment"].search([("res_model", "=", "res.partner"), ("res_id", "=", client.id)])
        self.assertTrue(pieces.filtered(lambda a: so.name in a.name and a.name.endswith("signé.pdf")),
                        "le contrat signé est dans la fiche du client")
        self.assertEqual(len(pieces.filtered(lambda a: so.name in a.name)), 1, "mis à jour, pas de doublon")
        self.assertTrue(client.message_ids.filtered(lambda m: "signé en ligne par Richard Filion" in (m.body or "")))
        if "documents.document" in self.env:
            documents = self.env["documents.document"].search([("partner_id", "=", client.id)])
            document = documents.filtered(lambda d: so.name in (d.name or ""))
            self.assertEqual(len(document), 1, "rangé dans Documents (un seul, mis à jour à la signature)")
            self.assertTrue(document.attachment_id.raw, "le PDF est dans le document")
            self.assertTrue(document.name.endswith("signé.pdf"))
            if "owner_id" in document._fields:
                self.assertFalse(document.owner_id.share, "propriétaire interne : visible par le bureau")

