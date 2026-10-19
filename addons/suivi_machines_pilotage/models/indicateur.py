# -*- coding: utf-8 -*-
"""Indicateurs du tableau de bord « Pilotage » : un compteur par carte, un clic ouvre la liste."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

from odoo.addons.suivi_machines_helpdesk.models.etapes import domaine_ferme, domaine_nom

SECTIONS = [("appels", "Appels de service"), ("entretiens", "Entretiens & réparations"),
            ("livraisons", "Livraisons & ramassages"), ("locations", "Locations"),
            ("qualite", "Bris & réparations"), ("facturation", "Facturation")]
# « Bris & réparations » est regroupe avec les entretiens : colonne masquee (valeur gardee pour les mises a jour)
SECTIONS_AFFICHEES = [k for k, _ in SECTIONS if k != "qualite"]
COULEURS = [("danger", "Rouge"), ("warning", "Orange"), ("success", "Vert"),
            ("info", "Bleu clair"), ("primary", "Violet")]


class PilotageIndicateur(models.Model):
    _name = "pilotage.indicateur"
    _description = "Indicateur de pilotage"
    _order = "section, sequence, id"

    name = fields.Char("Indicateur", required=True, translate=True)
    code = fields.Char("Code", required=True)
    section = fields.Selection(SECTIONS, "Section", required=True, group_expand="_expand_sections")
    sequence = fields.Integer(default=10)
    couleur = fields.Selection(COULEURS, "Couleur", default="primary", required=True)
    description = fields.Char("Description", translate=True)
    valeur = fields.Integer("Valeur", compute="_compute_valeur")
    sous_titre = fields.Char("Détail", compute="_compute_valeur")
    # Detail par type (etiquettes dans la carte) : [[libelle, nombre, couleur], ...]
    repartition = fields.Json("Répartition", compute="_compute_valeur")

    _code_unique = models.Constraint("UNIQUE(code)", "Un seul indicateur par code.")

    def _expand_sections(self, sections, domain):
        return SECTIONS_AFFICHEES

    # ------------------------------------------------------------ domaines (partages avec les menus)
    @api.model
    def _bornes(self):
        aujourdhui = fields.Date.context_today(self)
        maintenant = fields.Datetime.now()
        return {"aujourdhui": aujourdhui, "maintenant": maintenant,
                "debut_mois": aujourdhui.replace(day=1),
                "semaine": aujourdhui + timedelta(days=7), "mois": aujourdhui + timedelta(days=30),
                "dans_30j": maintenant + timedelta(days=30)}

    @api.model
    def _domaines(self):
        b = self._bornes()
        machines = [("est_machine", "=", True), ("machine_statut", "!=", "hors_service"),
                    ("date_prochain_entretien", "!=", False)]
        location = [("type_commande", "=", "location"), ("state", "=", "sale")]
        appels = [("est_entretien", "=", False), ("commande_reprise_id", "=", False)]
        # Ouvert = pas dans une etape Resolu / Annule / Cloture (un ticket sans etape compte)
        ouverts = ["!"] + domaine_ferme()
        transfert = [("move_ids.product_id.categ_id.suivi_machine", "=", True)]
        a_faire = [("state", "not in", ("done", "cancel"))]
        livraison = [("location_id.usage", "=", "internal"), ("location_dest_id.usage", "=", "customer")]
        ramassage = [("location_id.usage", "=", "customer"), ("location_dest_id.usage", "=", "internal")]
        return {
            "entretien_retard": ("stock.lot", machines + [("date_prochain_entretien", "<", b["aujourdhui"])]),
            "entretien_semaine": ("stock.lot", machines + [("date_prochain_entretien", ">=", b["aujourdhui"]),
                                                          ("date_prochain_entretien", "<=", b["semaine"])]),
            "entretien_mois": ("stock.lot", machines + [("date_prochain_entretien", ">=", b["aujourdhui"]),
                                                       ("date_prochain_entretien", "<=", b["mois"])]),
            "entretiens_faits": ("machine.intervention", [("type", "=", "entretien"), ("state", "=", "fait"),
                                                          ("date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
            "locations_actives": ("sale.order", location + ["|", ("date_fin_location", "=", False),
                                                            ("date_fin_location", ">=", b["maintenant"])]),
            "reprises_30j": ("sale.order", location + [("date_fin_location", ">=", b["maintenant"]),
                                                       ("date_fin_location", "<=", b["dans_30j"])]),
            "locations_depassees": ("sale.order", location + [("date_fin_location", "<", b["maintenant"])]),
            # Appels de service : tout ticket ouvert pas encore planifie (hors reprises). Des qu'un
            # technicien est assigne, il passe dans Entretiens / Reparations planifies a faire.
            "appels_ouverts": ("helpdesk.ticket", [("type_ticket", "!=", "reprise"),
                                                   ("statut_entretien", "!=", "planifie")] + ouverts),
            "entretiens_a_planifier": ("helpdesk.ticket", [("est_entretien", "=", True),
                                                           ("statut_entretien", "=", "a_planifier")]),
            # Ticket qui vient d'arriver : etape « Nouveau » (ou pas d'etape), personne ne l'a encore pris en
            # charge (aucun technicien assigne, rien de planifie)
            "tickets_nouveaux": ("helpdesk.ticket", ["|", ("stage_id", "=", False)]
                                 + domaine_nom("nouveau", "stage_id.name")
                                 + [("user_id", "=", False), ("statut_entretien", "not in", ["planifie", "fait"])]),
            # Planifie = assigne a un technicien (ou intervention planifiee) : dans sa journee
            # Entretiens + reparations + machines a remplacer assignes a un technicien, pas encore valides
            "entretiens_ouverts": ("helpdesk.ticket", [("statut_entretien", "=", "planifie")]),
            # Reparation / machine a remplacer assignee a un technicien, pas encore resolue
            "reparations_planifiees": ("helpdesk.ticket", [("est_entretien", "=", False),
                                                           ("statut_entretien", "=", "planifie")]),
            "reprises_ouvertes": ("helpdesk.ticket", [("type_ticket", "=", "reprise")] + ouverts),
            # Tous les tickets pas encore resolus/annules : le meme nombre que les colonnes ouvertes de
            # l'Assistance (vue d'ensemble « Appels ouverts »)
            "tickets_ouverts": ("helpdesk.ticket", list(ouverts)),
            "appels_mois": ("helpdesk.ticket", appels + [
                ("create_date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
            "appels_sans_machine": ("helpdesk.ticket", appels + ouverts + [("lot_id", "=", False)]),
            "livraisons_a_faire": ("stock.picking", transfert + a_faire + livraison),
            "ramassages_a_faire": ("stock.picking", transfert + a_faire + ramassage),
            "sans_livreur": ("stock.picking", transfert + a_faire + [("livreur_id", "=", False)]),
            # Toutes les livraisons ET tous les ramassages termines ce mois (une etiquette chacun)
            "livraisons_faites": ("stock.picking", self._fait_ce_mois(b) + [
                ("type_tournee", "in", ("livraison", "ramassage"))]),
            # Contrats Monroy signes en ligne par le client depuis le 1er du mois (notification verte)
            "contrats_signes_mois": ("sale.order", [("type_contrat_id", "!=", False), ("signed_on", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
            "bris_mois": ("machine.intervention", [("type", "=", "bris"), ("state", "!=", "annule"),
                                                   ("date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
            "machines_probleme": ("stock.lot", [("est_machine", "=", True),
                                                ("machine_statut", "in", ("en_reparation", "a_remplacer",
                                                                           "hors_service"))]),
            "a_facturer": ("machine.intervention", [("etat_facturation", "=", "a_facturer")]),
            "sage_clients": ("account.move", [("move_type", "in", ("out_invoice", "out_refund")),
                                              ("statut_sage", "=", "a_transferer")]),
            "sage_fournisseurs": ("account.move", [("move_type", "in", ("in_invoice", "in_refund")),
                                                   ("statut_sage", "=", "a_transferer")]),
            "facturer_sage": ("machine.intervention", [("etat_facturation", "=", "bon_cree")]),
        }

    @api.model
    def _fait_ce_mois(self, b=None):
        b = b or self._bornes()
        return [("state", "=", "done"), ("date_done", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]

    @api.model
    def _parts_transferts_faits(self):
        """Carte « Livraisons & ramassages faits ce mois » : TOUTES les livraisons et tous les ramassages
        (machines, accessoires, locations), genre -> domaine."""
        base = self._fait_ce_mois()
        return {"livraison": base + [("type_tournee", "=", "livraison")],
                "ramassage": base + [("type_tournee", "=", "ramassage")]}

    def action_ouvrir_livrees(self):
        """Etiquette « Livraison » : les livraisons de machines faites ce mois."""
        return self._action_pour_code_filtre("livrees_mois", self.env._("Livraisons faites ce mois"))

    def action_ouvrir_ramassees(self):
        """Etiquette « Ramassage » : les ramassages de machines faits ce mois."""
        return self._action_pour_code_filtre("ramassees_mois", self.env._("Ramassages faits ce mois"))

    @api.model
    def _action_pour_code_filtre(self, filtre, nom):
        action = self.env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_transferts")
        # Tous les transferts (pas seulement ceux des machines)
        action.update({"context": {"search_default_" + filtre: 1}, "name": nom, "display_name": nom,
                       "domain": []})
        action.pop("help", None)
        return action

    @api.model
    def _parts_reparation(self, genre=None):
        """Partie « Réparations » des cartes d'entretien (machines) : code -> (modele, domaine).
        genre : None = réparations + machines à remplacer, « reparation » ou « remplacement » = l'un des deux."""
        b = self._bornes()
        debut = fields.Datetime.to_datetime(b["aujourdhui"])
        jour = timedelta(days=1)
        reparations = [("est_entretien", "=", False), ("statut_entretien", "in", ("a_planifier", "planifie")),
                       ("date_planifiee", "!=", False)]
        types_faits = ("bris", "reparation", "remplacement")
        if genre == "remplacement":
            reparations.append(("type_demande", "=", "remplacement"))
            types_faits = ("remplacement",)
        elif genre == "reparation":
            reparations.append(("type_demande", "!=", "remplacement"))
            types_faits = ("bris", "reparation")
        return {
            "entretien_retard": ("helpdesk.ticket", reparations + [("date_planifiee", "<", debut)]),
            "entretien_semaine": ("helpdesk.ticket", reparations + [
                ("date_planifiee", ">=", debut),
                ("date_planifiee", "<", fields.Datetime.to_datetime(b["semaine"]) + jour)]),
            "entretien_mois": ("helpdesk.ticket", reparations + [
                ("date_planifiee", ">=", debut),
                ("date_planifiee", "<", fields.Datetime.to_datetime(b["mois"]) + jour)]),
            "entretiens_faits": ("machine.intervention", [
                ("type", "in", types_faits), ("state", "=", "fait"),
                ("date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
        }

    @api.model
    def _compte_reparations(self, code, genre=None):
        model, domaine = self._parts_reparation(genre).get(code, (None, None))
        return self.env[model].search_count(domaine) if model else 0

    def _ouvrir_part(self, genre, titre):
        self.ensure_one()
        model, domaine = self._parts_reparation(genre).get(self.code, (None, None))
        if not model:
            return False
        xmlid = ("suivi_machines_pilotage.action_pilotage_appels" if model == "helpdesk.ticket"
                 else "suivi_machines_pilotage.action_pilotage_entretiens_faits")
        action = self._action_xml(xmlid, titre, {}, domaine)
        action.pop("help", None)
        return action

    def action_ouvrir_reparations(self):
        """Etiquette « Réparation » d'une carte d'entretien : la liste des réparations correspondantes."""
        return self._ouvrir_part("reparation", self.env._("Réparations — %s", self.name))

    def action_ouvrir_remplacements(self):
        """Etiquette « Machine à remplacer » d'une carte d'entretien : les machines à remplacer correspondantes."""
        return self._ouvrir_part("remplacement", self.env._("Machines à remplacer — %s", self.name))

    @api.model
    def _repartition_par_type(self, domaine):
        """Nombre de tickets par type (Entretien, Reparation, Machine a remplacer) pour la carte."""
        Ticket = self.env["helpdesk.ticket"]
        libelles = dict(Ticket._fields["type_demande"]._description_selection(self.env))
        couleurs = {"entretien": "info", "reparation": "danger", "remplacement": "warning"}
        nombres = dict(Ticket._read_group(domaine, ["type_demande"], ["__count"]))
        # Les 3 types toujours affiches (meme a 0), puis les autres s'il y en a
        ordre = ["entretien", "reparation", "remplacement"]
        ordre += [t for t in nombres if t not in ordre]
        return [[libelles.get(type_, self.env._("Autre")), nombres.get(type_, 0), couleurs.get(type_, "secondary")]
                for type_ in ordre]

    def _compute_valeur(self):
        domaines = self._domaines()
        for ind in self:
            model, domaine = domaines.get(ind.code, (None, None))
            ind.repartition = False
            if not model:
                ind.valeur, ind.sous_titre = 0, False
                continue
            Model = self.env[model]
            ind.valeur = Model.search_count(domaine)
            ind.sous_titre = ind.description
            if ind.code == "entretiens_ouverts" and ind.valeur:
                ind.repartition = self._repartition_par_type(domaine)
            elif ind.code in self._parts_reparation():
                # Carte regroupee : machines a entretenir + reparations (une etiquette chacune)
                entretiens = ind.valeur
                reparations = self._compte_reparations(ind.code, "reparation")
                remplacements = self._compte_reparations(ind.code, "remplacement")
                ind.valeur = entretiens + reparations + remplacements
                if ind.valeur:
                    ind.repartition = [[self.env._("Entretien"), entretiens, "info", ""],
                                       [self.env._("Réparation"), reparations, "danger", "reparations"],
                                       [self.env._("Machine à remplacer"), remplacements, "warning",
                                        "remplacements"]]
            elif ind.code == "livraisons_faites" and ind.valeur:
                Picking = self.env["stock.picking"]
                parts = self._parts_transferts_faits()
                ind.repartition = [
                    [self.env._("Livraison"), Picking.search_count(parts["livraison"]), "success", "livrees"],
                    [self.env._("Ramassage"), Picking.search_count(parts["ramassage"]), "warning", "ramassees"]]
            devise = self.env.company.currency_id
            if model == "machine.intervention" and ind.code in ("a_facturer", "facturer_sage"):
                total = sum(Model.search(domaine).mapped("montant_frais"))
                ind.sous_titre = self.env._("Total : %s", devise.format(total))
            elif model == "account.move":
                total = sum(Model.search(domaine).mapped("amount_total_signed"))
                ind.sous_titre = self.env._("Total : %s", devise.format(abs(total)))

    # ------------------------------------------------------------ clic sur la carte
    _ACTIONS = {
        "entretien_retard": ("suivi_machines_pilotage.action_pilotage_entretiens", "retard"),
        "entretien_semaine": ("suivi_machines_pilotage.action_pilotage_entretiens", "semaine"),
        "entretien_mois": ("suivi_machines_pilotage.action_pilotage_entretiens", "mois"),
        "entretiens_faits": ("suivi_machines_pilotage.action_pilotage_entretiens_faits", "ce_mois"),
        "locations_actives": ("suivi_machines_pilotage.action_pilotage_locations", "en_cours"),
        "reprises_30j": ("suivi_machines_pilotage.action_pilotage_locations", "fin_30j"),
        "locations_depassees": ("suivi_machines_pilotage.action_pilotage_locations", "depassees"),
        "appels_ouverts": ("suivi_machines_pilotage.action_pilotage_appels", ("a_traiter", "ouverts")),
        "entretiens_a_planifier": ("suivi_machines_pilotage.action_pilotage_appels", ("entretiens_a_planifier",)),
        "tickets_nouveaux": ("suivi_machines_pilotage.action_pilotage_appels", ("nouveaux",)),
        "entretiens_ouverts": ("suivi_machines_pilotage.action_pilotage_appels",
                               ("planifies_a_faire", "grp_type_demande")),
        "reprises_ouvertes": ("suivi_machines_pilotage.action_pilotage_appels", ("type_reprise", "ouverts")),
        "appels_mois": ("suivi_machines_pilotage.action_pilotage_appels", ("type_appel", "ce_mois")),
        "appels_sans_machine": ("suivi_machines_pilotage.action_pilotage_appels", ("type_appel", "ouverts",
                                                                                   "sans_machine")),
        "livraisons_a_faire": ("suivi_machines_pilotage.action_pilotage_transferts", "livraisons_a_faire"),
        "ramassages_a_faire": ("suivi_machines_pilotage.action_pilotage_transferts", "ramassages_a_faire"),
        "sans_livreur": ("suivi_machines_pilotage.action_pilotage_transferts", "sans_livreur"),
        "livraisons_faites": ("suivi_machines_pilotage.action_pilotage_transferts", ("livrees_mois", "ramassees_mois")),
        "bris_mois": ("suivi_machines_pilotage.action_pilotage_bris", "ce_mois"),
        "machines_probleme": ("suivi_machines_pilotage.action_pilotage_machines_probleme", None),
        "a_facturer": ("suivi_machines_pilotage.action_pilotage_facturation", "a_facturer"),
        "facturer_sage": ("suivi_machines_pilotage.action_pilotage_facturation", "bon_cree"),
        "sage_clients": ("suivi_sage.action_sage_clients", "sage_a_transferer"),
        "sage_fournisseurs": ("suivi_sage.action_sage_fournisseurs", "sage_a_transferer"),
    }

    def action_ouvrir(self):
        self.ensure_one()
        if self.code == "contrats_signes_mois":
            return self._action_detail(self.code)
        if self.code in ("entretien_retard", "entretien_semaine", "entretien_mois"):
            action = self._action_entretiens_et_reparations()
            if action:
                return action
        return self._action_pour_code(self.code, self.name)

    @api.model
    def action_appels_de_service(self):
        """Menu « Appels de service » : la vue complete de l'Assistance (colonnes par etape) de l'equipe
        des appels de service, comme depuis l'application Assistance ; sinon la liste des appels."""
        if "helpdesk.team" in self.env:
            Equipe = self.env["helpdesk.team"]
            equipe = Equipe.browse(self.env["sale.order"]._reglages_reprise().get("equipe") or []).exists() \
                or Equipe.search([], limit=1)
            if equipe and hasattr(equipe, "action_view_ticket"):
                return self._sans_active_id(equipe.action_view_ticket(), equipe)
        return self.env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_appels")

    @api.model
    def _sans_active_id(self, action, equipe):
        """L'action de l'equipe attend l'equipe ouverte (active_id) : depuis un menu il n'y en a pas, on
        evalue donc son contexte et son domaine ici, avec l'equipe."""
        valeurs = {"active_id": equipe.id, "active_ids": equipe.ids, "uid": self.env.uid,
                   "context": dict(self.env.context)}
        for cle, defaut in (("context", {"default_team_id": equipe.id}),
                            ("domain", [("team_id", "=", equipe.id)])):
            if isinstance(action.get(cle), str):
                try:
                    action[cle] = safe_eval(action[cle], valeurs)
                except Exception:  # noqa: BLE001 - expression inconnue : l'equipe suffit
                    action[cle] = defaut
        return action

    @api.model
    def _liste_echeance(self, code):
        """Ce que montre une carte d'echeance (en retard, semaine, 30 jours) : (modele, domaine). Avec des
        reparations / machines a remplacer : une seule liste de tickets (reparations + tickets d'entretien
        des machines comptees) ; sinon la liste des machines a entretenir. Le chiffre compte la meme chose."""
        modele_lots, domaine_lots = self._domaines()[code]
        _modele, domaine_tickets = self._parts_reparation()[code]
        if not self.env["helpdesk.ticket"].search_count(domaine_tickets):
            return modele_lots, domaine_lots
        lots = self.env["stock.lot"].search(domaine_lots)
        if lots:
            entretiens = [("est_entretien", "=", True), ("lot_id", "in", lots.ids),
                          ("statut_entretien", "in", ("a_planifier", "planifie"))]
            domaine_tickets = list(Domain.OR([domaine_tickets, entretiens]))
        return "helpdesk.ticket", domaine_tickets

    def _action_entretiens_et_reparations(self):
        """Carte d'echeance avec des reparations : la liste des tickets ; sinon False (liste des machines)."""
        modele, domaine_tickets = self._liste_echeance(self.code)
        if modele != "helpdesk.ticket":
            return False
        action = self._action_xml("suivi_machines_pilotage.action_pilotage_appels", self.name, {}, domaine_tickets)
        action.pop("help", None)
        return action

    @api.model
    def _action_pour_code(self, code, nom=None):
        """Liste filtree d'un code (avec ou sans carte affichee)."""
        xmlid, filtre = self._ACTIONS.get(code, (None, None))
        if not xmlid:
            return False
        action = self.env["ir.actions.act_window"]._for_xml_id(xmlid)
        contexte = {}
        for filtre_nom in ((filtre,) if isinstance(filtre, str) else filtre or ()):
            contexte["search_default_" + filtre_nom] = 1
        # Carte regroupee sur un seul modele (ex. entretiens + reparations + machines a remplacer faits ce
        # mois) : la liste montre exactement ce que la carte compte
        # La liste montre EXACTEMENT ce que le chiffre compte : le critere de la carte (et ses etiquettes du
        # meme modele), sans filtre de recherche qui pourrait compter autrement ; les regroupements restent
        model, domaine = self._domaines().get(code, (None, None))
        model_parts, domaine_parts = self._parts_reparation().get(code, (None, None))
        if model and model == action.get("res_model"):
            action["domain"] = list(Domain.OR([domaine, domaine_parts])) if model_parts == model else domaine
            contexte = {cle: val for cle, val in contexte.items() if cle.startswith("search_default_grp")}
        action["context"] = contexte
        if nom:
            action["display_name"] = action["name"] = nom
        # Le message « aucun enregistrement » (HTML) s'afficherait en texte brut depuis un bouton
        action.pop("help", None)
        return action
