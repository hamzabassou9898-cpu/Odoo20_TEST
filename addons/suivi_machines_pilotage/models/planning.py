# -*- coding: utf-8 -*-
"""Planning de la semaine : une ligne par technicien, une colonne par jour, glisser-deposer."""
from collections import Counter, defaultdict
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
        return [*domaine, *self._domaine_techniciens_planning()]

    @api.model
    def _domaine_techniciens_planning(self):
        """Taches montrees au Planning selon leur technicien (crochet du portail : techniciens portail)."""
        return []

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
        tous_techniciens = self._techniciens_planning(tout).sorted(lambda u: (u.name or "").lower())
        techniciens = tous_techniciens
        if technicien_id:
            techniciens = techniciens.filtered(lambda u: u.id == technicien_id)
        noms_jours = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        jours = []
        for i in range((fin - debut).days):
            d = debut + timedelta(days=i)
            jours.append({"iso": d.isoformat(), "aujourdhui": d == aujourdhui, "libelle": fields.Date.to_string(d),
                          "titre": "%s %s" % (noms_jours[d.weekday()], d.day), "weekend": d.weekday() >= 5})
        # Chaque case (technicien x jour) dans l'ordre de la tournee, avec ses pastilles (1, 2, 14h00...)
        cases = defaultdict(lambda: self.browse())
        for tache in taches:
            locale = pytz.UTC.localize(tache.date).astimezone(fuseau)
            cases[(tache.technicien_id.id, aujourdhui if locale.date() < debut else locale.date())] |= tache
        cartes = []
        for (_tech, jour_case), case in cases.items():
            case = case._trier_tournee()
            pastilles = case._pastilles_tournee()
            fixes = Counter(pastilles[t.id] for t in case if t.heure_fixe)
            for tache in case:
                cartes.append(self._carte_planning(tache, types, jour_case, pastilles[tache.id],
                                                   tache.heure_fixe and fixes[pastilles[tache.id]] > 1))
        par_technicien = self._par_technicien(taches)
        lignes = []
        for i, tech in enumerate(techniciens):
            siennes = par_technicien.get(tech.id, self)
            lignes.append({"id": tech.id, "nom": tech.name,
                           "initiales": "".join(m[:1] for m in (tech.name or "?").split()[:2]).upper(),
                           "couleur": COULEURS_TECH[i % len(COULEURS_TECH)], "nombre": len(siennes),
                           "en_retard": len(siennes.filtered(lambda t: t.etat_suivi == "en_retard"))})
        if not technicien_id or technicien_id < 0:
            sans = par_technicien.get(False, self)
            # En haut, comme les « postes ouverts » du Planning d'Odoo : a glisser sur un technicien
            lignes.insert(0, {"id": 0, "nom": self.env._("Sans technicien"), "initiales": "?", "couleur": "#94a3b8",
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
                            "techniciens": [{"id": t.id, "nom": t.name} for t in tous_techniciens],
                            "types": [{"code": c, "nom": n} for c, n in types.items()]},
                "indicateurs": self._indicateurs_planning(taches, avant, debut),
                "graphiques": self._graphiques_planning(taches, jours, lignes, debut, periode, technicien_id, type_tache,
                                                        par_technicien),
                "peut_deplacer": self.env.user.has_group("suivi_machines_pilotage.group_pilotage")}

    @api.model
    def _par_technicien(self, taches):
        """Taches regroupees par technicien (id, False sans technicien), dans leur ordre : un seul passage."""
        groupes = defaultdict(list)
        for tache in taches:
            groupes[tache.technicien_id.id].append(tache.id)
        return {cle: self.browse(ids) for cle, ids in groupes.items()}

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
        borne = self._vers_utc(debut, time.min)
        # Un seul passage sur les taches, puis des comptes en Python
        lignes = [{"type_tache": t.type_tache, "etat_suivi": t.etat_suivi, "a_faire": t.a_faire,
                   "technicien_id": t.technicien_id.id, "date": t.date} for t in taches]
        prevues = [l for l in lignes if l["date"] >= borne]

        def nb(condition, lot=lignes):
            return sum(1 for l in lot if condition(l))
        reparations = nb(lambda t: t["type_tache"] == "reparation")
        return {
            "total": len(lignes), "tendance": round(100 * (len(prevues) - avant) / avant) if avant else False,
            "en_retard": nb(lambda t: t["etat_suivi"] == "en_retard"),
            "sans_technicien": nb(lambda t: t["a_faire"] and not t["technicien_id"]),
            "completion": round(100 * nb(lambda t: t["etat_suivi"] == "fait", prevues) / len(prevues)) if prevues else 0,
            "objectif": self._parametre_planning("objectif_completion", 90),
            "livraisons": nb(lambda t: t["type_tache"] == "livraison"),
            "ramassages": nb(lambda t: t["type_tache"] == "ramassage"),
            "entretiens_reparations": nb(lambda t: t["type_tache"] == "entretien") + reparations,
            "reparations": reparations,
        }

    @api.model
    def _graphiques_planning(self, taches, jours, lignes, debut, periode, technicien_id, type_tache,
                             par_technicien=None):
        fuseau = pytz.timezone(FUSEAU)
        par_technicien = self._par_technicien(taches) if par_technicien is None else par_technicien

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
            siennes = par_technicien.get(ligne["id"], self)
            dates = [max(jour_local(t), debut) for t in siennes]
            series.append({"nom": ligne["nom"], "couleur": ligne["couleur"],
                           "valeurs": [len([d for d in dates if a <= d < b]) for a, b, _l in colonnes]})
        # Repartition par type
        types = dict(self._fields["type_tache"]._description_selection(self.env))
        par_type = Counter(taches.mapped("type_tache"))
        repartition = [{"nom": types[code], "couleur": COULEURS_HEX.get(code, "#6b7280"), "valeur": par_type[code]}
                       for code in types if par_type[code]]
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
    def _carte_planning(self, tache, types, jour, pastille, conflit):
        locale = pytz.UTC.localize(tache.date).astimezone(pytz.timezone(FUSEAU))
        return {
            "id": tache.id, "type": tache.type_tache, "libelle_type": types.get(tache.type_tache, ""),
            "couleur": COULEURS.get(tache.type_tache, "secondary"), "titre": tache.titre or "",
            "client": tache.partner_id.display_name or "", "heure": locale.strftime("%H h %M"),
            "jour": jour.isoformat(), "technicien_id": tache.technicien_id.id or 0,
            "etat": tache.etat_suivi, "deplacable": bool(tache.a_faire),
            "pastille": pastille, "heure_fixe": tache.heure_fixe, "conflit": conflit,
        }

    # ------------------------------------------------------------ ordre de la tournee
    def _cle_tournee(self):
        """Les taches placees par le superviseur (1, 2, 3...) d'abord, puis les autres par heure prevue."""
        return (0 if self.ordre_tournee else 1, self.ordre_tournee, self.date or datetime.min, self.id)

    def _trier_tournee(self):
        return self.sorted(lambda tache: tache._cle_tournee())

    def _pastilles_tournee(self):
        """{id: pastille} de taches d'une meme journee deja triees : 1, 2, 3... ou l'heure fixe (14h00)."""
        fuseau = pytz.timezone(FUSEAU)
        pastilles, rang = {}, 0
        for tache in self:
            if tache.heure_fixe and tache.date:
                locale = pytz.UTC.localize(tache.date).astimezone(fuseau)
                pastilles[tache.id] = "%sh%02d" % (locale.hour, locale.minute)
            else:
                rang += 1
                pastilles[tache.id] = str(rang)
        return pastilles

    @api.model
    def _taches_journee(self, technicien_id, jour):
        """Taches d'un technicien (0 : sans technicien) pour une journee, retards compris aujourd'hui."""
        aujourdhui = datetime.now(pytz.timezone(FUSEAU)).date()
        return self.search(self._domaine_planning(jour, jour + timedelta(days=1), technicien_id or -1,
                                                  retards=jour == aujourdhui))

    def _numeroter_tournee(self):
        """Ces taches, dans cet ordre, deviennent 1, 2, 3... de la tournee."""
        for rang, tache in enumerate(self, 1):
            if tache.ordre_tournee != rang:
                tache.write({"ordre_tournee": rang})

    @api.model
    def deplacer_planning(self, tache_id, technicien_id, jour_iso, avant_id=False):
        """Carte deposee dans une case : nouveau technicien et/ou nouveau jour (meme heure). Deposee sur une
        autre carte, elle prend sa place dans la tournee ; sinon elle passe a la fin de la journee."""
        # Vue SQL : relue a jour (une tache faite entre-temps ne bouge plus)
        self.env.flush_all()
        self.invalidate_model()
        tache = self.browse(tache_id).exists()
        if not tache:
            raise UserError(self.env._("Cette tâche n'existe plus : actualisez le planning."))
        if not tache.a_faire:
            raise UserError(self.env._("Cette tâche est déjà faite."))
        fuseau = pytz.timezone(FUSEAU)
        jour = date.fromisoformat(jour_iso)
        locale = pytz.UTC.localize(tache.date).astimezone(fuseau) if tache.date else None
        if tache.technicien_id.id != (technicien_id or False) or not locale or locale.date() != jour:
            heure = locale.time() if locale else time(9, 0)
            tache.write({"technicien_id": technicien_id or False, "date": self._vers_utc(jour, heure)})
        tournee = list((self._taches_journee(technicien_id, jour) - tache)._trier_tournee())
        avant = self.browse(avant_id) if avant_id else None
        tournee.insert(tournee.index(avant) if avant in tournee else len(tournee), tache)
        self.browse([t.id for t in tournee])._numeroter_tournee()
        self.invalidate_model()
        return True
