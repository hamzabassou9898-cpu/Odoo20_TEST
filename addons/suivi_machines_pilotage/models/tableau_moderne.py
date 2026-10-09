# -*- coding: utf-8 -*-
"""Vue d'ensemble moderne du Pilotage : toutes les donnees en un seul appel."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.tools.misc import format_amount, format_datetime

TYPES_COULEUR = {"livraison": "success", "ramassage": "warning", "entretien": "info",
                 "reparation": "danger", "installation": "primary", "autre": "secondary"}
COULEURS_TECH = ["#7c3aed", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444", "#6366f1", "#ec4899", "#14b8a6"]


class PilotageIndicateur(models.Model):
    _inherit = "pilotage.indicateur"

    # ------------------------------------------------------------ outils
    @api.model
    def _fuseau(self):
        return pytz.timezone(self.env.context.get("tz") or self.env.user.tz or "America/Toronto")

    @api.model
    def _bornes_periode(self, periode):
        """Debut/fin (UTC) de la periode choisie : jour, semaine (7 jours) ou mois (30 jours)."""
        fuseau = self._fuseau()
        aujourdhui = datetime.now(fuseau).date()
        debut = fuseau.localize(datetime.combine(aujourdhui, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        jours = {"jour": 1, "semaine": 7, "mois": 30}.get(periode, 1)
        return debut, debut + timedelta(days=jours)

    @api.model
    def _compte(self, code):
        domaines = self._domaines()
        if code not in domaines:
            return 0
        model, domaine = domaines[code]
        return self.env[model].search_count(domaine)

    @api.model
    def _debut_mois(self, decalage=0):
        """1er du mois (UTC), decale de n mois (-1 = mois dernier)."""
        fuseau = self._fuseau()
        aujourdhui = datetime.now(fuseau).date().replace(day=1)
        mois = aujourdhui.month - 1 + decalage
        premier = aujourdhui.replace(year=aujourdhui.year + mois // 12, month=mois % 12 + 1)
        return fuseau.localize(datetime.combine(premier, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _ventes(self, debut, fin):
        commandes = self.env["sale.order"].search([("state", "=", "sale"), ("date_order", ">=", debut),
                                                   ("date_order", "<", fin)])
        devise = self.env.company.currency_id
        return sum(c.currency_id._convert(c.amount_untaxed, devise, c.company_id, c.date_order.date())
                   for c in commandes)

    @api.model
    def _domaine_clients(self):
        # Tous les contacts actifs, exactement comme l'application Contacts
        return []

    @api.model
    def action_par_code(self, code):
        """Ouvre la liste d'une carte (meme comportement que la vue « Toutes les cartes »)."""
        action = self._action_detail(code)
        if action is None:
            indicateur = self.search([("code", "=", code)], limit=1)
            action = indicateur.action_ouvrir() if indicateur else False
        if action:
            action.pop("help", None)
        return action

    @api.model
    def _action_xml(self, xmlid, nom, contexte=None, domaine=None):
        action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
        action.update({"name": nom, "display_name": nom, "context": contexte or {}})
        if domaine is not None:
            action["domain"] = domaine
        return action

    @api.model
    def _action_detail(self, code):
        """Clics de la vue d'ensemble qui ne correspondent pas a une carte."""
        if code == "ventes_mois":
            return {"type": "ir.actions.act_window", "name": self.env._("Ventes du mois"),
                    "res_model": "sale.order", "views": [(False, "list"), (False, "form")],
                    "domain": [("state", "=", "sale"), ("date_order", ">=", self._debut_mois())],
                    "context": {"create": False}}
        if code == "clients":
            xmlid = "contacts.action_contacts" if self.env.ref("contacts.action_contacts", raise_if_not_found=False) \
                else "base.action_partner_form"
            action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
            action.update({"name": self.env._("Nos contacts"), "domain": self._domaine_clients(),
                           "context": {"default_is_company": True}})
            return action
        if code == "tournees_a_faire":
            return self._action_xml("suivi_machines_pilotage.action_pilotage_transferts",
                                    self.env._("Livraisons & ramassages à faire"),
                                    {"search_default_livraisons_a_faire": 1, "search_default_ramassages_a_faire": 1})
        if code == "machines_chez_client":
            return self._action_xml("suivi_machines.action_machines", self.env._("Machines chez les clients"), {},
                                    [("est_machine", "=", True),
                                     ("machine_statut", "in", ("chez_client", "livree", "vendue"))])
        prefixe, _sep, valeur = code.partition(":")
        if prefixe == "technicien" and valeur.isdigit():
            tech = self.env["res.users"].browse(int(valeur))
            return self._action_xml("suivi_machines_pilotage.action_portail_techniciens",
                                    self.env._("Tâches de %s", tech.name),
                                    {"search_default_technicien_id": tech.id, "search_default_semaine": 1})
        if prefixe == "probleme" and valeur:
            return self._action_xml("suivi_machines_pilotage.action_pilotage_appels",
                                    self.env._("Appels : %s", valeur), {"search_default_type_appel": 1},
                                    [("tag_ids.name", "=", valeur),
                                     ("create_date", ">=", fields.Datetime.now() - timedelta(days=30))])
        if prefixe == "semaine" and valeur:
            debut = fields.Datetime.to_datetime(valeur)
            return self._action_xml("suivi_machines_pilotage.action_pilotage_appels",
                                    self.env._("Appels de la semaine du %s", debut.strftime("%d/%m")),
                                    {"search_default_type_appel": 1},
                                    [("create_date", ">=", debut), ("create_date", "<", debut + timedelta(weeks=1))])
        if prefixe == "tache" and valeur.isdigit():
            tache = self.env["portail.tache"].browse(int(valeur)).exists()
            return tache.action_ouvrir() if tache else False
        return None

    # ------------------------------------------------------------ donnees de la vue d'ensemble
    @api.model
    def donnees_tableau_moderne(self, periode="jour"):
        c = {code: self._compte(code) for code in self._domaines()}
        Ticket = self.env["helpdesk.ticket"]
        maintenant = fields.Datetime.now()
        appels = [("type_ticket", "=", "appel")]
        cette_semaine = Ticket.search_count(appels + [("create_date", ">=", maintenant - timedelta(days=7))])
        semaine_avant = Ticket.search_count(appels + [("create_date", ">=", maintenant - timedelta(days=14)),
                                                      ("create_date", "<", maintenant - timedelta(days=7))])
        ecart = cette_semaine - semaine_avant
        a_facturer = self.search([("code", "=", "a_facturer")], limit=1)

        # Ventes du mois (confirmees, hors taxes) vs meme periode le mois dernier
        devise = self.env.company.currency_id
        debut_mois, debut_mois_dernier = self._debut_mois(), self._debut_mois(-1)
        ventes = self._ventes(debut_mois, maintenant + timedelta(seconds=1))
        ventes_avant = self._ventes(debut_mois_dernier, debut_mois_dernier + (maintenant - debut_mois))
        if ventes_avant:
            pct = round(100 * (ventes - ventes_avant) / ventes_avant)
            tendance_ventes, couleur_ventes = "%+d %% vs mois dernier" % pct, "success" if pct >= 0 else "danger"
        else:
            tendance_ventes, couleur_ventes = "ce mois", "secondary"
        Partner = self.env["res.partner"]
        nb_clients = Partner.search_count(self._domaine_clients())
        nouveaux = Partner.search_count(self._domaine_clients() + [("create_date", ">=", debut_mois)])

        kpis = [
            {"code": "ventes_mois", "valeur": format_amount(self.env, round(ventes), devise, trailing_zeroes=False),
             "libelle": "Ventes du mois (hors taxes)", "icone": "payments", "couleur": "success",
             "tendance": tendance_ventes, "tendance_couleur": couleur_ventes},
            {"code": "clients", "valeur": nb_clients, "libelle": "Nos contacts", "icone": "person",
             "couleur": "primary", "tendance": "+%s ce mois" % nouveaux if nouveaux else "",
             "tendance_couleur": "success"},
            {"code": "appels_ouverts", "valeur": c.get("appels_ouverts", 0), "libelle": "Appels de service ouverts",
             "icone": "build", "couleur": "danger",
             "tendance": "%+d vs sem. dern." % ecart, "tendance_couleur": "danger" if ecart > 0 else "success"},
            {"code": "entretiens_ouverts", "valeur": c.get("entretiens_ouverts", 0),
             "libelle": "Entretiens planifiés à faire", "icone": "schedule", "couleur": "info",
             "tendance": "%s en retard" % c.get("entretien_retard", 0),
             "tendance_couleur": "danger" if c.get("entretien_retard") else "secondary"},
            {"code": "tournees_a_faire",
             "valeur": c.get("livraisons_a_faire", 0) + c.get("ramassages_a_faire", 0),
             "libelle": "Livraisons & ramassages à faire", "icone": "local_shipping", "couleur": "primary",
             "tendance": "%s livrées ce mois" % c.get("livraisons_faites", 0), "tendance_couleur": "success"},
            {"code": "locations_actives", "valeur": c.get("locations_actives", 0), "libelle": "Locations en cours",
             "icone": "calendar_today", "couleur": "warning",
             "tendance": "%s reprises ≤ 30 j" % c.get("reprises_30j", 0), "tendance_couleur": "secondary"},
            {"code": "a_facturer", "valeur": c.get("a_facturer", 0), "libelle": "Interventions à facturer",
             "icone": "attach_money", "couleur": "success",
             "tendance": (a_facturer.sous_titre or "").replace("Total : ", ""), "tendance_couleur": "success"},
        ]

        # A traiter maintenant : du plus urgent au moins urgent, seulement ce qui est > 0
        a_traiter = [
            ("locations_depassees", "danger", "Locations dépassées", "Machines à reprendre chez le client",
             "Planifier le ramassage"),
            ("sans_livreur", "danger", "Tournées sans technicien", "Livraisons ou ramassages à assigner", "Assigner"),
            ("notes_a_lire", "warning", "Notes de techniciens à lire", "Notes et photos envoyées depuis le portail",
             "Lire"),
            ("entretiens_a_planifier", "warning", "Entretiens à planifier",
             "Assigner un technicien : l'entretien ira dans sa journée", "Planifier"),
            ("entretien_retard", "warning", "Entretiens en retard", "Machines dont l'entretien est dépassé",
             "Planifier"),
            ("appels_sans_machine", "warning", "Appels sans machine", "Numéro de série à préciser", "Compléter"),
            ("reprises_ouvertes", "info", "Tickets de reprise ouverts", "Fin de location : machines à récupérer",
             "Ouvrir"),
            ("sage_clients", "primary", "Factures clients à enregistrer dans Sage", "À cocher une fois saisies",
             "Enregistrer"),
            ("sage_fournisseurs", "primary", "Factures fournisseurs à enregistrer dans Sage",
             "À cocher une fois saisies", "Enregistrer"),
        ]
        # Nouveaux tickets (etape « Nouveau ») : tout en haut, avec le dernier arrive
        model, domaine = self._domaines()["tickets_nouveaux"]
        dernier = self.env[model].search(domaine, order="create_date desc, id desc", limit=1)
        if dernier:
            detail = self.env._("Dernier : %(titre)s — %(client)s", titre=dernier.name,
                                client=dernier.partner_id.display_name or self.env._("client à préciser"))
            a_traiter.insert(0, ("tickets_nouveaux", "danger", "Nouveaux tickets à prendre en charge", detail, "Traiter"))
        alertes = [{"code": code, "nombre": c.get(code, 0), "niveau": niveau, "titre": titre, "detail": detail,
                    "bouton": bouton} for code, niveau, titre, detail, bouton in a_traiter if c.get(code)]

        # Techniciens sur la periode (aujourd'hui : retards inclus)
        debut, fin = self._bornes_periode(periode)
        Tache = self.env["portail.tache"]
        domaine_periode = ["|", "&", ("date", ">=", debut), ("date", "<", fin), ("etat_suivi", "=", "en_retard")]
        taches = Tache.search([("technicien_id", "!=", False)] + domaine_periode, order="date, id")
        techniciens = []
        for i, tech in enumerate(taches.technicien_id.sorted(lambda u: (u.name or "").lower())):
            siennes = taches.filtered(lambda t: t.technicien_id == tech)
            fait = len(siennes.filtered(lambda t: t.etat_suivi == "fait"))
            retard = len(siennes.filtered(lambda t: t.etat_suivi == "en_retard"))
            mots = (tech.name or "?").split()
            initiales = "".join(m[0] for m in mots[:2]).upper() if len(mots) > 1 else (tech.name or "?")[:2].upper()
            techniciens.append({"id": tech.id, "code": "technicien:%s" % tech.id, "nom": tech.name, "initiales": initiales,
                                "couleur": COULEURS_TECH[i % len(COULEURS_TECH)],
                                "total": len(siennes), "fait": fait, "retard": retard,
                                "a_faire": len(siennes) - fait - retard})
        total = len(taches)
        faits = len(taches.filtered(lambda t: t.etat_suivi == "fait"))
        retards = len(taches.filtered(lambda t: t.etat_suivi == "en_retard"))

        # Appels par type de probleme (30 jours) et par semaine (8 semaines)
        tickets_30j = Ticket.search(appels + [("create_date", ">=", maintenant - timedelta(days=30))])
        par_tag = {}
        for ticket in tickets_30j:
            for tag in ticket.tag_ids.filtered(lambda t: (t.name or "").upper() != "TEST"):
                par_tag[tag.name] = par_tag.get(tag.name, 0) + 1
        problemes = [{"nom": nom, "nombre": n, "code": "probleme:%s" % nom}
                     for nom, n in sorted(par_tag.items(), key=lambda x: -x[1])[:5]]
        lundi = (maintenant - timedelta(days=maintenant.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        semaines = []
        for k in range(7, -1, -1):
            d = lundi - timedelta(weeks=k)
            semaines.append({"libelle": d.strftime("%d/%m"), "code": "semaine:%s" % d.strftime("%Y-%m-%d %H:%M:%S"),
                             "nombre": Ticket.search_count(appels + [("create_date", ">=", d),
                                                                      ("create_date", "<", d + timedelta(weeks=1))])})

        # Prochaines taches a faire sur la periode
        prochaines = Tache.search([("a_faire", "=", True), ("date", ">=", debut), ("date", "<", fin)],
                                  order="date, id", limit=6)
        fuseau = self._fuseau().zone
        tournees = [{"id": t.id, "code": "tache:%s" % t.id, "quand": format_datetime(self.env(context=dict(self.env.context, tz=fuseau)), t.date,
                                                          dt_format="HH 'h' mm" if periode == "jour"
                                                          else "EEE d MMM '·' HH 'h' mm"),
                     "type": dict(t._fields["type_tache"].selection).get(t.type_tache),
                     "couleur": TYPES_COULEUR.get(t.type_tache, "secondary"),
                     "client": t.partner_id.display_name or "", "titre": t.titre or "",
                     "technicien": t.technicien_id.name or "Sans technicien"} for t in prochaines]

        Lot = self.env["stock.lot"]
        parc = [
            {"code": "machines_chez_client", "valeur": Lot.search_count([("est_machine", "=", True),
                                                                          ("machine_statut", "in",
                                                                           ("chez_client", "livree", "vendue"))]),
             "libelle": "Machines chez les clients"},
            {"code": "livraisons_faites", "valeur": c.get("livraisons_faites", 0), "libelle": "Livraisons faites"},
            {"code": "entretiens_faits", "valeur": c.get("entretiens_faits", 0), "libelle": "Entretiens faits"},
            {"code": "appels_mois", "valeur": c.get("appels_mois", 0), "libelle": "Appels reçus"},
            {"code": "machines_probleme", "valeur": c.get("machines_probleme", 0), "libelle": "Machines à problème",
             "alerte": bool(c.get("machines_probleme"))},
        ]

        prenom = (self.env.user.name or "").split()[0] if self.env.user.name else ""
        aujourdhui = format_datetime(self.env(context=dict(self.env.context, tz=fuseau)), maintenant,
                                     dt_format="EEEE d MMMM")
        return {
            "bonjour": prenom, "date": aujourdhui[:1].upper() + aujourdhui[1:], "periode": periode,
            "kpis": kpis, "alertes": alertes, "techniciens": techniciens,
            "progression": {"total": total, "faits": faits, "retards": retards,
                            "pourcentage": round(100 * faits / total) if total else 0},
            "problemes": problemes, "max_probleme": max([p["nombre"] for p in problemes] or [1]),
            "semaines": semaines, "max_semaine": max([s["nombre"] for s in semaines] or [1]) or 1,
            "tournees": tournees, "parc": parc,
        }
