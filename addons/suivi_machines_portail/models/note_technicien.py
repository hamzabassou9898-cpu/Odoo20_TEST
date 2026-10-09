# -*- coding: utf-8 -*-
"""Notes envoyees par les techniciens depuis le portail, affichees sur le ticket / transfert / intervention."""
from odoo import fields, models


class SuiviNoteTechnicien(models.Model):
    _name = "suivi.note.technicien"
    _description = "Note du technicien"
    _order = "date desc, id desc"
    _rec_name = "technicien_id"

    date = fields.Datetime("Date", default=fields.Datetime.now, required=True, readonly=True)
    technicien_id = fields.Many2one("res.users", "Technicien", required=True, readonly=True)
    note = fields.Text("Note", readonly=True)
    attachment_ids = fields.Many2many("ir.attachment", "suivi_note_technicien_attachment_rel", "note_id",
                                      "attachment_id", "Pièces jointes", readonly=True)
    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket", ondelete="cascade", index="btree_not_null")
    picking_id = fields.Many2one("stock.picking", "Transfert", ondelete="cascade", index="btree_not_null")
    intervention_id = fields.Many2one("machine.intervention", "Intervention", ondelete="cascade",
                                      index="btree_not_null")

    @staticmethod
    def _champ_source(source):
        return {"helpdesk.ticket": "ticket_id", "stock.picking": "picking_id",
                "machine.intervention": "intervention_id"}[source._name]

    def _creer(self, source, technicien, note, pieces):
        """Note + pieces jointes (rattachees au document, donc visibles avec ses droits)."""
        attachments = self.env["ir.attachment"].sudo().create([{
            "name": nom, "raw": contenu, "res_model": source._name, "res_id": source.id,
        } for nom, contenu in pieces])
        return self.sudo().create({
            "technicien_id": technicien.id, "note": note or False,
            "attachment_ids": [(6, 0, attachments.ids)], self._champ_source(source): source.id,
        })


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "ticket_id", "Notes du technicien")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "picking_id", "Notes du technicien")


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "intervention_id", "Notes du technicien")
