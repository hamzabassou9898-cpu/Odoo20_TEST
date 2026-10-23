# -*- coding: utf-8 -*-
"""Planning : la journee d'un technicien. Le superviseur glisse les taches pour choisir l'ordre de la tournee
et donne une heure fixe a celles ou le client attend a une heure precise. Le technicien voit cet ordre sur son
portail, sans pouvoir le changer."""
from datetime import date, datetime, time

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.portail_tache import FUSEAU


class JourneeTechnicien(models.TransientModel):
    _name = "pilotage.journee"
    _description = "Journée d'un technicien (ordre de la tournée)"

    technicien_id = fields.Many2one("res.users", "Technicien", readonly=True)
    jour = fields.Date("Jour", required=True, readonly=True)
    ligne_ids = fields.One2many("pilotage.journee.ligne", "journee_id", "Tâches")

    @api.model
    def default_get(self, fields_list):
        valeurs = super().default_get(fields_list)
        jour = valeurs.get("jour")
        if jour and "ligne_ids" in fields_list:
            Tache = self.env["portail.tache"]
            jour = fields.Date.to_date(jour)
            taches = Tache._taches_journee(valeurs.get("technicien_id") or 0, jour)._trier_tournee()
            fuseau = pytz.timezone(FUSEAU)
            types = dict(Tache._fields["type_tache"]._description_selection(self.env))
            lignes = []
            for rang, tache in enumerate(taches, 1):
                locale = pytz.UTC.localize(tache.date).astimezone(fuseau) if tache.date else None
                lignes.append((0, 0, {
                    "sequence": rang, "tache_ref": tache.id, "type_tache": types.get(tache.type_tache, ""),
                    "client": tache.partner_id.display_name or "", "titre": tache.titre or "",
                    "fait": not tache.a_faire, "heure_fixe": tache.heure_fixe,
                    "heure": locale.hour + locale.minute / 60 if locale else 9.0,
                }))
            valeurs["ligne_ids"] = lignes
        return valeurs

    @api.model
    def action_ouvrir(self, technicien_id, jour_iso):
        """Fenetre « Journée » d'une case du Planning (technicien 0 : taches sans technicien)."""
        try:
            jour = date.fromisoformat(jour_iso)
        except (TypeError, ValueError):
            raise UserError(self.env._("Jour invalide.")) from None
        technicien = self.env["res.users"].browse(technicien_id or 0).exists()
        nom = technicien.name or self.env._("Tâches sans technicien")
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "view_mode": "form",
            "views": [(self.env.ref("suivi_machines_pilotage.view_pilotage_journee_form").id, "form")],
            "target": "new", "name": self.env._("%(nom)s — %(jour)s", nom=nom, jour=jour.strftime("%d/%m/%Y")),
            "context": {"default_technicien_id": technicien.id, "default_jour": jour.isoformat()},
        }

    def action_enregistrer(self):
        """L'ordre des lignes devient l'ordre de la tournee ; l'heure fixe change l'heure de la date prevue."""
        self.ensure_one()
        Tache = self.env["portail.tache"]
        fuseau = pytz.timezone(FUSEAU)
        for rang, ligne in enumerate(self.ligne_ids.sorted(lambda l: (l.sequence, l.id)), 1):
            tache = Tache.browse(ligne.tache_ref).exists()
            if not tache:
                continue
            valeurs = {}
            if tache.ordre_tournee != rang:
                valeurs["ordre_tournee"] = rang
            if tache.heure_fixe != ligne.heure_fixe:
                valeurs["heure_fixe"] = ligne.heure_fixe
            if ligne.heure_fixe and tache.a_faire:
                minutes = round((ligne.heure or 0.0) * 60) % (24 * 60)
                locale = pytz.UTC.localize(tache.date).astimezone(fuseau).date() if tache.date else self.jour
                prevue = fuseau.localize(datetime.combine(locale, time(minutes // 60, minutes % 60)))
                prevue = prevue.astimezone(pytz.UTC).replace(tzinfo=None)
                if prevue != tache.date:
                    valeurs["date"] = prevue
            if valeurs:
                tache.write(valeurs)
        return {"type": "ir.actions.act_window_close"}


class JourneeTechnicienLigne(models.TransientModel):
    _name = "pilotage.journee.ligne"
    _description = "Tâche de la journée d'un technicien"
    _order = "sequence, id"

    journee_id = fields.Many2one("pilotage.journee", required=True, ondelete="cascade")
    sequence = fields.Integer("Ordre", default=10)
    tache_ref = fields.Integer("Réf. tâche")
    type_tache = fields.Char("Type")
    client = fields.Char("Client")
    titre = fields.Char("Tâche")
    fait = fields.Boolean("Faite")
    heure_fixe = fields.Boolean("Heure fixe", help="Le client attend à une heure précise.")
    heure = fields.Float("Heure", default=9.0)
