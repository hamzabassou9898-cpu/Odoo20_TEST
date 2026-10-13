# -*- coding: utf-8 -*-
"""Frise chronologique d'une machine : achat, livraisons, ramassages, entretiens, bris... sur une ligne."""
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.tools.misc import format_date

from .machine_intervention import TYPES

# Couleur de chaque evenement (classes Bootstrap d'Odoo)
COULEURS = {"reception": "secondary", "livraison": "success", "retour": "warning", "deplacement": "secondary",
            "installation": "success", "entretien": "info", "bris": "danger", "reparation": "danger",
            "remplacement": "warning", "ramassage": "warning", "autre": "secondary"}
MAX_EVENEMENTS = 14


class StockLot(models.Model):
    _inherit = "stock.lot"

    frise_html = fields.Html("Vie de la machine", compute="_compute_frise", sanitize=False)

    def _evenements_frise(self):
        """Evenements de la machine, du plus ancien au plus recent : (date, cle, libelle)."""
        self.ensure_one()
        evenements = []
        lignes = self.env["stock.move.line"].sudo().search(
            [("lot_id", "=", self.id), ("state", "=", "done")], order="date, id")
        for ligne in lignes:
            source, destination = ligne.location_id.usage, ligne.location_dest_id.usage
            client = ligne.picking_id.partner_id or ligne.move_id.partner_id
            if destination == "customer":
                cle, libelle = "livraison", self.env._("Livrée · %s", client.name) if client else self.env._("Livrée")
            elif source == "customer":
                cle, libelle = "retour", self.env._("Ramassée · %s", client.name) if client else self.env._("Ramassée")
            elif source in ("supplier", "inventory"):
                cle, libelle = "reception", self.env._("Entrée en stock")
            else:
                continue   # deplacement interne : pas utile a Josef
            evenements.append((ligne.date, cle, libelle))
        types = dict(TYPES)
        for interv in self.sudo().intervention_ids.filtered(lambda i: i.state == "fait").sorted("date"):
            libelle = types.get(interv.type, interv.type)
            if interv.type in ("bris", "reparation") and interv.description:
                libelle = "%s · %s" % (libelle, interv.description[:25])
            evenements.append((interv.date, interv.type, libelle))
        evenements.sort(key=lambda e: e[0] or fields.Datetime.now())
        return evenements

    @api.depends("intervention_ids.state", "intervention_ids.date", "date_prochain_entretien")
    def _compute_frise(self):
        for lot in self:
            if not lot.id or not lot.est_machine:
                lot.frise_html = False
                continue
            evenements = lot._evenements_frise()
            if not evenements:
                lot.frise_html = Markup('<p class="text-muted mb-0">%s</p>') % self.env._(
                    "Aucun événement pour l'instant (pas encore livrée ni entretenue).")
                continue
            plus_anciens = len(evenements) - MAX_EVENEMENTS
            points = []
            for date, cle, libelle in evenements[-MAX_EVENEMENTS:]:
                points.append(Markup(
                    '<div class="d-flex flex-column align-items-center text-center" style="min-width:110px">'
                    '<span class="badge rounded-pill text-bg-%s text-wrap" style="max-width:150px">%s</span>'
                    '<div style="width:2px;height:10px;background:#d0d4db"></div>'
                    '<small class="text-muted">%s</small></div>') % (
                    COULEURS.get(cle, "secondary"), escape(libelle),
                    format_date(self.env, date, date_format="MMM yyyy") if date else ""))
            clients = {libelle for _d, cle, libelle in evenements if cle == "livraison"}
            resume = [
                (len(clients), self.env._("Clients")),
                (sum(1 for e in evenements if e[1] == "entretien"), self.env._("Entretiens")),
                (sum(1 for e in evenements if e[1] in ("bris", "reparation")), self.env._("Bris / réparations")),
            ]
            cartes = Markup("").join(
                Markup('<div class="border rounded px-3 py-2"><div class="fs-4 fw-bold">%s</div>'
                       '<div class="small text-muted">%s</div></div>') % (nombre, texte) for nombre, texte in resume)
            if lot.date_prochain_entretien:
                cartes += Markup('<div class="border rounded px-3 py-2"><div class="fs-4 fw-bold">%s</div>'
                                 '<div class="small text-muted">%s</div></div>') % (
                    format_date(self.env, lot.date_prochain_entretien, date_format="d MMM yyyy"),
                    self.env._("Prochain entretien"))
            debut = Markup('<small class="text-muted me-2">%s</small>') % self.env._(
                "+%s plus anciens", plus_anciens) if plus_anciens > 0 else Markup("")
            lot.frise_html = Markup(
                '<div class="d-flex align-items-start gap-1 overflow-auto pb-2" '
                'style="background:linear-gradient(#e3e5ea,#e3e5ea) 0 11px/100%% 3px no-repeat">%s%s</div>'
                '<div class="d-flex flex-wrap gap-2 mt-2">%s</div>') % (debut, Markup("").join(points), cartes)
