# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
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
