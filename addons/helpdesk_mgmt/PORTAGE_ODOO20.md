# Portage de helpdesk_mgmt (OCA 19.0) vers Odoo 20

Source : https://github.com/OCA/helpdesk (branche 19.0), licence AGPL-3.
La branche 20.0 d'OCA est encore vide : portage local en attendant la version officielle.

Changements :
- securite : `ir.model.access.csv` + regles `ir.rule` -> `security/ir.access.csv`
  (Odoo 20 fusionne droits et regles dans `ir.access`)
- `mail.thread.cc` n'existe plus -> `mail.tracking.duration.mixin` (inclut `mail.thread`)
  et champ `email_cc` ajoute sur le ticket
- portail : carte "Tickets" de l'accueil `/my` retiree (nouveau systeme de cartes) ;
  `/my/tickets` et `/new/ticket` fonctionnent
- portail : appel a `ir.rule._compute_domain` retire (search applique deja les droits)
- JS : `publicWidget` -> `Interaction` ; Owl 3 (`proxy` au lieu de `useState`,
  plus de `static props`, `this.` dans les gabarits) ; `t-esc` -> `t-out`

Quand OCA publiera la version 20.0 officielle, la remplacer par celle-ci.
