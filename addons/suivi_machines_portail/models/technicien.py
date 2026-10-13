# -*- coding: utf-8 -*-
"""Phase 2 : techniciens utilisateurs portail (gratuits), assignables aux taches."""
from odoo import api, fields, models
from odoo.tools import SQL

# Utilisateurs assignables comme technicien : internes, ou portail coches « Technicien »
DOMAINE_TECHNICIEN = "['|', ('share', '=', False), ('partner_id.est_technicien', '=', True)]"


class ResPartner(models.Model):
    _inherit = "res.partner"

    est_technicien = fields.Boolean(
        "Technicien (portail)",
        help="Technicien qui consulte sa journée sur le portail web (utilisateur portail gratuit).")
    a_acces_portail = fields.Boolean("Accès portail", compute="_compute_a_acces_portail",
                                     help="Le contact a un utilisateur portail (ex. un technicien).")

    def _compute_a_acces_portail(self):
        for partner in self:
            partner.a_acces_portail = any(user.share for user in partner.sudo().with_context(active_test=False).user_ids)


class ResUsers(models.Model):
    _inherit = "res.users"

    est_technicien = fields.Boolean(related="partner_id.est_technicien")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    livreur_id = fields.Many2one(domain=DOMAINE_TECHNICIEN)


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    # Ancien champ (remplace par « Assigne a ») : garde pour les anciennes donnees, plus affiche
    technicien_terrain_id = fields.Many2one("res.users", "Technicien terrain (ancien)", copy=False)


class PortailTache(models.Model):
    _inherit = "portail.tache"

    _depends = {"helpdesk.ticket": ["technicien_terrain_id"]}

    # Portail techniciens : une colonne par technicien portail, meme sans tache
    technicien_id = fields.Many2one(group_expand="_group_expand_techniciens_portail")

    @api.model
    def _domaine_techniciens_portail(self):
        return [("share", "=", True), ("partner_id.est_technicien", "=", True)]

    @api.model
    def _group_expand_techniciens_portail(self, techniciens, domain):
        return techniciens | self.env["res.users"].search(self._domaine_techniciens_portail())

    def _sql_technicien_ticket(self):
        return SQL("COALESCE(t.user_id, t.technicien_terrain_id, t.technicien_id)")

    @api.model
    def _techniciens_planning(self, taches):
        """Planning : tous les techniciens portail (meme sans tache cette semaine) + ceux qui ont des taches."""
        portail = self.env["res.users"].sudo().search([("partner_id.est_technicien", "=", True)])
        return super()._techniciens_planning(taches) | portail.sudo(False)


class PortalEntry(models.Model):
    _inherit = "portal.entry"

    def _filter_visible_portal_cards(self):
        visibles = super()._filter_visible_portal_cards()
        carte = self.env.ref("suivi_machines_portail.portal_entry_ma_journee", raise_if_not_found=False)
        if carte and carte in self and self.env.user.est_technicien:
            visibles |= carte
        return visibles


class PilotageIndicateur(models.Model):
    _inherit = "pilotage.indicateur"

    @api.model
    def _techniciens_du_tableau(self, taches):
        """Tableau de bord : seulement les techniciens portail (comme le Portail techniciens)."""
        return super()._techniciens_du_tableau(taches).filtered(
            lambda u: u.share and u.partner_id.est_technicien)
