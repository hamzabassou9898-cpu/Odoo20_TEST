# -*- coding: utf-8 -*-
"""Planning de la semaine : une ligne par technicien, une colonne par jour, glisser-deposer."""
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from .portail_tache import FUSEAU

COULEURS = {"livraison": "success", "ramassage": "warning", "entretien": "info", "reparation": "danger",
            "installation": "primary", "autre": "secondary"}


class PortailTache(models.Model):
    _inherit = "portail.tache"

    @api.model
    def _lundi(self, jour_iso=None):
        fuseau = pytz.timezone(FUSEAU)
        try:
            jour = date.fromisoformat(jour_iso) if jour_iso else datetime.now(fuseau).date()
        except ValueError:
            jour = datetime.now(fuseau).date()
        return jour - timedelta(days=jour.weekday())

    @api.model
    def _vers_utc(self, jour, heure):
        fuseau = pytz.timezone(FUSEAU)
        return fuseau.localize(datetime.combine(jour, heure)).astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _techniciens_planning(self, taches):
        """Lignes du planning : les techniciens qui ont des taches cette semaine (crochet du portail)."""
        return taches.technicien_id

    @api.model
    def donnees_planning(self, jour_iso=None):
        lundi = self._lundi(jour_iso)
        fuseau = pytz.timezone(FUSEAU)
        debut, fin = self._vers_utc(lundi, time.min), self._vers_utc(lundi + timedelta(days=7), time.min)
        aujourdhui = datetime.now(fuseau).date()
        semaine_courante = lundi <= aujourdhui < lundi + timedelta(days=7)
        domaine = [("date", ">=", debut), ("date", "<", fin)]
        if semaine_courante:
            # Taches en retard (pas faites) : dans la colonne d'aujourd'hui, a replanifier
            domaine = ["|", "&", *domaine, "&", ("date", "<", debut), ("etat_suivi", "=", "en_retard")]
        taches = self.search(domaine, order="date, id")
        types = dict(self._fields["type_tache"]._description_selection(self.env))
        techniciens = self._techniciens_planning(taches).sorted(lambda u: (u.name or "").lower())
        jours = []
        for i in range(7):
            jour = lundi + timedelta(days=i)
            jours.append({"iso": jour.isoformat(), "aujourdhui": jour == aujourdhui,
                          "libelle": fields.Date.to_string(jour),
                          "titre": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"][i] + " %s" % jour.day})
        cartes = []
        for tache in taches:
            locale = pytz.UTC.localize(tache.date).astimezone(fuseau)
            cartes.append({
                "id": tache.id, "type": tache.type_tache, "libelle_type": types.get(tache.type_tache, ""),
                "couleur": COULEURS.get(tache.type_tache, "secondary"), "titre": tache.titre or "",
                "client": tache.partner_id.display_name or "", "heure": locale.strftime("%H h %M"),
                "jour": (aujourdhui if locale.date() < lundi else locale.date()).isoformat(),
                "technicien_id": tache.technicien_id.id or 0,
                "etat": tache.etat_suivi, "deplacable": bool(tache.a_faire),
            })
        lignes = [{"id": t.id, "nom": t.name, "initiales": "".join(m[:1] for m in (t.name or "?").split()[:2]).upper()}
                  for t in techniciens]
        lignes.append({"id": 0, "nom": self.env._("Sans technicien"), "initiales": "?"})
        return {"lundi": lundi.isoformat(), "precedente": (lundi - timedelta(days=7)).isoformat(),
                "suivante": (lundi + timedelta(days=7)).isoformat(),
                "titre": self.env._("Semaine du %s", lundi.strftime("%d/%m/%Y")),
                "jours": jours, "lignes": lignes, "cartes": cartes,
                "peut_deplacer": self.env.user.has_group("suivi_machines_pilotage.group_pilotage")}

    @api.model
    def deplacer_planning(self, tache_id, technicien_id, jour_iso):
        """Carte deposee dans une case : nouveau technicien et/ou nouveau jour (meme heure)."""
        tache = self.browse(tache_id).exists()
        if not tache:
            raise UserError(self.env._("Cette tâche n'existe plus : actualisez le planning."))
        if not tache.a_faire:
            raise UserError(self.env._("Cette tâche est déjà faite."))
        fuseau = pytz.timezone(FUSEAU)
        heure = pytz.UTC.localize(tache.date).astimezone(fuseau).time() if tache.date else time(9, 0)
        valeurs = {"technicien_id": technicien_id or False,
                   "date": self._vers_utc(date.fromisoformat(jour_iso), heure)}
        tache.write(valeurs)
        return True
