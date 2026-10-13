# -*- coding: utf-8 -*-
"""Indicateurs du tableau de bord « Pilotage » : un compteur par carte, un clic ouvre la liste."""
from datetime import timedelta

from odoo import api, fields, models

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
        ouverts = ["!", "|", "|", ("stage_id.name", "ilike", "résolu"), ("stage_id.name", "ilike", "annul"),
                   ("stage_id.name", "ilike", "clôtur")]
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
            "tickets_nouveaux": ("helpdesk.ticket", ["|", ("stage_id", "=", False), ("stage_id.name", "ilike", "nouveau"),
                                                     ("user_id", "=", False),
                                                     ("statut_entretien", "not in", ["planifie", "fait"])]),
            # Planifie = assigne a un technicien (ou intervention planifiee) : dans sa journee
            # Entretiens + reparations + machines a remplacer assignes a un technicien, pas encore valides
            "entretiens_ouverts": ("helpdesk.ticket", [("statut_entretien", "=", "planifie")]),
            # Reparation / machine a remplacer assignee a un technicien, pas encore resolue
            "reparations_planifiees": ("helpdesk.ticket", [("est_entretien", "=", False),
                                                           ("statut_entretien", "=", "planifie")]),
            "reprises_ouvertes": ("helpdesk.ticket", [("type_ticket", "=", "reprise")] + ouverts),
            "appels_mois": ("helpdesk.ticket", appels + [
                ("create_date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
            "appels_sans_machine": ("helpdesk.ticket", appels + ouverts + [("lot_id", "=", False)]),
            "livraisons_a_faire": ("stock.picking", transfert + a_faire + livraison),
            "ramassages_a_faire": ("stock.picking", transfert + a_faire + ramassage),
            "sans_livreur": ("stock.picking", transfert + a_faire + [("livreur_id", "=", False)]),
            "livraisons_faites": ("stock.picking", transfert + livraison + [
                ("state", "=", "done"), ("date_done", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
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
    def _parts_reparation(self):
        """Partie « Réparations » des cartes d'entretien (machines) : code -> (modele, domaine)."""
        b = self._bornes()
        debut = fields.Datetime.to_datetime(b["aujourdhui"])
        jour = timedelta(days=1)
        reparations = [("est_entretien", "=", False), ("statut_entretien", "in", ("a_planifier", "planifie")),
                       ("date_planifiee", "!=", False)]
        return {
            "entretien_retard": ("helpdesk.ticket", reparations + [("date_planifiee", "<", debut)]),
            "entretien_semaine": ("helpdesk.ticket", reparations + [
                ("date_planifiee", ">=", debut),
                ("date_planifiee", "<", fields.Datetime.to_datetime(b["semaine"]) + jour)]),
            "entretien_mois": ("helpdesk.ticket", reparations + [
                ("date_planifiee", ">=", debut),
                ("date_planifiee", "<", fields.Datetime.to_datetime(b["mois"]) + jour)]),
            "entretiens_faits": ("machine.intervention", [
                ("type", "in", ("bris", "reparation", "remplacement")), ("state", "=", "fait"),
                ("date", ">=", fields.Datetime.to_datetime(b["debut_mois"]))]),
        }

    @api.model
    def _compte_reparations(self, code):
        model, domaine = self._parts_reparation().get(code, (None, None))
        return self.env[model].search_count(domaine) if model else 0

    def action_ouvrir_reparations(self):
        """Etiquette « Réparation » d'une carte d'entretien : la liste des réparations correspondantes."""
        self.ensure_one()
        model, domaine = self._parts_reparation().get(self.code, (None, None))
        if not model:
            return False
        xmlid = ("suivi_machines_pilotage.action_pilotage_appels" if model == "helpdesk.ticket"
                 else "suivi_machines_pilotage.action_pilotage_entretiens_faits")
        action = self._action_xml(xmlid, self.env._("Réparations — %s", self.name), {}, domaine)
        action.pop("help", None)
        return action

    @api.model
    def _repartition_par_type(self, domaine):
        """Nombre de tickets par type (Entretien, Reparation, Machine a remplacer) pour la carte."""
        Ticket = self.env["helpdesk.ticket"]
        libelles = dict(Ticket._fields["type_demande"]._description_selection(self.env))
        couleurs = {"entretien": "info", "reparation": "danger", "remplacement": "warning"}
        groupes = Ticket._read_group(domaine, ["type_demande"], ["__count"])
        ordre = ["entretien", "reparation", "remplacement"]
        groupes = sorted(groupes, key=lambda g: ordre.index(g[0]) if g[0] in ordre else len(ordre))
        return [[libelles.get(type_, self.env._("Autre")), nombre, couleurs.get(type_, "secondary")]
                for type_, nombre in groupes]

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
                entretiens, reparations = ind.valeur, self._compte_reparations(ind.code)
                ind.valeur = entretiens + reparations
                if ind.valeur:
                    ind.repartition = [[self.env._("Entretien"), entretiens, "info", ""],
                                       [self.env._("Réparation"), reparations, "danger", "reparations"]]
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
        "livraisons_faites": ("suivi_machines_pilotage.action_pilotage_transferts", "livrees_mois"),
        "bris_mois": ("suivi_machines_pilotage.action_pilotage_bris", "ce_mois"),
        "machines_probleme": ("suivi_machines_pilotage.action_pilotage_machines_probleme", None),
        "a_facturer": ("suivi_machines_pilotage.action_pilotage_facturation", "a_facturer"),
        "facturer_sage": ("suivi_machines_pilotage.action_pilotage_facturation", "bon_cree"),
        "sage_clients": ("suivi_sage.action_sage_clients", "sage_a_transferer"),
        "sage_fournisseurs": ("suivi_sage.action_sage_fournisseurs", "sage_a_transferer"),
    }

    def action_ouvrir(self):
        self.ensure_one()
        return self._action_pour_code(self.code, self.name)

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
        action["context"] = contexte
        if nom:
            action["display_name"] = action["name"] = nom
        # Le message « aucun enregistrement » (HTML) s'afficherait en texte brut depuis un bouton
        action.pop("help", None)
        return action
