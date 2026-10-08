# -*- coding: utf-8 -*-
"""Les actions planifiees Reprise et Entretiens se relancent tout de suite apres les evenements
qui les concernent (sans attendre le passage quotidien)."""
from odoo import api, models

CRONS = ("suivi_machines_helpdesk.cron_tickets_reprise", "suivi_machines_helpdesk.cron_tickets_entretien")


def declencher(env, crons=CRONS):
    for xmlid in crons:
        cron = env.ref(xmlid, raise_if_not_found=False)
        if cron and cron.active:
            cron.sudo()._trigger()


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def write(self, vals):
        res = super().write(vals)
        if {"date_fin_location", "rental_return_date", "state", "type_commande"} & set(vals):
            declencher(self.env, CRONS[:1])
        return res


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        if moves.move_line_ids.lot_id.filtered("est_machine"):
            declencher(self.env)
        return moves


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    @api.model_create_multi
    def create(self, vals_list):
        interventions = super().create(vals_list)
        declencher(self.env, CRONS[1:])
        return interventions

    def write(self, vals):
        res = super().write(vals)
        if {"state", "date", "type"} & set(vals):
            declencher(self.env, CRONS[1:])
        return res


class StockLot(models.Model):
    _inherit = "stock.lot"

    def write(self, vals):
        res = super().write(vals)
        if {"intervalle_entretien", "machine_etat"} & set(vals):
            declencher(self.env, CRONS[1:])
        return res
