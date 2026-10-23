# -*- coding: utf-8 -*-
"""Fiche du ticket en deux colonnes equilibrees : a gauche le type de ticket (en evidence) et le client, a droite
l'assigne et la planification ; dessous, alignes sur la meme ligne, le parc machines et le contrat du client."""
from lxml import etree

from odoo import api, models

CHAMPS_TYPE = ("type_demande", "type_reparation")
CHAMPS_CONTRAT = ("contrat_client_id", "contrat_client_modele_id", "contrat_client_type", "contrat_client_debut",
                  "contrat_client_fin")


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    @api.model
    def _get_view(self, view_id=None, view_type="form", **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == "form":
            self._disposition_client_a_gauche(arch)
        return arch, view

    @api.model
    def _disposition_client_a_gauche(self, arch):
        """A gauche le type de ticket (en evidence, tout en haut), le client (code client, client, telephone,
        adresse) puis son parc machines ; a droite l'assigne, la date prevue, la planification, la priorite, les
        etiquettes, puis le contrat du client (debut, fin). L'equipe d'assistance est cachee (une seule equipe, « Appel de service »). Ne fait rien si la vue n'a pas cette forme."""
        for equipe_champ in arch.xpath("//field[@name='team_id']"):
            equipe_champ.set("invisible", "1")
        equipe = arch.xpath("//group/field[@name='team_id']/..") or arch.xpath("//group/field[@name='user_id']/..")
        client = arch.xpath("//group/field[@name='partner_id']/..")
        if not equipe or not client or equipe[0] is client[0]:
            return
        equipe, client = equipe[0], client[0]
        if equipe.getparent() is not client.getparent():
            return
        types = [n for n in client if n.tag in ("field", "label") and
                 (n.get("name") in CHAMPS_TYPE or n.get("for") in CHAMPS_TYPE)]
        if not types:
            return
        for noeud in reversed(types):
            client.remove(noeud)
            client.insert(0, noeud)    # le type de ticket tout en haut a gauche, au-dessus du code client
        for noeud in types:
            if noeud.tag == "field" and noeud.get("name") == "type_demande":
                noeud.set("class", " ".join(filter(None, [noeud.get("class"), "fw-bold fs-5 text-primary"])))
        equipe.addprevious(client)     # le client a gauche, l'assigne et la planification a droite
        # Choix du type de reparation sur deux lignes (pas une longue colonne de boutons)
        for reparation in client.xpath("./field[@name='type_reparation']"):
            reparation.set("options", "{'horizontal': true}")
        # Deux rangees alignees : en haut le client a cote de la planification ; dessous, sur la meme ligne,
        # le parc machines du client a cote du contrat du client
        rangee = etree.Element("group", name="rangee_parc_contrat")
        client.getparent().addnext(rangee)
        parc = arch.xpath("//group[@name='dossier_client_machine']/group[field[@name='lot_id']]")
        if parc:
            parc = parc[0]
            parc.set("invisible", "not commerce_id")
            parc.set("string", self.env._("Parc machines du client"))
            rangee.append(parc)
        else:
            etree.SubElement(rangee, "group")      # garde le contrat dans la colonne de droite
        contrat = [n for n in client.xpath("./field") if n.get("name") in CHAMPS_CONTRAT]
        if contrat:
            bloc = etree.SubElement(rangee, "group", string=self.env._("Contrat du client"),
                                    name="contrat_du_client", invisible="not contrat_client_id")
            for noeud in contrat:
                bloc.append(noeud)
