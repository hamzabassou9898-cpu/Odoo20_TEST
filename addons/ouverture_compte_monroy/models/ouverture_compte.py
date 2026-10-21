# -*- coding: utf-8 -*-
"""Ouverture de compte client : le formulaire Monroy « Ouverture compte client » rempli et signe en ligne.

Jose ouvre la demande (nom du client, courriel), l'envoie ; le client remplit les cases et signe sur sa page
(lien avec jeton, comme le contrat de location) ; Jose evalue la demande et l'approuve avec un code client :
le client est alors cree dans Contacts (ou mis a jour s'il existait deja)."""
import base64
import binascii

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

ETATS = [("brouillon", "Brouillon"), ("envoye", "Envoyé au client"), ("signe", "Signé, à évaluer"),
         ("approuve", "Approuvé"), ("refuse", "Refusé")]
FORMES = [("ltee", "Ltée"), ("inc", "Inc."), ("enr", "Enr")]
APPROVISIONNEMENTS = [("bureau", "Venir chercher au bureau de Monroy (sans minimum de commande)"),
                      ("livraison", "Livraison par Monroy avec achats minimums de 300$ par commande")]
PAIEMENTS = [("cheque", "chèque"), ("ppa", "PPA"), ("comptant", "comptant")]
# Renseignements personnels et bancaires : lus seulement par les responsables (le PDF signe les garde aussi)
RESPONSABLES = "sales_team.group_sale_manager"
# Cases que le client remplit sur sa page (texte), dans l'ordre du formulaire papier
CHAMPS_TEXTE = (
    "entreprise_nom", "autres_noms", "rue", "ville", "code_postal", "courriel", "contact_nom", "telephone",
    "telecopieur", "taxe_provinciale", "taxe_federale",
    "livraison_rue", "livraison_ville", "livraison_code_postal", "livraison_telephone", "livraison_telecopieur",
    "locateur_nom", "locateur_telephone",
    "actionnaire1_nom", "actionnaire1_adresse", "actionnaire1_ville", "actionnaire1_code_postal",
    "actionnaire1_telephone", "actionnaire1_actions", "actionnaire1_naissance",
    "actionnaire2_nom", "actionnaire2_adresse", "actionnaire2_ville", "actionnaire2_code_postal",
    "actionnaire2_telephone", "actionnaire2_actions", "actionnaire2_naissance",
    "banque_nom", "banque_adresse", "banque_compte", "banque_telephone",
    "terme", "caution_noms", "signe_a", "nom_majuscules",
)
CHAMPS_CHOIX = {"forme": FORMES, "approvisionnement": APPROVISIONNEMENTS, "paiement": PAIEMENTS}
# A remplir avant de signer
# Cases a remplir avant de signer : aucune pour le moment (demande de Monroy). Pour en exiger, ajouter leur nom
# ici (ex. "rue", "ville") : la page les montre en rouge et empeche de signer tant qu'elles sont vides.
OBLIGATOIRES = ()
LONGUEUR_MAX = 150


class OuvertureCompte(models.Model):
    _name = "ouverture.compte"
    _description = "Ouverture de compte client"
    _inherit = ["portal.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char("Numéro", required=True, readonly=True, copy=False, default="/")
    state = fields.Selection(ETATS, "État", default="brouillon", required=True, tracking=True, copy=False)
    user_id = fields.Many2one("res.users", "Responsable", default=lambda self: self.env.user, tracking=True,
                              help="Évalue et approuve la demande ; prévenu quand le client a signé.")
    company_id = fields.Many2one("res.company", "Société", default=lambda self: self.env.company, required=True)
    partner_id = fields.Many2one("res.partner", "Client", tracking=True, copy=False,
                                 help="Client créé (ou mis à jour) à l'approbation.")
    # Identification du client
    entreprise_nom = fields.Char("Nom de l'entreprise", tracking=True)
    forme = fields.Selection(FORMES, "Forme")
    autres_noms = fields.Char("Autre(s) nom(s) utilisé(s)")
    rue = fields.Char("Adresse")
    ville = fields.Char("Ville")
    code_postal = fields.Char("Code postal")
    courriel = fields.Char("Courriel", tracking=True)
    contact_nom = fields.Char("Contact")
    telephone = fields.Char("Téléphone")
    telecopieur = fields.Char("Télécopieur")
    taxe_provinciale = fields.Char("Permis taxe provinciale")
    taxe_federale = fields.Char("Permis taxe fédérale")
    # Adresse de livraison (si differente)
    livraison_rue = fields.Char("Adresse de livraison")
    livraison_ville = fields.Char("Ville (livraison)")
    livraison_code_postal = fields.Char("Code postal (livraison)")
    livraison_telephone = fields.Char("Téléphone (livraison)")
    livraison_telecopieur = fields.Char("Télécopieur (livraison)")
    locateur_nom = fields.Char("Nom du locateur", help="Si le client est locataire de l'immeuble.")
    locateur_telephone = fields.Char("Téléphone du locateur")
    # Actionnaires, associes ou proprietaire (renseignements personnels)
    actionnaire1_nom = fields.Char("Actionnaire 1 : nom", groups=RESPONSABLES)
    actionnaire1_adresse = fields.Char("Actionnaire 1 : adresse", groups=RESPONSABLES)
    actionnaire1_ville = fields.Char("Actionnaire 1 : ville", groups=RESPONSABLES)
    actionnaire1_code_postal = fields.Char("Actionnaire 1 : code postal", groups=RESPONSABLES)
    actionnaire1_telephone = fields.Char("Actionnaire 1 : téléphone", groups=RESPONSABLES)
    actionnaire1_actions = fields.Char("Actionnaire 1 : % actions", groups=RESPONSABLES)
    actionnaire1_naissance = fields.Char("Actionnaire 1 : date de naissance", groups=RESPONSABLES)
    actionnaire2_nom = fields.Char("Actionnaire 2 : nom", groups=RESPONSABLES)
    actionnaire2_adresse = fields.Char("Actionnaire 2 : adresse", groups=RESPONSABLES)
    actionnaire2_ville = fields.Char("Actionnaire 2 : ville", groups=RESPONSABLES)
    actionnaire2_code_postal = fields.Char("Actionnaire 2 : code postal", groups=RESPONSABLES)
    actionnaire2_telephone = fields.Char("Actionnaire 2 : téléphone", groups=RESPONSABLES)
    actionnaire2_actions = fields.Char("Actionnaire 2 : % actions", groups=RESPONSABLES)
    actionnaire2_naissance = fields.Char("Actionnaire 2 : date de naissance", groups=RESPONSABLES)
    # References bancaires
    banque_nom = fields.Char("Institution financière", groups=RESPONSABLES)
    banque_adresse = fields.Char("Adresse de la succursale", groups=RESPONSABLES)
    banque_compte = fields.Char("Numéro de compte", groups=RESPONSABLES)
    banque_telephone = fields.Char("Téléphone de la succursale", groups=RESPONSABLES)
    # Approvisionnement et credit
    approvisionnement = fields.Selection(APPROVISIONNEMENTS, "Mode d'approvisionnement")
    paiement = fields.Selection(PAIEMENTS, "Mode de paiement")
    terme = fields.Char("Terme (jours)")
    # Caution et signature du client
    caution_noms = fields.Char("Caution(s)", help="Personne(s) qui se portent caution du client.")
    signe_a = fields.Char("Signé à", help="Ville où le client signe.")
    nom_majuscules = fields.Char("Nom en lettres majuscules")
    signature = fields.Image("Signature", copy=False, attachment=True, max_width=1024, max_height=1024)
    signe_par = fields.Char("Signé par", copy=False)
    signe_le = fields.Datetime("Signé le", copy=False)
    # Evaluation au bureau
    approuve_par_id = fields.Many2one("res.users", "Approuvé par", readonly=True, copy=False)
    approuve_le = fields.Datetime("Approuvé le", readonly=True, copy=False)
    motif_refus = fields.Text("Motif du refus", copy=False)
    pdf_signe_id = fields.Many2one("ir.attachment", "PDF signé", readonly=True, copy=False)
    pdf_a_preparer = fields.Boolean("PDF signé à préparer", readonly=True, copy=False, index=True,
                                    help="Signé : le PDF est prêt quelques instants après (préparé en arrière-plan).")

    # ------------------------------------------------------------ creation, portail
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("ouverture.compte") or "/"
        return super().create(vals_list)

    def _compute_access_url(self):
        super()._compute_access_url()
        for ouverture in self:
            ouverture.access_url = "/ouverture/%s" % ouverture.id

    def _date_texte(self, moment):
        """Date du formulaire (jour/mois/annee), a l'heure du responsable."""
        if not moment:
            return ""
        return fields.Datetime.context_timestamp(self.with_user(self.user_id or self.env.user), moment).strftime(
            "%d/%m/%Y")

    def _get_report_base_filename(self):
        self.ensure_one()
        return self._nom_pdf()

    def _nom_pdf(self):
        self.ensure_one()
        suffixe = self.env._(" signée") if self.signature else ""
        return self.env._("Ouverture de compte %(numero)s%(suffixe)s", numero=self.name, suffixe=suffixe)

    @api.model
    def _valeurs_depuis_client(self, partner):
        """Formulaire prepare depuis une fiche existante (client deja connu : mise a jour de son dossier)."""
        societe = partner.commercial_partner_id
        return {"partner_id": partner.id, "entreprise_nom": societe.x_nom_legal or societe.name,
                "autres_noms": partner.name if partner != societe else False,
                "rue": partner.street, "ville": partner.city, "code_postal": partner.zip,
                "courriel": partner.email, "telephone": partner.phone,
                "contact_nom": partner.name if not partner.is_company else False}

    # ------------------------------------------------------------ par le client (page web)
    def _modifiable_par_client(self):
        self.ensure_one()
        return self.state == "envoye" and not self.signature

    def _completer_par_client(self, valeurs):
        """Cases remplies sur la page du client : seulement celles du formulaire, texte court, choix connus."""
        self.ensure_one()
        if not self._modifiable_par_client():
            raise UserError(self.env._("Ce formulaire est déjà signé : il ne peut plus être modifié."))
        a_ecrire = {}
        for champ, valeur in valeurs.items():
            if champ in CHAMPS_TEXTE:
                a_ecrire[champ] = (valeur or "").strip()[:LONGUEUR_MAX] or False
            elif champ in CHAMPS_CHOIX and valeur in dict(CHAMPS_CHOIX[champ]):
                a_ecrire[champ] = valeur
        if a_ecrire:
            self.sudo().write(a_ecrire)
        return a_ecrire

    def _champs_obligatoires(self):
        return OBLIGATOIRES

    def _manquants(self):
        self.ensure_one()
        obligatoires = self._champs_obligatoires()
        return [self._fields[champ].string for champ in obligatoires if not self.sudo()[champ]]

    def _signer(self, nom, signature):
        """Signature du client : formulaire complet obligatoire ; PDF signe, Jose prevenu."""
        self.ensure_one()
        if not self._modifiable_par_client():
            raise UserError(self.env._("Ce formulaire n'est pas à signer."))
        if not signature:
            raise UserError(self.env._("La signature est manquante."))
        manquants = self._manquants()
        if manquants:
            raise UserError(self.env._("Remplissez d'abord : %s.", ", ".join(manquants)))
        if isinstance(signature, bytes):
            signature = signature.decode()
        try:
            base64.b64decode(signature, validate=True)
        except (TypeError, ValueError, binascii.Error) as erreur:
            raise UserError(self.env._("Signature illisible.")) from erreur
        ouverture = self.sudo()
        ouverture.write({"signature": signature, "signe_par": (nom or "").strip()[:LONGUEUR_MAX],
                         "signe_le": fields.Datetime.now(), "state": "signe", "pdf_a_preparer": True})
        ouverture.message_post(
            body=Markup(self.env._("Formulaire rempli et <b>signé en ligne</b> par %s.")) % ouverture.signe_par)
        # Le PDF (quelques secondes) se prepare en arriere-plan : le client voit tout de suite « Signé »
        cron = self.env.ref("ouverture_compte_monroy.cron_pdf_ouverture_signee", raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        if ouverture.user_id:
            ouverture.activity_schedule(
                "mail.mail_activity_data_todo", user_id=ouverture.user_id.id,
                summary=self.env._("Évaluer l'ouverture de compte"),
                note=self.env._("%s a signé : vérifiez la demande puis approuvez-la avec un code client.",
                                ouverture.entreprise_nom or ouverture.name))
        return True

    def _preparer_pdf_signe(self):
        """PDF signe joint au fil de la demande (une fois) ; sans moteur PDF, la demande reste consultable."""
        for ouverture in self.sudo():
            pdf = ouverture._rendre_pdf()
            if pdf:
                message = ouverture.message_post(
                    body=self.env._("PDF du formulaire signé."),
                    attachments=[(ouverture._nom_pdf() + ".pdf", pdf)])
                if not ouverture.pdf_signe_id:
                    ouverture.pdf_signe_id = message.attachment_ids[:1]
            ouverture.pdf_a_preparer = False

    @api.model
    def _cron_pdf_signes(self):
        self.sudo().search([("pdf_a_preparer", "=", True)], limit=50)._preparer_pdf_signe()

    def _rendre_pdf(self):
        """PDF du formulaire (False sans moteur PDF : la demande reste consultable dans Odoo)."""
        self.ensure_one()
        try:
            return self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                "ouverture_compte_monroy.action_report_ouverture", self.ids)[0]
        except UserError:
            return False

    # ------------------------------------------------------------ au bureau
    def _verifier_envoi(self):
        self.ensure_one()
        if not self.courriel:
            raise UserError(self.env._("Indiquez le courriel du client avant d'envoyer le formulaire."))
        if self.state not in ("brouillon", "envoye"):
            raise UserError(self.env._("Ce formulaire est déjà signé."))

    def action_envoyer(self):
        """Fenetre du courriel (destinataire, objet, texte, pieces jointes) preparee avec le modele, a relire
        et modifier avant l'envoi, comme dans le CRM."""
        self.ensure_one()
        self._verifier_envoi()
        self._portal_ensure_token()
        return {"type": "ir.actions.act_window", "name": self.env._("Envoyer le formulaire au client"),
                "res_model": "ouverture.compte.envoyer", "view_mode": "form", "target": "new",
                "context": {"default_ouverture_id": self.id}}

    def _contenu_courriel(self):
        """Objet et texte du modele « Ouverture de compte », rendus pour cette demande."""
        self.ensure_one()
        modele = self.env.ref("ouverture_compte_monroy.mail_template_ouverture")
        return (modele._render_field("subject", self.ids)[self.id],
                modele._render_field("body_html", self.ids, compute_lang=True)[self.id])

    def _envoyer(self, courriel=None, sujet=None, corps=None, pieces=None):
        """Courriel au client avec le lien « Remplir et signer ». L'adresse est donnee directement au
        courriel : le futur client ne devient pas un contact avant l'approbation (Odoo creerait sinon un
        contact a partir de l'adresse du modele)."""
        self.ensure_one()
        if courriel:
            self.courriel = courriel.strip()
        self._verifier_envoi()
        self._portal_ensure_token()
        valeurs = {"email_to": self.courriel, "recipient_ids": []}
        if sujet:
            valeurs["subject"] = sujet
        if corps:
            valeurs["body_html"] = corps
        if pieces:
            valeurs["attachment_ids"] = [(4, piece.id) for piece in pieces]
        modele = self.env.ref("ouverture_compte_monroy.mail_template_ouverture")
        modele.send_mail(self.id, force_send=False, email_values=valeurs)
        self.state = "envoye"
        self.message_post(body=self.env._("Formulaire envoyé à %s.", self.courriel))
        return True

    def action_apercu(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.get_portal_url(), "target": "new"}

    def action_approuver(self):
        self.ensure_one()
        if self.state != "signe":
            raise UserError(self.env._("Seule une demande signée par le client peut être approuvée."))
        return {"type": "ir.actions.act_window", "name": self.env._("Approuver l'ouverture de compte"),
                "res_model": "ouverture.compte.approuver", "view_mode": "form", "target": "new",
                "context": {"default_ouverture_id": self.id,
                            "default_code_client": self.partner_id.commercial_partner_id.ref or False}}

    def action_refuser(self):
        for ouverture in self:
            if ouverture.state not in ("envoye", "signe"):
                raise UserError(self.env._("Seule une demande envoyée ou signée peut être refusée."))
            ouverture.state = "refuse"
            ouverture.activity_ids.action_feedback(feedback=self.env._("Demande refusée."))
        return True

    def action_brouillon(self):
        self.filtered(lambda o: o.state == "refuse").write({"state": "brouillon", "signature": False,
                                                           "signe_par": False, "signe_le": False})
        return True

    def action_ouvrir_client(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "res_model": "res.partner", "res_id": self.partner_id.id,
                "view_mode": "form", "views": [(False, "form")]}

    def _approuver(self, code_client):
        """Le client devient client Monroy : fiche creee (entreprise, contact, adresse de livraison) ou mise a
        jour, code client, PDF signe range dans son dossier et dans Documents."""
        self.ensure_one()
        code_client = (code_client or "").strip()
        if not code_client:
            raise ValidationError(self.env._("Le code client est obligatoire."))
        Partner = self.env["res.partner"]
        client = self.partner_id.commercial_partner_id
        if Partner.search_count([("ref", "=ilike", code_client), ("id", "!=", client.id)]):
            raise ValidationError(self.env._("Le code client %s est déjà utilisé.", code_client))
        ouverture = self.sudo()
        legal = " ".join(filter(None, [ouverture.entreprise_nom, dict(FORMES).get(ouverture.forme)]))
        # Aucune case obligatoire : sans nom d'entreprise, le contact ou le code client nomme la fiche
        nom = ouverture.autres_noms or ouverture.entreprise_nom or ouverture.contact_nom or code_client
        valeurs = {"name": nom,
                   "ref": code_client, "street": ouverture.rue, "city": ouverture.ville,
                   "zip": ouverture.code_postal, "email": ouverture.courriel, "phone": ouverture.telephone,
                   "x_nom_legal": legal}
        if client:
            client.write({cle: valeur for cle, valeur in valeurs.items() if valeur and (cle == "ref" or not client[cle])})
        else:
            client = Partner.create(valeurs)
        if ouverture.contact_nom and not client.child_ids.filtered(lambda c: c.name == ouverture.contact_nom):
            Partner.create({"name": ouverture.contact_nom, "parent_id": client.id, "type": "contact",
                            "email": ouverture.courriel, "phone": ouverture.telephone})
        if ouverture.livraison_rue and not client.child_ids.filtered(
                lambda c: c.type == "delivery" and c.street == ouverture.livraison_rue):
            Partner.create({"name": nom, "parent_id": client.id,
                            "type": "delivery", "street": ouverture.livraison_rue,
                            "city": ouverture.livraison_ville, "zip": ouverture.livraison_code_postal,
                            "phone": ouverture.livraison_telephone})
        ouverture.write({"partner_id": client.id, "state": "approuve", "approuve_par_id": self.env.user.id,
                         "approuve_le": fields.Datetime.now(), "pdf_a_preparer": False})
        ouverture._ranger_dans_le_dossier(client)
        ouverture.activity_ids.action_feedback(feedback=self.env._("Demande approuvée : code client %s.",
                                                                   code_client))
        client.message_post(body=Markup(self.env._("Compte client ouvert : <b>%(numero)s</b>, code client "
                                                   "<b>%(code)s</b>.")) % {"numero": ouverture.name,
                                                                          "code": code_client})
        return client

    def _ranger_dans_le_dossier(self, client):
        """PDF signe (avec l'approbation) dans les pieces jointes du client et dans Documents."""
        self.ensure_one()
        pdf = self._rendre_pdf()
        if not pdf:
            return False
        nom = self._nom_pdf() + ".pdf"
        piece = self.env["ir.attachment"].sudo().create({"name": nom, "raw": pdf, "mimetype": "application/pdf",
                                                         "res_model": "res.partner", "res_id": client.id})
        self.pdf_signe_id = piece
        if "documents.document" in self.env:
            self.env["sale.order"].with_user(self.env.user)._ranger_dans_documents(client, nom, pdf)
        return piece
