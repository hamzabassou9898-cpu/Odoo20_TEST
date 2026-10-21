# -*- coding: utf-8 -*-
"""Portail livreurs : informations d'affichage des tournees (livraisons et ramassages)."""
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.tools.misc import format_datetime

from odoo.addons.suivi_machines_helpdesk.models.etapes import domaine_nom, est_ferme, ou

# Appels de service : bons de livraison montres dans la colonne « Livraison & installation / Reprise »
LIMITE_BONS_KANBAN = 6
MOTS_ETAPE_LIVRAISON = ("reprise", "installation", "livraison")
# Colonnes Resolu / Annule : bons valides ou annules depuis 30 jours (les plus recents)
JOURS_LIVRAISONS_RECENTES = 30


def domaine_ou(mots):
    return ou([("name", "ilike", m) for m in mots])
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
    def _domaine_livraisons(self):
        """Livraisons chez le client de machines et d'accessoires (produits stockes)."""
        return [("type_tournee", "=", "livraison"), ("move_ids.product_id.is_storable", "=", True)]

    @api.model
    def _domaine_livraisons_a_faire(self):
        """Livraisons pas encore validees."""
        return self._domaine_livraisons() + [("state", "not in", ("done", "cancel"))]

    @api.model
    def _zones_livraisons_kanban(self):
        """Colonne -> bons montres : a faire (Livraison & installation / Reprise), livres (Resolu), annules
        (Annule). Livres et annules : les plus recents, sur JOURS_LIVRAISONS_RECENTES jours."""
        depuis = fields.Datetime.now() - timedelta(days=JOURS_LIVRAISONS_RECENTES)
        return [
            ("a_faire", domaine_ou(MOTS_ETAPE_LIVRAISON), self.env._("Bons de livraison à faire"),
             self._domaine_livraisons_a_faire(), "scheduled_date, id", "scheduled_date"),
            ("livres", domaine_nom("résolu"), self.env._("Bons de livraison validés"),
             self._domaine_livraisons() + [("state", "=", "done"), ("date_done", ">=", depuis)],
             "date_done desc, id desc", "date_done"),
            ("annules", domaine_nom("annul"), self.env._("Bons de livraison annulés"),
             self._domaine_livraisons() + [("state", "=", "cancel"), ("write_date", ">=", depuis)],
             "write_date desc, id desc", "write_date"),
        ]

    @api.model
    def livraisons_kanban_assistance(self):
        """Colonnes des appels de service : les bons de livraison (ce ne sont pas des tickets). A faire en
        haut de « Livraison & installation / Reprise » ; valide : dans Resolu ; annule : dans Annule."""
        if not self.has_access("read"):
            return {"zones": []}
        fuseau = pytz.timezone(FUSEAU)
        aujourdhui = datetime.now(fuseau).date()
        zones = []
        for genre, domaine_etape, titre, domaine, ordre, champ_date in self._zones_livraisons_kanban():
            etapes = self.env["helpdesk.stage"].search(domaine_etape)
            if genre == "a_faire":
                # « Livraison & installation / Reprise » ; jamais une etape Resolu / Annule
                etapes = etapes.filtered(lambda e: not est_ferme(e.name))
            total = self.search_count(domaine) if etapes else 0
            if not total:
                continue
            lignes = []
            for bon in self.search(domaine, order=ordre, limit=LIMITE_BONS_KANBAN):
                moment = bon[champ_date]
                local = moment and pytz.UTC.localize(moment).astimezone(fuseau)
                tech = bon.livreur_id
                lignes.append({
                    "id": bon.id, "nom": bon.name, "client": bon.partner_id.display_name or "",
                    "contrat": bon.origin or "",
                    "quand": format_datetime(self.env, moment, dt_format="EEE d MMM '·' HH 'h' mm") if moment else "",
                    "contenu": bon.machines_tournee or bon.accessoires_tournee or "",
                    "en_retard": bool(genre == "a_faire" and local and local.date() < aujourdhui),
                    "technicien": tech.name or "",
                    "initiales": "".join(m[:1] for m in (tech.name or "").split()[:2]).upper(),
                })
            zones.append({
                "genre": genre, "titre": titre, "etape_ids": etapes.ids, "total": total, "bons": lignes,
                "action": {"type": "ir.actions.act_window", "name": titre, "res_model": "stock.picking",
                           "views": [[False, "list"], [False, "form"]], "domain": domaine,
                           "context": {"create": False}},
            })
        return {"zones": zones}
