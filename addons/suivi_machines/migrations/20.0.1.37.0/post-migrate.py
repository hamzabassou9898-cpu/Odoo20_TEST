# -*- coding: utf-8 -*-
"""Documents du client : les commandes recentes envoyees ou confirmees sont rangees dans le profil de leur
client par la tache planifiee (site demarre : PDF complets), lancee tout de suite apres la mise a jour,
pas pendant (wkhtmltopdf n'a pas acces au site pendant une mise a jour)."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("suivi_machines.cron_ranger_pdf_clients", raise_if_not_found=False)
    if cron:
        cron._trigger()
