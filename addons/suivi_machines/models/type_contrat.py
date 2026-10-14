# -*- coding: utf-8 -*-
"""Types de contrat Monroy (location, convention, convention popcorn, proprietaire) et forfait annuel.

Chaque type regle le comportement du contrat (machine louee ou vendue) et le forfait annuel d'entretien
(clause 8.2 : montant par machine, a la signature puis tous les 12 mois). Les montants se modifient dans
Ventes > Configuration > Types de contrat, sans programmation.
"""
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models


class SuiviTypeContrat(models.Model):
    _name = "suivi.type.contrat"
    _description = "Type de contrat"
    _order = "sequence, id"

    name = fields.Char("Type de contrat", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    type_commande = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Machine", required=True, default="location",
        help="Location : la machine reste à Monroy (« En location » chez le client). "
             "Vente : la machine appartient au client (contrat propriétaire).")
    forfait_montant = fields.Float(
        "Forfait annuel par machine", digits="Product Price",
        help="Frais annuels d'entretien et de réparations usuelles (clause 8.2) : payés à la signature, "
             "puis tous les 12 mois, pour chaque machine. 0 = aucun forfait.")
    forfait_produit_id = fields.Many2one(
        "product.product", "Produit du forfait", domain="[('type', '=', 'service')]",
        default=lambda s: s.env.ref("suivi_machines.produit_forfait_entretien", raise_if_not_found=False),
        help="Service utilisé sur le bon de vente du forfait annuel.")
    # Appels de service (clause 7.3) : ce qui est couvert et ce qui se facture
    couvre_reparations = fields.Boolean(
        "Entretien et réparations couverts", default=True,
        help="Coché : l'entretien et les réparations usuelles sont couverts par le contrat (location, "
             "convention). Seuls l'appel de service inutile et les dommages se facturent. Décoché "
             "(propriétaire) : chaque appel se facture (déplacement + taux horaire + pièces).")
    frais_appel_inutile = fields.Float("Appel de service inutile", digits="Product Price",
                                       help="Clause 7.3 : montant facturé pour un appel de service inutile.")
    frais_deplacement = fields.Float("Frais de déplacement", digits="Product Price",
                                     help="Contrat propriétaire : frais de déplacement de chaque appel.")
    taux_horaire = fields.Float("Taux horaire", digits="Product Price",
                                help="Contrat propriétaire : main-d'œuvre par heure.")
    note = fields.Text("Note")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    type_contrat_id = fields.Many2one(
        "suivi.type.contrat", "Type de contrat", tracking=True, copy=True, index="btree_not_null",
        help="Location, convention, convention popcorn ou propriétaire : règle le type (vente / location) "
             "et le forfait annuel d'entretien.")
    forfait_montant = fields.Float(
        "Forfait annuel / machine", digits="Product Price", tracking=True, copy=True,
        compute="_compute_forfait_montant", store=True, readonly=False, precompute=True,
        help="Prix du forfait annuel d'entretien par machine pour CE contrat : celui du type de contrat, "
             "modifiable (prix négocié). Repris chaque année.")
    forfait_prochaine_date = fields.Date(
        "Prochain forfait annuel", copy=False, tracking=True,
        help="Anniversaire de la signature : ce jour-là, Odoo ajoute au contrat la ligne du forfait de "
             "l'année suivante, à facturer.")

    @api.depends("type_contrat_id")
    def _compute_forfait_montant(self):
        for order in self:
            order.forfait_montant = order.type_contrat_id.forfait_montant

    @api.onchange("type_contrat_id")
    def _onchange_type_contrat_id(self):
        if self.type_contrat_id:
            self.type_commande = self.type_contrat_id.type_commande

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("type_contrat_id") and "type_commande" not in vals:
                vals["type_commande"] = self.env["suivi.type.contrat"].browse(vals["type_contrat_id"]).type_commande
        commandes = super().create(vals_list)
        commandes._synchroniser_forfait(prix=True)
        return commandes

    def write(self, vals):
        if vals.get("type_contrat_id") and "type_commande" not in vals:
            vals = dict(vals, type_commande=self.env["suivi.type.contrat"].browse(
                vals["type_contrat_id"]).type_commande)
        res = super().write(vals)
        if not self.env.context.get("synchro_forfait") and (
                {"order_line", "type_contrat_id", "forfait_montant"} & set(vals)):
            self._synchroniser_forfait(prix=bool({"type_contrat_id", "forfait_montant"} & set(vals)))
        return res

    def action_confirm(self):
        res = super().action_confirm()
        # Clause 8.2 : forfait paye a la signature (ligne du contrat), puis tous les 12 mois
        aujourdhui = fields.Date.context_today(self)
        for contrat in self.filtered(lambda o: o.state == "sale" and o.forfait_montant > 0
                                     and not o.forfait_prochaine_date):
            contrat.forfait_prochaine_date = aujourdhui + relativedelta(months=12)
        return res

    # ------------------------------------------------------------ forfait annuel (ligne du contrat)
    def _produit_forfait(self):
        return self.type_contrat_id.forfait_produit_id or self.env.ref(
            "suivi_machines.produit_forfait_entretien", raise_if_not_found=False)

    def _libelle_forfait(self, debut, machines=None):
        libelle = self.env._(
            "Frais annuels d'entretien et de réparations usuelles (%(type)s) du %(debut)s au %(fin)s",
            type=self.type_contrat_id.name, debut=debut, fin=debut + relativedelta(months=12, days=-1))
        if machines:
            libelle += "\n" + self.env._("Machines : %s", ", ".join(machines.mapped(lambda l: l.ref or l.name)))
        return libelle

    def _synchroniser_forfait(self, prix=False):
        """Soumission : la ligne du forfait de la 1re annee suit le contrat (une par machine commandee).
        Le prix est celui du contrat (modifiable) ; un prix change a la main sur la ligne est garde."""
        for order in self.filtered(lambda o: o.state in ("draft", "sent")).with_context(synchro_forfait=True):
            ligne = order.order_line.filtered("est_forfait")[:1]
            nombre = int(sum(order.order_line.filtered("est_machine").mapped("product_uom_qty")))
            produit = order._produit_forfait()
            if order.forfait_montant <= 0 or not nombre or not produit:
                if ligne:
                    ligne.unlink()
                continue
            debut = fields.Date.context_today(order)
            if not ligne:
                order.write({"order_line": [(0, 0, {
                    "product_id": produit.id, "est_forfait": True, "product_uom_qty": nombre,
                    "price_unit": order.forfait_montant, "name": order._libelle_forfait(debut),
                    "sequence": max(order.order_line.mapped("sequence") or [10]) + 1})]})
                continue
            valeurs = {}
            if ligne.product_uom_qty != nombre:
                valeurs["product_uom_qty"] = nombre
            if prix or "product_uom_qty" in valeurs:
                valeurs["price_unit"] = order.forfait_montant if prix else ligne.price_unit
            if valeurs:
                ligne.write(valeurs)

    def _machines_forfait(self):
        """Nombre de machines facturees au forfait : celles du contrat encore chez le client ; avant la
        livraison, les machines commandees. 0 si toutes sont revenues (contrat termine)."""
        self.ensure_one()
        chez_client = self.machine_ids.filtered("machine_client_id")
        if chez_client:
            return len(chez_client), chez_client
        livrees = self.picking_ids.filtered(lambda p: p.state == "done" and p.picking_type_code == "outgoing")
        if livrees:
            return 0, chez_client
        return int(sum(self.order_line.filtered("est_machine").mapped("product_uom_qty"))), chez_client

    def _ajouter_forfait_annuel(self):
        """Anniversaire : ligne du forfait de l'annee ajoutee AU CONTRAT (a facturer avec « Créer une
        facture »), au prix de ce contrat ; activite pour le bureau ; prochaine date + 12 mois."""
        for contrat in self:
            debut = contrat.forfait_prochaine_date or fields.Date.context_today(self)
            nombre, machines = contrat._machines_forfait()
            contrat.forfait_prochaine_date = debut + relativedelta(months=12)
            produit = contrat._produit_forfait()
            if nombre <= 0 or not produit:
                contrat.message_post(body=self.env._(
                    "Forfait annuel du %s : aucune machine chez le client, rien à facturer.", debut))
                continue
            # Prix negocie : celui de la derniere ligne de forfait du contrat, sinon celui du contrat
            precedente = contrat.order_line.filtered("est_forfait").sorted("id")[-1:]
            prix = precedente.price_unit if precedente else contrat.forfait_montant
            contrat.with_context(synchro_forfait=True).write({"order_line": [(0, 0, {
                "product_id": produit.id, "est_forfait": True, "product_uom_qty": nombre, "price_unit": prix,
                "name": contrat._libelle_forfait(debut, machines)})]})
            contrat.message_post(body=Markup("<p>%s</p>") % self.env._(
                "Forfait annuel ajouté au contrat : %(nb)s machine(s) × %(prix)s, à facturer.",
                nb=nombre, prix=prix))
            contrat.activity_schedule(
                "mail.mail_activity_data_todo", user_id=(contrat.user_id or self.env.ref("base.user_admin")).id,
                summary=self.env._("Forfait annuel à facturer"),
                note=self.env._("Le forfait annuel d'entretien a été ajouté au contrat : « Créer une facture »."))

    @api.model
    def _cron_forfaits_annuels(self):
        """Chaque jour : forfait annuel des contrats dont l'anniversaire est arrive."""
        contrats = self.search([("state", "=", "sale"), ("forfait_montant", ">", 0),
                                ("forfait_prochaine_date", "<=", fields.Date.context_today(self))])
        contrats._ajouter_forfait_annuel()
        return contrats


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    est_forfait = fields.Boolean("Forfait annuel", copy=False, readonly=True,
                                 help="Ligne du forfait annuel d'entretien du contrat.")
