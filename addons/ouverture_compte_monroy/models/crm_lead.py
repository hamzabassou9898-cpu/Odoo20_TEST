# -*- coding: utf-8 -*-
"""Ouverture de compte depuis le CRM : a l'etape « 👤 Ouverture de compte », un bouton prepare la demande avec
ce que l'opportunite connait deja ; envoi, signature et approbation s'ecrivent dans le fil de l'opportunite.
A l'approbation, l'opportunite passe toute seule a l'etape suivante (Qualification)."""
import re

from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.suivi_machines_helpdesk.models.etapes import nom_etape

from .ouverture_compte import ETATS

# Etape creee par Monroy dans le CRM (nom avec emoji) : reconnue par son nom
ETAPE_OUVERTURE = re.compile(r"ouverture\s+de\s+compte", re.IGNORECASE)
EN_COURS = ("brouillon", "envoye", "signe")


class OuvertureCompte(models.Model):
    _inherit = "ouverture.compte"

    lead_id = fields.Many2one("crm.lead", "Opportunité", index="btree_not_null", copy=False, ondelete="set null",
                              help="Opportunité du CRM d'où la demande a été envoyée.")

    def action_voir_opportunite(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "crm.lead", "res_id": self.lead_id.id,
                "view_mode": "form", "views": [(False, "form")]}

    def _noter_dans_opportunite(self, texte):
        for ouverture in self.sudo().filtered("lead_id"):
            ouverture.lead_id.message_post(body=texte, message_type="comment", subtype_xmlid="mail.mt_note")

    def _envoyer(self, courriel=None, sujet=None, corps=None, pieces=None):
        resultat = super()._envoyer(courriel=courriel, sujet=sujet, corps=corps, pieces=pieces)
        self._noter_dans_opportunite(Markup(self.env._("📄 Ouverture de compte <b>%(numero)s</b> envoyée à %(courriel)s.")) % {
            "numero": self.name, "courriel": self.courriel})
        return resultat

    def _signer(self, nom, signature):
        resultat = super()._signer(nom, signature)
        self._noter_dans_opportunite(Markup(self.env._(
            "✍ Ouverture de compte <b>%(numero)s</b> signée en ligne par %(nom)s : à évaluer puis approuver.")) % {
            "numero": self.name, "nom": self.sudo().signe_par or "?"})
        return resultat

    def action_refuser(self):
        resultat = super().action_refuser()
        for ouverture in self:
            ouverture._noter_dans_opportunite(Markup(self.env._("Ouverture de compte <b>%s</b> refusée.")) % ouverture.name)
        return resultat

    def _approuver(self, code_client):
        client = super()._approuver(code_client)
        lead = self.sudo().lead_id
        if lead:
            if not lead.partner_id:
                lead.partner_id = client
            self._noter_dans_opportunite(Markup(self.env._(
                "✅ Compte client ouvert : <b>%(numero)s</b>, code client <b>%(code)s</b>.")) % {
                "numero": self.name, "code": client.ref})
            lead._passer_etape_suivante()
        return client


class CrmLead(models.Model):
    _inherit = "crm.lead"

    ouverture_compte_ids = fields.One2many("ouverture.compte", "lead_id", "Ouvertures de compte")
    ouverture_compte_id = fields.Many2one("ouverture.compte", "Ouverture de compte",
                                          compute="_compute_ouverture_compte")
    ouverture_compte_etat = fields.Selection(ETATS, "Ouverture de compte (état)", compute="_compute_ouverture_compte")
    ouverture_compte_code = fields.Char("Code client", compute="_compute_ouverture_compte")
    est_etape_ouverture = fields.Boolean("À l'étape Ouverture de compte", compute="_compute_est_etape_ouverture")

    @api.depends("ouverture_compte_ids.state", "partner_id.commercial_partner_id.ref")
    def _compute_ouverture_compte(self):
        for lead in self:
            ouverture = lead.sudo().ouverture_compte_ids.sorted("id", reverse=True)[:1]
            lead.ouverture_compte_id = ouverture
            lead.ouverture_compte_etat = ouverture.state
            lead.ouverture_compte_code = ouverture.state == "approuve" and ouverture.partner_id.commercial_partner_id.ref

    @api.depends("stage_id.name")
    def _compute_est_etape_ouverture(self):
        for lead in self:
            lead.est_etape_ouverture = bool(ETAPE_OUVERTURE.search(nom_etape(lead.stage_id)))

    def _valeurs_ouverture(self):
        """La demande remplie avec ce que l'opportunite (et sa fiche client) connait deja."""
        self.ensure_one()
        Ouverture = self.env["ouverture.compte"]
        valeurs = Ouverture._valeurs_depuis_client(self.partner_id) if self.partner_id else {}
        depuis_lead = {"entreprise_nom": self.partner_name, "contact_nom": self.contact_name,
                       "courriel": self.email_from, "telephone": self.phone, "rue": self.street,
                       "ville": self.city, "code_postal": self.zip}
        for champ, valeur in depuis_lead.items():
            if valeur and not valeurs.get(champ):
                valeurs[champ] = valeur
        if self.contact_name:   # la personne a qui le vendeur parle
            valeurs["contact_nom"] = self.contact_name
        valeurs.update(lead_id=self.id, user_id=(self.user_id or self.env.user).id)
        return valeurs

    def action_ouverture_compte(self):
        """La demande en cours de l'opportunite, sinon une nouvelle preparee avec ses informations. Avec un
        courriel, la fenetre d'envoi s'ouvre directement."""
        self.ensure_one()
        ouverture = self.ouverture_compte_id
        if ouverture.state in EN_COURS + ("approuve",):
            return self.action_voir_ouverture_compte()
        ouverture = self.env["ouverture.compte"].create(self._valeurs_ouverture())
        if ouverture.courriel:
            return ouverture.action_envoyer()
        return self.action_voir_ouverture_compte()

    def action_voir_ouverture_compte(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "ouverture.compte",
                "res_id": self.ouverture_compte_id.id, "view_mode": "form", "views": [(False, "form")]}

    def _passer_etape_suivante(self):
        """Compte approuve : l'opportunite encore a l'etape « Ouverture de compte » passe a la suivante."""
        for lead in self.filtered("est_etape_ouverture"):
            suivante = self.env["crm.stage"].search([
                ("sequence", ">", lead.stage_id.sequence), ("is_won", "=", False),
                "|", ("team_ids", "=", False), ("team_ids", "in", lead.team_id.ids)], order="sequence, id", limit=1)
            if suivante:
                lead.stage_id = suivante
