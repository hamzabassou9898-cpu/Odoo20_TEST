# -*- coding: utf-8 -*-
"""Ordre de la tournee choisi par le superviseur dans le Planning : les taches d'un technicien pour une
journee se font dans l'ordre 1, 2, 3... sans heure, sauf celles a heure fixe (« a 14 h »)."""
from odoo import fields, models


class OrdreTournee(models.AbstractModel):
    _name = "pilotage.ordre.tournee"
    _description = "Ordre dans la tournée du technicien"

    ordre_tournee = fields.Integer(
        "Ordre dans la tournée", default=0, copy=False,
        help="Place de la tâche dans la journée du technicien, choisie dans le Planning (0 : pas encore placée, "
             "elle passe après les tâches placées).")
    heure_fixe = fields.Boolean(
        "Heure fixe", copy=False,
        help="Le client attend à une heure précise : l'heure de la date prévue est affichée au technicien. "
             "Sinon, le technicien suit seulement l'ordre de sa tournée.")


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "pilotage.ordre.tournee"]


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _inherit = ["helpdesk.ticket", "pilotage.ordre.tournee"]


class MachineIntervention(models.Model):
    _name = "machine.intervention"
    _inherit = ["machine.intervention", "pilotage.ordre.tournee"]
