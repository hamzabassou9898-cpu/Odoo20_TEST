# -*- coding: utf-8 -*-
{
    "name": "Ouverture de compte client Monroy",
    "summary": "Formulaire « Ouverture compte client » envoyé au client, rempli et signé en ligne, "
               "évalué puis approuvé par le bureau : le client est créé avec son code client",
    "version": "20.0.1.10.1",
    "category": "Sales/Sales",
    "author": "Volcan",
    "website": "https://volcan.ca/",
    "license": "LGPL-3",
    "depends": ["suivi_machines_pilotage", "portal", "contacts", "crm"],
    "data": [
        "security/ir.access.csv",
        "data/ir_sequence.xml",
        "data/mail_template.xml",
        "data/ir_cron.xml",
        "report/ouverture_templates.xml",
        "views/ouverture_compte_views.xml",
        "views/approuver_views.xml",
        "views/res_partner_views.xml",
        "views/crm_lead_views.xml",
        "views/portail_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "ouverture_compte_monroy/static/src/ouverture_portail.js",
        ],
    },
    "installable": True,
}
