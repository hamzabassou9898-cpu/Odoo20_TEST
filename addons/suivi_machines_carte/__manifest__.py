# -*- coding: utf-8 -*-
{
    "name": "Cartes & Google Maps",
    "summary": "Adresses liées à Google Maps, aperçu de carte, itinéraire des livreurs, cartes des tournées, "
               "des appels et du parc machines",
    "version": "20.0.1.3.0",
    "category": "Productivity",
    "author": "Hamza Bassou",
    "license": "LGPL-3",
    # web_map : vue « Carte » d'Odoo Enterprise (application Map / Carte)
    "depends": ["suivi_machines_pilotage", "web_map"],
    "data": [
        "security/ir.access.csv",
        "views/carte_views.xml",
        "views/itineraire_views.xml",
        "views/map_views.xml",
    ],
    "installable": True,
}
