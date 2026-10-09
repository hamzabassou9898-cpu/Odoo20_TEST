# -*- coding: utf-8 -*-
"""Remplacer des techniciens : transfere les taches ouvertes d'anciens comptes vers les techniciens portail."""
from odoo import api, fields, models
from odoo.exceptions import UserError


class SuiviRemplacerTechniciens(models.TransientModel):
    _name = "suivi.remplacer.techniciens"
    _description = "Remplacer des techniciens"

    ligne_ids = fields.One2many("suivi.remplacer.techniciens.ligne", "wizard_id", "Remplacements")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "ligne_ids" not in fields_list:
            return res
        Users = self.env["res.users"]
        nouveaux = Users.search([("share", "=", True), ("partner_id.est_technicien", "=", True)]) \
            or Users.search([("share", "=", True), ("name", "ilike", "technicien")])
        nouveaux = nouveaux.sorted(lambda u: (u.name or "").lower())
        # Anciens comptes : tous ceux qui ont des taches a faire, sauf les techniciens portail actuels
        anciens = (self.env["portail.tache"].search([("a_faire", "=", True), ("technicien_id", "!=", False)])
                   .technicien_id - nouveaux).sorted(lambda u: (u.name or "").lower())
        # Proposition : les anciens « Technicien ... » associes dans l'ordre aux techniciens portail
        candidats = anciens.filtered(lambda u: "technicien" in (u.name or "").lower() and not u.share)
        lignes = []
        for i, ancien in enumerate(candidats | anciens):
            nouveau = nouveaux[i] if ancien in candidats and i < len(nouveaux) else False
            lignes.append((0, 0, {"ancien_id": ancien.id, "nouveau_id": nouveau and nouveau.id}))
        res["ligne_ids"] = lignes
        return res

    def action_remplacer(self):
        self.ensure_one()
        lignes = self.ligne_ids.filtered(lambda l: l.ancien_id and l.nouveau_id and l.ancien_id != l.nouveau_id)
        if not lignes:
            raise UserError(self.env._("Choisissez au moins un nouveau technicien."))
        bilan = []
        for ligne in lignes:
            nb = ligne._transferer()
            bilan.append("%s → %s : %s" % (ligne.ancien_id.name, ligne.nouveau_id.name, nb))
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"type": "success", "sticky": True, "title": self.env._("Tâches transférées"),
                       "message": "\n".join(bilan),
                       "next": {"type": "ir.actions.act_window_close"}},
        }


class SuiviRemplacerTechniciensLigne(models.TransientModel):
    _name = "suivi.remplacer.techniciens.ligne"
    _description = "Remplacement d'un technicien"

    wizard_id = fields.Many2one("suivi.remplacer.techniciens", required=True, ondelete="cascade")
    ancien_id = fields.Many2one("res.users", "Ancien compte", required=True,
                                context={"active_test": False})
    nouveau_id = fields.Many2one("res.users", "Technicien portail", domain="[('share', '=', True)]")
    nb_taches = fields.Integer("Tâches à faire", compute="_compute_nb_taches")

    @api.depends("ancien_id")
    def _compute_nb_taches(self):
        Tache = self.env["portail.tache"]
        for ligne in self:
            ligne.nb_taches = Tache.search_count([("technicien_id", "=", ligne.ancien_id.id),
                                                  ("a_faire", "=", True)]) if ligne.ancien_id else 0

    def _transferer(self):
        """Transfere les taches ouvertes ; l'historique (fait, annule) reste a l'ancien compte."""
        self.ensure_one()
        ancien, nouveau = self.ancien_id, self.nouveau_id
        nb = 0
        # Livraisons et ramassages pas encore faits
        pickings = self.env["stock.picking"].search([("livreur_id", "=", ancien.id),
                                                     ("state", "not in", ("done", "cancel"))])
        pickings.write({"livreur_id": nouveau.id})
        nb += len(pickings)
        # Tickets ouverts (assigne, technicien terrain ou technicien de la derniere intervention)
        tickets = self.env["helpdesk.ticket"].search([
            "|", "|", ("user_id", "=", ancien.id), ("technicien_terrain_id", "=", ancien.id),
            ("technicien_id", "=", ancien.id)]).filtered(lambda t: not t._est_ferme())
        tickets.write({"user_id": nouveau.id, "technicien_terrain_id": False})
        nb += len(tickets)
        # Interventions planifiees
        interventions = self.env["machine.intervention"].search([("user_id", "=", ancien.id),
                                                                 ("state", "=", "planifie")])
        interventions.write({"user_id": nouveau.id})
        nb += len(interventions)
        if nouveau.share:
            nouveau.partner_id.sudo().est_technicien = True
        return nb
