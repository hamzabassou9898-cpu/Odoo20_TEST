# Nettoyage de la base de TEST, deux modes :
#   - par défaut : supprime les anciens contrats de location de test (numéros S…, créés avec l'ancienne
#     version). Les contrats LOC… sont gardés ;
#   - CIBLE=demo : supprime TOUT ce que demo_monroy.py a créé (contrats « DEMO », tickets « Démo »,
#     anciens contacts [TEST], machines TEST-…).
#
# Sécurités :
#   - refuse de tourner si la base n'est pas neutralisée (donc jamais sur la production) ;
#   - par défaut, AFFICHE seulement ce qui serait fait ; il faut NETTOYER=oui pour supprimer ;
#   - tout se fait en une seule transaction : en cas d'erreur, rien n'est enregistré.
import os

from odoo.exceptions import UserError

APPLIQUER = os.environ.get("NETTOYER") == "oui"
DEMO = os.environ.get("CIBLE") == "demo"

if not env["ir.config_parameter"].sudo().get_bool("database.is_neutralized"):
    raise SystemExit("ARRÊT : cette base n'est pas neutralisée (production ?). Rien n'a été fait.")

env = env(context=dict(env.context, lang="fr_CA", tracking_disable=True, mail_notrack=True,
                       disable_cancel_warning=True))
Commande = env["sale.order"].sudo()
Ticket = env["helpdesk.ticket"].sudo().with_context(active_test=False)
tickets = Ticket.browse()
if DEMO:
    test = env["res.partner"].sudo().with_context(active_test=False).search([("name", "=like", "[TEST]%")])
    tickets = Ticket.search(["|", "|", ("tag_ids.name", "=", "Démo"), ("name", "=like", "[TEST]%"),
                             ("partner_id", "in", test.ids)])
    contrats = Commande.search(["|", "|", ("client_order_ref", "=", "DEMO"), ("partner_id", "in", test.ids),
                                ("ticket_assistance_id", "in", tickets.ids)])
else:
    contrats = Commande.search([("type_commande", "=", "location"), ("name", "not like", "LOC%")])
print("\n=== %d %s à supprimer ===" % (len(contrats), "contrat(s) et bon(s) de démonstration" if DEMO
                                      else "ancien(s) contrat(s) de location"))
for c in contrats:
    print("  %-10s %-8s %s" % (c.name, c.state, c.partner_id.display_name))
if not contrats and not tickets:
    raise SystemExit("Rien à nettoyer.")


def encore_chez_client(ligne):
    """La machine (n° de série) de cette livraison est-elle toujours chez le client ? Non si elle est
    déjà en stock (revenue par un retour, un échange ou un ajustement d'inventaire) ou repartie depuis."""
    en_stock = any(q.quantity > 0 and q.location_id.usage in ("internal", "transit") for q in ligne.lot_id.quant_ids)
    return not en_stock and not env["stock.move.line"].sudo().search_count([
        ("lot_id", "=", ligne.lot_id.id), ("state", "=", "done"),
        ("location_id", "=", ligne.location_dest_id.id), ("date", ">", ligne.date)])


retours, a_supprimer, deja = [], env["stock.picking"].sudo(), env["stock.lot"]
for c in contrats:
    for p in c.picking_ids:
        if p.state != "done":
            a_supprimer |= p
        elif p.location_dest_id.usage == "customer":
            lignes = p.move_line_ids.filtered(lambda l: l.lot_id and l.lot_id not in deja and encore_chez_client(l))
            deja |= lignes.lot_id
            accessoires = p.move_ids.filtered(lambda m: not m.has_tracking or m.has_tracking == "none") \
                if not p.return_ids else env["stock.move"]
            if lignes or accessoires:
                retours.append((p, lignes, accessoires))

factures = contrats.invoice_ids
reprises = env["helpdesk.ticket"].sudo().search([("commande_reprise_id", "in", contrats.ids)]) \
    if "commande_reprise_id" in env["helpdesk.ticket"]._fields else env["helpdesk.ticket"]
documents = env["documents.document"].sudo().search(
    ["|"] * (len(contrats) - 1) + [("name", "ilike", c.name) for c in contrats]) \
    if "documents.document" in env else []

print("\nTransferts non faits à annuler et supprimer : %d" % len(a_supprimer))
print("Livraisons faites : retour en entrepôt de %d machine(s) encore chez le client"
      % sum(len(l) for _p, l, _a in retours))
for _p, lignes, _a in retours:
    for l in lignes:
        print("  %s  n° %s  (%s)" % (l.product_id.display_name, l.lot_id.name, _p.name))
print("Factures à supprimer : %d" % len(factures))
print("Tickets de reprise liés à supprimer : %d" % len(reprises))
print("Documents (PDF) à supprimer : %d" % len(documents))
if DEMO:
    print("Tickets de démonstration à supprimer : %d" % len(tickets))

if not APPLIQUER:
    raise SystemExit("\nAPERÇU seulement : rien n'a été modifié. Relancer avec NETTOYER=oui pour supprimer.")

# 1. Machines encore chez le client : retour en entrepôt (transfert de retour natif, avec l'historique)
def retourner(picking, lignes, accessoires):
    retour = picking._create_return()
    lots_par_produit = {}
    for move in retour.move_ids:
        suivi = move.has_tracking and move.has_tracking != "none"
        lots = lignes.filtered(lambda l: l.product_id == move.product_id).lot_id if suivi else None
        if (suivi and not lots) or (not suivi and move.product_id not in accessoires.product_id):
            move.unlink()
        elif suivi:
            move.product_uom_qty = len(lots)
            lots_par_produit[move.id] = lots
    if not retour.move_ids:
        retour.unlink()
        return None
    retour.action_confirm()
    for move in retour.move_ids:
        move.move_line_ids.unlink()
        for lot in lots_par_produit.get(move.id, [None]):
            env["stock.move.line"].create({
                "move_id": move.id, "picking_id": retour.id, "product_id": move.product_id.id,
                "lot_id": lot.id if lot else False, "quantity": 1 if lot else move.product_uom_qty,
                "location_id": move.location_id.id, "location_dest_id": move.location_dest_id.id,
                "uom_id": move.uom_id.id})
    retour.move_ids.picked = True
    retour._action_done()
    return retour


for picking, lignes, accessoires in retours:
    try:
        with env.cr.savepoint():   # un retour impossible n'empêche pas le reste du nettoyage
            retour = retourner(picking, lignes, accessoires)
        if retour:
            print("Retour fait : %s" % retour.name)
    except Exception as erreur:
        print("Retour impossible pour %s (machine laissée telle quelle) : %s" % (picking.name, erreur))

# 2. Transferts pas encore faits
if a_supprimer:
    a_supprimer.action_cancel()
    a_supprimer.unlink()

# 3. Factures (base de test : remises en brouillon puis supprimées)
for f in factures:
    if f.state == "posted":
        f.button_draft()
    f.with_context(force_delete=True).unlink()

# 4. Tickets de reprise, documents, puis les contrats eux-mêmes
reprises.unlink()
if documents:
    pieces = documents.attachment_id
    documents.unlink()
    pieces.exists().unlink()
for c in contrats:
    if c.state not in ("draft", "cancel"):
        c._action_cancel()
contrats.unlink()

if DEMO:
    # Tickets de demonstration (avec leurs interventions et bons), contacts et techniciens [TEST]
    # archivés, machines TEST-… retirées du stock (ajustement d'inventaire a 0)
    interventions = env["machine.intervention"].sudo().search([("ticket_id", "in", tickets.ids)])
    if "suivi.bon.intervention" in env:
        env["suivi.bon.intervention"].sudo().search(["|", ("ticket_id", "in", tickets.ids),
                                                     ("intervention_id", "in", interventions.ids)]).unlink()
    ouverts = env["stock.picking"].sudo().search([("ticket_assistance_id", "in", tickets.ids),
                                                 ("state", "not in", ("done", "cancel"))])
    ouverts.action_cancel()
    ouverts.unlink()
    interventions.unlink()
    tickets.exists().unlink()
    env["res.users"].sudo().search([("name", "=like", "[TEST]%")]).write({"active": False})
    test.write({"active": False})
    quants = env["stock.quant"].sudo().search([("lot_id.name", "=like", "TEST-%"), ("quantity", ">", 0),
                                               ("location_id.usage", "=", "internal")])
    if quants:
        quants.with_context(inventory_mode=True).write({"inventory_quantity": 0})
        quants.action_apply_inventory()
    print("Démo retirée : %d ticket(s), %d contact(s) [TEST] archivé(s), %d machine(s) TEST- sorties du stock"
          % (len(tickets), len(test), len(quants)))

env.cr.commit()
print("\nTERMINÉ : %d ancien(s) contrat(s) supprimé(s). Les contrats LOC… n'ont pas été touchés." % len(contrats))
