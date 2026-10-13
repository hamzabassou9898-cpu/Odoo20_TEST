# -*- coding: utf-8 -*-
"""Machine a remplacer : echange en une seule operation.

Depuis le ticket « Machine a remplacer » : on choisit la machine de remplacement (en entrepot), puis
« Echanger la machine » cree ensemble le ramassage de l'ancienne (son n° de serie revient en inventaire)
et la livraison de la nouvelle, au meme client, avec le meme technicien et la meme date. Valider l'un
valide les deux ; l'intervention de remplacement est alors faite et le ticket resolu.
"""
from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.addons.suivi_machines.models.stock_picking import FREQUENCES_ENTRETIEN


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    lot_remplacement_id = fields.Many2one(
        "stock.lot", "Machine de remplacement", tracking=True, copy=False,
        domain="[('est_machine', '=', True), ('machine_statut', '=', 'entrepot')]",
        help="Machine en entrepôt qui sera livrée à la place de celle du ticket.")
    echange_retour_id = fields.Many2one("stock.picking", "Ramassage (échange)", copy=False, readonly=True)
    echange_livraison_id = fields.Many2one("stock.picking", "Livraison (échange)", copy=False, readonly=True)

    def _echange_verifier(self):
        self.ensure_one()
        if self.type_demande != "remplacement":
            raise UserError(self.env._("L'échange se fait depuis un ticket « Machine à remplacer »."))
        if self.echange_livraison_id:
            raise UserError(self.env._("L'échange est déjà créé : %s.", self.echange_livraison_id.name))
        if not self.lot_id or not self.lot_id.machine_client_id:
            raise UserError(self.env._("Choisissez la machine à remplacer (numéro de série chez le client)."))
        if not self.lot_remplacement_id:
            raise UserError(self.env._("Choisissez la machine de remplacement (en entrepôt)."))
        if self.lot_remplacement_id.machine_statut != "entrepot":
            raise UserError(self.env._("La machine de remplacement %s n'est pas en entrepôt.",
                                       self.lot_remplacement_id.display_name))
        if not self._technicien_ticket():
            raise UserError(self.env._("Assignez le technicien qui fera l'échange (Assigné à)."))

    def _echange_derniere_livraison(self):
        """Derniere livraison faite de l'ancienne machine vers l'endroit ou elle est (client ou location)."""
        self.ensure_one()
        return self.env["stock.move.line"].sudo().search(
            [("lot_id", "=", self.lot_id.id), ("state", "=", "done"),
             ("location_dest_id", "=", self.lot_id.location_id.id)], order="date desc, id desc", limit=1)

    def action_echanger_machine(self):
        """Ramassage de l'ancienne machine + livraison de la nouvelle, lies : une seule operation."""
        self.ensure_one()
        self._echange_verifier()
        ancienne, nouvelle = self.lot_id, self.lot_remplacement_id
        technicien = self._technicien_ticket()
        quand = self.date_planifiee or fields.Datetime.now()
        client = self.commerce_id or self.partner_id or ancienne.machine_client_id
        chez_client = ancienne.location_id
        entrepot = self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1)
        ligne_vente = self._echange_derniere_livraison().move_id.sale_line_id
        # Meme produit : l'echange reste dans le meme contrat (livre - retourne = toujours 1 machine)
        ligne = ligne_vente if ligne_vente and ligne_vente.product_id == nouvelle.product_id else ligne_vente.browse()
        Picking, Move = self.env["stock.picking"], self.env["stock.move"]
        commun = {"partner_id": client.id, "livreur_id": technicien.id, "scheduled_date": quand,
                  "origin": self.name, "ticket_assistance_id": self.id}
        retour = Picking.create(dict(commun, picking_type_id=entrepot.in_type_id.id,
                                     location_id=chez_client.id, location_dest_id=entrepot.lot_stock_id.id))
        Move.create({"product_id": ancienne.product_id.id, "product_uom_qty": 1,
                     "uom_id": ancienne.product_id.uom_id.id, "picking_id": retour.id,
                     "location_id": chez_client.id, "location_dest_id": entrepot.lot_stock_id.id,
                     "machine_lot_id": ancienne.id, "partner_id": client.id,
                     "sale_line_id": ligne.id, "to_refund": bool(ligne)})
        frequence = str(ancienne.intervalle_entretien or 12)
        livraison = Picking.create(dict(
            commun, picking_type_id=entrepot.out_type_id.id, location_id=entrepot.lot_stock_id.id,
            location_dest_id=chez_client.id, echange_picking_id=retour.id,
            frequence_entretien=frequence if frequence in dict(FREQUENCES_ENTRETIEN) else "12",
            prochain_entretien=ancienne.date_prochain_entretien))
        Move.create({"product_id": nouvelle.product_id.id, "product_uom_qty": 1,
                     "uom_id": nouvelle.product_id.uom_id.id, "picking_id": livraison.id,
                     "location_id": entrepot.lot_stock_id.id, "location_dest_id": chez_client.id,
                     "machine_lot_id": nouvelle.id, "partner_id": client.id, "sale_line_id": ligne.id})
        retour.echange_picking_id = livraison
        (retour | livraison).action_confirm()
        (retour | livraison).action_assign()
        # Retour depuis le client : Odoo ne reserve pas, on indique le n° de serie qui revient
        for move in retour.move_ids:
            if move.move_line_ids:
                move.move_line_ids.write({"lot_id": ancienne.id, "quantity": 1})
            else:
                self.env["stock.move.line"].create({
                    "move_id": move.id, "picking_id": retour.id, "product_id": ancienne.product_id.id,
                    "lot_id": ancienne.id, "quantity": 1, "location_id": chez_client.id,
                    "location_dest_id": entrepot.lot_stock_id.id})
        self.write({"echange_retour_id": retour.id, "echange_livraison_id": livraison.id})
        self.message_post(body=Markup("<p>%s</p>") % self.env._(
            "Échange créé : ramassage %(retour)s (%(ancienne)s revient en inventaire) et livraison %(livraison)s "
            "(%(nouvelle)s), technicien %(tech)s. Valider l'un valide les deux.",
            retour=retour.name, ancienne=ancienne.display_name, livraison=livraison.name,
            nouvelle=nouvelle.display_name, tech=technicien.name))
        return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": livraison.id,
                "view_mode": "form", "views": [(False, "form")], "target": "current"}

    def _terminer_echange(self):
        """Echange valide : intervention de remplacement faite (avec la nouvelle machine), ticket resolu."""
        for ticket in self:
            planifiees = ticket.sudo().intervention_ticket_ids.filtered(lambda i: i.state == "planifie")
            planifiees.with_context(synchro_intervention=True).write(
                {"lot_remplacement_id": ticket.lot_remplacement_id.id})
            planifiees.with_context(synchro_intervention=True).action_fait()
            # Etape « Resolu » si elle existe (la validation du transfert ne doit jamais bloquer)
            resolu = ticket._etape_contenant("résolu", ticket.team_id if "team_id" in ticket._fields else None)
            if resolu:
                ticket.stage_id = resolu
            ticket.message_post(body=self.env._("Échange de machine terminé : %s chez le client, %s en entrepôt.",
                                                ticket.lot_remplacement_id.display_name, ticket.lot_id.display_name))


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        tickets = self.env["helpdesk.ticket"].search([
            "|", ("echange_livraison_id", "in", self.ids), ("echange_retour_id", "in", self.ids)])
        tickets.filtered(lambda t: t.echange_livraison_id.state == "done" and t.echange_retour_id.state == "done"
                         and not t._est_ferme())._terminer_echange()
        return res
