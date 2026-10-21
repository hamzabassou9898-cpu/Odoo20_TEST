# -*- coding: utf-8 -*-
"""Portail livreurs : informations d'affichage des tournees (livraisons et ramassages)."""
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.tools.misc import format_datetime

from odoo.addons.suivi_machines_helpdesk.models.etapes import ou

# Appels de service : bons de livraison montres dans la colonne « Livraison & installation / Reprise »
LIMITE_BONS_KANBAN = 6
MOTS_ETAPE_LIVRAISON = ("reprise", "installation", "livraison")
# Meme fuseau que le Portail techniciens (portail_tache.FUSEAU ; pas importe : ordre de chargement des modeles)
FUSEAU = "America/Toronto"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    type_tournee = fields.Selection(
        [("livraison", "Livraison"), ("ramassage", "Ramassage"), ("autre", "Autre")],
        "Type de tournée", compute="_compute_type_tournee", store=True, index=True)
    date_tournee = fields.Char("Date de la tournée", compute="_compute_affichage_tournee")
    machines_tournee = fields.Char("Machines", compute="_compute_affichage_tournee")
    accessoires_tournee = fields.Char("Accessoires", compute="_compute_affichage_tournee")

    @api.depends("location_id.usage", "location_dest_id.usage", "company_id")
    def _compute_type_tournee(self):
        for picking in self:
            # Chez le client : emplacement Clients, ou l'emplacement interne « Location » (machines louees)
            societe = picking.company_id or self.env.company
            location = societe.rental_loc_id if "rental_loc_id" in societe._fields else self.env["stock.location"]

            def chez_client(emplacement):
                return emplacement.usage == "customer" or (location and emplacement == location)

            if chez_client(picking.location_dest_id) and not chez_client(picking.location_id):
                picking.type_tournee = "livraison"
            elif chez_client(picking.location_id) and not chez_client(picking.location_dest_id):
                picking.type_tournee = "ramassage"
            else:
                picking.type_tournee = "autre"

    @api.depends("scheduled_date", "move_ids.machine_lot_id", "move_ids.move_line_ids.lot_id",
                 "move_ids.product_uom_qty")
    def _compute_affichage_tournee(self):
        for picking in self:
            date = format_datetime(self.env, picking.scheduled_date, dt_format="EEE d MMM '·' HH 'h' mm") \
                if picking.scheduled_date else ""
            picking.date_tournee = date[:1].upper() + date[1:]
            lots = (picking.move_ids.machine_lot_id | picking.move_ids.move_line_ids.lot_id).filtered("est_machine")
            machines = ["%s (%s)" % (l.ref, l.name) if l.ref else l.name for l in lots]
            # Machines sans numero encore choisi (ex. retour cree depuis Location)
            sans_numero = picking.move_ids.filtered(
                lambda m: m.product_id.categ_id.suivi_machine and m.product_uom_qty > 0
                and not (m.machine_lot_id | m.move_line_ids.lot_id))
            machines += [self.env._("%(qte)g × %(produit)s (n° à préciser)", qte=m.product_uom_qty,
                                    produit=m.product_id.name) for m in sans_numero]
            picking.machines_tournee = ", ".join(machines) or False
            autres = picking.move_ids.filtered(
                lambda m: not m.product_id.categ_id.suivi_machine and m.product_uom_qty > 0)
            picking.accessoires_tournee = ", ".join(
                "%g × %s" % (m.product_uom_qty, m.product_id.name) for m in autres) or False

    # ------------------------------------------------------------ bons de livraison dans les appels de service
    @api.model
    def _domaine_livraisons_a_faire(self):
        """Livraisons chez le client (machines et accessoires) pas encore validees."""
        return [("type_tournee", "=", "livraison"), ("state", "not in", ("done", "cancel")),
                ("move_ids.product_id.is_storable", "=", True)]

    @api.model
    def livraisons_kanban_assistance(self):
        """Colonne « Livraison & installation / Reprise » des appels de service : les bons de livraison a
        faire (ce ne sont pas des tickets ; un bon valide n'y est plus)."""
        vide = {"etape_ids": [], "total": 0, "bons": []}
        if not self.has_access("read"):
            return vide
        etapes = self.env["helpdesk.stage"].search(ou([("name", "ilike", m) for m in MOTS_ETAPE_LIVRAISON]))
        if not etapes:
            return vide
        domaine = self._domaine_livraisons_a_faire()
        bons = self.search(domaine, order="scheduled_date, id", limit=LIMITE_BONS_KANBAN)
        fuseau = pytz.timezone(FUSEAU)
        aujourdhui = datetime.now(fuseau).date()
        lignes = []
        for bon in bons:
            prevu = bon.scheduled_date and pytz.UTC.localize(bon.scheduled_date).astimezone(fuseau).date()
            tech = bon.livreur_id
            lignes.append({
                "id": bon.id, "nom": bon.name, "client": bon.partner_id.display_name or "",
                "contrat": bon.origin or "", "quand": bon.date_tournee or "",
                "contenu": bon.machines_tournee or bon.accessoires_tournee or "",
                "en_retard": bool(prevu and prevu < aujourdhui),
                "technicien": tech.name or "",
                "initiales": "".join(m[:1] for m in (tech.name or "").split()[:2]).upper(),
            })
        return {"etape_ids": etapes.ids, "total": self.search_count(domaine), "bons": lignes,
                "action": {"type": "ir.actions.act_window", "name": self.env._("Bons de livraison à faire"),
                           "res_model": "stock.picking", "views": [[False, "list"], [False, "form"]],
                           "domain": domaine, "context": {"create": False}}}
