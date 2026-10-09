# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Un seul champ : « Technicien terrain » passe dans « Assigne a »."""
    cr.execute("""
        UPDATE helpdesk_ticket
           SET user_id = technicien_terrain_id, technicien_terrain_id = NULL
         WHERE technicien_terrain_id IS NOT NULL
     RETURNING id
    """)
    ids = [row[0] for row in cr.fetchall()]
    env = api.Environment(cr, SUPERUSER_ID, {})
    Ticket = env["helpdesk.ticket"]
    if not ids or "statut_entretien" not in Ticket._fields:
        return
    # Entretiens maintenant assignes : statut « Planifie » (Pilotage, journee du technicien)
    tickets = Ticket.browse(ids)
    # Le SQL ci-dessus a change ces colonnes : on oublie les anciennes valeurs en memoire
    tickets.invalidate_recordset(["user_id", "technicien_terrain_id"], flush=False)
    env.add_to_compute(Ticket._fields["statut_entretien"], tickets)
    tickets.flush_recordset(["statut_entretien"])
