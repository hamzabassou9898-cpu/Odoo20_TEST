# -*- coding: utf-8 -*-
from odoo import fields, models, tools
from odoo.tools import SQL

from .machine_intervention import TYPES


class MachineHistorique(models.Model):
    """Chronologie d'une machine : mouvements d'inventaire + interventions."""
    _name = "machine.historique"
    _description = "Historique machine"
    _auto = False
    _order = "date desc, id desc"
    _depends = {
        "stock.move.line": ["date", "lot_id", "product_id", "location_id", "location_dest_id",
                            "picking_id", "move_id", "state"],
        "machine.intervention": ["date", "lot_id", "product_id", "type", "name", "description",
                                 "partner_id", "user_id", "state"],
    }

    date = fields.Datetime("Date", readonly=True)
    lot_id = fields.Many2one("stock.lot", "Machine (n° de série)", readonly=True)
    product_id = fields.Many2one("product.product", "Produit", readonly=True)
    type = fields.Selection([("mouvement", "Mouvement d'inventaire")] + TYPES, "Type", readonly=True)
    reference = fields.Char("Référence", readonly=True)
    description = fields.Char("Description", readonly=True)
    partner_id = fields.Many2one("res.partner", "Client", readonly=True)
    user_id = fields.Many2one("res.users", "Par", readonly=True)
    state = fields.Char("Statut", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL("""
            CREATE OR REPLACE VIEW machine_historique AS (
                SELECT ml.id * 2 AS id, ml.date, ml.lot_id, ml.product_id,
                       'mouvement' AS type,
                       COALESCE(p.name, m.reference, m.origin) AS reference,
                       src.complete_name || ' → ' || dst.complete_name AS description,
                       COALESCE(p.partner_id, m.partner_id) AS partner_id,
                       ml.create_uid AS user_id,
                       'Fait' AS state
                FROM stock_move_line ml
                JOIN stock_move m ON m.id = ml.move_id
                JOIN stock_location src ON src.id = ml.location_id
                JOIN stock_location dst ON dst.id = ml.location_dest_id
                LEFT JOIN stock_picking p ON p.id = ml.picking_id
                WHERE ml.lot_id IS NOT NULL AND ml.state = 'done'
              UNION ALL
                SELECT i.id * 2 + 1, i.date, i.lot_id, i.product_id, i.type, i.name,
                       i.description, i.partner_id, i.user_id,
                       CASE i.state WHEN 'fait' THEN 'Faite'
                                    WHEN 'planifie' THEN 'Planifiée' ELSE 'Annulée' END
                FROM machine_intervention i
            )
        """))
