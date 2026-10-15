# -*- coding: utf-8 -*-
"""Bon d'intervention signe par le client sur le telephone du technicien (portail « Ma journee »)."""
import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Formulaire Monroy (papier « Rév. 01/26 ») : trois sections selon le travail
TYPES_BON = [("livraison", "Livraison des équipements"), ("entretien", "Entretien sur les équipements"),
             ("reprise", "Reprise des équipements")]
PROPRETES = [("tres_propre", "Très propre"), ("moyen", "Moyen"), ("sale", "Sale")]


def type_bon_de(type_tache):
    """Livraison / installation -> livraison ; ramassage -> reprise ; entretien, reparation... -> entretien."""
    if type_tache in ("livraison", "installation"):
        return "livraison"
    if type_tache == "ramassage":
        return "reprise"
    return "entretien"


def texte_engagement(env, type_bon, type_tache=None):
    """Texte que le client lit avant de signer (repris du formulaire papier)."""
    societe = (env.company.name or "").upper()
    if type_bon == "livraison":
        return env._(
            "J'ai reçu en bon état les articles mentionnés ci-dessus, ainsi que le congélateur pour lesquels je suis "
            "responsable. Je m'engage à remettre dans le même état de propreté qu'ils m'ont été livrés. Je comprends "
            "également que %(societe)s pourra me facturer tous items manquants ou en mauvais état lors de la remise des "
            "équipements. Dans le cas où les items ne sont pas remis lors de la reprise des équipements, le client devra "
            "les retourner à SES FRAIS.", societe=societe)
    if type_bon == "reprise":
        return env._("La propreté du congélateur et des accessoires lors de la reprise de possession à la fin du "
                     "contrat était :")
    travail = env._("une réparation") if type_tache == "reparation" else env._("un entretien")
    return env._(
        "Je confirme que %(societe)s a effectué %(travail)s sur les équipements en place. Je confirme également que les "
        "équipements que j'ai en ma possession sont tels qu'indiqué ci-dessus.", societe=env.company.name, travail=travail)




def ticket_d_origine(source, lot=None):
    """Ticket d'assistance d'ou vient le travail : le ticket lui-meme, celui de l'intervention ou du
    transfert, sinon le dernier ticket ouvert de la meme machine. Recordset vide s'il n'y en a pas."""
    Ticket = source.env["helpdesk.ticket"].sudo()
    if source._name == "helpdesk.ticket":
        return source
    for champ in ("ticket_id", "ticket_assistance_id"):
        if champ in source._fields and source[champ]:
            return source[champ]
    lot = lot or (source.lot_id if "lot_id" in source._fields else None)
    if not lot:
        return Ticket
    return Ticket.search(["|", ("lot_id", "=", lot.id), ("machines_reprise_ids", "in", lot.ids)],
                         order="id desc").filtered(lambda t: not t._est_ferme())[:1]

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
    type_bon = fields.Selection(TYPES_BON, "Formulaire", readonly=True)
    equipements = fields.Text("Équipements", readonly=True)
    texte = fields.Text("Engagement signé", readonly=True)
    proprete = fields.Selection(PROPRETES, "Propreté à la reprise", readonly=True)
    pleine = fields.Boolean("Pleine", readonly=True)
    en_fonction = fields.Boolean("En fonction", readonly=True)
    titre = fields.Char("Tâche", readonly=True)
    travail = fields.Text("Travail fait", readonly=True)
    signe_par = fields.Char("Signé par", readonly=True)
    signature = fields.Binary("Signature du client", attachment=True, readonly=True)
    signature_technicien = fields.Binary("Signature du technicien", attachment=True, readonly=True)
    technicien_signe_le = fields.Datetime("Signé par le technicien le", readonly=True)
    doit_signer_technicien = fields.Boolean(
        "Signature du technicien attendue", compute="_compute_doit_signer_technicien",
        help="Entretien / réparation : le technicien signe aussi le bon (comme sur le formulaire papier).")
    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket", readonly=True, index="btree_not_null")
    picking_id = fields.Many2one("stock.picking", "Transfert", readonly=True, index="btree_not_null")
    intervention_id = fields.Many2one("machine.intervention", "Intervention", readonly=True, index="btree_not_null")
    pdf_id = fields.Many2one("ir.attachment", "PDF", readonly=True)

    @api.depends("type_bon", "signature_technicien")
    def _compute_doit_signer_technicien(self):
        for bon in self:
            bon.doit_signer_technicien = bon.type_bon == "entretien" and not bon.signature_technicien

    def _signer_technicien(self, signature):
        """Le technicien signe le bon apres le client : le PDF est refait avec ses deux signatures."""
        self.ensure_one()
        if not signature:
            raise UserError(self.env._("La signature est vide."))
        if self.type_bon != "entretien" or self.signature_technicien:
            raise UserError(self.env._("Ce bon n'attend pas la signature du technicien."))
        bon = self.sudo()
        bon.write({"signature_technicien": signature, "technicien_signe_le": fields.Datetime.now()})
        pdf = bon._rendre_pdf()
        if pdf and bon.pdf_id:
            bon.pdf_id.raw = pdf        # meme piece jointe : le message du fil montre le bon complet
        elif pdf:
            source = bon._source()
            bon.pdf_id = self.env["ir.attachment"].sudo().create({
                "name": "%s.pdf" % bon.name.replace("/", "-"), "raw": pdf, "mimetype": "application/pdf",
                "res_model": source._name, "res_id": source.id})
        bon._poster(Markup("<p>%s</p>") % self.env._("Bon %s signé par le technicien %s.",
                                                     bon.name, bon.technicien_id.name))
        bon._prevenir_bureau()
        return True

    def _prevenir_bureau(self):
        """Bon complet (client, et technicien pour un entretien / une reparation) : le responsable (Jose)
        est prevenu DANS Odoo, quelle que soit sa preference (courriel ou Odoo) et meme sans envoi de
        courriel (base de test neutralisee) : activite a faire sur le ticket d'origine, message dans le ticket et
        notification a l'ecran. Ni le client ni les abonnes du document ne sont prevenus."""
        responsable = self.env["sale.order"]._reglages_reprise()["responsable"]
        if not responsable:
            return
        for bon in self.sudo():
            dossier = bon._dossier_bureau()   # ticket d'origine
            signatures = bon.signe_par or "?"
            if bon.signature_technicien:
                signatures = self.env._("%(client)s et le technicien %(tech)s",
                                        client=signatures, tech=bon.technicien_id.name)
            titre = self.env._("Bon %s signé", bon.name)
            texte = self.env._("Bon %(bon)s signé par %(signatures)s (%(client)s). Le PDF est dans le document.",
                               bon=bon.name, signatures=signatures, client=bon.partner_id.display_name or "")
            # Courriel / boite de reception Odoo selon la preference du responsable
            dossier.message_notify(partner_ids=responsable.partner_id.ids, author_id=bon.technicien_id.partner_id.id,
                                  subject=titre, body=Markup("<p>%s</p>") % texte)
            # Toujours visible dans Odoo : une activite a faire (horloge) sur le TICKET (jamais sur une
            # intervention : pas utile au bureau) ...
            if dossier._name == "helpdesk.ticket":
                dossier.activity_schedule("mail.mail_activity_data_todo", user_id=responsable.id,
                                          summary=titre, note=Markup("<p>%s</p>") % texte)
            # ... et une notification a l'ecran s'il est connecte
            responsable._bus_send("simple_notification", {
                "type": "success", "title": titre, "message": texte, "sticky": True})

    def _dossier_bureau(self):
        """Ticket d'origine du travail (voir ticket_d_origine), sinon le document source."""
        self.ensure_one()
        return self.ticket_id or ticket_d_origine(self._source(), self.lot_id) or self._source()

    def _poster(self, corps):
        """Message (note) dans le document source ET dans le ticket d'origine, avec le PDF du bon."""
        self.ensure_one()
        for document in {self._source(), self._dossier_bureau()}:
            message = document.with_context(mail_create_nosubscribe=True).message_post(
                body=corps, author_id=self.technicien_id.partner_id.id, message_type="comment",
                subtype_xmlid="mail.mt_note")
            if self.pdf_id:
                message.sudo().attachment_ids = [(4, self.pdf_id.id)]

    def _rendre_pdf(self):
        """PDF du bon (False sans moteur PDF : le bon reste consultable dans Odoo)."""
        self.ensure_one()
        try:
            pdf, _type = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                "suivi_machines_portail.rapport_bon_intervention", self.ids)
            return pdf
        except Exception:  # noqa: BLE001 - pas de moteur PDF
            _logger.warning("Bon %s : PDF non genere", self.name, exc_info=True)
            return False

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
        type_bon = type_bon_de(tache.type_tache)
        equipements = [ligne for ligne in (tache.machines, tache.accessoires) if ligne]
        etat = {}
        if type_bon == "reprise":
            etat = {"proprete": source.reprise_proprete, "pleine": source.reprise_pleine,
                    "en_fonction": source.reprise_en_fonction}
        bon = self.sudo().create({
            **etat, "type_bon": type_bon, "equipements": "\n".join(equipements) or False,
            "texte": texte_engagement(self.env, type_bon, tache.type_tache),
            "name": self.env["ir.sequence"].sudo().next_by_code("suivi.bon.intervention") or "/",
            "technicien_id": technicien.id, "partner_id": tache.partner_id.id, "lot_id": tache.lot_id.id,
            "type_tache": types.get(tache.type_tache, ""), "titre": tache.titre,
            "travail": self._travail_du_jour(source, technicien), "signe_par": (signe_par or "").strip()[:100],
            "signature": signature, champ: source.id,
        })
        bon._joindre_pdf()
        bon._terminer_source()
        if not bon.doit_signer_technicien:
            bon._prevenir_bureau()   # sinon : quand le technicien aura signe
        return bon

    def _joindre_pdf(self):
        """PDF du bon dans le fil du document et du ticket d'origine (au nom du technicien).
        Sans PDF possible : message seul."""
        for bon in self.sudo():
            source = bon._source()
            pdf = bon._rendre_pdf()
            if pdf:
                piece = self.env["ir.attachment"].sudo().create({
                    "name": "%s.pdf" % bon.name.replace("/", "-"), "raw": pdf, "mimetype": "application/pdf",
                    "res_model": source._name, "res_id": source.id})
                bon.pdf_id = piece
            # Le bon (et son PDF) dans l'intervention / le transfert ET dans le ticket d'origine
            bon._poster(Markup("<p><b>%s</b></p><p>%s</p>") % (
                self.env._("Bon d'intervention %s signé", bon.name),
                self.env._("Signé par %(nom)s sur le téléphone de %(tech)s.",
                           nom=bon.signe_par or "?", tech=bon.technicien_id.name)))

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
    # Reprise (ramassage) : cases du formulaire papier, cochees au portail avant la signature
    reprise_proprete = fields.Selection(PROPRETES, "Propreté à la reprise", copy=False)
    reprise_pleine = fields.Boolean("Pleine", copy=False)
    reprise_en_fonction = fields.Boolean("En fonction", copy=False)

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
