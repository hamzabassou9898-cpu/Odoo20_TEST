# -*- coding: utf-8 -*-
"""Portail techniciens : toutes les taches d'un technicien dans une seule vue.

Livraisons et ramassages (transferts), tickets d'entretien et de reparation, interventions
planifiees sans ticket. Vue SQL en lecture : assigner un technicien ou changer la date
(glisser-deposer) modifie directement le document d'origine.
"""
from odoo import fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.misc import format_datetime

TYPES_TACHE = [
    ("livraison", "Livraison"),
    ("ramassage", "Ramassage"),
    ("entretien", "Entretien"),
    ("reparation", "Réparation"),
    ("installation", "Installation"),
    ("autre", "Autre"),
]
# Decalage des identifiants : un seul id par tache, quelle que soit sa source
SOURCES = {1: "picking_id", 2: "ticket_id", 3: "intervention_id"}
# Fuseau de Quebec : une tache est « en retard » quand sa journee est passee
FUSEAU = "America/Toronto"


class PortailTache(models.Model):
    _name = "portail.tache"
    _description = "Tâche de technicien"
    _auto = False
    _order = "date, id"
    _rec_name = "titre"

    _depends = {
        "stock.picking": ["livreur_id", "scheduled_date", "partner_id", "state", "name", "origin",
                          "type_tournee", "company_id"],
        "stock.move": ["picking_id", "product_id"],
        "helpdesk.ticket": ["user_id", "technicien_id", "date_planifiee", "partner_id", "stage_id", "name",
                            "est_entretien", "commande_reprise_id", "lot_id"],
        "helpdesk.stage": ["name"],
        "machine.intervention": ["user_id", "date", "partner_id", "state", "name", "type", "lot_id",
                                 "ticket_id", "company_id"],
    }

    type_tache = fields.Selection(TYPES_TACHE, "Type", readonly=True)
    date = fields.Datetime("Date prévue", readonly=True)
    technicien_id = fields.Many2one("res.users", "Technicien", readonly=True)
    partner_id = fields.Many2one("res.partner", "Client", readonly=True)
    titre = fields.Char("Tâche", readonly=True)
    reference = fields.Char("Référence", readonly=True)
    a_faire = fields.Boolean("À faire", readonly=True)
    etat_suivi = fields.Selection(
        [("fait", "Faite"), ("en_retard", "En retard"), ("a_faire", "À faire")], "Suivi", readonly=True,
        help="En retard : la journée prévue est passée et la tâche n'est pas faite.")
    lot_id = fields.Many2one("stock.lot", "Machine", readonly=True)
    company_id = fields.Many2one("res.company", "Société", readonly=True)
    picking_id = fields.Many2one("stock.picking", "Transfert", readonly=True)
    ticket_id = fields.Many2one("helpdesk.ticket", "Ticket", readonly=True)
    intervention_id = fields.Many2one("machine.intervention", "Intervention", readonly=True)

    date_affichage = fields.Char("Quand", compute="_compute_affichage")
    route = fields.Char("Adresse", compute="_compute_affichage")
    machines = fields.Char("Machines", compute="_compute_affichage")
    accessoires = fields.Char("Accessoires", compute="_compute_affichage")
    statut = fields.Char("Statut", compute="_compute_affichage")
    tag_ids = fields.Many2many("helpdesk.tag", string="Étiquettes", compute="_compute_affichage",
                               help="Étiquettes du ticket (entretien en retard, problème signalé...).")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        ferme = "(résolu|resolu|annul|clôtur|clotur)"
        societe_ticket = SQL("t.company_id") if "company_id" in self.env["helpdesk.ticket"]._fields \
            else SQL("NULL::integer")
        self.env.cr.execute(SQL("""
            CREATE OR REPLACE VIEW %(table)s AS (
              SELECT u.*,
                     CASE WHEN NOT u.a_faire THEN 'fait'
                          WHEN (u.date AT TIME ZONE 'UTC' AT TIME ZONE %(fuseau)s)::date
                               < (now() AT TIME ZONE %(fuseau)s)::date THEN 'en_retard'
                          ELSE 'a_faire' END AS etat_suivi
                FROM (
                SELECT p.id * 10 + 1 AS id, p.type_tournee AS type_tache, p.scheduled_date AS date,
                       p.livreur_id AS technicien_id, p.partner_id, p.name AS titre, p.origin AS reference,
                       p.state NOT IN ('done', 'cancel') AS a_faire, NULL::integer AS lot_id, p.company_id,
                       p.id AS picking_id, NULL::integer AS ticket_id, NULL::integer AS intervention_id
                  FROM stock_picking p
                 WHERE p.type_tournee IN ('livraison', 'ramassage') AND p.state != 'cancel'
                   AND (p.livreur_id IS NOT NULL OR EXISTS (
                        SELECT 1 FROM stock_move m
                          JOIN product_product pp ON pp.id = m.product_id
                          JOIN product_template pt ON pt.id = pp.product_tmpl_id
                          JOIN product_category c ON c.id = pt.categ_id
                         WHERE m.picking_id = p.id AND c.suivi_machine))
                UNION ALL
                SELECT t.id * 10 + 2, CASE WHEN t.est_entretien THEN 'entretien' ELSE 'reparation' END,
                       COALESCE(t.date_planifiee, t.create_date), COALESCE(t.user_id, t.technicien_id),
                       t.partner_id, t.name, '#' || t.id, COALESCE(s.name::text, '') !~* %(ferme)s,
                       t.lot_id, %(societe_ticket)s, NULL, t.id, NULL
                  FROM helpdesk_ticket t
             LEFT JOIN helpdesk_stage s ON s.id = t.stage_id
                 WHERE t.commande_reprise_id IS NULL
                   AND COALESCE(s.name::text, '') !~* 'annul'
                UNION ALL
                SELECT i.id * 10 + 3, CASE WHEN i.type IN ('entretien', 'installation') THEN i.type
                                           WHEN i.type IN ('bris', 'reparation', 'remplacement') THEN 'reparation'
                                           ELSE 'autre' END,
                       i.date, i.user_id, i.partner_id, i.name, NULL, i.state = 'planifie', i.lot_id, i.company_id,
                       NULL, NULL, i.id
                  FROM machine_intervention i
                 WHERE i.state IN ('planifie', 'fait') AND i.ticket_id IS NULL AND i.type != 'ramassage'
                ) u
            )""", table=SQL.identifier(self._table), ferme=ferme,
            societe_ticket=societe_ticket, fuseau=FUSEAU))

    def _source(self):
        self.ensure_one()
        return self[SOURCES[self.id % 10]]

    def _compute_affichage(self):
        # Lecture des documents en sudo : un technicien voit ses taches meme sans droits sur les stocks
        for tache in self:
            src = tache.sudo()
            date = format_datetime(self.env, src.date, dt_format="EEE d MMM '·' HH 'h' mm") if src.date else ""
            vals = {"date_affichage": date[:1].upper() + date[1:], "accessoires": False,
                    "tag_ids": [(6, 0, src.ticket_id.tag_ids.ids)]}
            lot = src.lot_id
            vals["machines"] = ("%s (%s)" % (lot.ref, lot.name) if lot.ref else lot.name) if lot else False
            if src.picking_id:
                p = src.picking_id
                vals.update(route=p.route, machines=p.machines_tournee, accessoires=p.accessoires_tournee,
                            statut=dict(p._fields["state"]._description_selection(self.env)).get(p.state))
            elif src.ticket_id:
                t = src.ticket_id
                vals.update(route=", ".join(l.strip() for l in (t.adresse_commerce or "").splitlines() if l.strip()) or False,
                            statut=t.stage_id.name or self.env._("À faire"))
            else:
                i = src.intervention_id
                vals.update(route=i.route,
                            statut=dict(i._fields["state"]._description_selection(self.env)).get(i.state))
            tache.update(vals)

    def write(self, vals):
        """Glisser-deposer (technicien, date) : on modifie le document d'origine."""
        if not self.env.user.has_group("suivi_machines_pilotage.group_pilotage"):
            raise UserError(self.env._("Seul le pilotage peut réassigner ou déplacer une tâche."))
        autres = set(vals) - {"technicien_id", "date"}
        if autres:
            raise UserError(self.env._("Modifiez la tâche depuis son document (transfert, ticket ou intervention)."))
        champs = {
            "picking_id": {"technicien_id": "livreur_id", "date": "scheduled_date"},
            "ticket_id": {"technicien_id": "user_id", "date": "date_planifiee"},
            "intervention_id": {"technicien_id": "user_id", "date": "date"},
        }
        for tache in self:
            correspondance = champs[SOURCES[tache.id % 10]]
            valeurs = {correspondance[cle]: valeur for cle, valeur in vals.items()}
            if "date" in vals and not vals["date"]:
                valeurs.pop(correspondance["date"])
            tache._source().write(valeurs)
        self.env.flush_all()
        self.invalidate_model()
        return True

    def action_ouvrir(self):
        self.ensure_one()
        source = self._source()
        return {"type": "ir.actions.act_window", "res_model": source._name, "res_id": source.id,
                "views": [(False, "form")], "target": "current"}
