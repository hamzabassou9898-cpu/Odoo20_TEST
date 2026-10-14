# -*- coding: utf-8 -*-
"""Nettoyage des interventions :
- entretiens valides en double (meme machine, meme date et heure, faits) : un seul garde (celui lie a un ticket, sinon le
  plus ancien), les autres annules ;
- client vide : celui chez qui est la machine, sinon le client du ticket."""
from collections import defaultdict

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Intervention = env["machine.intervention"].with_context(tracking_disable=True)
    groupes = defaultdict(lambda: Intervention)
    for interv in Intervention.search([("type", "=", "entretien"), ("state", "=", "fait")], order="id"):
        groupes[(interv.lot_id.id, interv.date)] |= interv
    for doublons in groupes.values():
        if len(doublons) > 1:
            garde = doublons.filtered("ticket_id")[:1] or doublons[:1]
            (doublons - garde).write({"state": "annule"})
    for interv in Intervention.search([("partner_id", "=", False)]):
        client = interv.lot_id.machine_client_id or interv.ticket_id.partner_id
        if client:
            interv.partner_id = client
