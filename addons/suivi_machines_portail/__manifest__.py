# -*- coding: utf-8 -*-
{
    "name": "Suivi des machines - Portail des techniciens",
    "summary": "Les techniciens deviennent des utilisateurs portail (gratuits) : leur journée sur le portail web "
               "(livraisons, ramassages, entretiens, réparations)",
    "version": "20.0.1.25.0",
    "category": "Productivity",
    "author": "Volcan",
    "website": "https://volcan.ca/",
    "license": "LGPL-3",
    "depends": ["portal", "suivi_machines_pilotage"],
    "data": [
        "security/ir.access.csv",
        "data/portal_entry.xml",
        "views/res_partner_views.xml",
        "views/assignation_views.xml",
        "views/portail_templates.xml",
        "views/remplacer_views.xml",
        "views/note_technicien_views.xml",
        "views/bon_intervention_views.xml",
        "views/appel_web_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "suivi_machines_portail/static/src/appel_web/appel_web.scss",
        ],
    },
    "installable": True,
}
