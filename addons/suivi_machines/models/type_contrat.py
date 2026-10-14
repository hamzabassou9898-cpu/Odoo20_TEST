# -*- coding: utf-8 -*-
"""Types de contrat Monroy (location, convention, convention popcorn, proprietaire) et forfait annuel.

Chaque type regle le comportement du contrat (machine louee ou vendue) et le forfait annuel d'entretien
(clause 8.2 : montant par machine, a la signature puis tous les 12 mois). Les montants se modifient dans
Ventes > Configuration > Types de contrat, sans programmation.
"""
import logging
import re

from babel import dates as babel_dates
from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

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
    caution_signature = fields.Binary("Signature de la caution", copy=False, attachment=True)
    caution_signe_par = fields.Char("Caution signée par", copy=False)
    caution_signe_le = fields.Datetime("Caution signée le", copy=False)
    proprietaire_immeuble = fields.Char("Propriétaire de l'immeuble (nom et adresse)", copy=False)
    forfait_prochaine_date = fields.Date(
        "Prochain forfait annuel", copy=False, tracking=True,
        help="Anniversaire de la signature : ce jour-là, Odoo ajoute au contrat la ligne du forfait de "
             "l'année suivante, à facturer.")

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
    CHAMPS_CLIENT = ("contrat_initiales", "caution_nom", "caution_numero", "caution_rue", "caution_ville",
                     "caution_province", "proprietaire_immeuble")

    def _contrat_modifiable_par_client(self):
        """Le client complete son contrat tant qu'il ne l'a pas signe."""
        self.ensure_one()
        return bool(self.type_contrat_id) and self.state in ("draft", "sent") and not self.signature

    def _contrat_completer_par_client(self, valeurs):
        """Initiales, caution et proprietaire de l'immeuble saisis par le client sur sa page."""
        self.ensure_one()
        if not self._contrat_modifiable_par_client():
            raise UserError(self.env._("Le contrat est déjà signé : il ne peut plus être modifié."))
        self.write({champ: (valeurs.get(champ) or "").strip()[:150] or False for champ in self.CHAMPS_CLIENT})
        self.message_post(body=self.env._("Le client a complété le contrat (initiales, caution, propriétaire "
                                          "de l'immeuble)."))

    def _signer_caution(self, nom, signature):
        """Signature de la caution (compagnie), sur la page du client, avant la signature du contrat."""
        self.ensure_one()
        if not self._contrat_modifiable_par_client():
            raise UserError(self.env._("Le contrat est déjà signé : il ne peut plus être modifié."))
        if not signature:
            raise UserError(self.env._("La signature est vide."))
        nom = (nom or "").strip()[:100] or self.caution_nom
        self.write({"caution_signature": signature, "caution_signe_par": nom,
                    "caution_signe_le": fields.Datetime.now(), "caution_nom": self.caution_nom or nom})
        self.message_post(body=self.env._("Caution signée en ligne par %s.", nom))

    # ------------------------------------------------------------ contrat signe : dossier du client
    def _archiver_contrat_signe(self):
        """Contrat signe en ligne : son PDF signe est range dans le dossier du client (fiche client, et
        application Documents si elle est installee). Ne bloque jamais la signature."""
        for order in self.filtered(lambda o: o.type_contrat_id and o.signature):
            try:
                with self.env.cr.savepoint():
                    order._ranger_pdf_contrat()
            except Exception:  # noqa: BLE001 - la signature du client passe avant tout
                _logger.warning("Contrat %s : PDF signé non rangé dans le dossier du client", order.name,
                                exc_info=True)

    def _ranger_pdf_contrat(self):
        self.ensure_one()
        Attachment = self.env["ir.attachment"].sudo()
        piece = Attachment.search([("res_model", "=", "sale.order"), ("res_id", "=", self.id),
                                   ("mimetype", "=", "application/pdf")], order="id desc", limit=1)
        if not piece:
            pdf = self.env["ir.actions.report"].sudo().with_context(sale_include_signature=True)._render_qweb_pdf(
                "sale.action_report_saleorder", self.ids)[0]
            piece = Attachment.create({"name": "%s.pdf" % self.name, "raw": pdf, "mimetype": "application/pdf",
                                       "res_model": "sale.order", "res_id": self.id})
        client = self.partner_id.commercial_partner_id
        nom = self.env._("Contrat %(numero)s (%(type)s) signé.pdf", numero=self.name, type=self.type_contrat_id.name)
        copie = piece.copy({"name": nom, "res_model": "res.partner", "res_id": client.id})
        client.sudo().message_post(
            body=Markup("<p>%s</p>") % self.env._("Contrat %(numero)s (%(type)s) signé en ligne par %(signataire)s.",
                                                  numero=self.name, type=self.type_contrat_id.name,
                                                  signataire=self.signed_by or client.name),
            attachment_ids=copie.ids, message_type="comment", subtype_xmlid="mail.mt_note")
        if "documents.document" in self.env:
            self._ranger_dans_documents(client, nom, piece)

    def _ranger_dans_documents(self, client, nom, piece):
        """Application Documents (Enterprise) : dossier « Contrats clients », document relie au client."""
        Document = self.env["documents.document"].sudo()
        nom_dossier = self.env._("Contrats clients")
        valeurs = {"name": nom, "datas": piece.datas, "mimetype": "application/pdf", "partner_id": client.id,
                   "res_model": "res.partner", "res_id": client.id}
        if "documents.folder" in self.env:   # anciennes versions de Documents
            Dossier = self.env["documents.folder"].sudo()
            dossier = Dossier.search([("name", "=", nom_dossier)], limit=1) or Dossier.create({"name": nom_dossier})
        else:                                 # Documents 18+ : un dossier est un document de type « folder »
            dossier = Document.search([("type", "=", "folder"), ("name", "=", nom_dossier)], limit=1) \
                or Document.create({"name": nom_dossier, "type": "folder"})
        valeurs["folder_id"] = dossier.id
        return Document.create({cle: val for cle, val in valeurs.items() if cle in Document._fields})

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

    def action_confirm(self):
        res = super().action_confirm()
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

    def _ajouter_forfait_annuel(self):
        """Anniversaire : ligne du forfait de l'annee ajoutee AU CONTRAT (a facturer avec « Créer une
        facture »), au prix de ce contrat ; activite pour le bureau ; prochaine date + 12 mois."""
        for contrat in self:
            debut = contrat.forfait_prochaine_date or fields.Date.context_today(self)
            nombre, machines = contrat._machines_forfait()
            contrat.forfait_prochaine_date = debut + relativedelta(months=12)
            produit = contrat._produit_forfait()
            if nombre <= 0 or not produit:
                contrat.message_post(body=self.env._(
                    "Forfait annuel du %s : aucune machine chez le client, rien à facturer.", debut))
                continue
            # Prix negocie : celui de la derniere ligne de forfait du contrat, sinon celui du contrat
            precedente = contrat.order_line.filtered("est_forfait").sorted("id")[-1:]
            prix = precedente.price_unit if precedente else contrat.forfait_montant
            contrat.with_context(synchro_forfait=True).write({"order_line": [(0, 0, {
                "product_id": produit.id, "est_forfait": True, "product_uom_qty": nombre, "price_unit": prix,
                "name": contrat._libelle_forfait(debut, machines)})]})
            contrat.message_post(body=Markup("<p>%s</p>") % self.env._(
                "Forfait annuel ajouté au contrat : %(nb)s machine(s) × %(prix)s, à facturer.",
                nb=nombre, prix=prix))
            contrat.activity_schedule(
                "mail.mail_activity_data_todo", user_id=(contrat.user_id or self.env.ref("base.user_admin")).id,
                summary=self.env._("Forfait annuel à facturer"),
                note=self.env._("Le forfait annuel d'entretien a été ajouté au contrat : « Créer une facture »."))

    @api.model
    def _cron_forfaits_annuels(self):
        """Chaque jour : forfait annuel des contrats dont l'anniversaire est arrive."""
        contrats = self.search([("state", "=", "sale"), ("forfait_montant", ">", 0),
                                ("forfait_prochaine_date", "<=", fields.Date.context_today(self))])
        contrats._ajouter_forfait_annuel()
        return contrats


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    est_forfait = fields.Boolean("Forfait annuel", copy=False, readonly=True,
                                 help="Ligne du forfait annuel d'entretien du contrat.")
