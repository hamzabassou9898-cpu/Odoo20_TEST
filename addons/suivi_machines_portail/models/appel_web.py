# -*- coding: utf-8 -*-
"""Formulaire web « Appel de service » (/appel-de-service) : le client cree lui-meme son ticket.

Le code client (s'il le connait) retrouve son dossier : client, adresse, machines, contrat de location
(ramassage)... comme quand Josef le saisit au telephone.
"""
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.mail import email_normalize, plaintext2html

# Champs du formulaire : (nom, libelle, obligatoire). SANS_CODE : obligatoire seulement sans code client
# valide (sinon Odoo connait deja l'entreprise et son adresse : notre base, c'est le code client).
SANS_CODE = "sans_code"
CHAMPS_FORMULAIRE = [
    ("prenom", "Prénom", True),
    ("nom", "Nom", True),
    ("courriel", "Courriel", True),
    ("entreprise", "Entreprise", SANS_CODE),
    ("code_client", "Code client", False),
    ("telephone", "Téléphone", True),
    ("adresse", "Adresse", SANS_CODE),
    ("ville", "Ville", SANS_CODE),
]
LONGUEUR_CHAMP = 200
LONGUEUR_MESSAGE = 5000


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    recu_par_web = fields.Boolean(
        "Reçu par le formulaire web", readonly=True, copy=False,
        help="Ticket créé par le client lui-même avec le formulaire « Appel de service » du site web.")

    @api.model
    def _valeurs_formulaire_web(self, post):
        """Valeurs nettoyees du formulaire ; UserError (message pour le client) si quelque chose manque."""
        valeurs = {nom: (post.get(nom) or "").strip()[:LONGUEUR_CHAMP] for nom, _l, _o in CHAMPS_FORMULAIRE}
        valeurs["message"] = (post.get("message") or "").strip()[:LONGUEUR_MESSAGE]
        valeurs["type_demande"] = post.get("type_demande") or ""
        valeurs["type_reparation"] = post.get("type_reparation") or ""
        valeurs["code_client"] = valeurs["code_client"].upper()
        avec_code = bool(self._client_par_code(valeurs["code_client"]))
        manquants = [libelle for nom, libelle, obligatoire in CHAMPS_FORMULAIRE
                     if (obligatoire is True or (obligatoire == SANS_CODE and not avec_code)) and not valeurs[nom]]
        if manquants:
            raise UserError(self.env._("Veuillez remplir : %s.", ", ".join(manquants)))
        if not email_normalize(valeurs["courriel"]):
            raise UserError(self.env._("L'adresse courriel n'est pas valide."))
        if valeurs["type_demande"] not in dict(self._fields["type_demande"].selection):
            raise UserError(self.env._("Veuillez choisir le type de demande."))
        if valeurs["type_demande"] == "reparation":
            if valeurs["type_reparation"] not in dict(self._fields["type_reparation"].selection):
                raise UserError(self.env._("Veuillez choisir le type de réparation."))
        else:
            valeurs["type_reparation"] = ""
        if valeurs["type_reparation"] == "autre" and not valeurs["message"]:
            raise UserError(self.env._("Réparation « Autre » : décrivez le problème dans la section Message."))
        return valeurs

    @api.model
    def _description_formulaire_web(self, valeurs):
        lignes = Markup("").join(
            Markup("<li><strong>%s :</strong> %s</li>") % (libelle, valeurs[nom])
            for nom, libelle, _o in CHAMPS_FORMULAIRE if valeurs[nom])
        description = Markup("<p><strong>%s</strong></p><ul>%s</ul>") % (
            self.env._("Demande reçue par le formulaire web"), lignes)
        if valeurs["message"]:
            description += plaintext2html(valeurs["message"])
        return description

    @api.model
    def _creer_depuis_formulaire_web(self, post):
        """Cree le ticket du formulaire web (appele en sudo par le controleur public)."""
        valeurs = self._valeurs_formulaire_web(post)
        client = self._client_par_code(valeurs["code_client"])
        type_demande = valeurs["type_demande"]
        # Machine a remplacer : le client doit avoir une machine (message neutre, sans son dossier)
        if type_demande == "remplacement" and client and not self.new({"partner_id": client.id}).nb_machines_client:
            raise UserError(self.env._(
                "Aucune machine n'est enregistrée à votre dossier : choisissez un autre type de demande "
                "ou appelez-nous."))
        libelles = dict(self._fields["type_demande"]._description_selection(self.env))
        titre = libelles[type_demande]
        if valeurs["type_reparation"]:
            titre += " : %s" % dict(self._fields["type_reparation"]._description_selection(self.env))[
                valeurs["type_reparation"]]
        # Client connu (code client) : ses informations viennent d'Odoo ; ce qui a ete tape reste dans la
        # description. Client inconnu : ce qui a ete tape.
        commerce = (client.parent_id if client.parent_id and client.type == "contact" else client) if client else client
        vals = {
            "name": "%s — %s" % (titre, commerce.name if client else valeurs["entreprise"]),
            "type_demande": type_demande,
            "type_reparation": valeurs["type_reparation"] or False,
            "partner_email": (client and (client.email or commerce.email)) or email_normalize(valeurs["courriel"]),
            "partner_phone": (client and (client.phone or commerce.phone)) or valeurs["telephone"],
            "description": self._description_formulaire_web(valeurs),
            "recu_par_web": True,
        }
        if client:
            vals["partner_id"] = client.id
        if "partner_name" in self._fields:
            vals["partner_name"] = "%s %s" % (valeurs["prenom"], valeurs["nom"])
        ticket = self.with_context(mail_create_nosubscribe=True).create(vals)
        # Une seule machine chez le client : on la choisit (comme a l'ecran)
        if client and not ticket.lot_id and len(ticket.machines_client_ids) == 1:
            ticket.lot_id = ticket.machines_client_ids
        return ticket

    def _reference_web(self):
        """Numero montre au client apres l'envoi."""
        self.ensure_one()
        return self.ticket_ref if "ticket_ref" in self._fields and self.ticket_ref else "#%s" % self.id
