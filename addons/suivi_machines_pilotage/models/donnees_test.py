# -*- coding: utf-8 -*-
"""Generateur de tickets de test (entretiens et reparations) sur les vraies machines et techniciens.

Tous les tickets crees portent l'etiquette « TEST » : un bouton les supprime en une fois.
"""
import random
from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models
from odoo.exceptions import UserError

PROBLEMES = [
    ("tag_probleme_ne_gele_pas", "La machine ne gèle pas", "Le produit reste liquide depuis ce matin."),
    ("tag_probleme_fait_du_bruit", "Machine fait du bruit", "Bruit de frottement au démarrage du moteur."),
    ("tag_probleme_coule", "La machine coule", "Fuite d'eau sous la machine, le plancher est mouillé."),
    ("tag_probleme_ne_tourne_pas", "La vis ne tourne pas", "Le mélangeur reste immobile."),
    ("tag_probleme_gele_trop", "Gèle trop", "Le produit devient un bloc, impossible de servir."),
    ("tag_probleme_clignote_1", "Voyant clignote 1 fois", "Le voyant de l'écran clignote une fois."),
    ("tag_probleme_alarme_moteur", "Alarme moteur", "L'alarme du moteur sonne, la machine s'arrête."),
    ("tag_probleme_sent_le_brule", "Sent le brûlé", "Odeur de brûlé près du compresseur."),
]
HEURES = [8, 9, 10, 11, 13, 14, 15, 16]


class PilotageDonneesTest(models.TransientModel):
    _name = "pilotage.donnees.test"
    _description = "Tickets de test (entretiens et réparations)"

    nb_entretiens = fields.Integer("Tickets d'entretien", default=8)
    nb_reparations = fields.Integer("Tickets de réparation", default=8)
    jours = fields.Integer("Répartis sur (jours)", default=7, help="À partir d'hier (pour voir des retards).")
    nb_existants = fields.Integer("Tickets de test existants", compute="_compute_nb_existants")

    def _etiquette_test(self):
        return self.env.ref("suivi_machines_pilotage.tag_donnees_test")

    def _compute_nb_existants(self):
        nb = self.env["helpdesk.ticket"].search_count([("tag_ids", "in", self._etiquette_test().ids)])
        for wiz in self:
            wiz.nb_existants = nb

    def _techniciens(self):
        """Techniciens reels : ceux des livraisons, plus les techniciens portail (phase 2)."""
        Users = self.env["res.users"]
        techs = self.env["stock.picking"].search([("livreur_id", "!=", False)]).livreur_id
        if "est_technicien" in Users._fields:
            techs |= Users.search([("partner_id.est_technicien", "=", True)])
        return techs or self.env.user

    def _machines(self):
        """Machines chez les clients ; a defaut, toutes les machines (client pris dans les ventes)."""
        Lot = self.env["stock.lot"]
        lots = Lot.search([("est_machine", "=", True), ("machine_client_id", "!=", False),
                           ("machine_statut", "!=", "hors_service")])
        machines = [(lot, lot.machine_client_id) for lot in lots]
        if not machines:
            clients = self.env["sale.order"].search([], limit=50).partner_id
            lots = Lot.search([("est_machine", "=", True)], limit=50)
            machines = [(lot, clients[i % len(clients)]) for i, lot in enumerate(lots)] if clients else []
        if not machines:
            raise UserError(self.env._("Aucune machine (n° de série) ni client trouvé pour créer des tickets."))
        return machines

    def _assigner(self, user):
        """Technicien portail (phase 2) : technicien terrain ; interne : assigne au ticket."""
        if user.share and "technicien_terrain_id" in self.env["helpdesk.ticket"]._fields:
            return {"technicien_terrain_id": user.id}
        return {"user_id": user.id}

    def _date(self, i):
        tz = self.env.user.tz or "America/Toronto"
        jour = fields.Date.context_today(self.with_context(tz=tz)) + timedelta(days=(i % max(self.jours, 1)) - 1)
        heure = datetime.combine(jour, time(HEURES[i % len(HEURES)]))
        return pytz.timezone(tz).localize(heure).astimezone(pytz.UTC).replace(tzinfo=None)

    def action_generer(self):
        self.ensure_one()
        Ticket = self.env["helpdesk.ticket"].with_context(mail_create_nolog=True, tracking_disable=True)
        test = self._etiquette_test()
        techs, machines = self._techniciens(), self._machines()
        equipe = self.env["sale.order"]._reglages_reprise()["equipe"]
        hasard = random.Random(42)
        crees = Ticket
        retard, semaine = Ticket._etiquettes_entretien()
        etape_entretien = Ticket._etape_contenant("entretien", self.env["helpdesk.team"].browse(equipe) if equipe else None)
        for i in range(self.nb_entretiens):
            lot, client = machines[i % len(machines)]
            date = self._date(i)
            vals = {"name": "ENTRETIEN - %s - %s (TEST)" % (lot.ref or lot.name, client.display_name),
                    "partner_id": client.id, "lot_id": lot.id, "est_entretien": True,
                    "date_entretien_prevu": date.date(), "date_planifiee": date,
                    **self._assigner(techs[i % len(techs)]),
                    "tag_ids": [(6, 0, (test | (retard if date.date() < fields.Date.today() else semaine)).ids)]}
            if equipe:
                vals["team_id"] = equipe
            if etape_entretien:
                vals["stage_id"] = etape_entretien.id
            crees |= Ticket.create(vals)
        for i in range(self.nb_reparations):
            lot, client = machines[(i + self.nb_entretiens) % len(machines)]
            xmlid, titre, detail = PROBLEMES[i % len(PROBLEMES)]
            tag = self.env.ref("suivi_machines_helpdesk." + xmlid, raise_if_not_found=False)
            vals = {"name": "%s (TEST)" % titre, "partner_id": client.id, "lot_id": lot.id,
                    "date_planifiee": self._date(i + hasard.randint(0, 3)),
                    **self._assigner(techs[(i + 1) % len(techs)]),
                    "description": "<p>%s</p><p><i>Ticket de test généré automatiquement.</i></p>" % detail,
                    "tag_ids": [(6, 0, (test | (tag or test)).ids)]}
            if equipe:
                vals["team_id"] = equipe
            crees |= Ticket.create(vals)
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "success", "sticky": False,
                       "title": self.env._("Tickets de test créés"),
                       "message": self.env._("%(nb)s tickets (étiquette TEST) répartis entre %(techs)s.",
                                             nb=len(crees), techs=", ".join(techs.mapped("name"))),
                       "next": {"type": "ir.actions.act_window_close"}},
        }

    def action_supprimer(self):
        tickets = self.env["helpdesk.ticket"].search([("tag_ids", "in", self._etiquette_test().ids)])
        nb = len(tickets)
        tickets.unlink()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "info", "title": self.env._("Tickets de test supprimés"),
                       "message": self.env._("%s tickets supprimés.", nb),
                       "next": {"type": "ir.actions.act_window_close"}},
        }
