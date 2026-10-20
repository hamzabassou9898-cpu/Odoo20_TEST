# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


# Periode de location obligatoire pour confirmer un contrat de location
PERIODE_TEST = (fields.Datetime.to_datetime("2026-01-01 12:00:00"), fields.Datetime.to_datetime("2027-12-31 12:00:00"))


@tagged("post_install", "-at_install")
class TestPilotage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, skip_sms=True))
        cls.client = cls.env["res.partner"].create({"name": "Client pilotage", "ref": "PIL1"})
        categ = cls.env["product.category"].create({"name": "Machines (pilotage)", "suivi_machine": True})
        cls.produit = cls.env["product.product"].create({
            "name": "Machine pilotage", "categ_id": categ.id, "is_storable": True, "tracking": "serial"})
        cls.lot = cls.env["stock.lot"].create({"name": "PIL-1", "product_id": cls.produit.id})
        Interv = cls.env["machine.intervention"]
        Interv.create({"lot_id": cls.lot.id, "type": "installation", "state": "fait", "partner_id": cls.client.id})
        Interv.create({"lot_id": cls.lot.id, "type": "entretien", "state": "fait", "partner_id": cls.client.id,
                       "date": fields.Datetime.now() - relativedelta(months=13)})
        Interv.create({"lot_id": cls.lot.id, "type": "bris", "partner_id": cls.client.id,
                       "frais_ids": [(0, 0, {"product_id": cls.produit.id, "prix_unitaire": 80})]})

    def _ind(self, code):
        return self.env.ref("suivi_machines_pilotage.indicateur_" + code)

    def test_menu_locations(self):
        """Locations : « Nouveau contrat de location » en premier, « Types de contrat » à la fin."""
        menus = self.env.ref("suivi_machines_pilotage.menu_pilotage_locations").child_id.sorted("sequence")
        self.assertEqual(menus[0], self.env.ref("suivi_machines_pilotage.menu_pilotage_nouveau_contrat"))
        self.assertEqual(menus[-1], self.env.ref("suivi_machines_pilotage.menu_pilotage_types_contrat"))
        action = self.env.ref("suivi_machines_pilotage.action_pilotage_nouveau_contrat").run()
        self.assertEqual((action["res_model"], action["view_mode"]), ("sale.order", "form"))
        nouveau = self.env["sale.order"].with_context(**action["context"]).create({"partner_id": self.client.id})
        self.assertEqual(nouveau.type_commande, "location")
        self.assertTrue(nouveau.name.startswith("LOC"), nouveau.name)
        # Periode proposee : aujourd'hui -> dans un an (modifiable)
        self.assertTrue(nouveau.date_debut_location and nouveau.date_fin_location)
        self.assertEqual(nouveau.date_fin_location.year - nouveau.date_debut_location.year, 1)

    def test_menus_inventaire_et_appels(self):
        """Inventaire : Parc machines, mouvements de stock et inventaire physique ; Appels de service ouvre
        la vue de l'Assistance."""
        self.assertEqual(self.env.ref("suivi_machines_pilotage.menu_pilotage_parc").name, "Inventaire")
        self.assertEqual(self.env.ref("suivi_machines_pilotage.menu_pilotage_vue_ensemble").name, "Parc machines")
        actions = self.env.ref("suivi_machines_pilotage.menu_pilotage_parc").child_id.mapped("action")
        self.assertIn(self.env.ref("stock.stock_move_line_action"), actions)
        self.assertIn(self.env.ref("stock.action_view_inventory_tree"), actions)
        self.assertIn(self.env.ref("stock.action_picking_tree_outgoing"), actions, "Livraisons")
        action = self.env.ref("suivi_machines_pilotage.action_pilotage_appels_assistance").run()
        self.assertEqual(action["res_model"], "helpdesk.ticket")
        # Action d'equipe avec « active_id » (comme l'Assistance) : evaluee pour l'equipe, sans erreur
        equipe = self.client   # seul son id compte ici
        brute = {"context": "{'default_team_id': active_id}", "domain": "[('team_id', '=', active_id)]"}
        pret = self.env["pilotage.indicateur"]._sans_active_id(dict(brute), equipe)
        self.assertEqual(pret["context"], {"default_team_id": equipe.id})
        self.assertEqual(pret["domain"], [("team_id", "=", equipe.id)])

    def test_barre_de_menus(self):
        """Barre du Pilotage : Contacts avant Appels de service ; Ventes puis CRM avant Locations (vues natives)."""
        racine = self.env.ref("suivi_machines_pilotage.menu_pilotage_root")
        noms = racine.child_id.sorted("sequence").mapped("name")
        self.assertEqual(noms, ["Tableau de bord", "Contacts", "Appels de service", "Portail techniciens", "Planning",
                                "Ventes", "CRM", "Locations", "Facturation", "Inventaire"])
        for xmlid, action in (("menu_pilotage_contacts", "contacts.action_contacts"),
                              ("menu_pilotage_ventes", "sale.action_quotations_with_onboarding"),
                              ("menu_pilotage_crm", "crm.crm_lead_action_pipeline")):
            self.assertEqual(self.env.ref("suivi_machines_pilotage." + xmlid).action, self.env.ref(action), xmlid)
        # Contacts : vue « Hiérarchie » par défaut
        action = self.env.ref("contacts.action_contacts")
        self.assertTrue(action.view_mode.startswith("hierarchy,"))
        self.assertEqual(action.views[0][1], "hierarchy", "Contacts doit s'ouvrir sur la vue Hiérarchie")

    def test_planning_ouvre_le_ticket(self):
        """Planning : une tache d'intervention ouvre le ticket de la machine (jamais l'intervention quand un
        ticket existe)."""
        interv = self.env["machine.intervention"].create({
            "lot_id": self.lot.id, "type": "entretien", "state": "planifie", "partner_id": self.client.id,
            "user_id": self.env.user.id, "date": fields.Datetime.now()})
        Tache = self.env["portail.tache"]
        tache = Tache.search([("intervention_id", "=", interv.id)])
        self.assertTrue(tache)
        self.assertEqual(tache.action_ouvrir()["res_model"], "machine.intervention", "rien d'autre a ouvrir")
        ticket = self.env["helpdesk.ticket"].create({"name": "Entretien machine", "partner_id": self.client.id,
                                                     "lot_id": self.lot.id})
        action = tache.action_ouvrir()
        self.assertEqual((action["res_model"], action["res_id"]), ("helpdesk.ticket", ticket.id))

    def test_compteurs(self):
        self.assertGreaterEqual(self._ind("entretien_retard").valeur, 1)
        facturer = self._ind("a_facturer")
        self.assertGreaterEqual(facturer.valeur, 1)
        self.assertIn("Total", facturer.sous_titre)

    def test_livraisons_et_ramassages_faits(self):
        """Carte « Livraisons & ramassages faits ce mois » : une étiquette par sens, cliquable."""
        stock = self.env.ref("stock.stock_location_stock")
        clients = self.env.ref("stock.stock_location_customers")
        entrepot = self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1)
        lot = self.env["stock.lot"].create({"name": "PIL-LIV", "product_id": self.produit.id})
        self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)

        def transfert(type_op, source, dest):
            pk = self.env["stock.picking"].create({
                "picking_type_id": type_op.id, "partner_id": self.client.id, "location_id": source.id,
                "location_dest_id": dest.id, "livreur_id": self.env.user.id,
                "prochain_entretien": fields.Date.today() + relativedelta(months=12), "frequence_entretien": "12",
                "move_ids": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1,
                                     "uom_id": self.produit.uom_id.id, "location_id": source.id,
                                     "location_dest_id": dest.id})]})
            pk.action_confirm()
            pk.move_ids.move_line_ids.unlink()
            self.env["stock.move.line"].create({
                "move_id": pk.move_ids.id, "picking_id": pk.id, "product_id": self.produit.id, "lot_id": lot.id,
                "quantity": 1, "location_id": source.id, "location_dest_id": dest.id})
            pk.move_ids.picked = True
            pk.button_validate()
            self.assertEqual(pk.state, "done")
            return pk

        livraison = transfert(entrepot.out_type_id, stock, clients)
        ramassage = transfert(entrepot.in_type_id, clients, stock)
        ind = self._ind("livraisons_faites")
        ind.invalidate_recordset()
        self.assertEqual(ind.name, "Livraisons & ramassages faits ce mois")
        parts = {libelle: (nombre, lien) for libelle, nombre, _c, lien in ind.repartition}
        self.assertEqual(ind.valeur, parts["Livraison"][0] + parts["Ramassage"][0])
        self.assertEqual((parts["Livraison"][1], parts["Ramassage"][1]), ("livrees", "ramassees"))
        Picking = self.env["stock.picking"]
        self.assertIn(livraison, Picking.search(self.env["pilotage.indicateur"]._parts_transferts_faits()["livraison"]))
        self.assertIn(ramassage, Picking.search(self.env["pilotage.indicateur"]._parts_transferts_faits()["ramassage"]))
        self.assertIn("search_default_ramassees_mois", ind.action_ouvrir_ramassees()["context"])
        self.assertIn("search_default_livrees_mois", ind.action_ouvrir_livrees()["context"])
        action = ind.action_ouvrir()
        ind.invalidate_recordset()
        self.assertEqual(Picking.search_count(action["domain"]), ind.valeur, "la liste = le chiffre de la carte")
        self.assertTrue((livraison | ramassage) <= Picking.search(action["domain"]))
        arch = self.env["pilotage.indicateur"].get_views([(False, "kanban")])["views"]["kanban"]["arch"]
        self.assertIn("action_ouvrir_ramassees", arch)
        # Les filtres existent dans la recherche des transferts
        vue = self.env.ref("suivi_machines_pilotage.view_pilotage_transfert_search")
        recherche = self.env["stock.picking"].get_views([(vue.id, "search")])
        self.assertIn("ramassees_mois", recherche["views"]["search"]["arch"])
        liste = self.env["stock.picking"].get_views(
            [(self.env.ref("suivi_machines_pilotage.view_pilotage_transfert_list").id, "list")])
        self.assertIn('name="type_tournee"', liste["views"]["list"]["arch"], "étiquette Livraison / Ramassage")
        # Toutes les livraisons, pas seulement les machines : un accessoire livre compte aussi
        self.assertEqual(ind.action_ouvrir_livrees()["domain"], [])
        accessoire = self.env["product.product"].create({"name": "Pompe livrée", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(accessoire, stock, 5)
        pk = self.env["stock.picking"].create({
            "picking_type_id": entrepot.out_type_id.id, "partner_id": self.client.id, "location_id": stock.id,
            "location_dest_id": clients.id, "livreur_id": self.env.user.id,
            "move_ids": [(0, 0, {"product_id": accessoire.id, "product_uom_qty": 2, "uom_id": accessoire.uom_id.id,
                                 "location_id": stock.id, "location_dest_id": clients.id})]})
        pk.action_confirm()
        pk.action_assign()
        pk.move_ids.picked = True
        pk.button_validate()
        self.assertIn(pk, Picking.search(self.env["pilotage.indicateur"]._parts_transferts_faits()["livraison"]))
        # Location : vers l'emplacement interne « Location » = livraison chez le client
        societe = self.env.company
        if "rental_loc_id" in societe._fields:
            location = societe.rental_loc_id or self.env["stock.location"].create(
                {"name": "Location test", "usage": "internal", "location_id": stock.location_id.id})
            societe.rental_loc_id = location
            self.assertEqual(Picking.new({"location_id": stock.id, "location_dest_id": location.id,
                                          "company_id": societe.id}).type_tournee, "livraison")

    def test_appels_ouverts(self):
        avant = self._ind("appels_ouverts").valeur
        self.env["helpdesk.ticket"].create({"name": "Ne gèle pas", "code_client": "PIL1"})
        self._ind("appels_ouverts").invalidate_recordset()
        self.assertEqual(self._ind("appels_ouverts").valeur, avant + 1, "un appel sans étape est ouvert")

    def test_types_de_ticket(self):
        Ticket = self.env["helpdesk.ticket"]
        appel = Ticket.create({"name": "Ne gèle pas", "code_client": "PIL1"})
        entretien = Ticket.create({"name": "ENTRETIEN - PIL-1", "partner_id": self.client.id, "est_entretien": True})
        so = self.env["sale.order"].create({"partner_id": self.client.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1]})
        reprise = Ticket.create({"name": "Reprise - PIL-1", "partner_id": self.client.id,
                                 "commande_reprise_id": so.id})
        self.assertEqual((appel.type_ticket, entretien.type_ticket, reprise.type_ticket),
                         ("appel", "entretien", "reprise"))
        tous = appel | entretien | reprise

        def dans(code):
            model, domaine = self.env["pilotage.indicateur"]._domaines()[code]
            return tous & self.env[model].search(domaine)

        # Entretien sans technicien : « a planifier », donc dans les Appels de service
        self.assertEqual(entretien.statut_entretien, "a_planifier")
        self.assertEqual(dans("appels_ouverts"), appel | entretien)
        self.assertEqual(dans("entretiens_a_planifier"), entretien)
        self.assertFalse(dans("entretiens_ouverts"))
        self.assertEqual(dans("reprises_ouvertes"), reprise)
        # Assigne a un technicien : « planifie », il passe dans les Entretiens planifies a faire
        tech = self.env["res.users"].create({"name": "Tech pilotage", "login": "tech_pilotage"})
        entretien.user_id = tech
        self.assertEqual(entretien.statut_entretien, "planifie")
        self.assertEqual(dans("appels_ouverts"), appel)
        self.assertEqual(dans("entretiens_ouverts"), entretien)
        self.assertFalse(dans("entretiens_a_planifier"))
        tache = self.env["portail.tache"].search([("ticket_id", "=", entretien.id)])
        self.assertEqual((tache.technicien_id, tache.type_tache), (tech, "entretien"), "dans sa journée")
        # Clic sur la carte : la liste s'ouvre filtree sur le type + ouverts
        carte = self._ind("reprises_ouvertes")
        action = carte.action_ouvrir()
        self.assertEqual(action["domain"], self.env["pilotage.indicateur"]._domaines()["reprises_ouvertes"][1],
                         "le critère de la carte")
        # La liste « Appels de service » montre tous les types, regroupes par type
        liste = self.env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_appels")
        self.assertFalse(liste.get("domain"))
        self.assertIn("search_default_grp_type_demande", liste["context"])
        arch = self.env["helpdesk.ticket"].get_views(
            [(self.env.ref("suivi_machines_pilotage.view_pilotage_appels_list").id, "list")])["views"]["list"]["arch"]
        self.assertNotIn('create="false"', arch, "bouton Nouveau : créer un ticket depuis le Pilotage")
        self.env["helpdesk.ticket"].get_views([(False, "form")])

    def test_toutes_les_cartes_et_vues(self):
        indicateurs = self.env["pilotage.indicateur"].search([])
        self.assertGreaterEqual(len(indicateurs), 20)
        indicateurs.mapped("valeur")
        for ind in indicateurs:
            action = ind.action_ouvrir()
            self.assertEqual(action["type"], "ir.actions.act_window", ind.code)
            Model = self.env[action["res_model"]]
            Model.search_count(eval(action["domain"]) if isinstance(action["domain"], str) else action["domain"] or [])
            vues = [(v, m) for v, m in action["views"]]
            Model.get_views(vues + [(action.get("search_view_id") and action["search_view_id"][0], "search")])
        self.env["pilotage.indicateur"].get_views([(False, "kanban")])

    def test_reparations_planifiees(self):
        Ticket = self.env["helpdesk.ticket"]
        tech = self.env["res.users"].create({"name": "Tech répare", "login": "tech_repare"})
        sans_tech = Ticket.create({"name": "Fuit", "code_client": "PIL1", "type_demande": "reparation"})
        assignee = Ticket.create({"name": "Ne gèle pas", "code_client": "PIL1", "type_demande": "reparation",
                                  "user_id": tech.id})
        remplacer = Ticket.create({"name": "À remplacer", "code_client": "PIL1", "type_demande": "remplacement",
                                   "user_id": tech.id})
        commande = Ticket.create({"name": "Sans type", "code_client": "PIL1", "type_demande": False,
                                  "user_id": tech.id})
        tous = sans_tech | assignee | remplacer | commande
        domaines = self.env["pilotage.indicateur"]._domaines()
        model, domaine = domaines["entretiens_ouverts"]

        def dans(code):
            return tous & self.env["helpdesk.ticket"].search(domaines[code][1])

        self.assertEqual(dans("entretiens_ouverts"), assignee | remplacer, "un seul bloc : réparations comprises")
        self.assertEqual(dans("appels_ouverts"), sans_tech | commande, "pas encore planifiés")
        # Ticket ouvert -> intervention de reparation (bouton Interventions) : il glisse vers « Réparations planifiées »
        f = Form(self.env["machine.intervention"].with_context(**sans_tech._contexte_intervention()))
        f.type = "reparation"
        f.lot_id = self.lot
        f.user_id = tech
        f.save()
        self.assertEqual((sans_tech.user_id, sans_tech.statut_entretien), (tech, "planifie"))
        domaines = self.env["pilotage.indicateur"]._domaines()
        self.assertEqual(dans("entretiens_ouverts"), sans_tech | assignee | remplacer)
        self.assertEqual(dans("appels_ouverts"), commande)
        # Une seule carte « Entretiens & réparations à faire », divisée par type (étiquettes)
        self.assertFalse(self.env.ref("suivi_machines_pilotage.indicateur_reparations_planifiees",
                                      raise_if_not_found=False))
        entretien = Ticket.create({"name": "Entretien", "partner_id": self.client.id, "est_entretien": True,
                                   "user_id": tech.id})
        ind = self._ind("entretiens_ouverts")
        self.assertEqual(ind.name, "Entretiens & réparations à faire")
        ind.invalidate_recordset()
        repartition = {libelle: (nombre, couleur) for libelle, nombre, couleur in ind.repartition}
        self.assertGreaterEqual(repartition["Réparation"][0], 2)
        self.assertGreaterEqual(repartition["Machine à remplacer"][0], 1)
        self.assertGreaterEqual(repartition["Entretien"][0], 1)
        self.assertEqual(ind.valeur, sum(n for n, _c in repartition.values()))
        self.assertEqual(list(repartition)[0], "Entretien", "ordre : entretien, réparation, remplacement")
        vide = self.env["pilotage.indicateur"]._repartition_par_type([("id", "=", 0)])
        self.assertEqual([(l, n) for l, n, _c in vide],
                         [("Entretien", 0), ("Réparation", 0), ("Machine à remplacer", 0)], "toujours les 3 types")
        self.assertIn(entretien, self.env[model].search(domaine))
        action = ind.action_ouvrir()
        self.assertEqual(action["context"], {"search_default_grp_type_demande": 1}, "regroupé par type")
        self.assertEqual(self.env[model].search_count(action["domain"]), ind.valeur, "la liste = le chiffre")
        self.assertNotIn("help", action)
        arch = self.env["pilotage.indicateur"].get_views([(False, "kanban")])["views"]["kanban"]["arch"]
        self.assertIn("repartition", arch)
        # Resolue : elle quitte la carte
        assignee.stage_id = self.env["helpdesk.stage"].create({"name": "Résolu"})
        self.assertNotIn(assignee, self.env[model].search(domaine))

    def test_produits_par_categorie(self):
        menu = self.env.ref("suivi_machines_pilotage.menu_pilotage_produits_categorie")
        self.assertEqual(menu.parent_id, self.env.ref("suivi_machines_pilotage.menu_pilotage_parc"))
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "suivi_machines_pilotage.action_pilotage_produits_categorie")
        self.assertEqual(action["res_model"], "product.template")
        self.assertIn("search_default_group_by_categ_id", action["context"])
        self.assertEqual(list(action["views"][0]),
                         [self.env.ref("suivi_machines_pilotage.view_pilotage_produits_list").id, "list"])
        Produit = self.env["product.template"]
        self.assertFalse(Produit.fields_get(["prix_vente"])["prix_vente"].get("aggregator"),
                         "pas de total des prix par catégorie")
        self.assertEqual(self.produit.product_tmpl_id.prix_vente, self.produit.list_price)
        Produit.get_views([(v, m) for v, m in action["views"]], {"search_view_id": action["search_view_id"][0]})
        categories = [getattr(categ, "id", categ) for categ, _nb in Produit.read_group([], ["categ_id"], ["__count"])]
        self.assertIn(self.produit.categ_id.id, categories)

    def test_cartes_entretiens_et_reparations(self):
        """En retard / cette semaine / 30 jours / faits ce mois : entretiens + réparations, une étiquette chacun."""
        Ticket = self.env["helpdesk.ticket"]
        maintenant = fields.Datetime.now()
        retard = Ticket.create({"name": "Fuit", "code_client": "PIL1", "type_demande": "reparation",
                                "date_planifiee": maintenant - relativedelta(days=2)})
        semaine = Ticket.create({"name": "Bruit", "code_client": "PIL1", "type_demande": "reparation",
                                 "date_planifiee": maintenant + relativedelta(days=3)})
        remplacer = Ticket.create({"name": "Trop vieille", "code_client": "PIL1", "type_demande": "remplacement",
                                   "date_planifiee": maintenant + relativedelta(days=3)})
        self.env["machine.intervention"].create({"lot_id": self.lot.id, "type": "reparation", "state": "fait"})
        self.env["machine.intervention"].create({"lot_id": self.lot.id, "type": "remplacement", "state": "fait"})
        for code, ticket, nom in (("entretien_retard", retard, "Entretiens & réparations en retard"),
                                  ("entretien_semaine", semaine, "Entretiens & réparations cette semaine"),
                                  ("entretien_mois", semaine, "Entretiens & réparations dans 30 jours")):
            ind = self._ind(code)
            ind.invalidate_recordset()
            self.assertEqual(ind.name, nom)
            parts = {libelle: (nombre, lien) for libelle, nombre, _c, lien in ind.repartition}
            self.assertEqual(ind.valeur, parts["Entretien"][0] + parts["Réparation"][0]
                             + parts["Machine à remplacer"][0])
            self.assertEqual(parts["Machine à remplacer"][1], "remplacements", "étiquette cliquable")
            self.assertNotIn(remplacer, Ticket.search(ind.action_ouvrir_reparations()["domain"]),
                             "une machine à remplacer n'est pas une réparation")
            if code != "entretien_retard":
                self.assertGreaterEqual(parts["Machine à remplacer"][0], 1, code)
                self.assertIn(remplacer, Ticket.search(ind.action_ouvrir_remplacements()["domain"]))
            self.assertGreaterEqual(parts["Réparation"][0], 1, code)
            self.assertEqual(parts["Réparation"][1], "reparations", "étiquette cliquable")
            action = ind.action_ouvrir_reparations()
            self.assertIn(ticket, Ticket.search(action["domain"]), code)
            self.assertNotIn("help", action)
            # Clic sur la carte : une liste de tickets avec les reparations (plus jamais une liste vide)
            action = ind.action_ouvrir()
            self.assertEqual(action["res_model"], "helpdesk.ticket")
            self.assertIn(ticket, Ticket.search(action["domain"]), code)
            self.assertFalse(action["context"], "aucun filtre qui cacherait les reparations")
        self.assertNotIn(semaine, Ticket.search(self._ind("entretien_retard").action_ouvrir_reparations()["domain"]))
        faits = self._ind("entretiens_faits")
        faits.invalidate_recordset()
        self.assertEqual(faits.name, "Entretiens & réparations faits ce mois")
        parts = {libelle: nombre for libelle, nombre, _c, _l in faits.repartition}
        self.assertGreaterEqual(parts["Réparation"], 1)
        self.assertGreaterEqual(parts["Machine à remplacer"], 1)
        self.assertEqual(faits.action_ouvrir_reparations()["res_model"], "machine.intervention")
        remplacements = self.env["machine.intervention"].search(faits.action_ouvrir_remplacements()["domain"])
        self.assertEqual(set(remplacements.mapped("type")), {"remplacement"})
        # Clic sur la carte : la liste contient exactement ce que la carte compte
        action = faits.action_ouvrir()
        self.assertEqual(self.env[action["res_model"]].search_count(action["domain"]), faits.valeur)
        listes = self.env[action["res_model"]].search(action["domain"])
        self.assertIn("remplacement", listes.mapped("type"), "machines à remplacer dans la liste")
        self.assertTrue({"bris", "reparation"} & set(listes.mapped("type")), "réparations dans la liste")
        self.assertFalse(action["context"], "aucun filtre qui cacherait une partie")
        # Resolue : la reparation quitte « en retard »
        retard.stage_id = self.env["helpdesk.stage"].create({"name": "Résolu"})
        self.assertNotIn(retard, Ticket.search(self._ind("entretien_retard").action_ouvrir_reparations()["domain"]))
        arch = self.env["pilotage.indicateur"].get_views([(False, "kanban")])["views"]["kanban"]["arch"]
        self.assertIn("action_ouvrir_reparations", arch)
        self.assertIn("action_ouvrir_remplacements", arch)

    def _technicien_planning(self, nom, login):
        """Technicien comme au Planning : utilisateur portail coche « Technicien » si le portail est installe."""
        if "est_technicien" not in self.env["res.partner"]._fields:
            return self.env["res.users"].create({"name": nom, "login": login})
        user = self.env["res.users"].create({"name": nom, "login": login,
                                             "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])]})
        user.partner_id.est_technicien = True
        return user

    def _demain_14h(self):
        import pytz
        from datetime import datetime, time, timedelta
        fuseau = pytz.timezone("America/Toronto")
        demain = datetime.now(fuseau).date() + timedelta(days=1)
        return fuseau.localize(datetime.combine(demain, time(14, 0))).astimezone(pytz.UTC).replace(tzinfo=None)

    def test_rappel_la_veille(self):
        Ticket = self.env["helpdesk.ticket"]
        self.client.email = "client.pilotage@example.com"
        tech = self.env["res.users"].create({"name": "Tech rappel", "login": "tech_rappel"})
        ticket = Ticket.create({"name": "Ne gèle pas", "partner_id": self.client.id, "type_demande": "reparation",
                                "user_id": tech.id, "date_planifiee": self._demain_14h()})
        sans_courriel = self.env["res.partner"].create({"name": "Sans courriel"})
        Ticket.create({"name": "Autre", "partner_id": sans_courriel.id, "type_demande": "reparation",
                       "user_id": tech.id, "date_planifiee": self._demain_14h()})
        avant = self.env["mail.mail"].search_count([])
        envoyees = self.env["portail.tache"]._cron_rappel_veille()
        self.assertEqual(envoyees.ticket_id, ticket, "seulement le client joignable")
        courriel = self.env["mail.mail"].search([], order="id desc", limit=1)
        self.assertEqual(self.env["mail.mail"].search_count([]), avant + 1)
        self.assertIn(self.client, courriel.recipient_ids)
        self.assertIn("Tech rappel", courriel.body_html)
        self.assertIn("demain", courriel.body_html)
        self.assertEqual((courriel.model, courriel.res_id), ("helpdesk.ticket", ticket.id), "réponse dans le ticket")
        self.assertEqual(ticket.rappel_veille_le, fields.Date.context_today(ticket))
        self.assertTrue(ticket.message_ids.filtered(lambda m: "Rappel envoyé" in (m.body or "")))
        self.assertFalse(self.env["portail.tache"]._cron_rappel_veille(), "une seule fois")
        # Desactivable
        self.env["ir.config_parameter"].sudo().set_bool("suivi_machines_pilotage.rappel_veille_actif", False)
        ticket.rappel_veille_le = False
        self.assertFalse(self.env["portail.tache"]._cron_rappel_veille())
        self.assertTrue(self.env.ref("suivi_machines_pilotage.cron_rappel_veille").active)

    def test_planning_glisser_deposer(self):
        import pytz
        Ticket = self.env["helpdesk.ticket"]
        tech_a = self._technicien_planning("Tech Alpha", "tech_alpha")
        tech_b = self._technicien_planning("Tech Bravo", "tech_bravo")
        date = self._demain_14h()
        ticket = Ticket.create({"name": "Fuit", "partner_id": self.client.id, "type_demande": "reparation",
                                "user_id": tech_a.id, "date_planifiee": date})
        jour = pytz.UTC.localize(date).astimezone(pytz.timezone("America/Toronto")).date()
        donnees = self.env["portail.tache"].donnees_planning(jour.isoformat())
        self.assertEqual(len(donnees["jours"]), 7)
        self.assertEqual(donnees["jours"][0]["titre"][:3], "Lun")
        carte = next(c for c in donnees["cartes"] if c["titre"] == "Fuit")
        self.assertEqual((carte["technicien_id"], carte["jour"], carte["heure"]), (tech_a.id, jour.isoformat(), "14 h 00"))
        self.assertIn(tech_a.id, [l["id"] for l in donnees["lignes"]])
        self.assertTrue(donnees["peut_deplacer"])
        # Glisser sur Tech Bravo, le surlendemain : meme heure
        nouveau_jour = jour + relativedelta(days=1)
        self.env["portail.tache"].deplacer_planning(carte["id"], tech_b.id, nouveau_jour.isoformat())
        self.assertEqual(ticket.user_id, tech_b)
        self.assertEqual(ticket.date_planifiee, date + relativedelta(days=1))
        # Vers « Sans technicien »
        tache = self.env["portail.tache"].search([("ticket_id", "=", ticket.id)])
        self.env["portail.tache"].deplacer_planning(tache.id, 0, nouveau_jour.isoformat())
        self.assertFalse(ticket.user_id)
        # Tache faite : ne bouge plus
        ticket.stage_id = self.env["helpdesk.stage"].create({"name": "Résolu"})
        tache = self.env["portail.tache"].search([("ticket_id", "=", ticket.id)])
        with self.assertRaises(UserError):
            self.env["portail.tache"].deplacer_planning(tache.id, tech_a.id, jour.isoformat())
        self.assertTrue(self.env.ref("suivi_machines_pilotage.menu_pilotage_planning").action)
        # Tache en retard (semaine passee, pas faite) : dans la colonne d'aujourd'hui de la semaine courante
        retard = Ticket.create({"name": "Oubliée", "partner_id": self.client.id, "type_demande": "reparation",
                                "user_id": tech_a.id, "date_planifiee": fields.Datetime.now() - relativedelta(days=9)})
        donnees = self.env["portail.tache"].donnees_planning(False)
        carte = next(c for c in donnees["cartes"] if c["titre"] == "Oubliée")
        aujourdhui = next(j["iso"] for j in donnees["jours"] if j["aujourdhui"])
        self.assertEqual((carte["jour"], carte["etat"]), (aujourdhui, "en_retard"))
        self.assertTrue(retard)

    def test_planning_indicateurs_filtres_periodes(self):
        """Planning : cartes du haut, graphiques, filtres technicien / type, vues Jour / Semaine / Mois.
        Semaine lointaine et techniciens crees ici : le test ne depend pas des donnees deja presentes."""
        import pytz
        from datetime import datetime, time, timedelta
        Ticket, Tache = self.env["helpdesk.ticket"], self.env["portail.tache"]
        fuseau = pytz.timezone("America/Toronto")
        lundi = datetime.now(fuseau).date() + timedelta(days=400)
        lundi -= timedelta(days=lundi.weekday())

        def quand(jours, heure=14):
            return fuseau.localize(datetime.combine(lundi + timedelta(days=jours), time(heure))).astimezone(
                pytz.UTC).replace(tzinfo=None)
        tech_a = self._technicien_planning("Tech Planning A", "tech_planning_a")
        tech_b = self._technicien_planning("Tech Planning B", "tech_planning_b")
        Ticket.create([
            {"name": "Plan A1", "partner_id": self.client.id, "type_demande": "reparation", "user_id": tech_a.id,
             "date_planifiee": quand(0)},
            {"name": "Plan A2", "partner_id": self.client.id, "type_demande": "ramassage", "user_id": tech_a.id,
             "date_planifiee": quand(2)},
            {"name": "Plan B1", "partner_id": self.client.id, "type_demande": "reparation", "user_id": tech_b.id,
             "date_planifiee": quand(2)},
        ])
        # Un technicien : sa ligne seulement, ses taches et leur nombre
        d = Tache.donnees_planning(lundi.isoformat(), "semaine", tech_a.id)
        self.assertEqual([l["id"] for l in d["lignes"]], [tech_a.id])
        self.assertEqual(sorted(c["titre"] for c in d["cartes"]), ["Plan A1", "Plan A2"])
        self.assertEqual((d["lignes"][0]["nombre"], d["lignes"][0]["en_retard"]), (2, 0))
        self.assertNotIn("charge", d["lignes"][0], "pas de pourcentage de charge")
        k = d["indicateurs"]
        self.assertEqual((k["total"], k["ramassages"], k["entretiens_reparations"], k["reparations"]), (2, 1, 1, 1))
        self.assertEqual((k["completion"], k["objectif"], k["tendance"]), (0, 90, False))
        g = d["graphiques"]
        self.assertEqual(g["charge"]["etiquettes"], ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"])
        self.assertEqual(g["charge"]["series"][0]["valeurs"], [1, 0, 1, 0, 0, 0, 0])
        self.assertEqual(sum(r["valeur"] for r in g["repartition"]), 2)
        self.assertEqual((len(g["tendance"]["etiquettes"]), g["tendance"]["planifiees"][-1]), (12, 2))
        self.assertEqual(d["reference"], lundi.isoformat(), "semaine lointaine : on garde son lundi")
        # Filtre par type : les reparations des deux techniciens
        d = Tache.donnees_planning(lundi.isoformat(), "semaine", False, "reparation")
        mes_cartes = [c["titre"] for c in d["cartes"] if c["technicien_id"] in (tech_a.id, tech_b.id)]
        self.assertEqual(sorted(mes_cartes), ["Plan A1", "Plan B1"])
        self.assertTrue(all(c["type"] == "reparation" for c in d["cartes"]))
        self.assertIn({"id": tech_b.id, "nom": tech_b.name}, d["filtres"]["techniciens"])
        # Vue Jour : une colonne ; vue Mois : du 1er au dernier jour du mois, regroupe par semaine
        d = Tache.donnees_planning((lundi + timedelta(days=2)).isoformat(), "jour", tech_a.id)
        self.assertEqual(([j["iso"] for j in d["jours"]], [c["titre"] for c in d["cartes"]]),
                         ([(lundi + timedelta(days=2)).isoformat()], ["Plan A2"]))
        d = Tache.donnees_planning(lundi.isoformat(), "mois", tech_a.id)
        self.assertEqual(d["jours"][0]["iso"][-2:], "01")
        self.assertIn(len(d["jours"]), (28, 29, 30, 31))
        self.assertTrue(all(e.startswith("S") for e in d["graphiques"]["charge"]["etiquettes"]))
        # Sans technicien seulement
        Ticket.create({"name": "Plan libre", "partner_id": self.client.id, "type_demande": "reparation",
                       "date_planifiee": quand(1)})
        d = Tache.donnees_planning(lundi.isoformat(), "semaine", -1)
        self.assertEqual([l["id"] for l in d["lignes"]], [0])
        self.assertTrue(all(not c["technicien_id"] for c in d["cartes"]))
        self.assertIn("Plan libre", [c["titre"] for c in d["cartes"]])
        self.assertEqual(Tache.donnees_planning(lundi.isoformat(), "inconnue")["periode"], "semaine")

    def test_entretien_planifie_via_intervention(self):
        """Jose planifie l'entretien depuis Interventions : le ticket ouvert de la machine devient « Planifié »."""
        Ticket = self.env["helpdesk.ticket"]
        ticket = Ticket.create({"name": "Entretien - PIL-1", "partner_id": self.client.id, "lot_id": self.lot.id,
                                "est_entretien": True})
        self.assertEqual(ticket.statut_entretien, "a_planifier")
        tech = self.env["res.users"].create({"name": "Tech interv", "login": "tech_interv"})
        date = fields.Datetime.now() + relativedelta(days=3)
        interv = self.env["machine.intervention"].create({
            "lot_id": self.lot.id, "type": "entretien", "user_id": tech.id, "date": date,
            "partner_id": self.client.id})
        self.assertEqual(interv.ticket_id, ticket, "rattachée au ticket d'entretien ouvert de la machine")
        self.assertEqual((ticket.statut_entretien, ticket.user_id, ticket.date_planifiee),
                         ("planifie", tech, date))
        model, domaine = self.env["pilotage.indicateur"]._domaines()["entretiens_ouverts"]
        self.assertIn(ticket, self.env[model].search(domaine))
        # Une seule tache dans la journee du technicien (le ticket, pas l'intervention en double)
        taches = self.env["portail.tache"].search([("technicien_id", "=", tech.id)])
        self.assertEqual(len(taches), 1)
        self.assertEqual(taches.ticket_id, ticket)
        # Une reparation n'est jamais rattachee a un ticket d'entretien
        bris = self.env["machine.intervention"].create({"lot_id": self.lot.id, "type": "bris"})
        self.assertFalse(bris.ticket_id)
        # Resolu : « Fait », il quitte les listes
        ticket.stage_id = self.env["helpdesk.stage"].create({"name": "Résolu"})
        self.assertEqual(ticket.statut_entretien, "fait")
        self.assertNotIn(ticket, self.env[model].search(domaine))

    def test_entretiens_et_reparations_regroupes(self):
        """Une seule section « Entretiens & réparations » (plus de colonne « Bris & réparations »)."""
        Ind = self.env["pilotage.indicateur"]
        self.assertFalse(Ind.search([("section", "=", "qualite")]))
        for code in ("bris_mois", "machines_probleme"):
            self.assertFalse(self.env.ref("suivi_machines_pilotage.indicateur_" + code, raise_if_not_found=False),
                             "carte retirée")
        self.assertNotIn("qualite", Ind._expand_sections(None, []))
        # Menu « Entretiens & réparations » retiré : les cartes du tableau de bord ouvrent les listes
        for xmlid in ("menu_pilotage_entretiens", "menu_pilotage_bris", "menu_pilotage_entretiens_faits"):
            self.assertFalse(self.env.ref("suivi_machines_pilotage." + xmlid, raise_if_not_found=False), xmlid)
        self.assertFalse(self.env.ref("suivi_machines_pilotage.menu_pilotage_qualite", raise_if_not_found=False))
        # Portail techniciens : entree directe de la barre de menu
        racine = self.env.ref("suivi_machines_pilotage.menu_pilotage_root")
        portail = self.env.ref("suivi_machines_pilotage.menu_portail_livreurs")
        self.assertEqual(portail.parent_id, racine)
        self.assertTrue(portail.action)
        self.assertFalse(self.env.ref("suivi_machines_pilotage.menu_pilotage_transferts", raise_if_not_found=False))

    def test_vue_ensemble_moderne(self):
        Ind = self.env["pilotage.indicateur"]
        self.env["helpdesk.ticket"].create({"name": "Ne gèle pas", "code_client": "PIL1"})
        for periode in ("jour", "semaine", "mois"):
            d = Ind.donnees_tableau_moderne(periode)
            self.assertEqual(d["periode"], periode)
            self.assertEqual(list(d["blocs"]), ["appels", "locations", "facturation", "inventaire"],
                             "un bloc par menu, dans l'ordre de la barre")
            self.assertEqual(len(d["semaines"]), 8)
            for cle in ("alertes", "techniciens", "progression", "problemes", "tournees", "bonjour", "date"):
                self.assertIn(cle, d)
        d = Ind.donnees_tableau_moderne("jour")
        tuiles = {k["code"]: k for bloc in d["blocs"].values() for k in bloc}
        # « Appels ouverts » : tous les tickets pas résolus (comme les colonnes de l'Assistance)
        self.assertEqual(tuiles["tickets_ouverts"]["valeur"], Ind._compte("tickets_ouverts"))
        self.assertGreaterEqual(tuiles["tickets_ouverts"]["valeur"], Ind._compte("appels_ouverts"))
        self.assertGreaterEqual(tuiles["tickets_ouverts"]["valeur"], 1)
        action = Ind.action_par_code("tickets_ouverts")
        self.assertEqual(self.env["helpdesk.ticket"].search_count(action["domain"]), tuiles["tickets_ouverts"]["valeur"])
        self.assertEqual(tuiles["a_facturer"]["libelle"], "Appels à facturer")
        self.assertNotIn("sage_clients", [a["code"] for a in d["alertes"]], "Sage : dans le bloc Facturation")
        self.assertTrue(all(a["nombre"] > 0 for a in d["alertes"]), "seulement ce qui est à traiter")
        # Tout est cliquable : chaque element ouvre une liste (sans le message HTML brut)
        Tag = self.env["helpdesk.tag"]   # l'Assistance Enterprise a peut-etre deja l'etiquette (nom unique)
        tag = Tag.search([("name", "=", "Fait du bruit")], limit=1) or Tag.create({"name": "Fait du bruit"})
        tech = self.env["res.users"].create({"name": "Tech vue", "login": "tech_vue",
                                             "group_ids": [(6, 0, self.env.ref("base.group_portal").ids)]})
        if "est_technicien" in tech.partner_id._fields:   # module Portail : techniciens portail seulement
            tech.partner_id.est_technicien = True
        self.env["helpdesk.ticket"].create({"name": "Bruit", "code_client": "PIL1", "tag_ids": [(6, 0, tag.ids)],
                                            "user_id": tech.id, "date_planifiee": fields.Datetime.now()})
        d = Ind.donnees_tableau_moderne("semaine")
        codes = ([k["code"] for bloc in d["blocs"].values() for k in bloc] + [a["code"] for a in d["alertes"]]
                 + [t["code"] for t in d["techniciens"]] + [p["code"] for p in d["problemes"]]
                 + [s["code"] for s in d["semaines"]] + [r["code"] for r in d["tournees"]]
                 + [x["code"] for cle in ("statuts", "disponibles", "categories", "mouvements")
                    for x in d["stock"][cle]] + ["rupture", "mouvements"])
        self.assertIn("probleme:Fait du bruit", codes)
        self.assertIn("technicien:%s" % tech.id, codes)
        self.assertTrue(any(c.startswith("tache:") for c in codes))
        for code in codes:
            action = Ind.action_par_code(code)
            self.assertEqual(action["type"], "ir.actions.act_window", code)
            self.assertNotIn("help", action, code)
            domaine = action.get("domain") or []
            self.env[action["res_model"]].search_count(eval(domaine) if isinstance(domaine, str) else domaine)
        # « Produits par catégorie » : aussi en tuile du bloc Inventaire, chiffre = liste groupée par catégorie
        produits = Ind.action_par_code("produits_categorie")
        self.assertEqual(produits["res_model"], "product.template")
        self.assertIn("search_default_group_by_categ_id", produits["context"])
        self.assertEqual(self.env["product.template"].search_count(produits["domain"]),
                         {k["code"]: k for k in d["blocs"]["inventaire"]}["produits_categorie"]["valeur"])
        # Le chiffre « Livraisons & ramassages » ouvre les deux (pas seulement les livraisons)
        tournees = Ind.action_par_code("tournees_a_faire")
        self.assertEqual(self.env["stock.picking"].search_count(tournees["domain"]),
                         Ind._compte("livraisons_a_faire") + Ind._compte("ramassages_a_faire"))
        bruit = Ind.action_par_code("probleme:Fait du bruit")
        self.assertEqual(self.env["helpdesk.ticket"].search_count(bruit["domain"]), 1)
        self.assertFalse(Ind.action_par_code("code_inconnu"))
        # Plus de tuiles « Ventes du mois » ni « Nos contacts » (aucun menu ne leur correspond)
        self.assertFalse(Ind.action_par_code("ventes_mois"))
        # Contrat signé en ligne ce mois : notification verte dans « À traiter maintenant »
        contrat = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_contrat_id": self.env.ref("suivi_machines.type_contrat_location").id})
        contrat.write({"signature": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "signed_by": "Client", "signed_on": fields.Datetime.now()})
        alertes = {a["code"]: a for a in Ind.donnees_tableau_moderne("jour")["alertes"]}
        self.assertEqual(alertes["contrats_signes_mois"]["niveau"], "success")
        action = Ind.action_par_code("contrats_signes_mois")
        self.assertIn(contrat, self.env["sale.order"].search(action["domain"]))
        carte = self.env.ref("suivi_machines_pilotage.indicateur_contrats_signes_mois")
        carte.invalidate_recordset()
        self.assertGreaterEqual(carte.valeur, 1, "aussi dans Toutes les cartes")
        self.assertIn(contrat, self.env["sale.order"].search(carte.action_ouvrir()["domain"]))
        # Les deux vues dans le menu Tableau de bord
        racine = self.env.ref("suivi_machines_pilotage.menu_pilotage_tableau_racine")
        self.assertEqual([m.action for m in racine.child_id.sorted("sequence")], [
            self.env.ref("suivi_machines_pilotage.action_pilotage_vue_ensemble"),
            self.env.ref("suivi_machines_pilotage.action_pilotage_tableau_bord")])

    def test_chaque_chiffre_egal_a_sa_liste(self):
        """Vue d'ensemble : chaque chiffre (tuiles et « À traiter maintenant ») est égal au nombre de lignes
        de la liste qu'il ouvre."""
        Ind = self.env["pilotage.indicateur"]
        nouveau = self.env["helpdesk.stage"].create({"name": "Nouveau"})
        tech = self.env["res.users"].create({"name": "Tech chiffres", "login": "tech_chiffres"})
        self.env["helpdesk.ticket"].create([
            {"name": "Ouvert sans tech", "code_client": "PIL1", "stage_id": nouveau.id},
            {"name": "Ouvert avec tech", "code_client": "PIL1", "stage_id": nouveau.id, "user_id": tech.id,
             "type_demande": "reparation", "date_planifiee": fields.Datetime.now()}])
        d = Ind.donnees_tableau_moderne("jour")
        chiffres = [(k["code"], k["valeur"]) for bloc in d["blocs"].values() for k in bloc]
        chiffres += [(a["code"], a["nombre"]) for a in d["alertes"]]
        verifies = 0
        for code, valeur in chiffres:
            action = Ind.action_par_code(code)
            self.assertTrue(action, code)
            contexte = action.get("context") or {}
            if isinstance(contexte, str) or any(k.startswith("search_default_") and k != "search_default_grp_type_demande"
                                                for k in contexte):
                continue   # liste filtree par un filtre de recherche (verifie par d'autres tests)
            domaine = action.get("domain") or []
            if isinstance(domaine, str):
                continue
            self.assertEqual(self.env[action["res_model"]].search_count(domaine), valeur, code)
            verifies += 1
        self.assertGreaterEqual(verifies, 8)

    def test_nouveau_ticket_dans_a_traiter(self):
        Ind = self.env["pilotage.indicateur"]
        nouveau = self.env["helpdesk.stage"].create({"name": "Nouveau"})
        en_cours = self.env["helpdesk.stage"].create({"name": "En cours"})
        avant = Ind._compte("tickets_nouveaux")
        ticket = self.env["helpdesk.ticket"].create({"name": "La vis ne tourne pas", "code_client": "PIL1",
                                                     "stage_id": nouveau.id})
        d = Ind.donnees_tableau_moderne("jour")
        alerte = d["alertes"][0]
        self.assertEqual(alerte["code"], "tickets_nouveaux", "en premier dans À traiter maintenant")
        self.assertEqual(alerte["nombre"], avant + 1)
        self.assertIn("La vis ne tourne pas", alerte["detail"])
        self.assertIn("Client pilotage", alerte["detail"])
        action = Ind.action_par_code("tickets_nouveaux")
        self.assertIn(ticket, self.env["helpdesk.ticket"].search(action["domain"]))
        self.assertEqual(self.env["helpdesk.ticket"].search_count(action["domain"]), avant + 1)
        # Pris en charge (etape suivante) : il quitte la liste
        ticket.stage_id = en_cours
        self.assertEqual(Ind._compte("tickets_nouveaux"), avant)
        # Encore « Nouveau » mais assigne a un technicien (planifie) : pris en charge aussi
        ticket.stage_id = nouveau
        self.assertEqual(Ind._compte("tickets_nouveaux"), avant + 1)
        ticket.write({"type_demande": "reparation", "type_reparation": "coule",
                      "user_id": self.env.ref("base.user_admin").id})
        self.assertEqual(ticket.statut_entretien, "planifie")
        self.assertEqual(Ind._compte("tickets_nouveaux"), avant)
        filtre = self.env.ref("suivi_machines_pilotage.view_pilotage_appels_search", raise_if_not_found=False)
        if filtre:
            self.assertIn("user_id", filtre.arch_db)

    def test_menu_reserve_au_groupe(self):
        menu = self.env.ref("suivi_machines_pilotage.menu_pilotage_root")
        groupe = self.env.ref("suivi_machines_pilotage.group_pilotage")
        self.assertIn(groupe, menu.group_ids)
        self.assertIn(self.env.ref("base.user_admin"), groupe.user_ids)


@tagged("post_install", "-at_install")
class TestPortailLivreurs(TransactionCase):

    def test_portail(self):
        env = self.env(context=dict(self.env.context, tracking_disable=True, skip_sms=True))
        client = env["res.partner"].create({"name": "Camping test", "street": "1 rue", "city": "Québec"})
        categ = env["product.category"].create({"name": "Mach portail", "suivi_machine": True})
        prod = env["product.product"].create({"name": "F100 p", "categ_id": categ.id, "is_storable": True,
                                              "tracking": "serial"})
        pompe = env["product.product"].create({"name": "Pompe p", "is_storable": True})
        stock = env.ref("stock.stock_location_stock")
        lot = env["stock.lot"].create({"name": "P-1", "ref": "F900", "product_id": prod.id})
        env["stock.quant"]._update_available_quantity(prod, stock, 1, lot_id=lot)
        env["stock.quant"]._update_available_quantity(pompe, stock, 5)
        livreur_a = env["res.users"].create({"name": "Livreur A", "login": "livreur_a_test"})
        so = env["sale.order"].create({"partner_id": client.id, "type_commande": "location", "date_debut_location": PERIODE_TEST[0], "date_fin_location": PERIODE_TEST[1], "order_line": [
            (0, 0, {"product_id": prod.id, "product_uom_qty": 1, "machine_lot_id": lot.id}),
            (0, 0, {"product_id": pompe.id, "product_uom_qty": 2})]})
        so.action_confirm()
        pk = so.picking_ids
        pk.livreur_id = livreur_a
        self.assertEqual(pk.type_tournee, "livraison")
        self.assertIn("F900 (P-1)", pk.machines_tournee)
        self.assertIn("2 × Pompe p", pk.accessoires_tournee)
        self.assertTrue(pk.date_tournee)
        action = env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_portail_livreurs")
        domaine = eval(action["domain"])
        self.assertIn(pk, env["stock.picking"].search(domaine))
        env["stock.picking"].get_views([(False, "kanban"), (False, "search")] if False else
                                       [(env.ref("suivi_machines_pilotage.view_portail_livreurs_kanban").id, "kanban"),
                                        (env.ref("suivi_machines_pilotage.view_portail_livreurs_search").id, "search")])

        # Portail techniciens : livraison + ticket + intervention planifiee, dans une seule vue
        Tache = env["portail.tache"]
        tache_pk = Tache.search([("picking_id", "=", pk.id)])
        self.assertEqual((tache_pk.type_tache, tache_pk.technicien_id), ("livraison", livreur_a))
        self.assertIn("F900 (P-1)", tache_pk.machines)
        ticket = env["helpdesk.ticket"].create({"name": "Ne refroidit pas", "partner_id": client.id,
                                                "lot_id": lot.id, "user_id": livreur_a.id})
        interv = env["machine.intervention"].create({"lot_id": lot.id, "type": "reparation",
                                                     "partner_id": client.id, "user_id": livreur_a.id})
        taches = Tache.search([("technicien_id", "=", livreur_a.id)])
        self.assertEqual(set(taches.mapped("type_tache")), {"livraison", "reparation"})
        self.assertEqual(len(taches), 3)
        tache_ticket = taches.filtered(lambda t: t.ticket_id == ticket)
        self.assertIn("1 rue", tache_ticket.route)
        etiquette = env["helpdesk.tag"].search([("name", "=", "Ne refroidit pas")], limit=1) \
            or env["helpdesk.tag"].create({"name": "Ne refroidit pas", "color": 1})
        ticket.tag_ids = etiquette
        Tache.invalidate_model()
        self.assertEqual(tache_ticket.tag_ids, etiquette)
        self.assertEqual(tache_ticket.action_ouvrir()["res_model"], "helpdesk.ticket")
        # Glisser vers un autre technicien : le document d'origine change
        tech_b = env["res.users"].create({"name": "Tech B", "login": "tech_b_test"})
        taches.write({"technicien_id": tech_b.id})
        self.assertEqual((pk.livreur_id, ticket.user_id, interv.user_id), (tech_b, tech_b, tech_b))
        self.assertEqual(len(Tache.search([("technicien_id", "=", tech_b.id)])), 3)
        # Intervention faite / ticket rattache : plus de doublon dans le portail
        interv.ticket_id = ticket
        self.assertFalse(Tache.search([("intervention_id", "=", interv.id)]))
        Tache.get_views([(False, "kanban"), (False, "list"), (False, "calendar"), (False, "form"), (False, "search")])

        # Pilotage > Locations > Planifier un ramassage : la livraison terminee y figure, avec son bouton
        pk.action_assign()
        pk.move_ids.picked = True
        pk.livreur_id = pk.livreur_id or self.env.user  # technicien obligatoire pour valider
        pk.prochain_entretien = pk.prochain_entretien or fields.Date.today() + relativedelta(months=12)  # entretien obligatoire a la livraison
        pk.frequence_entretien = pk.frequence_entretien or "12"
        pk.button_validate()
        action = env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_planifier_ramassage")
        self.assertIn(pk, env["stock.picking"].search(eval(action["domain"])))
        vue = env["stock.picking"].get_views(
            [(env.ref("suivi_machines_pilotage.view_pilotage_livraisons_faites_list").id, "list")])
        self.assertIn("action_planifier_ramassage", vue["views"]["list"]["arch"])
        self.assertEqual(pk.action_planifier_ramassage()["res_model"], "suivi.machines.planifier.ramassage")

        # Suivi de Jose : en retard / fait
        tache_ticket = Tache.search([("ticket_id", "=", ticket.id)])
        self.assertEqual(tache_ticket.etat_suivi, "a_faire")
        ticket.date_planifiee = fields.Datetime.now() - relativedelta(days=2)
        Tache.invalidate_model()
        self.assertEqual(Tache.search([("ticket_id", "=", ticket.id)]).etat_suivi, "en_retard")
        etape = env["helpdesk.stage"].create({"name": "Résolu"})
        ticket.stage_id = etape
        Tache.invalidate_model()
        tache_ticket = Tache.search([("ticket_id", "=", ticket.id)])
        self.assertEqual((tache_ticket.etat_suivi, tache_ticket.a_faire), ("fait", False),
                         "ticket résolu : reste visible pour le suivi, en vert")

        # Un technicien voit ses taches, sans pouvoir les reassigner
        taches_b = Tache.with_user(tech_b).search([("technicien_id", "=", tech_b.id)])
        self.assertEqual(len(taches_b), 2, "transfert + ticket (l'intervention est rattachée au ticket)")
        self.assertTrue(taches_b.mapped("route"), "adresse lue même sans droits sur les documents")
        with self.assertRaises(UserError):
            taches_b.write({"technicien_id": livreur_a.id})



class TestTableauStock(TransactionCase):
    """Vue d'ensemble : la partie Stock & inventaire."""

    def test_stock_et_inventaire(self):
        env = self.env(context=dict(self.env.context, tracking_disable=True))
        Ind = env["pilotage.indicateur"]
        stock = env.ref("stock.stock_location_stock")
        categ = env["product.category"].create({"name": "Machines (stock)", "suivi_machine": True})
        produit = env["product.product"].create({"name": "Machine stock", "categ_id": categ.id,
                                                 "is_storable": True, "tracking": "serial"})
        lots = env["stock.lot"].create([{"name": "STK-%s" % i, "product_id": produit.id} for i in range(3)])
        for lot in lots:
            env["stock.quant"]._update_available_quantity(produit, stock, 1, lot_id=lot)
        accessoire = env["product.product"].create({"name": "Pompe (stock)", "is_storable": True, "sale_ok": True})
        d = Ind.donnees_tableau_moderne("jour")["stock"]
        dispo = {x["code"]: x["nombre"] for x in d["disponibles"]}
        self.assertEqual(dispo.get("dispo:%s" % produit.id), 3, "3 machines du modèle en entrepôt")
        statuts = {x["code"]: x["nombre"] for x in d["statuts"]}
        self.assertGreaterEqual(statuts.get("statut:entrepot", 0), 3)
        self.assertIn("categorie:%s" % categ.id, [x["code"] for x in d["categories"]])
        self.assertGreaterEqual(d["rupture"], 1, "accessoire sans stock")
        self.assertIn(accessoire, env["product.product"].search(Ind._domaine_rupture()))
        env["stock.quant"]._update_available_quantity(accessoire, stock, 4)
        self.assertNotIn(accessoire, Ind._produits_en_rupture(), "accessoire reçu : plus en rupture")
        if not accessoire.categ_id:
            categories = {x["code"]: x["nom"] for x in Ind.donnees_tableau_moderne("jour")["stock"]["categories"]}
            self.assertEqual(categories.get("categorie:0"), "Sans catégorie")
            self.assertIn(accessoire, env["product.product"].search(Ind.action_par_code("categorie:0")["domain"]))
        # Ouvre les bonnes listes
        machines = env["stock.lot"].search(Ind.action_par_code("dispo:%s" % produit.id)["domain"])
        self.assertEqual(machines, lots)
        self.assertEqual(Ind.action_par_code("statut:entrepot")["res_model"], "stock.lot")
        self.assertEqual(Ind.action_par_code("categorie:%s" % categ.id)["res_model"], "product.product")
        # Mouvement de stock : livraison faite -> dans « Derniers mouvements », ouvre le transfert
        client = env["res.partner"].create({"name": "Client stock"})
        clients = env.ref("stock.stock_location_customers")
        pk = env["stock.picking"].create({
            "picking_type_id": env.ref("stock.picking_type_out").id, "partner_id": client.id,
            "location_id": stock.id, "location_dest_id": clients.id,
            "move_ids": [(0, 0, {"product_id": produit.id, "product_uom_qty": 1, "machine_lot_id": lots[0].id,
                                 "location_id": stock.id, "location_dest_id": clients.id})]})
        pk.action_confirm()
        pk.action_assign()
        pk.move_ids.picked = True
        pk.write({"livreur_id": env.user.id, "prochain_entretien": fields.Date.today() + relativedelta(months=12),
                  "frequence_entretien": "12"})
        pk.button_validate()
        d = Ind.donnees_tableau_moderne("jour")["stock"]
        mouvement = d["mouvements"][0]
        self.assertEqual((mouvement["serie"], mouvement["entree"]), ("STK-0", False))
        self.assertEqual(Ind.action_par_code(mouvement["code"])["res_id"], pk.id)
