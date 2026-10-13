# -*- coding: utf-8 -*-
"""Bon d'intervention signe par le client sur le telephone du technicien (portail « Ma journee »)."""
import base64
import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BonIntervention(models.Model):
    _name = "suivi.bon.intervention"
    _description = "Bon d'intervention signé"
    _order = "date desc, id desc"

    name = fields.Char("Numéro", readonly=True, copy=False, default="/")
    date = fields.Datetime("Signé le", default=fields.Datetime.now, required=True, readonly=True)
    technicien_id = fields.Many2one("res.users", "Technicien", readonly=True)
    partner_id = fields.Many2one("res.partner", "Client", readonly=True)
    lot_id = fields.Many2one("stock.lot", "Machine", readonly=True)
    type_tache = fields.Char("Travail", readonly=True)
    titre = fields.Char("Tâche", readonly=True)
    travail = fields.Text("Travail fait", readonly=True)
    signe_par = fields.Char("Signé par", readonly=True)
    signature = fields.Binary("Signature du client", attachment=True, readonly=True)
    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket", readonly=True, index="btree_not_null")
    picking_id = fields.Many2one("stock.picking", "Transfert", readonly=True, index="btree_not_null")
    intervention_id = fields.Many2one("machine.intervention", "Intervention", readonly=True, index="btree_not_null")
    pdf_id = fields.Many2one("ir.attachment", "PDF", readonly=True)

    def _source(self):
        self.ensure_one()
        return self.ticket_id or self.picking_id or self.intervention_id

    @api.model
    def _travail_du_jour(self, source, technicien):
        """Travail fait = les notes que le technicien a envoyees aujourd'hui sur ce document."""
        aujourdhui = fields.Date.context_today(self)
        notes = source.sudo().note_technicien_ids.filtered(
            lambda n: n.technicien_id == technicien and fields.Date.context_today(self, n.date) == aujourdhui)
        textes = list(dict.fromkeys(n.note.strip() for n in notes.sorted("date") if n.note and n.note.strip()))
        return "\n".join(textes) or False   # sans doublon (note envoyee deux fois)

    @api.model
    def _creer_depuis_tache(self, tache, signe_par, signature):
        """Signature du client : bon + PDF dans le fil du document, puis tache terminee."""
        if not signature:
            raise UserError(self.env._("La signature est vide."))
        source = tache._source().sudo()
        technicien = tache.technicien_id
        champ = {"helpdesk.ticket": "ticket_id", "stock.picking": "picking_id",
                 "machine.intervention": "intervention_id"}[source._name]
        types = dict(tache._fields["type_tache"]._description_selection(self.env))
        bon = self.sudo().create({
            "name": self.env["ir.sequence"].sudo().next_by_code("suivi.bon.intervention") or "/",
            "technicien_id": technicien.id, "partner_id": tache.partner_id.id, "lot_id": tache.lot_id.id,
            "type_tache": types.get(tache.type_tache, ""), "titre": tache.titre,
            "travail": self._travail_du_jour(source, technicien), "signe_par": (signe_par or "").strip()[:100],
            "signature": signature, champ: source.id,
        })
        bon._joindre_pdf()
        bon._terminer_source()
        return bon

    def _joindre_pdf(self):
        """PDF du bon dans le fil du document (au nom du technicien). Sans PDF possible : message seul."""
        for bon in self.sudo():
            source = bon._source()
            pieces = []
            try:
                pdf, _type = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                    "suivi_machines_portail.rapport_bon_intervention", bon.ids)
                piece = self.env["ir.attachment"].sudo().create({
                    "name": "%s.pdf" % bon.name.replace("/", "-"), "raw": pdf, "mimetype": "application/pdf",
                    "res_model": source._name, "res_id": source.id})
                bon.pdf_id = piece
                pieces = piece.ids
            except Exception:  # pas de moteur PDF : le bon reste consultable dans Odoo
                _logger.warning("Bon %s : PDF non genere", bon.name, exc_info=True)
            message = source.with_context(mail_create_nosubscribe=True).message_post(
                body=Markup("<p><b>%s</b></p><p>%s</p>") % (
                    self.env._("Bon d'intervention %s signé", bon.name),
                    self.env._("Signé par %(nom)s sur le téléphone de %(tech)s.",
                               nom=bon.signe_par or "?", tech=bon.technicien_id.name)),
                author_id=bon.technicien_id.partner_id.id, message_type="comment",
                subtype_xmlid="mail.mt_note")
            if pieces:
                message.sudo().attachment_ids = [(6, 0, pieces)]

    def _terminer_source(self):
        """La tache signee est terminee : intervention faite, ticket resolu (entretien valide)."""
        for bon in self.sudo():
            if bon.intervention_id and bon.intervention_id.state == "planifie":
                bon.intervention_id.action_fait()
            ticket = bon.ticket_id
            if ticket and not ticket._est_ferme():
                if ticket.est_entretien and ticket.lot_id:
                    try:
                        with self.env.cr.savepoint():
                            self.env["suivi.machines.valider.entretien"].with_context(
                                default_ticket_id=ticket.id).create({
                                    "ticket_id": ticket.id, "technicien_id": bon.technicien_id.id,
                                    "note": bon.travail}).action_valider()
                        continue
                    except UserError:
                        _logger.info("Bon %s : entretien a valider par le bureau", bon.name)
                resolu = ticket._etape_contenant("résolu", ticket.team_id if "team_id" in ticket._fields else None)
                if resolu:
                    ticket.stage_id = resolu
            if bon.picking_id and bon.picking_id.state not in ("done", "cancel"):
                # Le stock se valide au bureau : on previent le responsable
                responsable = self.env["sale.order"]._reglages_reprise()["responsable"]
                if responsable:
                    bon.picking_id.activity_schedule(
                        "mail.mail_activity_data_todo", user_id=responsable.id,
                        summary=self.env._("Valider le transfert (bon signé)"),
                        note=self.env._("Le client a signé le bon %s : validez le transfert.", bon.name))

    def action_telecharger(self):
        self.ensure_one()
        return self.env.ref("suivi_machines_portail.action_rapport_bon_intervention").report_action(self)


class BonMixin(models.AbstractModel):
    _name = "suivi.bon.intervention.mixin"
    _description = "Documents avec bons d'intervention signés"

    bon_intervention_ids = fields.One2many("suivi.bon.intervention", compute="_compute_bons",
                                           string="Bons signés")

    def _compute_bons(self):
        champ = {"helpdesk.ticket": "ticket_id", "stock.picking": "picking_id",
                 "machine.intervention": "intervention_id"}[self._name]
        for doc in self:
            doc.bon_intervention_ids = self.env["suivi.bon.intervention"].sudo().search([(champ, "=", doc.id)])


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _inherit = ["helpdesk.ticket", "suivi.bon.intervention.mixin"]


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "suivi.bon.intervention.mixin"]


class MachineIntervention(models.Model):
    _name = "machine.intervention"
    _inherit = ["machine.intervention", "suivi.bon.intervention.mixin"]
