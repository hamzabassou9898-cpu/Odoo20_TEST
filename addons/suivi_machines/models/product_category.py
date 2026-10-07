# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    suivi_machine = fields.Boolean(
        "Suivi des machines",
        help="Les numéros de série des produits de cette catégorie apparaissent "
             "dans Inventaire > Machines.")
