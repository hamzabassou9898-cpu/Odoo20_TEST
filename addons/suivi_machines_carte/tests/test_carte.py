# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.carte import MAX_ARRETS, adresse_propre, url_itineraire, url_recherche


@tagged("post_install", "-at_install")
class TestCarte(TransactionCase):

    def test_liens(self):
        self.assertEqual(adresse_propre("640 Georges Muir\n\nCharlesbourg, , Canada"),
                         "640 Georges Muir, Charlesbourg, Canada")
        self.assertIn("query=640%20Georges%20Muir%2C%20Qu%C3%A9bec", url_recherche("640 Georges Muir, Québec"))
        url = url_itineraire(["A 1", "B 2", "C 3"])
        self.assertIn("destination=C%203", url)
        self.assertIn("waypoints=A%201%7CB%202", url)

    def test_itineraire_tournee(self):
        client = self.env["res.partner"].create({"name": "Client carte", "street": "10 rue du Sport", "city": "Lévis"})
        type_out = self.env.ref("stock.picking_type_out")
        vals = {"partner_id": client.id, "picking_type_id": type_out.id,
                "location_id": type_out.default_location_src_id.id,
                "location_dest_id": self.env.ref("stock.stock_location_customers").id}
        picking = self.env["stock.picking"].create(dict(vals, name="TEST/CARTE/0"))
        self.assertIn("10 rue du Sport", picking.adresse_carte)
        self.assertIn("<iframe", picking.carte_google)
        action = picking.action_itineraire_tournee()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("destination=10%20rue%20du%20Sport", action["url"])
        trop = self.env["stock.picking"]
        for i in range(MAX_ARRETS + 1):
            autre = self.env["res.partner"].create({"name": "C%s" % i, "street": "%s rue X" % (i + 1), "city": "Québec"})
            trop |= self.env["stock.picking"].create(dict(vals, partner_id=autre.id, name="TEST/CARTE/%s" % (i + 1)))
        with self.assertRaises(UserError):
            trop.action_itineraire_tournee()
