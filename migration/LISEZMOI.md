# Migration vers Odoo.sh

1. Sur ton Mac (Odoo local demarre) : `python3 exporter_vers_odoo_sh.py`
   -> genere `contacts_odoo.py` et `inventaire_odoo.py` (toutes les donnees dedans).
2. Dans chaque fichier genere, remplir le bloc "ODOO.SH" : URL, DB, USERNAME, PASSWORD (cle API).
3. Sur Odoo.sh, installer d'abord les modules : Contacts, Ventes, Inventaire, Facturation
   (+ `suivi_machines` depuis le depot GitHub du projet).
4. Lancer `python3 contacts_odoo.py` PUIS `python3 inventaire_odoo.py`.

Relancables sans risque (identifiants externes `migration_contacts.*` / `migration_inventaire.*`).
Non migre : commandes, factures, livraisons (historique) ; taxes des produits (celles d'Odoo.sh s'appliquent).
