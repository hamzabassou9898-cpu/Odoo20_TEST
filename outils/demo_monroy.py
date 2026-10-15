# Données de DÉMONSTRATION pour la base de TEST Monroy : beaucoup de contrats et d'appels de service,
# à TOUTES les étapes, de A à Z, créés exactement comme Jose le ferait (mêmes règles, mêmes boutons) :
# devis, envoi, signature, livraison assignée et validée, tickets planifiés, en retard, entretiens validés,
# échange de machine, frais facturés, ramassages...
# Les contrats sont faits sur les CLIENTS EXISTANTS de la base, depuis l'application Location (dates
# d'enlèvement et de retour) quand elle est installée, comme le menu « Nouveau contrat de location ».
# Repères pour les retrouver (et les supprimer avec nettoyage_anciens_contrats.py, CIBLE=demo) :
# référence client « DEMO » sur les contrats, étiquette « Démo » sur les tickets, machines TEST-….
#
# Sécurités : refuse de tourner si la base n'est pas neutralisée (jamais sur la production) ;
# chaque exemple est indépendant (s'il échoue, il est annulé et affiché, les autres continuent).
from datetime import datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import fields

if not env["ir.config_parameter"].sudo().get_bool("database.is_neutralized"):
    raise SystemExit("ARRÊT : cette base n'est pas neutralisée (production ?). Rien n'a été fait.")

env = env(context=dict(env.context, lang="fr_CA", tracking_disable=True, skip_sms=True,
                       mail_create_nosubscribe=True, mail_notrack=True))
Partner, Order, Lot, Ticket = env["res.partner"], env["sale.order"], env["stock.lot"], env["helpdesk.ticket"]
aujourdhui = fields.Date.context_today(Order)
maintenant = fields.Datetime.now()
entrepot = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
stock = entrepot.lot_stock_id
fuseau = pytz.timezone(env.user.tz or "America/Toronto")
# Signature (image PNG valide) pour les contrats « signés en ligne »
SIGNATURE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def heure(jours, h=9):
    """Date et heure (heure de Québec) dans N jours (négatif = passé), convertie pour Odoo."""
    local = fuseau.localize(datetime.combine(aujourdhui + timedelta(days=jours), time(h)))
    return local.astimezone(pytz.utc).replace(tzinfo=None)


# ------------------------------------------------------------ techniciens (portail, gratuits)
User = env["res.users"].sudo()
techs = User.search([("share", "=", True), ("partner_id.est_technicien", "=", True)], limit=3) \
    if "est_technicien" in Partner._fields else User.browse()
for i in range(len(techs), 1):   # aucun technicien portail : on en crée un
    tech = User.with_context(no_reset_password=True).create({
        "name": "Technicien démo", "login": "technicien.demo@exemple.invalid",
        "group_ids": [(6, 0, env.ref("base.group_portal").ids)]})
    if "est_technicien" in Partner._fields:
        tech.partner_id.est_technicien = True
    techs |= tech
tech_tour = [techs[i % len(techs)] for i in range(100)]

# ------------------------------------------------------------ machines de test (n° de série TEST-…)
produits = env["product.product"].search([("categ_id.suivi_machine", "=", True), ("tracking", "=", "serial"),
                                          ("is_storable", "=", True)], limit=3)
if not produits:
    categ = env["product.category"].search([("suivi_machine", "=", True)], limit=1) \
        or env["product.category"].create({"name": "Machines", "suivi_machine": True})
    produits = env["product.product"].create({"name": "Machine à slush (démo)", "categ_id": categ.id,
                                              "is_storable": True, "tracking": "serial", "list_price": 0})
deja = Lot.search_count([("name", "=like", "TEST-%")])
lots = Lot.create([{"name": "TEST-%04d" % (deja + n), "product_id": produits[n % len(produits)].id,
                    "ref": "T%03d" % (deja + n)} for n in range(1, 61)])
for lot in lots:
    env["stock.quant"]._update_available_quantity(lot.product_id, stock, 1, lot_id=lot)
reserve = list(lots)


def machine(produit=None):
    lot = next(l for l in reserve if not produit or l.product_id == produit)
    reserve.remove(lot)
    return lot


# ------------------------------------------------------------ clients existants (sans contrat en cours)
avec_contrat = Order.search([("state", "!=", "cancel"), "|", ("type_commande", "=", "location"),
                             ("type_contrat_id", "!=", False)]).partner_id.commercial_partner_id
exclus = avec_contrat | env.company.partner_id | User.search([]).partner_id
# Clients = fiches principales (pas des personnes rattachées) qui ont un code client
file_clients = list(Partner.search([("parent_id", "=", False), ("ref", "!=", False), ("id", "not in", exclus.ids),
                                    ("name", "not like", "[TEST]")], order="customer_rank desc, name", limit=30))
if len(file_clients) < 30:
    raise SystemExit("ARRÊT : il faut au moins 30 clients avec un code client et sans contrat dans Contacts ; "
                     "trouvés : %d. Rien n'a été fait." % len(file_clients))
types = {code: env.ref("suivi_machines.type_contrat_" + code)
         for code in ("location", "convention", "popcorn", "proprietaire")}


LOCATION_APP = "is_rental_order" in Order._fields   # application Location (Enterprise) installée


def contrat(type_code, debut_jours=-30, duree_mois=12, nb=1):
    """Contrat de location (application Location : dates d'enlèvement et de retour) ou bon de vente
    « Propriétaire », comme le menu « Nouveau contrat de location »."""
    type_c = types[type_code]
    produit = produits[len(file_clients) % len(produits)]
    location = type_c.type_commande == "location"
    lignes = []
    for _i in range(nb):
        ligne = {"product_id": produit.id, "product_uom_qty": 1, "machine_lot_id": machine(produit).id}
        if location and LOCATION_APP and "is_rental" in env["sale.order.line"]._fields \
                and getattr(produit, "rent_ok", False):
            ligne["is_rental"] = True
        lignes.append((0, 0, ligne))
    valeurs = {"partner_id": file_clients.pop(0).id, "type_contrat_id": type_c.id, "contrat_initiales": "TT",
               "saison": "annee", "client_order_ref": "DEMO", "order_line": lignes}
    contexte = {"default_type_commande": type_c.type_commande}
    if location:
        debut = heure(debut_jours)
        fin = debut + relativedelta(months=duree_mois)
        if LOCATION_APP:
            valeurs.update(is_rental_order=True, rental_start_date=debut, rental_return_date=fin)
            contexte.update(in_rental_app=True, default_is_rental_order=True)
        else:
            valeurs.update(date_debut_location=debut, date_fin_location=fin)
    return Order.with_context(**contexte).create(valeurs)


def signer(order):
    """Le client signe en ligne : signature, puis confirmation (PDF signé rangé dans Documents)."""
    order.write({"signature": SIGNATURE, "signed_by": order.partner_id.name, "signed_on": maintenant})
    order.action_confirm()
    if hasattr(order, "_archiver_contrat_signe"):
        order._archiver_contrat_signe()
    return order


def livrer(order, tech, il_y_a_jours=20, frequence="12"):
    """Jose assigne le technicien, le n° de série est réservé, prochain entretien, puis Valider."""
    livraison = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
    livraison.write({"livreur_id": tech.id, "scheduled_date": heure(-il_y_a_jours, 10),
                     "frequence_entretien": frequence,
                     "prochain_entretien": aujourdhui + relativedelta(months=int(frequence), days=-il_y_a_jours)})
    livraison.action_assign()
    livraison.move_ids.picked = True
    livraison.button_validate()
    return livraison


def planifier_ramassage(livraison, tech, dans_jours):
    """Bouton « Planifier le ramassage » de la livraison."""
    wiz = env["suivi.machines.planifier.ramassage"].with_context(default_picking_id=livraison.id).create(
        {"livreur_id": tech.id if tech else False, "date": heure(dans_jours, 13)})
    wiz.lot_ids = wiz.machines_livrees_ids
    return env["stock.picking"].browse(wiz.action_planifier()["res_id"])


def valider(picking, tech):
    picking.action_assign()
    picking.move_ids.picked = True
    picking.livreur_id = tech
    picking.button_validate()


def resoudre(ticket):
    resolu = ticket._etape_contenant("résolu", ticket.team_id if "team_id" in ticket._fields else None)
    if resolu:
        ticket.stage_id = resolu


resume, erreurs = [], []


def exemple(texte, fonction):
    """Un exemple complet : s'il échoue, seul lui est annulé et l'erreur est affichée."""
    try:
        with env.cr.savepoint():
            rec = fonction()
        resume.append((rec, texte))
        return rec
    except Exception as erreur:
        erreurs.append("%s : %s" % (texte, erreur))
        return None


# ============================================================ CONTRATS, de A à Z
for code in ("convention", "location", "popcorn"):
    exemple("Devis en brouillon (pas encore envoyé)", lambda code=code: contrat(code))
for code in ("convention", "location"):
    def _envoye(code=code):
        c = contrat(code)
        c.action_quotation_sent()
        return c
    exemple("Envoyé au client, en attente de sa signature", _envoye)
for code in ("convention", "popcorn"):
    exemple("Signé ce mois — livraison à faire, AUCUN technicien (À traiter)",
            lambda code=code: signer(contrat(code, debut_jours=3)))
for i, code in enumerate(("location", "convention", "convention")):
    def _planifiee(code=code, i=i):
        c = signer(contrat(code, debut_jours=i + 1))
        c.picking_ids.write({"livreur_id": tech_tour[i].id, "scheduled_date": heure(i + 1, 9 + 2 * i)})
        return c
    exemple("Signé — livraison planifiée (Planning + portail du technicien)", _planifiee)
livres = []
for i, (code, nb) in enumerate((("convention", 1), ("convention", 2), ("location", 1), ("location", 2),
                                ("popcorn", 1), ("convention", 1), ("location", 1), ("convention", 1))):
    def _livre(code=code, nb=nb, i=i):
        c = signer(contrat(code, debut_jours=-(20 + 15 * i), nb=nb))
        livrer(c, tech_tour[i], il_y_a_jours=18 + 15 * i, frequence=("6", "12")[i % 2])
        return c
    c = exemple("Livré et validé — %d machine(s) en location chez le client" % nb, _livre)
    if c:
        livres.append(c)


def _ramassage_planifie():
    c = signer(contrat("convention", debut_jours=-360))
    planifier_ramassage(livrer(c, tech_tour[1], il_y_a_jours=355), tech_tour[1], 4)
    return c


exemple("Fin de location — ramassage planifié dans 4 jours", _ramassage_planifie)


def _ramassage_sans_tech():
    c = signer(contrat("location", debut_jours=-350))
    planifier_ramassage(livrer(c, tech_tour[2], il_y_a_jours=345), None, 2)
    return c


exemple("Fin de location — ramassage planifié SANS technicien (À traiter)", _ramassage_sans_tech)
for i in range(2):
    def _ramasse(i=i):
        c = signer(contrat("location", debut_jours=-200 - 30 * i, duree_mois=6))
        livraison = livrer(c, tech_tour[i], il_y_a_jours=195 + 30 * i)
        valider(planifier_ramassage(livraison, tech_tour[i], -3 - i), tech_tour[i])
        return c
    exemple("Terminé — livré puis ramassé, machine revenue en entrepôt", _ramasse)
for i in range(2):
    def _depasse(i=i):
        c = signer(contrat("location", debut_jours=-400 - 20 * i))
        livrer(c, tech_tour[i + 1], il_y_a_jours=395 + 20 * i)
        return c
    exemple("Location DÉPASSÉE — machine encore chez le client (À traiter)", _depasse)
proprios = []
for i in range(2):
    def _proprio(i=i):
        c = signer(contrat("proprietaire"))
        livrer(c, tech_tour[i], il_y_a_jours=10 + 5 * i)
        return c
    c = exemple("Propriétaire — machine vendue et livrée", _proprio)
    if c:
        proprios.append(c)


# ============================================================ APPELS DE SERVICE
def chez(order):
    return order.order_line.machine_lot_id.filtered(lambda l: l.machine_statut not in ("entrepot",))[:1] \
        or order.order_line.machine_lot_id[:1]


TAG_DEMO = env["helpdesk.tag"].search([("name", "=", "Démo")], limit=1) \
    or env["helpdesk.tag"].create({"name": "Démo"})


def ticket(order, nom, type_demande, **valeurs):
    return Ticket.create(dict({"name": nom, "partner_id": order.partner_id.id, "type_demande": type_demande,
                               "lot_id": chez(order).id, "tag_ids": [(4, TAG_DEMO.id)]}, **valeurs))


cibles = livres + proprios
for i, (probleme, nom) in enumerate((("coule", "La machine coule"), ("bruit", "Fait du bruit"),
                                     ("ne_tourne_pas", "Ne tourne pas"), ("gele_trop", "Gèle trop"))):
    exemple("Réparation — nouveau, aucun technicien (à planifier)",
            lambda i=i, probleme=probleme, nom=nom: ticket(cibles[i % len(cibles)], nom, "reparation",
                                                            type_reparation=probleme))
for i in range(4):
    exemple("Réparation — planifiée (aujourd'hui / demain)",
            lambda i=i: ticket(cibles[(i + 2) % len(cibles)], "Ne gèle pas", "reparation",
                               type_reparation="ne_gele_pas", user_id=tech_tour[i].id,
                               date_planifiee=heure(i % 2, 9 + 2 * i)))
for i in range(2):
    exemple("Réparation — EN RETARD (date passée)",
            lambda i=i: ticket(cibles[(i + 5) % len(cibles)], "Coule sous le comptoir", "reparation",
                               type_reparation="coule", user_id=tech_tour[i + 1].id, date_planifiee=heure(-3 - i, 14)))
for i in range(3):
    exemple("Entretien — planifié",
            lambda i=i: ticket(livres[i % len(livres)], "Entretien annuel", "entretien",
                               user_id=tech_tour[i].id, date_planifiee=heure(i, 10)))
for i in range(2):
    def _entretien_fait(i=i):
        t = ticket(livres[(i + 3) % len(livres)], "Entretien fait", "entretien", user_id=tech_tour[i].id,
                   date_planifiee=heure(-1, 10))
        wiz = env["suivi.machines.valider.entretien"].with_context(default_ticket_id=t.id).create(
            {"note": "Nettoyage complet, joints changés."})
        wiz.action_valider()
        resoudre(t)
        return t
    exemple("Entretien — FAIT et validé (prochain entretien recalculé)", _entretien_fait)


def _remplacement_planifie():
    c = livres[1 % len(livres)]
    return ticket(c, "Compresseur faible, à remplacer", "remplacement", user_id=tech_tour[2].id,
                  date_planifiee=heure(2, 9))


exemple("Machine à remplacer — planifiée", _remplacement_planifie)


def _echange_fait():
    c = livres[2 % len(livres)]
    ancienne = chez(c)
    t = ticket(c, "Machine morte, échange", "remplacement", user_id=tech_tour[0].id, date_planifiee=heure(-1, 9))
    t.lot_remplacement_id = machine(ancienne.product_id)
    action = t.action_echanger_machine()
    livraison = env["stock.picking"].browse(action["res_id"])
    livraison.write({"frequence_entretien": "12", "prochain_entretien": aujourdhui + relativedelta(months=12)})
    valider(livraison, tech_tour[0])
    return t


exemple("Machine à remplacer — ÉCHANGE FAIT (ancienne en entrepôt, nouvelle chez le client)", _echange_fait)
for i, c in enumerate(proprios):
    def _facture(c=c, i=i):
        t = ticket(c, "Réparation chez un propriétaire", "reparation", type_reparation="ne_gele_pas",
                   user_id=tech_tour[i].id, date_planifiee=heure(-2, 13))
        t.action_facturer_frais()   # bon de vente des frais selon le contrat (déplacement + taux horaire)
        resoudre(t)
        return t
    exemple("Propriétaire — réparation faite, frais à facturer (bon de vente créé)", _facture)
for i in range(2):
    exemple("Commande de produits",
            lambda i=i: ticket(cibles[(i + 1) % len(cibles)], "Commande de sirop", "commande",
                               description="2 caisses de sirop framboise bleue, 1 caisse cola."))
exemple("Ajuster un contrat",
        lambda: ticket(livres[0], "Ajouter une 2e machine pour l'été", "ajustement"))

env.cr.commit()
print("\n=== Données de démonstration créées : %d exemples ===" % len(resume))
for rec, texte in resume:
    nom = rec.name if rec._name == "sale.order" else rec.display_name
    print("  %-36s %-34s %s" % ((nom or "")[:36], (rec.partner_id.name or "")[:34], texte))
print("\nTechniciens : %s" % ", ".join(techs.mapped("name")))
print("Machines de test : %s à %s" % (lots[0].name, lots[-1].name))
if erreurs:
    print("\n%d exemple(s) n'ont pas pu être créés (les autres sont faits) :" % len(erreurs))
    for e in erreurs:
        print("  - " + e)
