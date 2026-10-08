# -*- coding: utf-8 -*-
{
    "name": "Suivi des machines",
    "summary": "Dossier de chaque machine (numéro de série) : interventions, "
               "historique, santé et tableau de bord",
    "version": "20.0.1.12.0",
    "category": "Inventory/Inventory",
    "author": "Hamza Bassou",
    "license": "LGPL-3",
    "depends": ["stock", "sale_stock", "mail"],
    "data": [
        "security/ir.access.csv",
        "data/ir_sequence.xml",
        "data/produits_frais.xml",
        "views/machine_intervention_views.xml",
        "views/machine_historique_views.xml",
        "views/stock_lot_views.xml",
        "views/product_category_views.xml",
        "views/sale_order_views.xml",
        "views/stock_picking_views.xml",
        "views/menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
