# -*- coding: utf-8 -*-
"""Fiche contact Monroy : nom legal, autres numeros et code client de la societe (champs crees a l'origine
directement dans la base ; memes noms techniques pour garder les valeurs deja saisies)."""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_nom_legal = fields.Char("Nom légal")
    x_autres_numeros = fields.Text("Autres numéros")
    x_code_societe = fields.Char("Code client (entreprise)", related="parent_id.ref")
