# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    livreur_id = fields.Many2one("res.users", "Livreur", index="btree_not_null", tracking=True,
                                 domain="[('share', '=', False)]",
                                 help="Personne qui fait la livraison (ou la reprise) de la machine.")


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
