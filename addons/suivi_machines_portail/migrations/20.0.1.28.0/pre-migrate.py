# -*- coding: utf-8 -*-
"""Formulaire web « Appel de service » retire (les clients appellent Jose) : ses pages et le bandeau du ticket
sont supprimes AVANT la mise a jour. Sinon Odoo valide les autres vues du ticket avec l'ancien bandeau, qui
utilise le champ « recu_par_web » retire, et la mise a jour s'arrete. Les tickets deja recus restent."""

VUES = ("appel_de_service_page", "appel_de_service_merci", "helpdesk_ticket_view_form_recu_par_web")


def migrate(cr, version):
    cr.execute("""SELECT res_id FROM ir_model_data
                   WHERE module = 'suivi_machines_portail' AND model = 'ir.ui.view' AND name IN %s""", (VUES,))
    vues = [ligne[0] for ligne in cr.fetchall()]
    if not vues:
        return
    # Vues qui en heritent (aucune prevue, par prudence), puis les vues elles-memes et leurs xmlids
    cr.execute("DELETE FROM ir_ui_view WHERE inherit_id IN %s", (tuple(vues),))
    cr.execute("DELETE FROM ir_ui_view WHERE id IN %s", (tuple(vues),))
    cr.execute("""DELETE FROM ir_model_data
                   WHERE module = 'suivi_machines_portail' AND model = 'ir.ui.view' AND name IN %s""", (VUES,))
