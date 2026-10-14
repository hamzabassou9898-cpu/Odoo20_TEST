# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

# Frequence des entretiens (mois)
FREQUENCES_ENTRETIEN = [("3", "Tous les 3 mois"), ("6", "Tous les 6 mois"), ("12", "Tous les 12 mois"),
                        ("24", "Tous les 24 mois")]


class StockPicking(models.Model):
    _inherit = "stock.picking"

    livreur_id = fields.Many2one("res.users", "Technicien assigné", index="btree_not_null", tracking=True,
                                 domain="[('share', '=', False)]",
                                 help="Technicien qui fait la livraison (ou le ramassage) de la machine.")
    # Livraison de machines chez le client : premier entretien et frequence (gardes sur la machine)
    livre_machines = fields.Boolean("Livre des machines", compute="_compute_livre_machines")
    prochain_entretien = fields.Date(
        "Prochain entretien", copy=False,
        help="Date du premier entretien des machines livrées. Odoo la garde sur la fiche de chaque machine "
             "et prévient le bureau un mois avant.")
    frequence_entretien = fields.Selection(
        FREQUENCES_ENTRETIEN, "Fréquence des entretiens", copy=False,
        help="Ensuite, Odoo calcule chaque entretien : dernier entretien + fréquence.")

    # Echange de machine : le ramassage de l'ancienne et la livraison de la nouvelle, valides ensemble
    echange_picking_id = fields.Many2one(
        "stock.picking", "Échange lié", copy=False, readonly=True, index="btree_not_null",
        help="Échange de machine : l'autre transfert (ramassage ou livraison). Valider l'un valide les deux.")

    @api.depends("move_ids.product_id", "location_dest_id")
    def _compute_livre_machines(self):
        for picking in self:
            picking.livre_machines = any(m.est_machine and m._vers_client() for m in picking.move_ids)

    # Fiche de machine en haut du transfert : des que le n° de serie est choisi
    machine_fiche_ids = fields.Many2many("stock.lot", string="Machines du transfert",
                                         compute="_compute_machine_fiche")
    machine_fiche_count = fields.Integer("Nb machines", compute="_compute_machine_fiche")
    machine_fiche_label = fields.Char("Machine", compute="_compute_machine_fiche")

    @api.depends("move_ids.machine_lot_id", "move_ids.move_line_ids.lot_id")
    def _compute_machine_fiche(self):
        for picking in self:
            lots = (picking.move_ids.machine_lot_id | picking.move_ids.move_line_ids.lot_id).filtered("est_machine")
            picking.machine_fiche_ids = lots
            picking.machine_fiche_count = len(lots)
            picking.machine_fiche_label = (lots.ref or lots.name) if len(lots) == 1 else \
                self.env._("%s machines", len(lots))

    def action_fiche_machines(self):
        """Une machine : sa fiche ; plusieurs : la liste des fiches."""
        self.ensure_one()
        lots = self.machine_fiche_ids
        if len(lots) == 1:
            return {"type": "ir.actions.act_window", "res_model": "stock.lot", "res_id": lots.id,
                    "view_mode": "form", "views": [(False, "form")], "target": "current"}
        return {"type": "ir.actions.act_window", "name": self.env._("Machines - %s", self.name),
                "res_model": "stock.lot", "view_mode": "list,form", "views": [(False, "list"), (False, "form")],
                "domain": [("id", "in", lots.ids)]}

    technicien_requis = fields.Boolean(
        "Technicien requis", compute="_compute_technicien_requis",
        help="Livraison chez un client ou ramassage : le technicien assigné est obligatoire pour valider.")

    @api.depends("location_id.usage", "location_dest_id.usage", "state")
    def _compute_technicien_requis(self):
        for picking in self:
            picking.technicien_requis = picking._est_tournee_client() and picking.state not in ("done", "cancel")

    def _est_tournee_client(self):
        """Livraison chez le client ou ramassage chez lui (location comprise)."""
        self.ensure_one()
        societe = self.company_id or self.env.company
        loc_location = societe.rental_loc_id if "rental_loc_id" in societe._fields else False
        emplacements = self.location_id | self.location_dest_id
        return "customer" in emplacements.mapped("usage") or bool(loc_location and loc_location in emplacements)

    def button_validate(self):
        # Echange de machine : une seule operation (le ramassage et la livraison ensemble)
        lies = self.echange_picking_id.filtered(lambda p: p.state not in ("done", "cancel")) - self
        if lies:
            return (self | lies).button_validate()
        sans_technicien = self.filtered(lambda p: p._est_tournee_client() and not p.livreur_id
                                        and p.state not in ("done", "cancel"))
        if sans_technicien:
            raise UserError(self.env._(
                "Choisissez le technicien assigné avant de valider : %s.",
                ", ".join(sans_technicien.mapped("name"))))
        sans_entretien = self.filtered(lambda p: p.livre_machines and p.state not in ("done", "cancel")
                                       and not (p.prochain_entretien and p.frequence_entretien))
        if sans_entretien:
            raise UserError(self.env._(
                "Indiquez le prochain entretien et sa fréquence (3, 6, 12 mois…) avant de valider : %s.",
                ", ".join(sans_entretien.mapped("name"))))
        return super().button_validate()

    def _action_done(self):
        res = super()._action_done()
        self._enregistrer_entretien_machines()
        return res

    def _enregistrer_entretien_machines(self):
        """Machines livrees chez le client : premier entretien et frequence sur leur fiche."""
        for picking in self.filtered(lambda p: p.state == "done" and p.prochain_entretien and p.frequence_entretien):
            lots = picking.move_ids.filtered(lambda m: m.est_machine and m._vers_client()).move_line_ids.lot_id
            lots.write({"prochain_entretien_fixe": picking.prochain_entretien,
                        "intervalle_entretien": int(picking.frequence_entretien)})


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        moves._creer_interventions_retour()
        return moves

    def _creer_interventions_retour(self):
        """Retour d'une machine (de chez le client vers l'entrepot) : intervention « Ramassage »
        faite, avec le livreur, et les frais de reprise si leur prix est renseigne."""
        frais = self.env.ref("suivi_machines.produit_frais_livraison", raise_if_not_found=False)
        Interv = self.env["machine.intervention"]
        for ml in self.move_line_ids.filtered(lambda l: l.state == "done" and l.lot_id.est_machine):
            societe = ml.company_id or self.env.company
            loc_location = societe.rental_loc_id if "rental_loc_id" in societe._fields else False
            depuis_client = (ml.location_id.usage == "customer"
                             or (loc_location and ml.location_id == loc_location))
            vers_entrepot = ml.location_dest_id.usage == "internal" and ml.location_dest_id != loc_location
            if not (depuis_client and vers_entrepot):
                continue
            picking = ml.picking_id or ml.move_id.picking_id
            vals = {
                "lot_id": ml.lot_id.id,
                "type": "ramassage",
                "state": "fait",
                "partner_id": (picking.partner_id or ml.move_id.partner_id).id,
                "user_id": (picking.livreur_id or self.env.user).id,
                "description": self.env._("Retour de la machine (%s)", picking.name or ml.reference or ""),
            }
            if frais and frais.lst_price:
                vals["frais_ids"] = [(0, 0, {"product_id": frais.id, "name": frais.display_name,
                                             "prix_unitaire": frais.lst_price})]
            vals.update(self._vals_intervention_retour(ml, picking))
            Interv.sudo().create(vals)

    def _vals_intervention_retour(self, ml, picking):
        """Point d'extension : valeurs supplementaires de l'intervention de retour."""
        return {}
