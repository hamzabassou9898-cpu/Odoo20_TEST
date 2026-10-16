# -*- coding: utf-8 -*-
"""Fiche du ticket : a gauche le client (code client, client, telephone, adresse, contrat) puis l'equipe et
la planification ; a droite le type de ticket et le type de reparation."""
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
        """Groupe du client a gauche (en haut), suivi de l'equipe / planification ; le type a droite.
        Ne fait rien si la vue n'a pas cette forme (vue de creation rapide, autre version d'Odoo)."""
        # Groupe de l'equipe / de l'assigne (l'equipe peut etre cachee si une seule equipe)
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
        for noeud in types:
            client.remove(noeud)
        for noeud in list(equipe):
            client.append(noeud)       # sous les champs du client
        for noeud in types:
            equipe.append(noeud)       # le type de ticket, seul a droite
        equipe.addprevious(client)     # le client passe a gauche
