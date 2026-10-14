# -*- coding: utf-8 -*-
"""Forfait annuel devenu une ligne du contrat : l'ancienne vue du contrat (bouton « Forfaits annuels »,
methode supprimee) bloquerait la validation des vues a la mise a jour. On la retire avant le chargement ;
elle est recreee depuis views/type_contrat_views.xml."""


def migrate(cr, version):
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'suivi_machines' AND model = 'ir.ui.view' AND name = 'view_order_form_type_contrat'
    """)
    vues = [ligne[0] for ligne in cr.fetchall()]
    if not vues:
        return
    # Vues heritant de celle-ci (personnalisations) : retirees aussi, sinon elles bloquent la suppression
    cr.execute("DELETE FROM ir_ui_view WHERE inherit_id = ANY(%s)", [vues])
    cr.execute("DELETE FROM ir_ui_view WHERE id = ANY(%s)", [vues])
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'suivi_machines' AND model = 'ir.ui.view' AND name = 'view_order_form_type_contrat'
    """)
