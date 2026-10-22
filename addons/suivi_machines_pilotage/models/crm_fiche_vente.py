# -*- coding: utf-8 -*-
"""Fiche de vente Monroy sur l'opportunite : les sections du « Formulaire de vente interne » du site
(prospection et acquisition client). Le formulaire du site remplit directement ces cases."""
from odoo import api, fields, models

TYPES_CLIENTELE = [("commercant", "Commerçant"), ("entreprise", "Entreprise"), ("particulier", "Particulier")]
TYPES_COMMERCE = [("depanneur", "Dépanneur"), ("restaurant", "Restaurant"), ("casse_croute", "Casse-croûte"),
                  ("bar_laitier", "Bar laitier"), ("cinema", "Cinéma"), ("comptoir_bonbons", "Comptoir à bonbons"),
                  ("salle_quilles", "Salle de quilles"), ("autre", "Autre")]
REGIONS = [("quebec", "Grande région de Québec"), ("portneuf", "Portneuf"),
           ("chaudiere_appalaches", "Chaudière-Appalaches / Beauce"), ("charlevoix", "Charlevoix"),
           ("bas_saint_laurent", "Bas-Saint-Laurent"), ("gaspesie", "Gaspésie"),
           ("cote_nord", "Côte-Nord et Îles-de-la-Madeleine")]
EQUIPEMENTS = [("barbotine_1", "Machine à barbotine – 1 réservoir (comptoir)"),
               ("barbotine_2", "Machine à barbotine – 2 réservoirs (comptoir)"),
               ("barbotine_3", "Machine à barbotine – 3 réservoirs (comptoir)"),
               ("barbotine_pied", "Machine à barbotine – sur pied"),
               ("popcorn", "Machine à popcorn"), ("a_determiner", "À déterminer")]
POTENTIELS = [("tres_bon", "Très bon"), ("bon", "Bon"), ("moyen", "Moyen"), ("faible", "Faible")]
DUREES = [("ete", "Saisonnier (été)"), ("6_mois", "6 mois"), ("1_an", "1 an"), ("2_ans", "2 ans"),
          ("3_ans", "3 ans"), ("autre", "Autre (préciser en commentaires)")]

# Cases que le formulaire du site peut remplir (en plus de celles du CRM deja permises)
CHAMPS_FORMULAIRE = ["user_id", "type_clientele", "type_commerce", "deja_client", "partner_id", "region_desservie",
                     "street", "city", "state_id", "zip", "country_id", "function", "telephone_contact",
                     "equipement_souhaite", "potentiel_emplacement", "machine_concurrente", "fournisseur_concurrent",
                     "type_contrat_envisage_id", "duree_location", "debut_location_souhaite", "via_formulaire_web"]
SUPPORT_FORMULAIRE = "Formulaire web"


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # 1. Informations generales
    type_clientele = fields.Selection(TYPES_CLIENTELE, "Type de clientèle", tracking=True)
    type_commerce = fields.Selection(TYPES_COMMERCE, "Type de commerce")
    deja_client = fields.Boolean("Déjà client chez Monroy ?")
    region_desservie = fields.Selection(REGIONS, "Région desservie", tracking=True)
    # 2. Contact du projet (nom, fonction et courriel : champs natifs de l'opportunite)
    telephone_contact = fields.Char("Téléphone du contact")
    # 3. Besoin & qualification
    equipement_souhaite = fields.Selection(EQUIPEMENTS, "Équipement souhaité", tracking=True)
    potentiel_emplacement = fields.Selection(POTENTIELS, "Potentiel de l'emplacement")
    machine_concurrente = fields.Boolean("Utilise déjà une machine concurrente ?")
    fournisseur_concurrent = fields.Char("Fournisseur / marque concurrente")
    # 4. Type de contrat envisage : les vrais types de contrat (ceux de « Nouvelle location »)
    type_contrat_envisage_id = fields.Many2one("suivi.type.contrat", "Type de contrat envisagé", tracking=True)
    est_proprietaire = fields.Boolean(compute="_compute_est_proprietaire")
    est_location_envisagee = fields.Boolean(compute="_compute_est_proprietaire")
    duree_location = fields.Selection(DUREES, "Durée de location")
    debut_location_souhaite = fields.Date("Début de location souhaité")
    # Case cachee du formulaire du site : l'opportunite recoit toujours le support « Formulaire web »
    via_formulaire_web = fields.Boolean("Reçue par le formulaire web", copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        support = False
        for vals in vals_list:
            if vals.get("via_formulaire_web"):
                support = support or self._support_formulaire_web()
                vals["medium_id"] = support.id
        return super().create(vals_list)

    @api.model
    def _support_formulaire_web(self):
        Support = self.env["utm.medium"].sudo()
        return Support.search([("name", "=ilike", SUPPORT_FORMULAIRE)], limit=1) \
            or Support.create({"name": SUPPORT_FORMULAIRE})

    @api.depends("type_contrat_envisage_id")
    def _compute_est_proprietaire(self):
        proprietaire = self.env.ref("suivi_machines.type_contrat_proprietaire", raise_if_not_found=False)
        for lead in self:
            type_contrat = lead.type_contrat_envisage_id
            lead.est_proprietaire = bool(type_contrat) and type_contrat == proprietaire
            lead.est_location_envisagee = bool(type_contrat) and type_contrat.type_commande == "location" \
                and type_contrat != proprietaire

    @api.model
    def _configuration_formulaire_vente(self):
        """Le « Formulaire de vente interne » du site peut remplir ces cases de l'opportunite."""
        champs = self.env["ir.model.fields"]
        if hasattr(champs, "formbuilder_whitelist"):   # module Site Web installe
            champs.formbuilder_whitelist("crm.lead", CHAMPS_FORMULAIRE)
        self._support_formulaire_web()
