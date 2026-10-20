# -*- coding: utf-8 -*-
"""Types de contrat Monroy (location, convention, convention popcorn, proprietaire) et forfait annuel.

Chaque type regle le comportement du contrat (machine louee ou vendue) et le forfait annuel d'entretien
(clause 8.2 : montant par machine, a la signature puis tous les 12 mois). Les montants se modifient dans
Ventes > Configuration > Types de contrat, sans programmation.
"""
import logging
import re
from datetime import date

from babel import dates as babel_dates
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.image import image_data_uri

_logger = logging.getLogger(__name__)


class SuiviTypeContrat(models.Model):
    _name = "suivi.type.contrat"
    _description = "Type de contrat"
    _order = "sequence, id"

    name = fields.Char("Type de contrat", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    type_commande = fields.Selection(
        [("vente", "Vente"), ("location", "Location")], "Machine", required=True, default="location",
        help="Location : la machine reste à Monroy (« En location » chez le client). "
             "Vente : la machine appartient au client (contrat propriétaire).")
    forfait_montant = fields.Float(
        "Forfait annuel par machine", digits="Product Price",
        help="Frais annuels d'entretien et de réparations usuelles (clause 8.2) : payés à la signature, "
             "puis tous les 12 mois, pour chaque machine. 0 = aucun forfait.")
    forfait_produit_id = fields.Many2one(
        "product.product", "Produit du forfait", domain="[('type', '=', 'service')]",
        default=lambda s: s.env.ref("suivi_machines.produit_forfait_entretien", raise_if_not_found=False),
        help="Service utilisé sur le bon de vente du forfait annuel.")
    # Appels de service (clause 7.3) : ce qui est couvert et ce qui se facture
    couvre_reparations = fields.Boolean(
        "Entretien et réparations couverts", default=True,
        help="Coché : l'entretien et les réparations usuelles sont couverts par le contrat (location, "
             "convention). Seuls l'appel de service inutile et les dommages se facturent. Décoché "
             "(propriétaire) : chaque appel se facture (déplacement + taux horaire + pièces).")
    frais_appel_inutile = fields.Float("Appel de service inutile", digits="Product Price",
                                       help="Clause 7.3 : montant facturé pour un appel de service inutile.")
    frais_deplacement = fields.Float("Frais de déplacement", digits="Product Price",
                                     help="Contrat propriétaire : frais de déplacement de chaque appel.")
    taux_horaire = fields.Float("Taux horaire", digits="Product Price",
                                help="Contrat propriétaire : main-d'œuvre par heure.")
    modele = fields.Selection(
        [("location", "Location / entreprise"), ("convention", "Convention slush"),
         ("popcorn", "Convention popcorn"), ("proprietaire", "Propriétaire")], "Modèle de contrat",
        required=True, default="location",
        help="Texte du contrat imprimé avec le devis et signé en ligne par le client.")
    clause_penale = fields.Float("Clause pénale", digits="Product Price",
                                 help="Dommages liquidés en cas de défaut du client (clause pénale).")
    note = fields.Text("Note")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    type_contrat_id = fields.Many2one(
        "suivi.type.contrat", "Type de contrat", tracking=True, copy=True, index="btree_not_null",
        help="Location, convention, convention popcorn ou propriétaire : règle le type (vente / location) "
             "et le forfait annuel d'entretien.")
    forfait_montant = fields.Float(
        "Forfait annuel / machine", digits="Product Price", tracking=True, copy=True,
        compute="_compute_forfait_montant", store=True, readonly=False, precompute=True,
        help="Prix du forfait annuel d'entretien par machine pour CE contrat : celui du type de contrat, "
             "modifiable (prix négocié). Repris chaque année.")
    contrat_modele = fields.Selection(related="type_contrat_id.modele")
    saison = fields.Selection([("annee", "Année"), ("hiver", "Hiver"), ("ete", "Été"), ("ecole", "École")],
                              "Saison", copy=True, help="Période d'activité indiquée en haut du contrat.")
    prix_detail_353 = fields.Float("Prix de détail 353 ml", digits="Product Price", copy=True)
    prix_detail_510 = fields.Float("Prix de détail 510 ml", digits="Product Price", copy=True)
    prix_detail_775 = fields.Float("Prix de détail 775 ml", digits="Product Price", copy=True)
    # Rempli par le client sur sa page (lien du devis), avant de signer
    contrat_initiales = fields.Char("Initiales du client", copy=False)
    caution_nom = fields.Char("Caution : nom", copy=False)
    caution_numero = fields.Char("Caution : numéro civique", copy=False)
    caution_rue = fields.Char("Caution : rue", copy=False)
    caution_ville = fields.Char("Caution : ville", copy=False)
    caution_province = fields.Char("Caution : province", copy=False)
    # Anciens champs (signature separee de la caution, retiree) : gardes pour les bases ou une ancienne
    # vue les affiche encore ; plus utilises
    caution_signature = fields.Binary("Ancienne signature de la caution", copy=False, attachment=True)
    caution_signe_par = fields.Char("Ancienne caution signée par", copy=False)
    caution_signe_le = fields.Datetime("Ancienne caution signée le", copy=False)
    contrat_compagnie = fields.Selection(
        [("oui", "Oui"), ("non", "Non")], "Signe au nom d'une compagnie", copy=False,
        help="Réponse du client sur sa page : « Oui » = la caution s'applique et elle est signée avec la "
             "signature du contrat.")
    proprietaire_immeuble = fields.Char("Propriétaire de l'immeuble (nom et adresse)", copy=False)
    forfait_prochaine_date = fields.Date(
        "Prochain forfait annuel", copy=False, tracking=True,
        help="Anniversaire de la signature : ce jour-là, Odoo rappelle au bureau de renouveler le forfait "
             "(prix à ajuster).")
    forfait_a_renouveler = fields.Boolean(
        "Forfait à renouveler", copy=False, readonly=True,
        help="L'anniversaire est arrivé : renouveler le forfait avec le bouton « Renouveler le forfait ».")

    def _date_entretien_saison(self, depuis):
        """Prochain entretien d'une machine de ce contrat, apres la date « depuis » (dernier entretien ou
        installation), selon la saison :
        - Annee, Ecole : a la date de renouvellement du contrat (sa fin), puis tous les 12 mois ;
        - Ete : le 1er novembre (machine fermee l'hiver ; date deplacable jusqu'au printemps) ;
        - Hiver : aucun entretien periodique (la machine revient a la fin de la periode).
        None : pas de saison, la frequence de la machine s'applique."""
        self.ensure_one()
        if self.saison == "hiver":
            return False
        if self.saison == "ete":
            novembre = date(depuis.year, 11, 1)
            return novembre if novembre > depuis else date(depuis.year + 1, 11, 1)
        if self.saison in ("annee", "ecole"):
            if not self.date_fin_location:
                return depuis + relativedelta(months=12)
            prochain = fields.Datetime.context_timestamp(self, self.date_fin_location).date()
            while prochain <= depuis:
                prochain += relativedelta(months=12)
            return prochain
        return None

    @api.depends("type_contrat_id")
    def _compute_forfait_montant(self):
        for order in self:
            order.forfait_montant = order.type_contrat_id.forfait_montant

    @api.depends("type_contrat_id")
    def _compute_require_signature(self):
        # Contrat Monroy : le client le signe en ligne avec le devis
        super()._compute_require_signature()
        for order in self.filtered("type_contrat_id"):
            order.require_signature = True

    # ------------------------------------------------------------ contrat imprime / signe en ligne
    def _contrat_valeurs(self):
        """Valeurs du contrat (QWeb) tirees d'Odoo : parties, machines, periode, montants."""
        self.ensure_one()
        type_contrat = self.type_contrat_id
        client = self.partner_id.commercial_partner_id
        devise = self.currency_id

        def date_fr(valeur, motif="d MMMM yyyy"):
            # Le contrat est toujours en francais, meme si la langue n'est pas installee
            return babel_dates.format_date(valeur, motif, locale="fr_CA") if valeur else ""

        debut = self.date_debut_location and self.date_debut_location.date() or self.date_order.date()
        fin = self.date_fin_location and self.date_fin_location.date()
        renouvellement = (fin + relativedelta(days=1), fin + (fin - debut) + relativedelta(days=1)) \
            if fin and fin > debut else (None, None)
        lignes_machines = self.order_line.filtered("est_machine")
        series = lignes_machines.machine_lot_id | self.machine_ids
        depart = sum(self.order_line.filtered(lambda l: not l.est_forfait and not l.display_type)
                     .mapped("price_subtotal"))
        mois = date_fr(self.signed_on and self.signed_on.date(), "MMMM")
        def blanc(valeur):
            """Valeur remplie depuis Odoo (en gras), sinon une ligne a remplir a la main."""
            return Markup("<strong>%s</strong>") % valeur if valeur else "______________"

        return {
            "blanc": blanc,
            # Signatures en images (page du client et PDF)
            "signature_client": image_data_uri(self.signature) if self.signature else "",
            # Compagnie : la caution est signee avec la signature du contrat
            "signature_caution": image_data_uri(self.signature) if self.signature and self.contrat_compagnie == "oui"
                                 else "",
            "modele": type_contrat.modele, "type": type_contrat,
            "proprietaire": self.company_id, "client": client,
            "commerce": self.partner_id if self.partner_id.is_company else client,
            "contact": self.partner_id.name if self.partner_id != client else "",
            "telephone": self.partner_id.phone or client.phone or "",
            "courriel": self.partner_id.email or client.email or "",
            "numero_client": client.ref or "",
            "modeles_machines": ", ".join(dict.fromkeys(lignes_machines.product_id.mapped("display_name"))),
            # N° de serie choisis sur le bon de livraison (reportes sur les lignes du contrat) ; blanc avant
            "series": ", ".join(series.mapped(lambda l: l.ref and "%s (%s)" % (l.ref, l.name) or l.name)),
            "debut": date_fr(debut), "fin": date_fr(fin),
            "renouvellement_debut": date_fr(renouvellement[0]), "renouvellement_fin": date_fr(renouvellement[1]),
            "montant_depart": devise.format(depart) if depart else "",
            "forfait": devise.format(self.forfait_montant),
            "appel_inutile": devise.format(type_contrat.frais_appel_inutile),
            "deplacement": devise.format(type_contrat.frais_deplacement),
            "taux_horaire": devise.format(type_contrat.taux_horaire),
            "clause_penale": devise.format(type_contrat.clause_penale),
            # Format du formulaire original : « 2.75$ », « 359.99$ »
            "prix_353": "%.2f" % self.prix_detail_353 if self.prix_detail_353 else "",
            "prix_510": "%.2f" % self.prix_detail_510 if self.prix_detail_510 else "",
            "prix_775": "%.2f" % self.prix_detail_775 if self.prix_detail_775 else "",
            "montant_depart_nombre": "%.2f" % depart if depart else "",
            "forfait_texte": ("%.2f$" if type_contrat.modele == "convention" else "%.2f $") % self.forfait_montant,
            "telephone2": self.partner_id.mobile if "mobile" in self.partner_id._fields else "",
            "coches": self._contrat_cases_modele(lignes_machines.product_id),
            "saisons": [self.saison] if self.saison else [],
            "signe_annee2": "%02d" % (self.signed_on.year % 100) if self.signed_on else "",
            "saison": dict(self._fields["saison"]._description_selection(self.env)).get(self.saison, ""),
            "signe_ville": self.company_id.city or "", "signe_jour": self.signed_on and self.signed_on.day or "",
            "signe_mois": mois, "signe_annee": self.signed_on and self.signed_on.year or "",
        }

    # ------------------------------------------------------------ rempli par le client (page du devis)
    CHAMPS_CLIENT = ("contrat_initiales", "contrat_compagnie", "caution_nom", "caution_numero", "caution_rue",
                     "caution_ville", "caution_province", "proprietaire_immeuble")

    def _contrat_modifiable_par_client(self):
        """Le client complete son contrat tant qu'il ne l'a pas signe."""
        self.ensure_one()
        return bool(self.type_contrat_id) and self.state in ("draft", "sent") and not self.signature

    def _contrat_completer_par_client(self, valeurs):
        """Initiales, caution et proprietaire de l'immeuble saisis par le client sur sa page."""
        self.ensure_one()
        if not self._contrat_modifiable_par_client():
            raise UserError(self.env._("Le contrat est déjà signé : il ne peut plus être modifié."))
        # Enregistre automatiquement pendant que le client remplit les cases du contrat (champs recus seulement)
        ecriture = {champ: (valeurs.get(champ) or "").strip()[:150] or False
                    for champ in self.CHAMPS_CLIENT if champ in valeurs}
        if ecriture.get("contrat_compagnie") not in (None, False, "oui", "non"):
            ecriture.pop("contrat_compagnie")
        if ecriture:
            self.write(ecriture)

    # ------------------------------------------------------------ PDF dans le dossier (Documents) du client
    def _archiver_contrat_signe(self):
        """Contrat signe en ligne : message dans la fiche du client + PDF signe dans ses Documents."""
        for order in self.filtered(lambda o: o.type_contrat_id and o.signature):
            pdf = order._archiver_pdf_client()
            if pdf:
                client = order.partner_id.commercial_partner_id
                client.sudo().message_post(
                    body=Markup("<p>%s</p>") % self.env._(
                        "Contrat %(numero)s (%(type)s) signé en ligne par %(signataire)s.", numero=order.name,
                        type=order.type_contrat_id.name, signataire=order.signed_by or client.name),
                    attachment_ids=pdf.ids, message_type="comment", subtype_xmlid="mail.mt_note")

    def _nom_document_client(self, signe=None):
        self.ensure_one()
        # Meme nom quelle que soit la langue de celui qui range le PDF (bureau en francais, client du
        # portail en anglais...) : sinon le contrat signe ne remplace pas le devis et fait un doublon
        self = self.with_context(lang=self.company_id.partner_id.lang or self.env.lang)
        if self.type_contrat_id:
            nom = self.env._("Contrat %(numero)s (%(type)s)", numero=self.name, type=self.type_contrat_id.name)
            signe = bool(self.signature) if signe is None else signe
            return nom + (self.env._(" signé") if signe else "") + ".pdf"
        if self.type_commande == "location":
            return self.env._("Contrat de location %s.pdf", self.name)
        return self.env._("Bon de vente %s.pdf", self.name)

    def _archiver_pdf_client(self):
        """PDF du bon de vente / de la location / du contrat range dans le profil du client : application
        Documents si installee, sinon pieces jointes de sa fiche. Mis a jour (pas de doublon). Ne bloque
        jamais la confirmation ni la signature. Retourne la piece jointe de la fiche client (ou False)."""
        return self._ranger_pdf_et_erreurs()[0]

    def _ranger_pdf_et_erreurs(self):
        """Range le PDF de chaque commande ; retourne (pieces rangees, {numero: raison de l'echec})."""
        resultat, erreurs = self.env["ir.attachment"], {}
        for order in self:
            try:
                with self.env.cr.savepoint():
                    resultat |= order._ranger_pdf_client()
            except Exception as erreur:  # noqa: BLE001 - la vente passe avant tout
                _logger.warning("%s : PDF non rangé dans le profil du client", order.name, exc_info=True)
                erreurs[order.name] = str(erreur).strip().splitlines()[0][:200] if str(erreur).strip() \
                    else type(erreur).__name__
        return resultat, erreurs

    def action_ranger_pdf_client(self):
        """Action « Ranger le PDF dans le profil du client » (menu Action, ventes seulement) : refait le PDF
        avec le site demarre et remplace celui de la fiche et des Documents du client."""
        self.check_access("write")
        ranges, erreurs = self._ranger_pdf_et_erreurs()
        message = self.env._("%s PDF rangé(s) dans le profil du client.", len(ranges))
        if erreurs:
            # La raison s'affiche a l'ecran (plus besoin du journal du serveur pour comprendre)
            message += " " + self.env._("Non rangé : %s", " ; ".join(
                "%s (%s)" % (numero, raison) for numero, raison in erreurs.items()))
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"message": message, "type": "warning" if erreurs else "success",
                           "sticky": bool(erreurs)}}

    def _ranger_pdf_client(self):
        self.ensure_one()
        pdf = self.env["ir.actions.report"].sudo().with_context(sale_include_signature=True)._render_qweb_pdf(
            "sale.action_report_saleorder", self.ids)[0]
        client = self.partner_id.commercial_partner_id
        nom = self._nom_document_client()
        # Meme document du devis envoye au contrat signe : renomme et mis a jour, pas de doublon
        noms = list({nom, self._nom_document_client(signe=False)})
        Attachment = self.env["ir.attachment"].sudo()
        piece = Attachment.search([("res_model", "=", "res.partner"), ("res_id", "=", client.id),
                                   ("name", "in", noms)], limit=1)
        if piece:
            piece.write({"name": nom, "raw": pdf})
        else:
            piece = Attachment.create({"name": nom, "raw": pdf, "mimetype": "application/pdf",
                                       "res_model": "res.partner", "res_id": client.id})
        if "documents.document" in self.env:
            self._ranger_dans_documents(client, nom, pdf, noms)
        return piece

    def _ranger_dans_documents(self, client, nom, pdf, noms=None):
        """Application Documents : dossier « Contrats et ventes clients », document relie au client (bouton
        Documents de sa fiche). Champs standards seulement : nom, fichier, client, dossier."""
        Document = self.env["documents.document"].sudo()
        nom_dossier = self.env._("Contrats et ventes clients")
        # Visible par tout le bureau : proprietaire interne (le vendeur, sinon l'administrateur) et acces
        # interne en modification. Sans cela, un contrat signe au portail appartient au client portail et
        # le bouton Documents de la fiche reste a 0 pour Jose
        acces = {}
        if "owner_id" in Document._fields:
            vendeur = self.user_id if self.user_id and not self.user_id.share else self.env.ref("base.user_admin")
            acces["owner_id"] = vendeur.id
        if "access_internal" in Document._fields:
            acces["access_internal"] = "edit"
        if "documents.folder" in self.env:   # anciennes versions de Documents
            Dossier = self.env["documents.folder"].sudo()
            dossier = Dossier.search([("name", "=", nom_dossier)], limit=1) or Dossier.create({"name": nom_dossier})
        else:                                 # Documents 18+ : un dossier est un document de type « folder »
            dossier = Document.search([("type", "=", "folder"), ("name", "=", nom_dossier)], limit=1) \
                or Document.create(dict(acces, name=nom_dossier, type="folder"))
            if "access_internal" in Document._fields and dossier.access_internal != "edit":
                dossier.access_internal = "edit"
        document = Document.search([("partner_id", "=", client.id), ("name", "in", noms or [nom]),
                                    ("folder_id", "=", dossier.id)], limit=1)
        # Le fichier d'un document est sa piece jointe (attachment_id) : Documents (Odoo 20) n'a plus de
        # champ « datas » sur le document lui-meme
        if document and document.attachment_id:
            document.attachment_id.write({"name": nom, "raw": pdf})
            document.write(dict(acces, name=nom))
        else:
            fichier = self.env["ir.attachment"].sudo().create({"name": nom, "raw": pdf,
                                                               "mimetype": "application/pdf"})
            valeurs = dict(acces, name=nom, attachment_id=fichier.id, partner_id=client.id,
                           folder_id=dossier.id)
            if document:
                document.write(valeurs)
            else:
                document = Document.create(valeurs)
        return document

    @api.model
    def _contrat_cases_modele(self, produits):
        """Cases « MODÈLE » du formulaire cochees d'apres le nom / la reference des machines du contrat."""
        cases = set()
        for produit in produits:
            texte = " %s %s " % ((produit.default_code or "").upper(), (produit.name or "").upper())
            bebe, comptoir = "BÉBÉ" in texte or "BEBE" in texte, "COMPTOIR" in texte
            for code in ("F100", "SP10", "FC1", "FC2", "FC3", "V1", "V2"):
                if re.search(r"(?<![A-Z0-9])%s(?![0-9])" % code, texte):
                    if code in ("FC1", "FC2") and bebe:
                        cases.add("B" + code)
                    elif code in ("F100", "SP10") and comptoir:
                        cases.add(code + "C")
                    else:
                        cases.add(code)
        if produits and not cases:
            cases.add("AUTRE")
        return cases

    @api.onchange("type_contrat_id")
    def _onchange_type_contrat_id(self):
        if self.type_contrat_id:
            self.type_commande = self.type_contrat_id.type_commande

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("type_contrat_id") and "type_commande" not in vals:
                vals["type_commande"] = self.env["suivi.type.contrat"].browse(vals["type_contrat_id"]).type_commande
        commandes = super().create(vals_list)
        commandes._synchroniser_forfait(prix=True)
        return commandes

    def write(self, vals):
        if vals.get("type_contrat_id") and "type_commande" not in vals:
            vals = dict(vals, type_commande=self.env["suivi.type.contrat"].browse(
                vals["type_contrat_id"]).type_commande)
        res = super().write(vals)
        if not self.env.context.get("synchro_forfait") and (
                {"order_line", "type_contrat_id", "forfait_montant"} & set(vals)):
            self._synchroniser_forfait(prix=bool({"type_contrat_id", "forfait_montant"} & set(vals)))
        return res

    def _find_mail_template(self):
        """« Envoyer » un contrat de location pas encore signe : courriel Monroy en francais avec le bouton
        « Lire et signer mon contrat » (le lien securise du client)."""
        self.ensure_one()
        if (self.state in ("draft", "sent") and not self.env.context.get("proforma")
                and (self.type_commande == "location" or self.type_contrat_id)):
            modele = self.env.ref("suivi_machines.mail_template_contrat_location", raise_if_not_found=False)
            if modele:
                return modele
        return super()._find_mail_template()

    def action_confirm(self):
        res = super().action_confirm()
        # Profil du client : une vente confirmee (signee ou non) ; un contrat seulement une fois signe
        # (rien a l'envoi du devis)
        self.filtered(lambda o: o.state == "sale" and (
            o.signature or (o.type_commande == "vente" and not o.type_contrat_id)))._archiver_pdf_client()
        # Clause 8.2 : forfait paye a la signature (ligne du contrat), puis tous les 12 mois
        aujourdhui = fields.Date.context_today(self)
        for contrat in self.filtered(lambda o: o.state == "sale" and o.forfait_montant > 0
                                     and not o.forfait_prochaine_date):
            contrat.forfait_prochaine_date = aujourdhui + relativedelta(months=12)
        return res

    # ------------------------------------------------------------ forfait annuel (ligne du contrat)
    def _produit_forfait(self):
        return self.type_contrat_id.forfait_produit_id or self.env.ref(
            "suivi_machines.produit_forfait_entretien", raise_if_not_found=False)

    def _libelle_forfait(self, debut, machines=None):
        libelle = self.env._(
            "Frais annuels d'entretien et de réparations usuelles (%(type)s) du %(debut)s au %(fin)s",
            type=self.type_contrat_id.name, debut=debut, fin=debut + relativedelta(months=12, days=-1))
        if machines:
            libelle += "\n" + self.env._("Machines : %s", ", ".join(machines.mapped(lambda l: l.ref or l.name)))
        return libelle

    def _synchroniser_forfait(self, prix=False):
        """Soumission : la ligne du forfait de la 1re annee suit le contrat (une par machine commandee).
        Le prix est celui du contrat (modifiable) ; un prix change a la main sur la ligne est garde."""
        for order in self.filtered(lambda o: o.state in ("draft", "sent")).with_context(synchro_forfait=True):
            ligne = order.order_line.filtered("est_forfait")[:1]
            nombre = int(sum(order.order_line.filtered("est_machine").mapped("product_uom_qty")))
            produit = order._produit_forfait()
            if order.forfait_montant <= 0 or not nombre or not produit:
                if ligne:
                    ligne.unlink()
                continue
            debut = fields.Date.context_today(order)
            if not ligne:
                order.write({"order_line": [(0, 0, {
                    "product_id": produit.id, "est_forfait": True, "product_uom_qty": nombre,
                    "price_unit": order.forfait_montant, "name": order._libelle_forfait(debut),
                    "sequence": max(order.order_line.mapped("sequence") or [10]) + 1})]})
                continue
            valeurs = {}
            if ligne.product_uom_qty != nombre:
                valeurs["product_uom_qty"] = nombre
            if prix or "product_uom_qty" in valeurs:
                valeurs["price_unit"] = order.forfait_montant if prix else ligne.price_unit
            if valeurs:
                ligne.write(valeurs)

    def _machines_forfait(self):
        """Nombre de machines facturees au forfait : celles du contrat encore chez le client ; avant la
        livraison, les machines commandees. 0 si toutes sont revenues (contrat termine)."""
        self.ensure_one()
        chez_client = self.machine_ids.filtered("machine_client_id")
        if chez_client:
            return len(chez_client), chez_client
        livrees = self.picking_ids.filtered(lambda p: p.state == "done" and p.picking_type_code == "outgoing")
        if livrees:
            return 0, chez_client
        return int(sum(self.order_line.filtered("est_machine").mapped("product_uom_qty"))), chez_client

    def _forfait_prix_precedent(self):
        """Prix negocie : celui de la derniere ligne de forfait du contrat, sinon celui du contrat."""
        self.ensure_one()
        precedente = self.order_line.filtered("est_forfait").sorted("id")[-1:]
        return precedente.price_unit if precedente else self.forfait_montant

    def _ajouter_forfait_annuel(self, prix, nombre=None):
        """Renouvellement fait par le bureau : ligne du forfait de l'annee ajoutee AU CONTRAT (a facturer
        avec « Créer une facture ») au prix choisi ; prochaine date + 12 mois ; rappel termine."""
        self.ensure_one()
        debut = self.forfait_prochaine_date or fields.Date.context_today(self)
        nombre_machines, machines = self._machines_forfait()
        nombre = nombre_machines if nombre is None else nombre
        produit = self._produit_forfait()
        if nombre <= 0 or not produit:
            raise UserError(self.env._("Aucune machine de ce contrat n'est chez le client : rien à renouveler."))
        if prix < 0:
            raise UserError(self.env._("Le prix du forfait ne peut pas être négatif."))
        self.with_context(synchro_forfait=True).write({
            "forfait_prochaine_date": debut + relativedelta(months=12), "forfait_a_renouveler": False,
            "order_line": [(0, 0, {"product_id": produit.id, "est_forfait": True, "product_uom_qty": nombre,
                                   "price_unit": prix, "name": self._libelle_forfait(debut, machines)})]})
        self.message_post(body=Markup("<p>%s</p>") % self.env._(
            "Forfait annuel renouvelé : %(nb)s machine(s) × %(prix).2f $, à facturer.", nb=nombre, prix=prix))
        self._activites_forfait().action_feedback(feedback=self.env._("Forfait renouvelé à %.2f $.", prix))

    def _activites_forfait(self):
        resume = self.env._("Forfait annuel à renouveler")
        return self.activity_ids.filtered(lambda a: a.summary == resume)

    def action_renouveler_forfait(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": self.env._("Renouveler le forfait"),
                "res_model": "suivi.forfait.renouvellement", "view_mode": "form", "views": [(False, "form")],
                "target": "new", "context": {"default_order_id": self.id}}

    @api.model
    def _cron_forfaits_annuels(self):
        """Chaque jour : anniversaire arrive -> rappel au bureau (le prix est ajuste avant de renouveler)."""
        contrats = self.search([("state", "=", "sale"), ("forfait_montant", ">", 0),
                                ("forfait_a_renouveler", "=", False),
                                ("forfait_prochaine_date", "<=", fields.Date.context_today(self))])
        for contrat in contrats:
            contrat.forfait_a_renouveler = True
            contrat.activity_schedule(
                "mail.mail_activity_data_todo", date_deadline=contrat.forfait_prochaine_date,
                user_id=(contrat.user_id or self.env.ref("base.user_admin")).id,
                summary=self.env._("Forfait annuel à renouveler"),
                note=self.env._("Anniversaire du contrat : ajustez le prix puis cliquez sur « Renouveler le "
                                "forfait » (prix de l'an dernier : %.2f $).", contrat._forfait_prix_precedent()))
        return contrats


class RenouvellementForfait(models.TransientModel):
    _name = "suivi.forfait.renouvellement"
    _description = "Renouveler le forfait annuel"

    order_id = fields.Many2one("sale.order", "Contrat", required=True, readonly=True)
    partner_id = fields.Many2one(related="order_id.partner_id", string="Client")
    date_debut = fields.Date(related="order_id.forfait_prochaine_date", string="Début de la période")
    prix_precedent = fields.Float("Prix de l'an dernier", readonly=True, digits="Product Price")
    prix = fields.Float("Nouveau prix (par machine)", required=True, digits="Product Price")
    nombre = fields.Integer("Nombre de machines", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env["sale.order"].browse(res.get("order_id") or self.env.context.get("default_order_id"))
        if order:
            prix = order._forfait_prix_precedent()
            res.update(prix_precedent=prix, prix=prix, nombre=order._machines_forfait()[0])
        return res

    def action_renouveler(self):
        self.ensure_one()
        self.order_id._ajouter_forfait_annuel(self.prix, self.nombre)
        return {"type": "ir.actions.act_window_close"}


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    est_forfait = fields.Boolean("Forfait annuel", copy=False, readonly=True,
                                 help="Ligne du forfait annuel d'entretien du contrat.")
