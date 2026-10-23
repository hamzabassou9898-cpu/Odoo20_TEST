# -*- coding: utf-8 -*-
"""Fiche du ticket : a gauche le type de ticket (en evidence) puis le client (code client, client, telephone,
adresse, contrat) ; a droite l'assigne et la planification."""
from odoo import api, models

CHAMPS_TYPE = ("type_demande", "type_reparation")


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
        """A gauche le type de ticket (en evidence, tout en haut) puis le client (code client, client, telephone,
        adresse, contrat) ; a droite l'assigne, la date prevue, la planification, la priorite et les etiquettes. L'equipe d'assistance est
        cachee (une seule equipe, « Appel de service »). Ne fait rien si la vue n'a pas cette forme."""
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
