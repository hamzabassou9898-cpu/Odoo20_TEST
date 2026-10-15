# Données de DÉMONSTRATION pour la base de TEST Monroy : des contrats de location à chaque étape et des
# appels de service de chaque type, créés exactement comme Jose le ferait (mêmes règles, mêmes boutons).
# Tout ce qui est créé commence par « [TEST] » ou « TEST- » : facile à retrouver et à supprimer.
#
# Sécurités : refuse de tourner si la base n'est pas neutralisée (jamais sur la production) ;
# une seule transaction (en cas d'erreur, rien n'est enregistré) ; ne tourne qu'une fois.
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields

if not env["ir.config_parameter"].sudo().get_bool("database.is_neutralized"):
    raise SystemExit("ARRÊT : cette base n'est pas neutralisée (production ?). Rien n'a été fait.")

env = env(context=dict(env.context, lang="fr_CA", tracking_disable=True, skip_sms=True,
                       mail_create_nosubscribe=True, mail_notrack=True))
Partner, Order, Lot = env["res.partner"], env["sale.order"], env["stock.lot"]
if Partner.search_count([("name", "=like", "[TEST]%"), ("ref", "=like", "TEST%")]):
    raise SystemExit("Les données [TEST] existent déjà. Rien n'a été fait.")

aujourdhui = fields.Date.context_today(Order)
maintenant = fields.Datetime.now()
stock = env.ref("stock.warehouse0").lot_stock_id
# Petite signature (image PNG valide) pour les contrats « signés en ligne »
SIGNATURE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def heure(jours, h=9):
    """Date et heure (heure de Québec) dans N jours, convertie pour Odoo."""
    import pytz
    fuseau = pytz.timezone(env.user.tz or "America/Toronto")
    local = fuseau.localize(datetime.combine(aujourdhui + timedelta(days=jours), time(h)))
    return local.astimezone(pytz.utc).replace(tzinfo=None)


# ------------------------------------------------------------ techniciens (portail, gratuits)
User = env["res.users"].sudo()
techs = User.search([("share", "=", True), ("partner_id.est_technicien", "=", True)], limit=2) \
    if "est_technicien" in Partner._fields else User.browse()
for i in range(len(techs), 2):
    tech = User.with_context(no_reset_password=True).create({
        "name": "[TEST] Technicien %d" % (i + 1), "login": "test.technicien%d@exemple.invalid" % (i + 1),
        "group_ids": [(6, 0, env.ref("base.group_portal").ids)]})
    if "est_technicien" in Partner._fields:
        tech.partner_id.est_technicien = True
    techs |= tech
tech1, tech2 = techs[0], techs[1]

# ------------------------------------------------------------ machines de test (n° de série TEST-…)
produit = env["product.product"].search([("categ_id.suivi_machine", "=", True), ("tracking", "=", "serial"),
                                         ("is_storable", "=", True)], limit=1)
if not produit:
    categ = env["product.category"].search([("suivi_machine", "=", True)], limit=1) \
        or env["product.category"].create({"name": "Machines", "suivi_machine": True})
    produit = env["product.product"].create({"name": "[TEST] Machine à slush", "categ_id": categ.id,
                                             "is_storable": True, "tracking": "serial", "list_price": 0})
lots = Lot.create([{"name": "TEST-%04d" % n, "product_id": produit.id, "ref": "T%03d" % n}
                   for n in range(1, 13)])
for lot in lots:
    env["stock.quant"]._update_available_quantity(produit, stock, 1, lot_id=lot)
machines = iter(lots)

# ------------------------------------------------------------ clients fictifs
NOMS = ["Dépanneur des Érables", "Aréna du Lac", "Casse-croûte Chez Lili", "Cinéma Le Phare",
        "Bar laitier La Vache", "Salle de quilles Strike", "Camp Plein Air Boréal", "Resto Le Quai",
        "Épicerie du Village", "Comptoir à bonbons Sucré"]
clients = Partner.create([{
    "name": "[TEST] %s" % nom, "ref": "TEST%02d" % (i + 1), "is_company": True, "street": "%d, rue Principale" % (10 * (i + 1)),
    "city": "Québec", "zip": "G1A 1A1", "country_id": env.ref("base.ca").id,
    "email": "test%02d@exemple.invalid" % (i + 1), "phone": "418 555-01%02d" % (i + 1)} for i, nom in enumerate(NOMS)])
client = iter(clients)
types = {code: env.ref("suivi_machines.type_contrat_" + code)
         for code in ("location", "convention", "popcorn", "proprietaire")}


def contrat(type_code, debut_jours=-30, duree_mois=12, nb=1):
    """Contrat de location (ou bon de vente « Propriétaire ») avec ses machines, comme le bouton
    « Nouveau contrat de location »."""
    type_c = types[type_code]
    valeurs = {"partner_id": next(client).id, "type_contrat_id": type_c.id, "contrat_initiales": "TT",
               "order_line": [(0, 0, {"product_id": produit.id, "product_uom_qty": 1,
                                      "machine_lot_id": next(machines).id}) for _i in range(nb)]}
    if type_c.type_commande == "location":
        debut = heure(debut_jours)
        valeurs.update(date_debut_location=debut, date_fin_location=debut + relativedelta(months=duree_mois))
    return Order.with_context(default_type_commande=type_c.type_commande).create(valeurs)


def signer(order):
    """Le client signe en ligne : signature, puis confirmation (PDF signé rangé dans Documents)."""
    order.write({"signature": SIGNATURE, "signed_by": order.partner_id.name, "signed_on": maintenant})
    order.action_confirm()
    if hasattr(order, "_archiver_contrat_signe"):
        order._archiver_contrat_signe()
    return order


def livrer(order, tech, il_y_a_jours=20):
    """Le technicien livre : n° de série, technicien, prochain entretien, puis Valider."""
    livraison = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
    livraison.action_assign()   # réserve les n° de série choisis sur le contrat
    livraison.move_ids.picked = True
    livraison.write({"livreur_id": tech.id, "frequence_entretien": "12",
                     "prochain_entretien": aujourdhui + relativedelta(months=12, days=-il_y_a_jours)})
    livraison.button_validate()
    return livraison


def planifier_ramassage(livraison, tech, dans_jours):
    """Bouton « Planifier le ramassage » de la livraison."""
    Wiz = env["suivi.machines.planifier.ramassage"].with_context(default_picking_id=livraison.id)
    wiz = Wiz.create({"livreur_id": tech.id if tech else False, "date": heure(dans_jours, 13)})
    wiz.lot_ids = wiz.machines_livrees_ids
    return env["stock.picking"].browse(wiz.action_planifier()["res_id"])


def faire(picking, tech):
    picking.action_assign()
    picking.move_ids.picked = True
    picking.livreur_id = tech
    picking.button_validate()


resume = []
# 1. Devis pas encore envoyé
c = contrat("convention")
resume.append((c, "Devis en brouillon (pas encore envoyé)"))
# 2. Envoyé au client, en attente de sa signature
c = contrat("location")
c.action_quotation_sent()
resume.append((c, "Envoyé au client, en attente de signature"))
# 3. Signé ce mois, livraison à faire SANS technicien (carte « Tournées sans technicien »)
c = signer(contrat("convention", debut_jours=3))
resume.append((c, "Signé — livraison à faire, aucun technicien assigné"))
# 4. Signé, livraison planifiée avec un technicien (Planning + portail du technicien)
c = signer(contrat("popcorn", debut_jours=2))
c.picking_ids.write({"livreur_id": tech1.id, "scheduled_date": heure(1, 10)})
resume.append((c, "Signé — livraison planifiée demain avec %s" % tech1.name))
# 5. Livré : machine chez le client (2 machines)
c = signer(contrat("location", debut_jours=-20, nb=2))
livrer(c, tech1)
resume.append((c, "Livré — 2 machines en location chez le client"))
# 6. Livré puis ramassage planifié (fin de location dans 5 jours)
c = signer(contrat("convention", debut_jours=-360))
livraison = livrer(c, tech2, il_y_a_jours=355)
planifier_ramassage(livraison, tech2, 5)
resume.append((c, "Livré — ramassage planifié dans 5 jours avec %s" % tech2.name))
# 7. Livré puis ramassé : machine revenue en entrepôt
c = signer(contrat("location", debut_jours=-200, duree_mois=6))
livraison = livrer(c, tech1, il_y_a_jours=195)
faire(planifier_ramassage(livraison, tech1, -2), tech1)
resume.append((c, "Livré puis ramassé — machine revenue en entrepôt"))
# 8. Location dépassée : la fin est passée et la machine est encore chez le client
c = signer(contrat("location", debut_jours=-400))
livrer(c, tech2, il_y_a_jours=395)
resume.append((c, "Location DÉPASSÉE — machine à reprendre (À traiter)"))
# 9. Propriétaire : bon de vente livré (chaque appel de service se facture)
c = signer(contrat("proprietaire"))
livrer(c, tech1, il_y_a_jours=10)
resume.append((c, "Propriétaire — machine vendue et livrée"))

# ------------------------------------------------------------ appels de service
Ticket = env["helpdesk.ticket"]
chez = {o.partner_id: o.order_line.machine_lot_id[:1] for o, _t in resume if o.state == "sale"}
convention, proprio, depasse = resume[4][0], resume[8][0], resume[7][0]
tickets = Ticket.create([
    {"name": "[TEST] La machine coule", "partner_id": convention.partner_id.id, "type_demande": "reparation",
     "type_reparation": "coule", "lot_id": chez[convention.partner_id].id,
     "description": "Nouveau ticket, aucun technicien : à planifier."},
    {"name": "[TEST] Entretien annuel", "partner_id": depasse.partner_id.id, "type_demande": "entretien",
     "lot_id": chez[depasse.partner_id].id, "user_id": tech1.id, "date_planifiee": heure(0, 10)},
    {"name": "[TEST] Ne gèle pas", "partner_id": proprio.partner_id.id, "type_demande": "reparation",
     "type_reparation": "ne_gele_pas", "lot_id": chez[proprio.partner_id].id, "user_id": tech2.id,
     "date_planifiee": heure(-3, 14), "description": "Réparation EN RETARD (date passée). Propriétaire : facturable."},
    {"name": "[TEST] Machine à remplacer", "partner_id": convention.partner_id.id, "type_demande": "remplacement",
     "lot_id": chez[convention.partner_id].id, "description": "Compresseur mort : échanger la machine."},
    {"name": "[TEST] Commande de barbotine", "partner_id": proprio.partner_id.id, "type_demande": "commande",
     "description": "2 caisses de sirop framboise bleue."},
])
for t in tickets:
    resume.append((t, t.type_demande))

env.cr.commit()
print("\n=== Données de démonstration créées ===")
for rec, texte in resume:
    print("  %-12s %-34s %s" % (rec.display_name if rec._name == "helpdesk.ticket" else rec.name,
                                rec.partner_id.name, texte))
print("\nTechniciens : %s" % ", ".join(techs.mapped("name")))
print("Machines de test : TEST-0001 à TEST-0012 (%s)" % produit.display_name)
