# -*- coding: utf-8 -*-
{
    "name": "Pilotage",
    "summary": "Tableau de bord du suivi des machines : entretiens, locations, reprises, bris, facturation",
    "version": "20.0.1.19.0",
    "category": "Productivity",
    "author": "Hamza Bassou",
    "license": "LGPL-3",
    "depends": ["suivi_machines_helpdesk", "suivi_sage"],
    "data": [
        "security/groups.xml",
        "security/ir.access.csv",
        "data/indicateurs.xml",
        "views/pilotage_views.xml",
        "views/portail_views.xml",
        "views/portail_techniciens_views.xml",
        "views/indicateur_views.xml",
        "views/donnees_test_views.xml",
        "views/ajuster_contrat_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "suivi_machines_pilotage/static/src/tableau_moderne/*",
        ],
    },
    "application": True,
    "installable": True,
}
