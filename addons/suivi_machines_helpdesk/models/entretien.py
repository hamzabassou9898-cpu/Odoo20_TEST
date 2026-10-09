# -*- coding: utf-8 -*-
"""Tickets « Entretien » automatiques + etiquettes « en retard » / « a faire cette semaine »."""
from datetime import datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .reprise import _param_int

PARAM_JOURS_ENTRETIEN = "suivi_machines_helpdesk.jours_avant_entretien"


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    est_entretien = fields.Boolean("Ticket d'entretien", readonly=True, copy=False, index=True)
    date_entretien_prevu = fields.Date("Entretien prévu le", readonly=True, copy=False)
    date_planifiee = fields.Datetime(
        "Date prévue", compute="_compute_date_planifiee", store=True, readonly=False, copy=False,
        tracking=True, help="Rendez-vous du technicien chez le client (Portail techniciens).")

    @api.depends("date_entretien_prevu")
    def _compute_date_planifiee(self):
        for ticket in self:
            if ticket.date_entretien_prevu and not ticket.date_planifiee:
                # 13 h UTC = 9 h du matin a Quebec
                ticket.date_planifiee = datetime.combine(ticket.date_entretien_prevu, time(13, 0))

    @api.model
    def _etiquettes_entretien(self):
        return (self.env.ref("suivi_machines_helpdesk.tag_entretien_retard"),
                self.env.ref("suivi_machines_helpdesk.tag_entretien_semaine"))

    @api.model
    def _etape_contenant(self, mot, equipe=None):
        Etape = self.env["helpdesk.stage"]
        etapes = Etape.search([("name", "ilike", mot)])
        if equipe and "team_ids" in Etape._fields:
            etapes = etapes.filtered(lambda e: equipe in e.team_ids) or etapes
        return etapes[:1]

    @api.model
    def _ou_est_machine(self, lot):
        """Libelle selon l'Inventaire : client actuel, sinon emplacement (entrepot)."""
        if lot.machine_client_id:
            return lot.machine_client_id.name
        if lot.location_id:
            return self.env._("En entrepôt (%s)", lot.location_id.display_name)
        return self.env._("Sans emplacement")

    @api.model
    def _cron_tickets_entretien(self):
        """Chaque jour : ticket « Entretien » pour chaque machine chez un client dont l'entretien
        est du dans les X jours (7 par defaut) ou en retard ; etiquettes mises a jour."""
        icp = self.env["ir.config_parameter"].sudo()
        jours = _param_int(icp, PARAM_JOURS_ENTRETIEN, 7)
        aujourdhui = fields.Date.context_today(self)
        limite = aujourdhui + timedelta(days=jours)
        retard, semaine = self._etiquettes_entretien()
        reglages = self.env["sale.order"]._reglages_reprise()
        equipe = reglages["equipe"]
        etape = self._etape_contenant("entretien", self.env["helpdesk.team"].browse(equipe) if equipe else None)
        Ticket = self.with_context(mail_create_nolog=True)

        # 1) Tickets deja ouverts : etiquettes a jour (ou retirees si l'entretien a ete fait)
        ouverts = Ticket.search([("est_entretien", "=", True)])
        for ticket in ouverts:
            lot = ticket.lot_id
            if lot.date_prochain_entretien != ticket.date_entretien_prevu:
                ticket.tag_ids = [(3, retard.id), (3, semaine.id)]   # entretien fait
            elif ticket.date_entretien_prevu and ticket.date_entretien_prevu < aujourdhui:
                ticket.tag_ids = [(3, semaine.id), (4, retard.id)]

        # 2) Nouveaux tickets
        # Toutes les machines (chez un client ou en entrepot), sauf hors service
        lots = self.env["stock.lot"].search([("est_machine", "=", True), ("machine_statut", "!=", "hors_service"),
                                             ("date_prochain_entretien", "!=", False),
                                             ("date_prochain_entretien", "<=", limite)])
        crees = Ticket
        for lot in lots:
            if Ticket.with_context(active_test=False).search_count(
                    [("est_entretien", "=", True), ("lot_id", "=", lot.id),
                     ("date_entretien_prevu", "=", lot.date_prochain_entretien)]):
                continue
            client = lot.machine_client_id
            en_retard = lot.date_prochain_entretien < aujourdhui
            vals = {
                "name": self.env._("Entretien - %(machine)s - %(ou)s",
                                   machine=lot.ref or lot.name, ou=self._ou_est_machine(lot)),
                "partner_id": client.id,
                "code_client": Ticket._code_du_client(client) if client else False,
                "lot_id": lot.id,
                "est_entretien": True,
                "date_entretien_prevu": lot.date_prochain_entretien,
                "tag_ids": [(4, (retard if en_retard else semaine).id)],
                "description": self.env._(
                    "<p>Entretien de la machine %(serie)s prévu le %(date)s%(retard)s.</p>",
                    serie=lot.name, date=fields.Date.to_string(lot.date_prochain_entretien),
                    retard=self.env._(" (en retard)") if en_retard else ""),
            }
            if equipe:
                vals["team_id"] = equipe
            ticket = Ticket.create(vals)
            if etape and ticket.stage_id != etape:
                ticket.stage_id = etape
            if reglages["responsable"] and "activity_ids" in ticket._fields:
                ticket.activity_schedule(
                    "mail.mail_activity_data_todo",
                    date_deadline=max(lot.date_prochain_entretien, aujourdhui),
                    summary=self.env._("Planifier entretien"),
                    note=self.env._("Planifier l'entretien de la machine %(serie)s (%(ou)s).",
                                    serie=lot.name, ou=self._ou_est_machine(lot)),
                    user_id=reglages["responsable"].id)
            crees |= ticket
        return crees

    @api.model
    def _action_verifier_entretiens(self):
        """Menu « Verifier les entretiens » : lance la verification et affiche un resume."""
        crees = self._cron_tickets_entretien()
        Lot = self.env["stock.lot"]
        chez_client = Lot.search([("est_machine", "=", True), ("machine_statut", "!=", "hors_service")])
        sans_date = chez_client.filtered(lambda l: not l.date_prochain_entretien)
        avec_date = (chez_client - sans_date).sorted("date_prochain_entretien")
        lignes = [self.env._("%s ticket(s) d'entretien créé(s).", len(crees)),
                  self.env._("%s machine(s) suivie(s).", len(chez_client))]
        if sans_date:
            lignes.append(self.env._("%(nb)s sans date d'entretien (aucun entretien ni installation connus) : %(liste)s",
                                     nb=len(sans_date), liste=", ".join(sans_date[:10].mapped("name"))))
        if avec_date:
            prochain = avec_date[0]
            lignes.append(self.env._("Prochaine échéance : %(serie)s (%(client)s) le %(date)s.",
                                     serie=prochain.name,
                                     client=self._ou_est_machine(prochain),
                                     date=fields.Date.to_string(prochain.date_prochain_entretien)))
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": self.env._("Vérification des entretiens"), "message": "\n".join(lignes),
                           "sticky": True, "type": "success" if crees else "info"}}

    def action_valider_entretien(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Valider l'entretien"),
                "res_model": "suivi.machines.valider.entretien", "view_mode": "form",
                "views": [(False, "form")], "target": "new", "context": {"default_ticket_id": self.id}}

    def action_nouvelle_intervention(self):
        action = super().action_nouvelle_intervention()
        if self.est_entretien:
            action["context"]["default_type"] = "entretien"
        return action


FREQUENCES = [("3", "Tous les 3 mois"), ("6", "Tous les 6 mois"), ("12", "Tous les 12 mois"),
              ("24", "Tous les 24 mois")]


class ValiderEntretien(models.TransientModel):
    _name = "suivi.machines.valider.entretien"
    _description = "Valider un entretien"

    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket d'entretien", required=True)
    lot_id = fields.Many2one(related="ticket_id.lot_id", string="Machine")
    date_entretien = fields.Date("Date de l'entretien", required=True, default=fields.Date.context_today)
    frequence = fields.Selection(FREQUENCES, "Fréquence des entretiens", required=True,
                                 default=lambda s: s._default_frequence())
    technicien_id = fields.Many2one("res.users", "Technicien", required=True,
                                    default=lambda s: s._default_technicien(),
                                    domain="[('share', '=', False)]")
    note = fields.Text("Ce qui a été fait")

    def _ticket_contexte(self):
        return self.env["helpdesk.ticket"].browse(self.env.context.get("default_ticket_id"))

    def _default_frequence(self):
        mois = str(self._ticket_contexte().lot_id.intervalle_entretien or 12)
        return mois if mois in dict(FREQUENCES) else "12"

    def _default_technicien(self):
        return self._ticket_contexte().technicien_id or self.env.user

    def action_valider(self):
        self.ensure_one()
        ticket, lot = self.ticket_id, self.ticket_id.lot_id
        if not lot:
            raise UserError(self.env._("Indiquez d'abord la machine (numéro de série) du ticket."))
        if self.date_entretien > fields.Date.context_today(self):
            raise UserError(self.env._("La date de l'entretien ne peut pas être dans le futur."))
        lot.intervalle_entretien = int(self.frequence)
        self.env["machine.intervention"].create({
            "lot_id": lot.id,
            "type": "entretien",
            "state": "fait",
            "date": fields.Datetime.to_datetime(self.date_entretien).replace(hour=12),
            "user_id": self.technicien_id.id,
            "partner_id": lot.machine_client_id.id or ticket.partner_id.id,
            "ticket_id": ticket.id,
            "description": self.note or ticket.name,
        })
        retard, semaine = ticket._etiquettes_entretien()
        ticket.tag_ids = [(3, retard.id), (3, semaine.id)]
        message = self.env._("Entretien validé le %(date)s par %(tech)s. Prochain entretien : %(prochain)s "
                             "(%(freq)s).", date=fields.Date.to_string(self.date_entretien),
                             tech=self.technicien_id.name,
                             prochain=fields.Date.to_string(lot.date_prochain_entretien),
                             freq=dict(FREQUENCES)[self.frequence].lower())
        ticket.message_post(body=message)
        todo = self.env.ref("mail.mail_activity_data_todo")
        ticket.activity_ids.filtered(lambda a: a.activity_type_id == todo).action_feedback(feedback=message)
        resolu = ticket._etape_contenant("résolu", ticket.team_id if "team_id" in ticket._fields else None)
        if resolu:
            ticket.stage_id = resolu
        return {"type": "ir.actions.act_window_close"}
