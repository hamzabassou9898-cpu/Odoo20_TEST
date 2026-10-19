# -*- coding: utf-8 -*-
"""Vue d'ensemble moderne du Pilotage : toutes les donnees en un seul appel."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools.misc import format_datetime

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
        if code in ("entretien_retard", "entretien_semaine", "entretien_mois"):
            # Cartes d'echeance : le chiffre compte exactement les lignes de la liste qu'elles ouvrent
            model, domaine = self._liste_echeance(code)
            return self.env[model].search_count(domaine)
        model, domaine = domaines[code]
        return self.env[model].search_count(domaine) + self._compte_reparations(code)

    @api.model
    def action_par_code(self, code):
        """Ouvre la liste d'une carte (meme comportement que la vue « Toutes les cartes »)."""
        action = self._action_detail(code)
        if action is None:
            indicateur = self.search([("code", "=", code)], limit=1)
            # Carte retiree du tableau (ex. Machines a probleme) : la liste s'ouvre quand meme
            action = indicateur.action_ouvrir() if indicateur else self._action_pour_code(code)
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
        if code == "tickets_ouverts":
            return self._action_xml("suivi_machines_pilotage.action_pilotage_appels", self.env._("Appels ouverts"),
                                    {}, self._domaines()[code][1])
        if code == "contrats_signes_mois":
            return {"type": "ir.actions.act_window", "name": self.env._("Contrats signés ce mois"),
                    "res_model": "sale.order", "views": [(False, "list"), (False, "form")],
                    "domain": self._domaines()[code][1], "context": {"create": False}}
        if code == "tournees_a_faire":
            domaines = self._domaines()
            return self._action_xml("suivi_machines_pilotage.action_pilotage_transferts",
                                    self.env._("Livraisons & ramassages à faire"), {},
                                    list(Domain.OR([domaines["livraisons_a_faire"][1],
                                                    domaines["ramassages_a_faire"][1]])))
        if code == "produits_categorie":
            return self._action_xml("suivi_machines_pilotage.action_pilotage_produits_categorie",
                                    self.env._("Produits par catégorie"), {"search_default_group_by_categ_id": 1}, [])
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
        if prefixe == "statut" and valeur:
            libelle = dict(self.env["stock.lot"]._fields["machine_statut"]._description_selection(self.env)).get(valeur)
            return self._action_xml("suivi_machines.action_machines", self.env._("Machines : %s", libelle or valeur),
                                    {}, [("est_machine", "=", True), ("machine_statut", "=", valeur)])
        if prefixe == "dispo" and valeur.isdigit():
            produit = self.env["product.product"].browse(int(valeur))
            return self._action_xml("suivi_machines.action_machines",
                                    self.env._("Disponibles en entrepôt : %s", produit.display_name), {},
                                    [("est_machine", "=", True), ("machine_statut", "=", "entrepot"),
                                     ("product_id", "=", produit.id)])
        if prefixe == "categorie" and valeur.isdigit():
            categorie = self.env["product.category"].browse(int(valeur)).exists()
            return {"type": "ir.actions.act_window",
                    "name": self.env._("Stock : %s", categorie.display_name or self.env._("Sans catégorie")),
                    "res_model": "product.product", "views": [(False, "list"), (False, "form")],
                    "domain": [("categ_id", "child_of", categorie.id) if categorie else ("categ_id", "=", False),
                               ("is_storable", "=", True)],
                    "context": {"create": False}}
        if code == "rupture":
            return {"type": "ir.actions.act_window", "name": self.env._("Produits en rupture de stock"),
                    "res_model": "product.product", "views": [(False, "list"), (False, "form")],
                    "domain": self._domaine_rupture(), "context": {"create": False}}
        if prefixe == "transfert" and valeur.isdigit():
            return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": int(valeur),
                    "views": [(False, "form")], "target": "current"}
        if code == "mouvements":
            return {"type": "ir.actions.act_window", "name": self.env._("Mouvements de stock"),
                    "res_model": "stock.move.line", "views": [(False, "list"), (False, "form")],
                    "domain": [("state", "=", "done")], "context": {"create": False}}
        if prefixe == "tache" and valeur.isdigit():
            tache = self.env["portail.tache"].browse(int(valeur)).exists()
            return tache.action_ouvrir() if tache else False
        return None

    # ------------------------------------------------------------ stock & inventaire
    @api.model
    def _domaine_rupture(self):
        """Produits stockes vendus ou loues (hors machines suivies) sans stock en entrepot."""
        return [("id", "in", self._produits_en_rupture().ids)]

    @api.model
    def _produits_en_rupture(self):
        # Un produit jamais recu n'a aucun quant : on part des produits et on retire ceux qui ont du stock
        produits = self.env["product.product"].search(
            [("is_storable", "=", True), ("sale_ok", "=", True),
             "|", ("categ_id", "=", False), ("categ_id.suivi_machine", "=", False)])
        en_stock = self.env["stock.quant"]._read_group(
            self._emplacements_stock() + [("product_id", "in", produits.ids)], ["product_id"], ["quantity:sum"])
        return produits - self.env["product.product"].union(*[p for p, qte in en_stock if qte > 0])

    @api.model
    def _emplacements_stock(self):
        """Stock reel : emplacements internes, sans l'emplacement « Location » (machines chez les clients)."""
        domaine = [("location_id.usage", "=", "internal")]
        societe = self.env.company
        if "rental_loc_id" in societe._fields and societe.rental_loc_id:
            domaine.append(("location_id", "!=", societe.rental_loc_id.id))
        return domaine

    @api.model
    def _donnees_stock(self):
        Lot = self.env["stock.lot"]
        libelles = dict(Lot._fields["machine_statut"]._description_selection(self.env))
        couleurs = {"entrepot": "g", "chez_client": "violet", "vendue": "b", "livree": "b",
                    "en_reparation": "r", "a_remplacer": "r", "hors_service": "gy", "sans_emplacement": "gy"}
        par_statut = dict(Lot._read_group([("est_machine", "=", True)], ["machine_statut"], ["__count"]))
        statuts = [{"code": "statut:%s" % cle, "nom": libelles.get(cle, cle), "nombre": par_statut.get(cle, 0),
                    "couleur": couleurs.get(cle, "gy")}
                   for cle in libelles if par_statut.get(cle)]
        dispo = Lot._read_group([("est_machine", "=", True), ("machine_statut", "=", "entrepot")],
                                ["product_id"], ["__count"], order="__count desc", limit=6)
        disponibles = [{"code": "dispo:%s" % produit.id, "nom": produit.display_name, "nombre": n}
                       for produit, n in dispo]
        # Stock par categorie (quantites en main, tous produits stockes)
        par_produit = self.env["stock.quant"]._read_group(self._emplacements_stock(), ["product_id"],
                                                          ["quantity:sum"])
        par_categorie = {}
        for produit, quantite in par_produit:
            if quantite:
                par_categorie[produit.categ_id] = par_categorie.get(produit.categ_id, 0) + quantite
        categories = [{"code": "categorie:%s" % (categ.id or 0),
                       "nom": categ.display_name or self.env._("Sans catégorie"), "nombre": round(qte)}
                      for categ, qte in sorted(par_categorie.items(), key=lambda x: -x[1])[:6]]
        # Derniers mouvements de stock (faits)
        lignes = self.env["stock.move.line"].search([("state", "=", "done")], order="date desc, id desc", limit=7)
        fuseau = self._fuseau().zone
        env_tz = self.env(context=dict(self.env.context, tz=fuseau))
        mouvements = [{
            "id": ml.id, "code": "transfert:%s" % ml.picking_id.id if ml.picking_id else "mouvements",
            "quand": format_datetime(env_tz, ml.date, dt_format="d MMM '·' HH 'h' mm"),
            "produit": ml.product_id.display_name, "serie": ml.lot_id.name or "",
            "quantite": "%g" % ml.quantity,
            "de": ml.location_id.name or "", "vers": ml.location_dest_id.name or "",
            "entree": ml.location_dest_id.usage == "internal" and ml.location_id.usage != "internal",
            "reference": ml.picking_id.name or ml.reference or "",
        } for ml in lignes]
        return {"statuts": statuts, "max_statut": max([x["nombre"] for x in statuts] or [1]),
                "disponibles": disponibles, "max_dispo": max([x["nombre"] for x in disponibles] or [1]),
                "categories": categories, "max_categorie": max([x["nombre"] for x in categories] or [1]) or 1,
                "rupture": len(self._produits_en_rupture()),
                "mouvements": mouvements}

    @api.model
    def _techniciens_du_tableau(self, taches):
        """Techniciens affiches dans le bloc « Techniciens » (le portail des techniciens filtre plus finement)."""
        return taches.technicien_id

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
        Lot = self.env["stock.lot"]
        chez_clients = Lot.search_count([("est_machine", "=", True),
                                         ("machine_statut", "in", ("chez_client", "livree", "vendue"))])
        en_entrepot = Lot.search_count([("est_machine", "=", True), ("machine_statut", "=", "entrepot")])

        rupture = len(self._produits_en_rupture())

        def tuile(code, libelle, valeur=None, pastille="", couleur="secondary", alerte=False):
            return {"code": code, "libelle": libelle, "valeur": c.get(code, 0) if valeur is None else valeur,
                    "pastille": pastille, "pastille_couleur": couleur, "alerte": alerte}

        # Un bloc par menu de la barre, dans le meme ordre (lien « Tout voir » vers le menu)
        retard = c.get("entretien_retard", 0)
        blocs = {
            "appels": [
                tuile("tickets_ouverts", self.env._("Appels ouverts"),
                      pastille=self.env._("%s sans technicien", c.get("appels_ouverts")) if c.get("appels_ouverts") else "",
                      couleur="warning"),
                tuile("entretiens_ouverts", self.env._("Entretiens & réparations à faire"),
                      pastille=self.env._("%s en retard", retard) if retard else "", couleur="danger"),
                tuile("appels_mois", self.env._("Appels reçus ce mois"),
                      pastille="%+d vs sem. dern." % ecart if ecart else "", couleur="danger" if ecart > 0 else "success"),
            ],
            "locations": [
                tuile("locations_actives", self.env._("Locations en cours")),
                tuile("reprises_30j", self.env._("Reprises dans 30 jours")),
                tuile("locations_depassees", self.env._("Locations dépassées"),
                      alerte=bool(c.get("locations_depassees"))),
            ],
            "facturation": [
                tuile("a_facturer", self.env._("Appels à facturer"),
                      pastille=(a_facturer.sous_titre or "").replace("Total : ", ""), couleur="success"),
                tuile("sage_clients", self.env._("Factures clients à enregistrer dans Sage")),
                tuile("sage_fournisseurs", self.env._("Factures fournisseurs à enregistrer dans Sage")),
            ],
            "inventaire": [
                tuile("statut:entrepot", self.env._("Machines en entrepôt"), en_entrepot),
                tuile("machines_chez_client", self.env._("Machines chez les clients"), chez_clients),
                tuile("tournees_a_faire", self.env._("Livraisons & ramassages à faire"),
                      c.get("livraisons_a_faire", 0) + c.get("ramassages_a_faire", 0)),
                tuile("livraisons_faites", self.env._("Livraisons & ramassages faits ce mois")),
                tuile("produits_categorie", self.env._("Produits par catégorie"),
                      self.env["product.template"].search_count([]),
                      pastille=self.env._("%s en rupture", rupture) if rupture else "", couleur="danger"),
            ],
        }

        # A traiter maintenant : du plus urgent au moins urgent, seulement ce qui est > 0 (les factures a
        # enregistrer dans Sage sont dans le bloc Facturation)
        a_traiter = [
            ("locations_depassees", "danger", "Locations dépassées", "Machines à reprendre chez le client",
             "Planifier le ramassage"),
            ("sans_livreur", "danger", "Tournées sans technicien", "Livraisons ou ramassages à assigner", "Assigner"),
            ("notes_a_lire", "warning", "Notes de techniciens à lire", "Notes et photos envoyées depuis le portail",
             "Lire"),
            ("entretiens_a_planifier", "warning", "Entretiens à planifier",
             "Assigner un technicien : l'entretien ira dans sa journée", "Planifier"),
            ("entretien_retard", "warning", "Entretiens & réparations en retard", "Date d'entretien ou de réparation dépassée",
             "Planifier"),
            ("appels_sans_machine", "warning", "Appels sans machine", "Numéro de série à préciser", "Compléter"),
            ("reprises_ouvertes", "info", "Tickets de reprise ouverts", "Fin de location : machines à récupérer",
             "Ouvrir"),
            ("contrats_signes_mois", "success", "Contrats signés ce mois",
             "Signés en ligne par le client : rangés dans son dossier", "Voir"),
            ("bons_signes_mois", "success", "Bons d'intervention signés ce mois",
             "Signés par le client et le technicien sur le téléphone", "Voir"),
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
        taches = taches.filtered(lambda t: t.technicien_id in self._techniciens_du_tableau(taches))
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
            for tag in ticket.tag_ids:
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

        prenom = (self.env.user.name or "").split()[0] if self.env.user.name else ""
        aujourdhui = format_datetime(self.env(context=dict(self.env.context, tz=fuseau)), maintenant,
                                     dt_format="EEEE d MMMM")
        return {
            "bonjour": prenom, "date": aujourdhui[:1].upper() + aujourdhui[1:], "periode": periode,
            "blocs": blocs, "alertes": alertes, "techniciens": techniciens,
            "progression": {"total": total, "faits": faits, "retards": retards,
                            "pourcentage": round(100 * faits / total) if total else 0},
            "problemes": problemes, "max_probleme": max([p["nombre"] for p in problemes] or [1]),
            "semaines": semaines, "max_semaine": max([s["nombre"] for s in semaines] or [1]) or 1,
            "tournees": tournees, "stock": self._donnees_stock(),
        }
