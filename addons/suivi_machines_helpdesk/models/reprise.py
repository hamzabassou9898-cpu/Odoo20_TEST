# -*- coding: utf-8 -*-
"""Tickets « Reprise » crees automatiquement avant la fin d'une location."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

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
    date_fin_reprise = fields.Datetime("Fin de location (reprise)", readonly=True, copy=False)
    est_reprise = fields.Boolean(compute="_compute_est_reprise")

    def _compute_est_reprise(self):
        for ticket in self:
            ticket.est_reprise = bool(ticket.commande_reprise_id)

    @api.model
    def _etape_reprise(self, nom=ETAPE_DEFAUT, equipe=None):
        """Etape « Reprise de machine » : nom exact, sinon une etape contenant « reprise »,
        de preference dans l'equipe du ticket."""
        Etape = self.env["helpdesk.stage"]
        etapes = Etape.search([("name", "=ilike", nom)]) or Etape.search([("name", "ilike", "reprise")])
        if equipe and "team_ids" in Etape._fields:
            etapes = etapes.filtered(lambda e: equipe in e.team_ids) or etapes
        return etapes[:1]

    def _mettre_en_reprise(self):
        for ticket in self:
            etape = self._etape_reprise(equipe=ticket.team_id if "team_id" in ticket._fields else None)
            if etape and ticket.stage_id != etape:
                ticket.stage_id = etape

    def _livraison_machine(self):
        """Livraison terminee du contrat qui a fait sortir la machine du ticket."""
        self.ensure_one()
        return self.commande_reprise_id.picking_ids.filtered(
            lambda p: p.state == "done" and p.picking_type_code == "outgoing"
            and self.lot_id in p.move_line_ids.lot_id).sorted("date_done", reverse=True)[:1]

    def action_ramassage(self):
        """Bon de retour de la machine (depuis la livraison du contrat), lie au ticket."""
        self.ensure_one()
        self._mettre_en_reprise()
        encours = self.livraison_ids.filtered(
            lambda p: p.state not in ("done", "cancel") and p.location_dest_id.usage == "internal"
            and self.lot_id in p.move_ids.machine_lot_id)[:1]
        if encours:
            return self._ouvrir_picking(encours)
        livraison = self._livraison_machine()
        if not livraison:
            raise UserError(self.env._(
                "Aucune livraison terminée de la machine %s sur ce contrat : utilisez le bouton "
                "Retour du contrat (application Location).", self.lot_id.name or "?"))
        retour = livraison._create_return()
        moves = retour.move_ids.filtered(lambda m: m.product_id == self.lot_id.product_id)
        (retour.move_ids - moves[:1]).unlink()
        moves[:1].write({"product_uom_qty": 1, "machine_lot_id": self.lot_id.id})
        retour.write({"ticket_assistance_id": self.id})
        retour.action_confirm()
        retour.action_assign()
        # Retour depuis le client (pas de reservation) : indiquer la machine qui revient
        retour.move_ids.move_line_ids.filtered(lambda l: not l.lot_id).write({"lot_id": self.lot_id.id})
        retour.message_post(body=self.env._("Retour créé depuis le ticket %s.", self.display_name))
        return self._ouvrir_picking(retour)

    def _ouvrir_picking(self, picking):
        return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": picking.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def action_prolonger_location(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Prolonger la location"),
                "res_model": "suivi.machines.prolonger.location", "view_mode": "form",
                "views": [(False, "form")], "target": "new", "context": {"default_ticket_id": self.id}}


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
        etape = self.env["helpdesk.ticket"]._etape_reprise(nom_etape)
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
                # Un ticket par machine et par date de fin (une prolongation en cree un nouveau)
                deja = Ticket.with_context(active_test=False).search_count(
                    [("commande_reprise_id", "=", order.id), ("lot_id", "=", lot.id),
                     ("date_fin_reprise", "=", order.date_fin_location)])
                if deja:
                    continue
                vals = {
                    "name": self.env._("Reprise - %(machine)s - %(client)s",
                                       machine=lot.ref or lot.name, client=client.display_name),
                    "partner_id": client.id,
                    "code_client": Ticket._code_du_client(client),
                    "lot_id": lot.id,
                    "commande_reprise_id": order.id,
                    "date_fin_reprise": order.date_fin_location,
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
                # Certaines equipes remettent l'etape par defaut a la creation : on la force
                if reglages["etape"] and ticket.stage_id != reglages["etape"]:
                    ticket.stage_id = reglages["etape"]
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


class ProlongerLocation(models.TransientModel):
    _name = "suivi.machines.prolonger.location"
    _description = "Prolonger une location"

    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket de reprise", required=True)
    commande_id = fields.Many2one(related="ticket_id.commande_reprise_id", string="Contrat")
    date_fin_actuelle = fields.Datetime(related="ticket_id.commande_reprise_id.date_fin_location",
                                        string="Fin actuelle")
    nouvelle_date_fin = fields.Datetime("Nouvelle fin de location", required=True,
                                        default=lambda s: s._default_nouvelle_date())
    note = fields.Text("Note")

    def _default_nouvelle_date(self):
        ticket = self.env["helpdesk.ticket"].browse(self.env.context.get("default_ticket_id"))
        fin = ticket.commande_reprise_id.date_fin_location or fields.Datetime.now()
        return fin + relativedelta(months=1)

    def action_prolonger(self):
        self.ensure_one()
        commande = self.ticket_id.commande_reprise_id
        if self.date_fin_actuelle and self.nouvelle_date_fin <= self.date_fin_actuelle:
            raise UserError(self.env._("La nouvelle date doit être après la fin actuelle."))
        # Application Location : sa date de retour ; sinon notre date de fin
        champ = "rental_return_date" if "rental_return_date" in commande._fields else "date_fin_location"
        commande.write({champ: self.nouvelle_date_fin})
        if champ != "date_fin_location":
            commande.date_fin_location = self.nouvelle_date_fin
        date_txt = fields.Datetime.to_string(self.nouvelle_date_fin)[:10]
        message = self.env._("Location prolongée jusqu'au %s.", date_txt)
        if self.note:
            message += " " + self.note
        commande.message_post(body=message)
        ticket = self.ticket_id
        ticket.message_post(body=message)
        ticket.activity_ids.filtered(
            lambda a: a.activity_type_id == self.env.ref("mail.mail_activity_data_todo")
        ).action_feedback(feedback=message)
        # Ticket resolu (etape « Resolu » si elle existe)
        resolu = self.env["helpdesk.stage"].search([("name", "=ilike", "résolu")], limit=1)
        if resolu:
            ticket.stage_id = resolu
        return {"type": "ir.actions.act_window_close"}
