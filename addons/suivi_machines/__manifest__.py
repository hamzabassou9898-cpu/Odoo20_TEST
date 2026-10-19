# -*- coding: utf-8 -*-
{
    "name": "Suivi des machines",
    "summary": "Dossier de chaque machine (numéro de série) : interventions, "
               "historique, santé et tableau de bord",
    "version": "20.0.1.55.0",
    "category": "Inventory/Inventory",
    "author": "Volcan",
    "website": "https://volcan.ca/",
    "license": "LGPL-3",
    "depends": ["stock", "sale_stock", "mail"],
    "data": [
        "security/ir.access.csv",
        "data/ir_sequence.xml",
        "data/produits_frais.xml",
        "data/types_contrat.xml",
        "data/mail_template_contrat.xml",
        "views/machine_intervention_views.xml",
        "views/machine_historique_views.xml",
        "views/stock_lot_views.xml",
        "views/product_category_views.xml",
        "views/sale_order_views.xml",
        "views/type_contrat_views.xml",
        "views/res_partner_views.xml",
        "report/contrat_templates.xml",
        "views/stock_picking_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_frontend": ["suivi_machines/static/src/js/contrat_portail.js"],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
