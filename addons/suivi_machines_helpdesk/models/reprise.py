# -*- coding: utf-8 -*-
"""Tickets « Reprise » crees automatiquement avant la fin d'une location."""
from datetime import timedelta

from odoo import api, fields, models

PARAM_JOURS = "suivi_machines_helpdesk.jours_avant_reprise"
PARAM_EQUIPE = "suivi_machines_helpdesk.equipe_reprise_id"
PARAM_ETAPE = "suivi_machines_helpdesk.etape_reprise"
ETAPE_DEFAUT = "Reprise de machine"


def _param_int(icp, cle, defaut):
    # Odoo 20 : get_int ; versions precedentes : get_param
    if hasattr(icp, "get_int"):
        return icp.get_int(cle, defaut)
    return int(icp.get_param(cle, defaut) or 0)


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    commande_reprise_id = fields.Many2one("sale.order", "Contrat de location (reprise)",
                                          index="btree_not_null", copy=False, readonly=True)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    ticket_reprise_ids = fields.One2many("helpdesk.ticket", "commande_reprise_id", "Tickets de reprise")
    nb_tickets_reprise = fields.Integer("Nb tickets de reprise", compute="_compute_nb_tickets_reprise")

    def _compute_nb_tickets_reprise(self):
        for order in self:
            order.nb_tickets_reprise = len(order.sudo().ticket_reprise_ids)

    def action_voir_tickets_reprise(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Reprise - %s", self.name),
                "res_model": "helpdesk.ticket", "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")],
                "domain": [("commande_reprise_id", "=", self.id)]}

    @api.model
    def _cron_tickets_reprise(self):
        """Chaque jour : un ticket « Reprise » par machine encore louee dont la location
        se termine dans les X prochains jours (X = parametre, 3 par defaut)."""
        icp = self.env["ir.config_parameter"].sudo()
        jours = _param_int(icp, PARAM_JOURS, 3)
        equipe = _param_int(icp, PARAM_EQUIPE, 0)
        # Etape « Reprise de machine » (nom modifiable par parametre) et son equipe
        nom_etape = (icp.get_str(PARAM_ETAPE, ETAPE_DEFAUT) if hasattr(icp, "get_str")
                     else icp.get_param(PARAM_ETAPE, ETAPE_DEFAUT)) or ETAPE_DEFAUT
        etape = self.env["helpdesk.stage"].search([("name", "=ilike", nom_etape)], limit=1)
        if etape and not equipe and "team_ids" in etape._fields:
            equipe = etape.team_ids[:1].id
        limite = fields.Datetime.now() + timedelta(days=jours)
        commandes = self.search([("type_commande", "=", "location"), ("state", "=", "sale"),
                                 ("date_fin_location", "!=", False), ("date_fin_location", "<=", limite)])
        Ticket = self.env["helpdesk.ticket"].with_context(mail_create_nolog=True)
        crees = Ticket
        for order in commandes:
            client = order.partner_shipping_id or order.partner_id
            for lot in order.machine_ids.filtered(lambda l: l.machine_statut == "chez_client"):
                deja = Ticket.with_context(active_test=False).search_count(
                    [("commande_reprise_id", "=", order.id), ("lot_id", "=", lot.id)])
                if deja:
                    continue
                vals = {
                    "name": self.env._("Reprise - %(machine)s - %(client)s",
                                       machine=lot.ref or lot.name, client=client.display_name),
                    "partner_id": client.id,
                    "code_client": Ticket._code_du_client(client),
                    "lot_id": lot.id,
                    "commande_reprise_id": order.id,
                    "description": self.env._(
                        "<p>Fin de la location le %(date)s (contrat %(contrat)s) : "
                        "reprise de la machine %(serie)s à planifier.</p>",
                        date=fields.Datetime.to_string(order.date_fin_location)[:10],
                        contrat=order.name, serie=lot.name),
                }
                if equipe:
                    vals["team_id"] = equipe
                if etape:
                    vals["stage_id"] = etape.id
                crees |= Ticket.create(vals)
        return crees
