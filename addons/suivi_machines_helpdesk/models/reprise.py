# -*- coding: utf-8 -*-
"""Tickets « Reprise » crees automatiquement avant la fin d'une location."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

PARAM_JOURS = "suivi_machines_helpdesk.jours_avant_reprise"
PARAM_EQUIPE = "suivi_machines_helpdesk.equipe_reprise_id"
PARAM_ETAPE = "suivi_machines_helpdesk.etape_reprise"
PARAM_RESPONSABLE = "suivi_machines_helpdesk.responsable_reprise_id"
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
    def _reglages_reprise(self):
        icp = self.env["ir.config_parameter"].sudo()
        equipe = _param_int(icp, PARAM_EQUIPE, 0)
        # Etape « Reprise de machine » (nom modifiable par parametre) et son equipe
        nom_etape = (icp.get_str(PARAM_ETAPE, ETAPE_DEFAUT) if hasattr(icp, "get_str")
                     else icp.get_param(PARAM_ETAPE, ETAPE_DEFAUT)) or ETAPE_DEFAUT
        etape = self.env["helpdesk.stage"].search([("name", "=ilike", nom_etape)], limit=1)
        if etape and not equipe and "team_ids" in etape._fields:
            equipe = etape.team_ids[:1].id
        # Responsable de la planification : parametre, sinon l'administrateur
        responsable = self.env["res.users"].browse(_param_int(icp, PARAM_RESPONSABLE, 0)).exists() \
            or self.env.ref("base.user_admin", raise_if_not_found=False)
        return {"jours": _param_int(icp, PARAM_JOURS, 3), "equipe": equipe, "etape": etape,
                "responsable": responsable}

    def _machines_a_reprendre(self):
        """Machines de la commande encore chez un client (pas revenues en entrepot)."""
        self.ensure_one()
        return self.machine_ids.filtered(lambda l: l.machine_client_id)

    @api.model
    def _cron_tickets_reprise(self):
        """Chaque jour : un ticket « Reprise » par machine encore louee dont la location
        se termine dans les X prochains jours (X = parametre, 3 par defaut)."""
        reglages = self._reglages_reprise()
        limite = fields.Datetime.now() + timedelta(days=reglages["jours"])
        commandes = self.search([("type_commande", "=", "location"), ("state", "=", "sale"),
                                 ("date_fin_location", "!=", False), ("date_fin_location", "<=", limite)])
        return commandes._creer_tickets_reprise(reglages)

    def _creer_tickets_reprise(self, reglages=None):
        reglages = reglages or self._reglages_reprise()
        Ticket = self.env["helpdesk.ticket"].with_context(mail_create_nolog=True)
        crees = Ticket
        for order in self:
            client = order.partner_shipping_id or order.partner_id
            date_fin = (fields.Datetime.to_string(order.date_fin_location)[:10]
                        if order.date_fin_location else "?")
            for lot in order._machines_a_reprendre():
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
                        date=date_fin, contrat=order.name, serie=lot.name),
                }
                if reglages["equipe"]:
                    vals["team_id"] = reglages["equipe"]
                if reglages["etape"]:
                    vals["stage_id"] = reglages["etape"].id
                ticket = Ticket.create(vals)
                if reglages["responsable"] and "activity_ids" in ticket._fields:
                    ticket.activity_schedule(
                        "mail.mail_activity_data_todo",
                        date_deadline=fields.Date.to_date(order.date_fin_location) or fields.Date.context_today(self),
                        summary=self.env._("Planifier ramassage de machine"),
                        note=self.env._("Planifier le ramassage de la machine %(serie)s chez %(client)s "
                                        "(fin de location le %(date)s).", serie=lot.name,
                                        client=client.display_name, date=date_fin),
                        user_id=reglages["responsable"].id)
                crees |= ticket
        return crees

    def action_creer_tickets_reprise(self):
        """Bouton du contrat : cree le ticket de reprise maintenant (sans attendre le delai),
        sinon explique pourquoi ce n'est pas possible."""
        self.ensure_one()
        if self.type_commande != "location":
            raise UserError(self.env._("Ce bon n'est pas une location (Type = Vente)."))
        if self.state != "sale":
            raise UserError(self.env._("Confirmez d'abord le contrat de location."))
        tickets = self._creer_tickets_reprise()
        if tickets:
            return self._action_tickets(tickets)
        if self.ticket_reprise_ids:
            return self.action_voir_tickets_reprise()
        lignes = [self.env._("Aucune machine de ce contrat n'est actuellement chez le client.")]
        if not self.machine_ids:
            lignes.append(self.env._("Aucun numéro de série sur le contrat ni sur sa livraison "
                                     "(choisissez-le sur la ligne ou dans la livraison)."))
        for lot in self.machine_ids:
            lignes.append(self.env._("- %(serie)s : %(statut)s, emplacement %(empl)s",
                                     serie=lot.name, statut=dict(lot._fields["machine_statut"].selection).get(
                                         lot.machine_statut, lot.machine_statut),
                                     empl=lot.location_id.display_name or "?"))
        if not self.date_fin_location:
            lignes.append(self.env._("Date de fin de location absente."))
        raise UserError("\n".join(lignes))

    def _action_tickets(self, tickets):
        if len(tickets) == 1:
            return {"type": "ir.actions.act_window", "res_model": "helpdesk.ticket", "res_id": tickets.id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "name": self.env._("Reprise - %s", self.name),
                "res_model": "helpdesk.ticket", "view_mode": "list,form",
                "views": [(False, "list"), (False, "form")], "domain": [("id", "in", tickets.ids)]}
