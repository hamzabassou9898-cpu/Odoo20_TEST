# -*- coding: utf-8 -*-
"""Notes envoyees par les techniciens depuis le portail, affichees sur le ticket / transfert / intervention."""
from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import plaintext2html


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
    # Suivi : une activite « a faire » pour le responsable, la note passe a « Lue » quand elle est faite
    lu = fields.Boolean("Lue", default=False, index=True, copy=False)
    activity_id = fields.Many2one("mail.activity", "Activité", ondelete="set null", readonly=True, copy=False)
    responsable_id = fields.Many2one("res.users", "Responsable", readonly=True)
    document = fields.Char("Document", compute="_compute_document")
    statut_lecture = fields.Selection([("a_lire", "À lire"), ("lue", "Lue")], "Statut", compute="_compute_statut_lecture")

    @api.depends("lu")
    def _compute_statut_lecture(self):
        for note in self:
            note.statut_lecture = "lue" if note.lu else "a_lire"

    @api.depends("ticket_id", "picking_id", "intervention_id")
    def _compute_document(self):
        for note in self:
            note.document = note._source().display_name

    def _source(self):
        self.ensure_one()
        return self.ticket_id or self.picking_id or self.intervention_id

    @staticmethod
    def _champ_source(source):
        return {"helpdesk.ticket": "ticket_id", "stock.picking": "picking_id",
                "machine.intervention": "intervention_id"}[source._name]

    def _creer(self, source, technicien, note, pieces):
        """Note + pieces jointes (rattachees au document, donc visibles avec ses droits)."""
        attachments = self.env["ir.attachment"].sudo().create([{
            "name": nom, "raw": contenu, "res_model": source._name, "res_id": source.id,
        } for nom, contenu in pieces])
        note_tech = self.sudo().create({
            "technicien_id": technicien.id, "note": note or False,
            "attachment_ids": [(6, 0, attachments.ids)], self._champ_source(source): source.id,
        })
        note_tech._noter_dans_le_fil()
        note_tech._prevenir_responsable()
        return note_tech

    def _noter_dans_le_fil(self):
        """Aussi en « Note » (interne) dans le fil du document, au nom du technicien, avec les pieces jointes."""
        for note in self.sudo():
            corps = Markup("<p><b>%s</b></p>") % self.env._("Note du technicien (portail)")
            if note.note:
                corps += plaintext2html(note.note)
            message = note._source().with_context(mail_create_nosubscribe=True).message_post(
                body=corps, author_id=note.technicien_id.partner_id.id,
                message_type="comment", subtype_xmlid="mail.mt_note")
            # Odoo n'attache pas de fichiers au message d'un utilisateur portail : on les relie ici
            # (memes fichiers, deja rattaches au document)
            if note.attachment_ids:
                message.sudo().attachment_ids = [(6, 0, note.attachment_ids.ids)]

    def _responsable(self):
        """Responsable de la planification (parametre de l'assistance), sinon l'administrateur."""
        return self.env["sale.order"].sudo()._reglages_reprise().get("responsable") \
            or self.env.ref("base.user_admin")

    def _prevenir_responsable(self):
        """Activite « A faire » sur le document : pastille de l'horloge + notification du responsable."""
        for note in self.sudo():
            responsable = note._responsable()
            source = note._source()
            pieces = len(note.attachment_ids)
            resume = self.env._("Note de %(tech)s à lire", tech=note.technicien_id.name)
            detail = (note.note or "") + ("\n" if note.note and pieces else "") + (
                self.env._("%s pièce(s) jointe(s)", pieces) if pieces else "")
            activite = source.activity_schedule(
                "mail.mail_activity_data_todo", user_id=responsable.id, summary=resume,
                note=plaintext2html(detail) if detail else False)
            note.write({"activity_id": activite.id, "responsable_id": responsable.id})

    def action_marquer_lu(self):
        """Note lue : l'activite du responsable est faite."""
        for note in self:
            activite = note.sudo().activity_id
            note.sudo().write({"lu": True})
            if activite and activite.active:
                activite.action_done()
        return True

    def action_ouvrir_document(self):
        self.ensure_one()
        source = self._source()
        return {"type": "ir.actions.act_window", "res_model": source._name, "res_id": source.id,
                "views": [(False, "form")], "target": "current"}


class MailActivity(models.Model):
    _inherit = "mail.activity"

    def _notes_technicien(self):
        return self.env["suivi.note.technicien"].sudo().search([("activity_id", "in", self.ids), ("lu", "=", False)])

    def _action_done(self, feedback=False, attachment_ids=None):
        # Activite faite depuis l'horloge ou le ticket : la note du technicien devient « Lue »
        self._notes_technicien().write({"lu": True})
        return super()._action_done(feedback=feedback, attachment_ids=attachment_ids)

    def unlink(self):
        self._notes_technicien().write({"lu": True})
        return super().unlink()


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "ticket_id", "Notes du technicien")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "picking_id", "Notes du technicien")


class MachineIntervention(models.Model):
    _inherit = "machine.intervention"

    note_technicien_ids = fields.One2many("suivi.note.technicien", "intervention_id", "Notes du technicien")


class PilotageIndicateur(models.Model):
    _inherit = "pilotage.indicateur"

    @api.model
    def _domaines(self):
        domaines = super()._domaines()
        domaines["notes_a_lire"] = ("suivi.note.technicien", [("lu", "=", False)])
        return domaines

    def action_ouvrir(self):
        if self.code == "notes_a_lire":
            action = self.env["ir.actions.act_window"]._for_xml_id("suivi_machines_portail.action_notes_technicien")
            action["context"] = {"search_default_a_lire": 1}
            return action
        return super().action_ouvrir()
