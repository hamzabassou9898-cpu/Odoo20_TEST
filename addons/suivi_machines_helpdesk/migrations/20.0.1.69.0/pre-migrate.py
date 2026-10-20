# -*- coding: utf-8 -*-
"""Type de ticket « Passer une commande » retire : les tickets qui l'avaient sont gardes, sans type (Jose en
choisit un si besoin)."""


def migrate(cr, version):
    cr.execute("UPDATE helpdesk_ticket SET type_demande = NULL WHERE type_demande = 'commande'")
