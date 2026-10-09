# -*- coding: utf-8 -*-
"""Phase 2 : techniciens utilisateurs portail (gratuits), assignables aux taches."""
from odoo import fields, models
from odoo.tools import SQL

# Utilisateurs assignables comme technicien : internes, ou portail coches « Technicien »
DOMAINE_TECHNICIEN = "['|', ('share', '=', False), ('partner_id.est_technicien', '=', True)]"


class ResPartner(models.Model):
    _inherit = "res.partner"

    est_technicien = fields.Boolean(
        "Technicien (portail)",
        help="Technicien qui consulte sa journée sur le portail web (utilisateur portail gratuit).")


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

    def _sql_technicien_ticket(self):
        return SQL("COALESCE(t.user_id, t.technicien_terrain_id, t.technicien_id)")


class PortalEntry(models.Model):
    _inherit = "portal.entry"

    def _filter_visible_portal_cards(self):
        visibles = super()._filter_visible_portal_cards()
        carte = self.env.ref("suivi_machines_portail.portal_entry_ma_journee", raise_if_not_found=False)
        if carte and carte in self and self.env.user.est_technicien:
            visibles |= carte
        return visibles
