# -*- coding: utf-8 -*-
{
    "name": "Phase 2 - Portail web des techniciens",
    "summary": "Les techniciens deviennent des utilisateurs portail (gratuits) : leur journée sur le portail web "
               "(livraisons, ramassages, entretiens, réparations)",
    "version": "20.0.1.1.0",
    "category": "Productivity",
    "author": "Hamza Bassou",
    "license": "LGPL-3",
    "depends": ["portal", "suivi_machines_pilotage"],
    "data": [
        "security/ir.access.csv",
        "data/portal_entry.xml",
        "views/res_partner_views.xml",
        "views/assignation_views.xml",
        "views/portail_templates.xml",
        "views/remplacer_views.xml",
    ],
    "installable": True,
}
