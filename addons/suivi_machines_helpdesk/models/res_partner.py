# -*- coding: utf-8 -*-
"""Fiche client : contrat de location actuel (choisi automatiquement), historique d'achat, sante du client."""
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models

NIVEAUX_SANTE = [("fidele", "Client fidèle"), ("surveiller", "À surveiller"), ("risque", "À risque")]


class ResPartner(models.Model):
    _inherit = "res.partner"

    contrat_location_id = fields.Many2one(
        "sale.order", "Contrat de location actuel", compute="_compute_contrats_client",
        groups="sales_team.group_sale_salesman",
        help="Choisi automatiquement : le contrat confirmé dont des machines sont chez le client, "
             "sinon le plus récent.")
    # Calcules avec le contrat (pas « related » sur un champ calcule : evite les avertissements d'Odoo)
    contrat_location_type = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Type de contrat", compute="_compute_contrats_client",
        groups="sales_team.group_sale_salesman")
    contrat_location_debut = fields.Datetime("Début du contrat", compute="_compute_contrats_client",
                                             groups="sales_team.group_sale_salesman")
    contrat_location_fin = fields.Datetime("Fin du contrat", compute="_compute_contrats_client",
                                           groups="sales_team.group_sale_salesman")
    historique_achat_ids = fields.Many2many(
        "sale.order", string="Historique d'achat", compute="_compute_contrats_client",
        groups="sales_team.group_sale_salesman")

    # Sante du client (un coup d'oeil sur la fiche)
    sante_devise_id = fields.Many2one("res.currency", compute="_compute_sante")
    # Onglets de la fiche client (comme dans le ticket)
    machine_client_ids = fields.Many2many("stock.lot", string="Machines chez le client",
                                          compute="_compute_onglets_client", groups="helpdesk.group_helpdesk_user")
    appel_client_ids = fields.Many2many("helpdesk.ticket", string="Appels de service",
                                        compute="_compute_onglets_client", groups="helpdesk.group_helpdesk_user")
    sante_nb_machines = fields.Integer("Machines chez lui", compute="_compute_sante",
                                       groups="sales_team.group_sale_salesman")
    sante_nb_appels = fields.Integer("Appels (12 mois)", compute="_compute_sante",
                                     groups="sales_team.group_sale_salesman")
    sante_impayes = fields.Monetary("Impayés", currency_field="sante_devise_id", compute="_compute_sante",
                                    groups="sales_team.group_sale_salesman")
    sante_chiffre = fields.Monetary("Chiffre d'affaires total", currency_field="sante_devise_id",
                                    compute="_compute_sante", groups="sales_team.group_sale_salesman")
    sante_niveau = fields.Selection(NIVEAUX_SANTE, "Santé du client", compute="_compute_sante",
                                    groups="sales_team.group_sale_salesman")
    sante_raison = fields.Char("Pourquoi", compute="_compute_sante", groups="sales_team.group_sale_salesman")

    def _compute_sante(self):
        maintenant = fields.Datetime.now()
        aujourdhui = fields.Date.context_today(self)
        Lot, Ticket, Facture = (self.env["stock.lot"].sudo(), self.env["helpdesk.ticket"].sudo(),
                                self.env["account.move"].sudo())
        for partner in self:
            partner.sante_devise_id = self.env.company.currency_id
            client = partner.commercial_partner_id
            if not client.id:
                partner.update({"sante_nb_machines": 0, "sante_nb_appels": 0, "sante_impayes": 0,
                                "sante_chiffre": 0, "sante_niveau": False, "sante_raison": False})
                continue
            du_client = [("partner_id", "child_of", client.id)]
            factures = Facture.search(du_client + [("move_type", "=", "out_invoice"), ("state", "=", "posted"),
                                                   ("payment_state", "in", ("not_paid", "partial"))])
            en_retard = factures.filtered(
                lambda f: f.invoice_date_due and f.invoice_date_due < aujourdhui - timedelta(days=60))
            appels_90j = Ticket.search_count(du_client + [("create_date", ">=", maintenant - timedelta(days=90))])
            raisons = []
            if en_retard:
                raisons.append(self.env._("factures impayées depuis plus de 60 jours"))
            if appels_90j > 5:
                raisons.append(self.env._("%s appels en 3 mois", appels_90j))
            if raisons:
                niveau = "risque"
            elif factures or appels_90j >= 3:
                niveau = "surveiller"
                raisons.append(self.env._("factures à payer") if factures
                               else self.env._("%s appels en 3 mois", appels_90j))
            else:
                niveau = "fidele"
            commandes = self.env["sale.order"].sudo().search(du_client + [("state", "=", "sale")])
            partner.update({
                "sante_nb_machines": Lot.search_count([("est_machine", "=", True),
                                                       ("machine_client_id", "child_of", client.id)]),
                "sante_nb_appels": Ticket.search_count(du_client + [
                    ("create_date", ">=", maintenant - timedelta(days=365))]),
                "sante_impayes": sum(factures.mapped("amount_residual")),
                "sante_chiffre": sum(commandes.mapped("amount_untaxed")),
                "sante_niveau": niveau,
                "sante_raison": ", ".join(raisons).capitalize() if raisons else False,
            })

    def _compute_onglets_client(self):
        Lot, Ticket = self.env["stock.lot"], self.env["helpdesk.ticket"]
        for partner in self:
            client = partner.commercial_partner_id
            if not client.id:
                partner.update({"machine_client_ids": False, "appel_client_ids": False})
                continue
            partner.machine_client_ids = Lot.search([("est_machine", "=", True),
                                                     ("machine_client_id", "child_of", client.id)])
            partner.appel_client_ids = Ticket.search([("partner_id", "child_of", client.id)],
                                                     order="create_date desc, id desc")

    # Boutons intelligents inutiles pour Monroy, retires de la fiche client (si le module est installe)
    BOUTONS_MASQUES = ("action_schedule_meeting", "action_open_partner_ledger", "open_partner_ledger",
                       "action_view_partner_ledger", "action_open_unreconciled_items")
    TEXTES_MASQUES = ("Éléments ouverts", "Open Items")

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "form":
            for bouton in arch.xpath("//div[@name='button_box']/button"):
                texte = " ".join(bouton.itertext())
                if bouton.get("name") in self.BOUTONS_MASQUES or any(t in texte for t in self.TEXTES_MASQUES):
                    bouton.set("invisible", "1")
        return arch, view

    def _compute_contrats_client(self):
        Commande = self.env["sale.order"]
        for partner in self:
            client = partner.commercial_partner_id
            if not client.id:
                partner.update({"contrat_location_id": False, "historique_achat_ids": False,
                                "contrat_location_type": False, "contrat_location_debut": False,
                                "contrat_location_fin": False})
                continue
            commandes = Commande.search([("partner_id", "child_of", client.id), ("state", "=", "sale")],
                                        order="date_order desc, id desc")
            partner.historique_achat_ids = commandes
            locations = commandes.filtered(lambda c: c.type_commande == "location")
            # Contrat actuel : machines encore chez le client, sinon le plus recent
            contrat = locations.filtered(lambda c: c._machines_a_reprendre())[:1] or locations[:1] \
                or commandes.filtered("type_contrat_id")[:1]   # contrat proprietaire (machine au client)
            partner.update({"contrat_location_id": contrat, "contrat_location_type": contrat.type_commande,
                            "contrat_location_debut": contrat.date_debut_location,
                            "contrat_location_fin": contrat.date_fin_location})


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    # Contrat du client, affiche des que le client est choisi
    contrat_client_id = fields.Many2one("sale.order", "Contrat de location", compute="_compute_contrat_client",
                                        groups="sales_team.group_sale_salesman")
    contrat_client_type = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Type de contrat", compute="_compute_contrat_client",
        groups="sales_team.group_sale_salesman")
    contrat_client_modele_id = fields.Many2one("suivi.type.contrat", "Contrat", compute="_compute_contrat_client",
                                               groups="sales_team.group_sale_salesman",
                                               help="Location, convention, popcorn ou propriétaire.")
    # Ce que couvre le contrat du client (visible par tous : bandeau du ticket)
    contrat_couverture = fields.Selection(
        [("couvert", "Couvert par le contrat"), ("facture", "Facturé au client")], "Appels de service",
        compute="_compute_contrat_client")
    contrat_couverture_texte = fields.Char("Couverture du contrat", compute="_compute_contrat_client")
    contrat_client_debut = fields.Datetime("Début du contrat", compute="_compute_contrat_client",
                                           groups="sales_team.group_sale_salesman")
    contrat_client_fin = fields.Datetime("Fin du contrat", compute="_compute_contrat_client",
                                         groups="sales_team.group_sale_salesman")

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        tickets._noter_contrat()
        return tickets

    def write(self, vals):
        res = super().write(vals)
        if "partner_id" in vals:
            self._noter_contrat()
        return res

    def _noter_contrat(self):
        """Note automatique dans le fil du ticket : le contrat du client et ce qu'il couvre / facture."""
        for ticket in self.filtered("contrat_couverture_texte"):
            ticket.with_context(mail_create_nosubscribe=True).message_post(
                body=Markup("<p><b>%s</b></p><p>%s</p>") % (
                    self.env._("Contrat du client"), ticket.contrat_couverture_texte),
                message_type="comment", subtype_xmlid="mail.mt_note")

    def _couverture_du_contrat(self, type_contrat):
        """Bandeau du ticket : ce que le contrat du client couvre et ce qui se facture."""
        devise = self.env.company.currency_id
        if not type_contrat:
            return {"contrat_couverture": False, "contrat_couverture_texte": False}
        if type_contrat.couvre_reparations:
            texte = self.env._("%(type)s : entretien et réparations usuelles couverts par le contrat.",
                               type=type_contrat.name)
            if type_contrat.frais_appel_inutile:
                texte += " " + self.env._("À facturer seulement : appel de service inutile (%(montant)s) "
                                          "ou dommages.", montant=devise.format(type_contrat.frais_appel_inutile))
            return {"contrat_couverture": "couvert", "contrat_couverture_texte": texte}
        return {"contrat_couverture": "facture", "contrat_couverture_texte": self.env._(
            "%(type)s : chaque appel se facture — déplacement %(deplacement)s + %(taux)s de l'heure + pièces.",
            type=type_contrat.name, deplacement=devise.format(type_contrat.frais_deplacement),
            taux=devise.format(type_contrat.taux_horaire))}

    @api.depends("partner_id")
    def _compute_contrat_client(self):
        for ticket in self:
            client = (ticket.commerce_id or ticket.partner_id).sudo()
            contrat = client.contrat_location_id if client else self.env["sale.order"].sudo()
            ticket.update({"contrat_client_id": contrat, "contrat_client_type": contrat.type_commande,
                           "contrat_client_modele_id": contrat.type_contrat_id,
                           **ticket._couverture_du_contrat(contrat.type_contrat_id),
                           "contrat_client_debut": contrat.date_debut_location,
                           "contrat_client_fin": contrat.date_fin_location})
