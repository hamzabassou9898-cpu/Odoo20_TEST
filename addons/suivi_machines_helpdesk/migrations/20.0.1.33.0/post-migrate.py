# -*- coding: utf-8 -*-
"""Tickets existants : type de ticket (obligatoire) et origine automatique."""


def migrate(cr, version):
    if not version:
        return
    # Tickets crees par les actions planifiees (entretiens a echeance, fins de location)
    cr.execute("UPDATE helpdesk_ticket SET origine_auto = 'entretien' "
               "WHERE origine_auto IS NULL AND est_entretien")
    cr.execute("UPDATE helpdesk_ticket SET origine_auto = 'reprise' "
               "WHERE origine_auto IS NULL AND commande_reprise_id IS NOT NULL")
    # Anciens appels de service sans type : Reparation (le champ est obligatoire dans le formulaire)
    cr.execute("UPDATE helpdesk_ticket SET type_demande = CASE "
               "WHEN est_entretien THEN 'entretien' "
               "WHEN commande_reprise_id IS NOT NULL THEN 'ramassage' ELSE 'reparation' END "
               "WHERE type_demande IS NULL")
