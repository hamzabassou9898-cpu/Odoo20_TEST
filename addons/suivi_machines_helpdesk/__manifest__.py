# -*- coding: utf-8 -*-
{
    "name": "Suivi des machines - Assistance",
    "summary": "Ticket d'assistance relié au code client et au dossier de la machine "
               "(série, location, entretien, historique, interventions)",
    "version": "20.0.1.19.0",
    "category": "Services/Helpdesk",
    "author": "Hamza Bassou",
    "license": "LGPL-3",
    "depends": ["suivi_machines", "helpdesk", "sale"],
    "data": [
        "security/ir.access.csv",
        "data/cron_reprise.xml",
        "data/entretien.xml",
        "views/helpdesk_ticket_views.xml",
        "views/stock_lot_views.xml",
        "views/liens_ticket_views.xml",
        "views/entretien_views.xml",
    ],
    "auto_install": False,
    "installable": True,
}
