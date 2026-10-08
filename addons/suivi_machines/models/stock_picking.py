# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    livreur_id = fields.Many2one("res.users", "Livreur", index="btree_not_null", tracking=True,
                                 domain="[('share', '=', False)]",
                                 help="Personne qui fait la livraison (ou la reprise) de la machine.")
