# -*- coding: utf-8 -*-
"""Produits par categorie (Pilotage) : prix affiche sans total par categorie."""
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Meme prix que « Prix de vente », mais jamais additionne dans les regroupements
    prix_vente = fields.Float(related="list_price", string="Prix de vente", aggregator=None)
