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
    machines_reprise_ids = fields.Many2many("stock.lot", "helpdesk_ticket_reprise_lot_rel", "ticket_id", "lot_id",
                                            string="Machines à reprendre", copy=False)
    est_reprise = fields.Boolean(compute="_compute_est_reprise")

    @api.depends("commande_reprise_id")
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
        icp = self.env["ir.config_parameter"].sudo()
        nom = (icp.get_str(PARAM_ETAPE, ETAPE_DEFAUT) if hasattr(icp, "get_str")
               else icp.get_param(PARAM_ETAPE, ETAPE_DEFAUT)) or ETAPE_DEFAUT
        for ticket in self:
            etape = self._etape_reprise(nom, equipe=ticket.team_id if "team_id" in ticket._fields else None)
            if etape and ticket.stage_id != etape:
                ticket.stage_id = etape

    def _est_ferme(self):
        nom = (self.stage_id.name or "").lower()
        return any(mot in nom for mot in ("résolu", "resolu", "annul", "clôtur", "clotur"))

    def _nommer_reprise(self):
        for ticket in self:
            lots = ticket.machines_reprise_ids or ticket.lot_id
            refs = [l.ref or l.name for l in lots]
            machines = ", ".join(refs[:4]) + (self.env._(" +%s", len(refs) - 4) if len(refs) > 4 else "")
            client = ticket.partner_id.name or ""
            ticket.name = self.env._("Reprise - %(machines)s - %(client)s", machines=machines, client=client)
            fin = (fields.Datetime.to_string(ticket.date_fin_reprise)[:10] if ticket.date_fin_reprise else "?")
            ticket.description = self.env._(
                "<p>Fin de la location le %(date)s (contrat %(contrat)s) : reprise à planifier de "
                "%(nb)s machine(s) : %(series)s.</p>", date=fin, contrat=ticket.commande_reprise_id.name,
                nb=len(lots), series=", ".join(lots.mapped("name")))

    def _tickets_du_contrat(self):
        """Tickets de reprise du meme contrat dont la machine est encore chez le client.
        Ticket « Ramassage » cree a la main : seulement ses machines."""
        self.ensure_one()
        if self.origine_auto != "reprise":
            return self
        tickets = self.commande_reprise_id.ticket_reprise_ids.filtered(
            lambda t: (t.machines_reprise_ids | t.lot_id).filtered("machine_client_id"))
        return tickets | self

    def action_ramassage(self):
        """Un seul bon de retour pour toutes les machines du contrat encore chez le client,
        une ligne par machine avec SON numero de serie ; lie aux tickets de reprise."""
        self.ensure_one()
        tickets = self._tickets_du_contrat()
        tickets._mettre_en_reprise()
        Picking = self.env["stock.picking"]
        encours = Picking.search([("ticket_assistance_id", "in", tickets.ids),
                                  ("state", "not in", ("done", "cancel")),
                                  ("location_dest_id.usage", "=", "internal")], limit=1)
        if encours:
            return self._ouvrir_picking(encours)
        lots = (tickets.machines_reprise_ids | tickets.lot_id).filtered("machine_client_id")
        livraisons = self.commande_reprise_id.picking_ids.filtered(
            lambda p: p.state == "done" and p.location_dest_id.usage != "internal"
            and p.move_line_ids.lot_id & lots).sorted("date_done", reverse=True)
        if not lots or not livraisons:
            raise UserError(self.env._(
                "Aucune livraison terminée des machines de ce contrat : utilisez le bouton "
                "Retour du contrat (application Location)."))
        retour = livraisons[0]._create_return()
        source, destination = retour.location_id, retour.location_dest_id
        retour.move_ids.unlink()
        Move = self.env["stock.move"]
        for lot in lots:
            Move.create({"product_id": lot.product_id.id, "product_uom_qty": 1,
                         "uom_id": lot.product_id.uom_id.id, "picking_id": retour.id,
                         "location_id": source.id, "location_dest_id": destination.id,
                         "machine_lot_id": lot.id, "partner_id": retour.partner_id.id})
        # Accessoires loues avec le contrat (pompes, etc.) : quantite livree pas encore revenue
        accessoires = []
        # Accessoires seulement si toutes les machines du contrat reviennent
        tout_le_contrat = not (self.commande_reprise_id._machines_a_reprendre() - lots)
        for ligne in self.commande_reprise_id.order_line if tout_le_contrat else []:
            produit = ligne.product_id
            if (not produit or not produit.is_storable or produit.categ_id.suivi_machine
                    or ligne.qty_delivered <= 0):
                continue
            Move.create({"product_id": produit.id, "product_uom_qty": ligne.qty_delivered,
                         "uom_id": ligne.product_uom_id.id, "picking_id": retour.id,
                         "location_id": source.id, "location_dest_id": destination.id,
                         "partner_id": retour.partner_id.id})
            accessoires.append("%s x %s" % (ligne.qty_delivered, produit.display_name))
        retour.write({"ticket_assistance_id": self.id})
        retour.action_confirm()
        retour.action_assign()
        # Retour depuis le client (pas de reservation) : chaque ligne = la machine de son mouvement
        for move in retour.move_ids:
            lignes = move.move_line_ids
            if move.machine_lot_id:
                vals = {"lot_id": move.machine_lot_id.id, "quantity": 1}
            elif move.has_tracking in ("lot", "serial"):
                continue   # accessoire suivi par lot : numero a indiquer dans « Details »
            else:
                vals = {"quantity": move.product_uom_qty}
            if lignes:
                lignes[:1].write(vals)
                lignes[1:].unlink()
            else:
                self.env["stock.move.line"].create(dict(vals, **{
                    "move_id": move.id, "picking_id": retour.id, "product_id": move.product_id.id,
                    "location_id": source.id, "location_dest_id": destination.id}))
        retour.message_post(body=self.env._(
            "Ramassage de %(nb)s machine(s) (%(series)s)%(acc)s, créé depuis le ticket %(ticket)s.",
            nb=len(lots), series=", ".join(lots.mapped("name")),
            acc=(self.env._(" et des accessoires : %s", ", ".join(accessoires)) if accessoires else ""),
            ticket=self.display_name))
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
        return {"jours": _param_int(icp, PARAM_JOURS, 30), "equipe": equipe, "etape": etape,
                "responsable": responsable}

    def _prolonger_location(self, nouvelle_date_fin, note=None):
        """Renouvellement : meme contrat, nouvelle date de fin (application Location si installee)."""
        self.ensure_one()
        if self.date_fin_location and nouvelle_date_fin <= self.date_fin_location:
            raise UserError(self.env._("La nouvelle date doit être après la fin actuelle."))
        champ = "rental_return_date" if "rental_return_date" in self._fields else "date_fin_location"
        self.write({champ: nouvelle_date_fin})
        if champ != "date_fin_location":
            self.date_fin_location = nouvelle_date_fin
        message = self.env._("Location prolongée jusqu'au %s.", fields.Datetime.to_string(nouvelle_date_fin)[:10])
        if note:
            message += " " + note
        self.message_post(body=message)
        return message

    def _machines_a_reprendre(self):
        """Machines de la commande encore chez un client (pas revenues en entrepot)."""
        self.ensure_one()
        return self.machine_ids.filtered(lambda l: l.machine_client_id)

    @api.model
    def _cron_tickets_reprise(self):
        """Chaque jour : un ticket « Reprise » par machine encore louee dont la location
        se termine dans les X prochains jours (X = parametre, 30 par defaut)."""
        reglages = self._reglages_reprise()
        limite = fields.Datetime.now() + timedelta(days=reglages["jours"])
        commandes = self.search([("type_commande", "=", "location"), ("state", "=", "sale"),
                                 ("date_fin_location", "!=", False), ("date_fin_location", "<=", limite)])
        return commandes._creer_tickets_reprise(reglages)

    def _creer_tickets_reprise(self, reglages=None):
        """Un seul ticket de reprise par contrat (et par date de fin) regroupant toutes ses
        machines encore chez le client ; une machine ajoutee plus tard rejoint le ticket ouvert."""
        reglages = reglages or self._reglages_reprise()
        Ticket = self.env["helpdesk.ticket"].with_context(mail_create_nolog=True)
        crees = Ticket
        for order in self:
            client = order.partner_shipping_id or order.partner_id
            existants = Ticket.with_context(active_test=False).search(
                [("commande_reprise_id", "=", order.id), ("date_fin_reprise", "=", order.date_fin_location)])
            deja = existants.machines_reprise_ids | existants.lot_id
            lots = order._machines_a_reprendre() - deja
            if not lots:
                continue
            # On complete seulement un ticket cree par Odoo (jamais un ticket ecrit a la main)
            ouvert = existants.filtered(lambda t: not t._est_ferme() and t.origine_auto == "reprise")[:1]
            if ouvert:
                ouvert.machines_reprise_ids = [(4, lot.id) for lot in lots]
                ouvert._nommer_reprise()
                continue
            vals = {
                "partner_id": client.id,
                "code_client": Ticket._code_du_client(client),
                "lot_id": lots[:1].id,
                "machines_reprise_ids": [(6, 0, lots.ids)],
                "commande_reprise_id": order.id,
                "origine_auto": "reprise",
                "date_fin_reprise": order.date_fin_location,
                "name": self.env._("Reprise"),
            }
            if reglages["equipe"]:
                vals["team_id"] = reglages["equipe"]
            ticket = Ticket.create(vals)
            ticket._nommer_reprise()
            ticket._mettre_en_reprise()
            if reglages["responsable"] and "activity_ids" in ticket._fields:
                ticket.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=fields.Date.to_date(order.date_fin_location) or fields.Date.context_today(self),
                    summary=self.env._("Planifier ramassage de machine"),
                    note=self.env._("Planifier le ramassage de %(nb)s machine(s) (%(series)s) chez %(client)s.",
                                    nb=len(lots), series=", ".join(lots.mapped("name")),
                                    client=client.display_name),
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
        message = self.ticket_id.commande_reprise_id._prolonger_location(self.nouvelle_date_fin, self.note)
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
