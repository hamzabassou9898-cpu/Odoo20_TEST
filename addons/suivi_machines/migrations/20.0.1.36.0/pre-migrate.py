# -*- coding: utf-8 -*-
"""Vue du contrat retiree avant la mise a jour (champs de signature de la caution supprimes : la caution
est signee avec la signature du contrat) ; elle est recreee depuis views/type_contrat_views.xml."""


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
