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
    forfait_montant = fields.Float(related="type_contrat_id.forfait_montant")
    forfait_prochaine_date = fields.Date(
        "Prochain forfait annuel", copy=False, tracking=True,
        help="Date du prochain forfait annuel d'entretien (anniversaire de la signature). "
             "Odoo prépare le bon de vente ce jour-là.")
    forfait_contrat_id = fields.Many2one(
        "sale.order", "Contrat (forfait)", copy=False, readonly=True, index="btree_not_null",
        help="Contrat dont ce bon de vente facture le forfait annuel d'entretien.")
    forfait_ids = fields.One2many("sale.order", "forfait_contrat_id", "Forfaits annuels")
    nb_forfaits = fields.Integer("Nb forfaits annuels", compute="_compute_nb_forfaits")

    @api.depends("forfait_ids")
    def _compute_nb_forfaits(self):
        for order in self:
            order.nb_forfaits = len(order.forfait_ids)

    @api.onchange("type_contrat_id")
    def _onchange_type_contrat_id(self):
        if self.type_contrat_id:
            self.type_commande = self.type_contrat_id.type_commande

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("type_contrat_id") and "type_commande" not in vals:
                vals["type_commande"] = self.env["suivi.type.contrat"].browse(vals["type_contrat_id"]).type_commande
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("type_contrat_id") and "type_commande" not in vals:
            vals = dict(vals, type_commande=self.env["suivi.type.contrat"].browse(
                vals["type_contrat_id"]).type_commande)
        return super().write(vals)

    def action_confirm(self):
        res = super().action_confirm()
        # Clause 8.2 : forfait paye a la signature, puis tous les 12 mois
        aujourdhui = fields.Date.context_today(self)
        for contrat in self.filtered(lambda o: o.state == "sale" and o.forfait_montant > 0
                                     and not o.forfait_contrat_id and not o.forfait_prochaine_date):
            contrat.forfait_prochaine_date = aujourdhui
            contrat._creer_forfait_annuel()
        return res

    def action_voir_forfaits(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Forfaits annuels - %s", self.name),
                "res_model": "sale.order", "view_mode": "list,form", "views": [(False, "list"), (False, "form")],
                "domain": [("forfait_contrat_id", "=", self.id)],
                "context": {"create": False}}

    # ------------------------------------------------------------ forfait annuel
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

    def _creer_forfait_annuel(self):
        """Bon de vente du forfait annuel (brouillon, a confirmer par le bureau) ; prochaine date + 12 mois."""
        Commande = self.env["sale.order"]
        crees = Commande
        for contrat in self:
            debut = contrat.forfait_prochaine_date or fields.Date.context_today(self)
            nombre, machines = contrat._machines_forfait()
            contrat.forfait_prochaine_date = debut + relativedelta(months=12)
            if nombre <= 0:
                contrat.message_post(body=self.env._(
                    "Forfait annuel du %s : aucune machine chez le client, rien à facturer.", debut))
                continue
            type_contrat = contrat.type_contrat_id
            produit = type_contrat.forfait_produit_id or self.env.ref(
                "suivi_machines.produit_forfait_entretien", raise_if_not_found=False)
            libelle = self.env._(
                "Frais annuels d'entretien et de réparations usuelles (%(type)s) du %(debut)s au %(fin)s",
                type=type_contrat.name, debut=debut,
                fin=debut + relativedelta(months=12, days=-1))
            if machines:
                libelle += "\n" + self.env._("Machines : %s", ", ".join(machines.mapped(lambda l: l.ref or l.name)))
            forfait = Commande.create({
                "partner_id": contrat.partner_id.id, "type_commande": "vente", "origin": contrat.name,
                "forfait_contrat_id": contrat.id, "user_id": contrat.user_id.id,
                "order_line": [(0, 0, {"product_id": produit.id, "name": libelle, "product_uom_qty": nombre,
                                       "price_unit": type_contrat.forfait_montant})]})
            contrat.message_post(body=Markup("<p>%s</p>") % self.env._(
                "Forfait annuel %(forfait)s préparé : %(nb)s machine(s) × %(montant)s.",
                forfait=forfait.name, nb=nombre, montant=type_contrat.forfait_montant))
            forfait.activity_schedule(
                "mail.mail_activity_data_todo", user_id=(contrat.user_id or self.env.ref("base.user_admin")).id,
                summary=self.env._("Forfait annuel à confirmer et facturer"),
                note=self.env._("Contrat %s : forfait annuel d'entretien.", contrat.name))
            crees |= forfait
        return crees

    @api.model
    def _cron_forfaits_annuels(self):
        """Chaque jour : forfait annuel des contrats dont l'anniversaire est arrive."""
        contrats = self.search([("state", "=", "sale"), ("forfait_contrat_id", "=", False),
                                ("type_contrat_id.forfait_montant", ">", 0),
                                ("forfait_prochaine_date", "<=", fields.Date.context_today(self))])
        return contrats._creer_forfait_annuel()
