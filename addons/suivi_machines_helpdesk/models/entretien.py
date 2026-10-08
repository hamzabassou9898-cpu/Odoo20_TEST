# -*- coding: utf-8 -*-
"""Tickets « Entretien » automatiques + etiquettes « en retard » / « a faire cette semaine »."""
from datetime import timedelta

from odoo import api, fields, models

from .reprise import _param_int

PARAM_JOURS_ENTRETIEN = "suivi_machines_helpdesk.jours_avant_entretien"


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    est_entretien = fields.Boolean("Ticket d'entretien", readonly=True, copy=False, index=True)
    date_entretien_prevu = fields.Date("Entretien prévu le", readonly=True, copy=False)

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
            elif ticket.date_entretien_prevu < aujourdhui:
                ticket.tag_ids = [(3, semaine.id), (4, retard.id)]

        # 2) Nouveaux tickets
        lots = self.env["stock.lot"].search([("est_machine", "=", True), ("machine_client_id", "!=", False),
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
                "name": self.env._("Entretien - %(machine)s - %(client)s",
                                   machine=lot.ref or lot.name, client=client.display_name),
                "partner_id": client.id,
                "code_client": Ticket._code_du_client(client),
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
                    note=self.env._("Planifier l'entretien de la machine %(serie)s chez %(client)s.",
                                    serie=lot.name, client=client.display_name),
                    user_id=reglages["responsable"].id)
            crees |= ticket
        return crees

    @api.model
    def _action_verifier_entretiens(self):
        """Menu « Verifier les entretiens » : lance la verification et affiche un resume."""
        crees = self._cron_tickets_entretien()
        Lot = self.env["stock.lot"]
        chez_client = Lot.search([("est_machine", "=", True), ("machine_client_id", "!=", False)])
        sans_date = chez_client.filtered(lambda l: not l.date_prochain_entretien)
        avec_date = (chez_client - sans_date).sorted("date_prochain_entretien")
        lignes = [self.env._("%s ticket(s) d'entretien créé(s).", len(crees)),
                  self.env._("%s machine(s) chez un client.", len(chez_client))]
        if sans_date:
            lignes.append(self.env._("%(nb)s sans date d'entretien (aucun entretien ni installation connus) : %(liste)s",
                                     nb=len(sans_date), liste=", ".join(sans_date[:10].mapped("name"))))
        if avec_date:
            prochain = avec_date[0]
            lignes.append(self.env._("Prochaine échéance : %(serie)s chez %(client)s le %(date)s.",
                                     serie=prochain.name, client=prochain.machine_client_id.display_name,
                                     date=fields.Date.to_string(prochain.date_prochain_entretien)))
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": self.env._("Vérification des entretiens"), "message": "\n".join(lignes),
                           "sticky": True, "type": "success" if crees else "info"}}

    def action_nouvelle_intervention(self):
        action = super().action_nouvelle_intervention()
        if self.est_entretien:
            action["context"]["default_type"] = "entretien"
        return action
