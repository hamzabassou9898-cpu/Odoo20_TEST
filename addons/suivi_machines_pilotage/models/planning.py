# -*- coding: utf-8 -*-
"""Planning de la semaine : une ligne par technicien, une colonne par jour, glisser-deposer."""
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from .portail_tache import FUSEAU
from .tableau_moderne import COULEURS_TECH

COULEURS = {"livraison": "success", "ramassage": "warning", "entretien": "info", "reparation": "danger",
            "installation": "primary", "autre": "secondary"}
COULEURS_HEX = {"livraison": "#16a34a", "ramassage": "#d97706", "entretien": "#0284c7", "reparation": "#dc2626",
                "installation": "#7c3aed", "autre": "#6b7280"}


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
    def _periode_planning(self, jour, periode):
        """Debut (inclus), fin (exclue), precedente et suivante de la periode affichee."""
        if periode == "jour":
            return jour, jour + timedelta(days=1), jour - timedelta(days=1), jour + timedelta(days=1)
        if periode == "mois":
            debut = jour.replace(day=1)
            fin = (debut + timedelta(days=32)).replace(day=1)
            return debut, fin, (debut - timedelta(days=1)).replace(day=1), fin
        lundi = jour - timedelta(days=jour.weekday())
        return lundi, lundi + timedelta(days=7), lundi - timedelta(days=7), lundi + timedelta(days=7)

    @api.model
    def _domaine_planning(self, debut, fin, technicien_id=False, type_tache=False, retards=False):
        domaine = [("date", ">=", self._vers_utc(debut, time.min)), ("date", "<", self._vers_utc(fin, time.min))]
        if retards:
            # Taches en retard (pas faites) : dans la colonne d'aujourd'hui, a replanifier
            domaine = ["|", "&", *domaine, "&", ("date", "<", self._vers_utc(debut, time.min)),
                       ("etat_suivi", "=", "en_retard")]
        if technicien_id:
            domaine = [*domaine, ("technicien_id", "=", technicien_id if technicien_id > 0 else False)]
        if type_tache:
            domaine = [*domaine, ("type_tache", "=", type_tache)]
        return domaine

    @api.model
    def donnees_planning(self, jour_iso=None, periode="semaine", technicien_id=False, type_tache=False):
        """Planning (jour, semaine ou mois) : grille techniciens x jours, indicateurs et graphiques.
        technicien_id : un technicien, -1 pour « Sans technicien » ; type_tache : un type de tache."""
        periode = periode if periode in ("jour", "semaine", "mois") else "semaine"
        fuseau = pytz.timezone(FUSEAU)
        aujourdhui = datetime.now(fuseau).date()
        jour = self._lundi(jour_iso) if periode == "semaine" else self._jour(jour_iso)
        debut, fin, precedente, suivante = self._periode_planning(jour, periode)
        courante = debut <= aujourdhui < fin
        tout = self.search(self._domaine_planning(debut, fin, retards=courante), order="date, id")
        taches = tout.filtered(lambda t: (not technicien_id or t.technicien_id.id == max(technicien_id, 0))
                               and (not type_tache or t.type_tache == type_tache))
        types = dict(self._fields["type_tache"]._description_selection(self.env))
        techniciens = self._techniciens_planning(tout).sorted(lambda u: (u.name or "").lower())
        if technicien_id:
            techniciens = techniciens.filtered(lambda u: u.id == technicien_id)
        noms_jours = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        jours = []
        for i in range((fin - debut).days):
            d = debut + timedelta(days=i)
            jours.append({"iso": d.isoformat(), "aujourdhui": d == aujourdhui, "libelle": fields.Date.to_string(d),
                          "titre": "%s %s" % (noms_jours[d.weekday()], d.day), "weekend": d.weekday() >= 5})
        cartes = []
        for tache in taches:
            locale = pytz.UTC.localize(tache.date).astimezone(fuseau)
            cartes.append({
                "id": tache.id, "type": tache.type_tache, "libelle_type": types.get(tache.type_tache, ""),
                "couleur": COULEURS.get(tache.type_tache, "secondary"), "titre": tache.titre or "",
                "client": tache.partner_id.display_name or "", "heure": locale.strftime("%H h %M"),
                "jour": (aujourdhui if locale.date() < debut else locale.date()).isoformat(),
                "technicien_id": tache.technicien_id.id or 0,
                "etat": tache.etat_suivi, "deplacable": bool(tache.a_faire),
            })
        lignes = []
        for i, tech in enumerate(techniciens):
            siennes = taches.filtered(lambda t: t.technicien_id == tech)
            lignes.append({"id": tech.id, "nom": tech.name,
                           "initiales": "".join(m[:1] for m in (tech.name or "?").split()[:2]).upper(),
                           "couleur": COULEURS_TECH[i % len(COULEURS_TECH)], "nombre": len(siennes),
                           "en_retard": len(siennes.filtered(lambda t: t.etat_suivi == "en_retard"))})
        if not technicien_id or technicien_id < 0:
            sans = taches.filtered(lambda t: not t.technicien_id)
            lignes.append({"id": 0, "nom": self.env._("Sans technicien"), "initiales": "?", "couleur": "#94a3b8",
                           "nombre": len(sans), "en_retard": len(sans.filtered(lambda t: t.etat_suivi == "en_retard"))})
        if periode == "jour":
            titre = self.env._("%(jour)s %(date)s", jour=noms_jours[debut.weekday()], date=debut.strftime("%d/%m/%Y"))
        elif periode == "mois":
            titre = self.env._("Mois de %s", debut.strftime("%m/%Y"))
        else:
            titre = self.env._("Semaine du %s", debut.strftime("%d/%m/%Y"))
        avant = self.search_count(self._domaine_planning(precedente, debut, technicien_id, type_tache))
        return {"lundi": debut.isoformat(), "debut": debut.isoformat(), "periode": periode,
                # Jour garde en changeant de vue (Jour / Semaine / Mois) : aujourd'hui s'il est dans la periode
                "reference": (aujourdhui if courante else debut).isoformat(),
                "precedente": precedente.isoformat(), "suivante": suivante.isoformat(), "titre": titre,
                "jours": jours, "lignes": lignes, "cartes": cartes,
                "filtres": {"technicien_id": technicien_id or 0, "type_tache": type_tache or "",
                            "techniciens": [{"id": t.id, "nom": t.name} for t in
                                            self._techniciens_planning(tout).sorted(lambda u: (u.name or "").lower())],
                            "types": [{"code": c, "nom": n} for c, n in types.items()]},
                "indicateurs": self._indicateurs_planning(taches, avant, debut),
                "graphiques": self._graphiques_planning(taches, jours, lignes, debut, periode, technicien_id, type_tache),
                "peut_deplacer": self.env.user.has_group("suivi_machines_pilotage.group_pilotage")}

    @api.model
    def _jour(self, jour_iso):
        try:
            return date.fromisoformat(jour_iso) if jour_iso else datetime.now(pytz.timezone(FUSEAU)).date()
        except ValueError:
            return datetime.now(pytz.timezone(FUSEAU)).date()

    @api.model
    def _parametre_planning(self, cle, defaut):
        return self.env["ir.config_parameter"].sudo().get_int("suivi_machines_pilotage.planning_" + cle, defaut) or defaut

    @api.model
    def _indicateurs_planning(self, taches, avant, debut):
        """Cartes du haut. Tendance et % complete : seulement les taches prevues dans la periode (les retards
        reportes d'avant sont comptes a part)."""
        def nb(condition, lot=taches):
            return len(lot.filtered(condition))
        borne = self._vers_utc(debut, time.min)
        prevues = taches.filtered(lambda t: t.date >= borne)
        reparations = nb(lambda t: t.type_tache == "reparation")
        return {
            "total": len(taches), "tendance": round(100 * (len(prevues) - avant) / avant) if avant else False,
            "en_retard": nb(lambda t: t.etat_suivi == "en_retard"),
            "sans_technicien": nb(lambda t: t.a_faire and not t.technicien_id),
            "completion": round(100 * nb(lambda t: t.etat_suivi == "fait", prevues) / len(prevues)) if prevues else 0,
            "objectif": self._parametre_planning("objectif_completion", 90),
            "livraisons": nb(lambda t: t.type_tache == "livraison"),
            "ramassages": nb(lambda t: t.type_tache == "ramassage"),
            "entretiens_reparations": nb(lambda t: t.type_tache == "entretien") + reparations,
            "reparations": reparations,
        }

    @api.model
    def _graphiques_planning(self, taches, jours, lignes, debut, periode, technicien_id, type_tache):
        fuseau = pytz.timezone(FUSEAU)

        def jour_local(tache):
            return pytz.UTC.localize(tache.date).astimezone(fuseau).date()

        # Charge par technicien : par jour (jour, semaine) ou par semaine (mois)
        if periode == "mois":
            semaines = sorted({date.fromisoformat(j["iso"]) - timedelta(days=date.fromisoformat(j["iso"]).weekday())
                               for j in jours})
            colonnes = [(s, s + timedelta(days=7), "S%s" % s.isocalendar()[1]) for s in semaines]
        else:
            colonnes = [(date.fromisoformat(j["iso"]), date.fromisoformat(j["iso"]) + timedelta(days=1),
                         j["titre"].split()[0]) for j in jours]
        series = []
        for ligne in [l for l in lignes if l["id"]][:len(COULEURS_TECH)]:
            siennes = taches.filtered(lambda t: t.technicien_id.id == ligne["id"])
            dates = [max(jour_local(t), debut) for t in siennes]
            series.append({"nom": ligne["nom"], "couleur": ligne["couleur"],
                           "valeurs": [len([d for d in dates if a <= d < b]) for a, b, _l in colonnes]})
        # Repartition par type
        types = dict(self._fields["type_tache"]._description_selection(self.env))
        repartition = [{"nom": types[code], "couleur": COULEURS_HEX.get(code, "#6b7280"), "valeur": nombre}
                       for code in types if (nombre := len(taches.filtered(lambda t: t.type_tache == code)))]
        # Planifiees / faites sur les 12 dernieres semaines (jusqu'a la semaine affichee)
        derniere = debut - timedelta(days=debut.weekday())
        premiere = derniere - timedelta(weeks=11)
        historique = self.search(self._domaine_planning(premiere, derniere + timedelta(days=7), technicien_id,
                                                        type_tache))
        semaines = [premiere + timedelta(weeks=i) for i in range(12)]
        planifiees, faites = [0] * 12, [0] * 12
        for tache in historique:
            rang = (jour_local(tache) - premiere).days // 7
            if 0 <= rang < 12:
                planifiees[rang] += 1
                faites[rang] += tache.etat_suivi == "fait"
        return {"charge": {"etiquettes": [c[2] for c in colonnes], "series": series},
                "repartition": repartition,
                "tendance": {"etiquettes": ["S%s" % s.isocalendar()[1] for s in semaines],
                             "planifiees": planifiees, "faites": faites}}

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
