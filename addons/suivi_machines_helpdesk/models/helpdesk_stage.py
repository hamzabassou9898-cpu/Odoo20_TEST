# -*- coding: utf-8 -*-
"""Ce qu'une etape veut dire pour Monroy (fermee, nouvelle), lu dans son nom francais : une etape native
renommee (ex. « Solved » devenue « Entretien & Reparation ») garde son ancien nom anglais, qui ne compte pas."""
from odoo import api, fields, models

from .etapes import contient, est_ferme, etapes_selon, nom_etape


def est_nouvelle(nom):
    return contient(nom, "nouveau")


class HelpdeskStage(models.Model):
    _inherit = "helpdesk.stage"

    etape_fermee = fields.Boolean("Ferme le ticket", compute="_compute_sens_etape", search="_search_etape_fermee",
                                  help="Nom (en français) contenant Résolu, Clôturé ou Annulé.")
    etape_nouvelle = fields.Boolean("Étape des nouveaux tickets", compute="_compute_sens_etape",
                                    search="_search_etape_nouvelle")

    @api.depends("name")
    def _compute_sens_etape(self):
        for etape in self:
            nom = nom_etape(etape)
            etape.etape_fermee = est_ferme(nom)
            etape.etape_nouvelle = est_nouvelle(nom)

    def _search_etape_fermee(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [("id", "in", etapes_selon(self, est_ferme).ids)]

    def _search_etape_nouvelle(self, operator, value):
        if operator != "in":
            return NotImplemented
        return [("id", "in", etapes_selon(self, est_nouvelle).ids)]
