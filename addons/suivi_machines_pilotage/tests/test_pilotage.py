# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


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

    def test_compteurs(self):
        self.assertGreaterEqual(self._ind("entretien_retard").valeur, 1)
        self.assertGreaterEqual(self._ind("bris_mois").valeur, 1)
        facturer = self._ind("a_facturer")
        self.assertGreaterEqual(facturer.valeur, 1)
        self.assertIn("Total", facturer.sous_titre)

    def test_appels_ouverts(self):
        avant = self._ind("appels_ouverts").valeur
        self.env["helpdesk.ticket"].create({"name": "Ne gèle pas", "code_client": "PIL1"})
        self._ind("appels_ouverts").invalidate_recordset()
        self.assertEqual(self._ind("appels_ouverts").valeur, avant + 1, "un appel sans étape est ouvert")

    def test_types_de_ticket(self):
        Ticket = self.env["helpdesk.ticket"]
        appel = Ticket.create({"name": "Ne gèle pas", "code_client": "PIL1"})
        entretien = Ticket.create({"name": "ENTRETIEN - PIL-1", "partner_id": self.client.id, "est_entretien": True})
        so = self.env["sale.order"].create({"partner_id": self.client.id, "type_commande": "location"})
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
        action = self._ind("reprises_ouvertes").action_ouvrir()
        self.assertEqual(action["context"], {"search_default_type_reprise": 1, "search_default_ouverts": 1})
        # La liste « Appels de service » montre tous les types, regroupes par type
        liste = self.env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_appels")
        self.assertFalse(liste.get("domain"))
        self.assertIn("search_default_grp_type_demande", liste["context"])

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
        commande = Ticket.create({"name": "Sirop", "code_client": "PIL1", "type_demande": "commande",
                                  "user_id": tech.id})
        tous = sans_tech | assignee | remplacer | commande
        domaines = self.env["pilotage.indicateur"]._domaines()
        model, domaine = domaines["reparations_planifiees"]

        def dans(code):
            return tous & self.env["helpdesk.ticket"].search(domaines[code][1])

        self.assertEqual(dans("reparations_planifiees"), assignee | remplacer)
        self.assertEqual(dans("appels_ouverts"), sans_tech | commande, "pas encore planifiés")
        self.assertFalse(dans("entretiens_ouverts"))
        # Ticket ouvert -> Nouvelle intervention de reparation : il glisse vers « Réparations planifiées »
        f = Form(self.env["machine.intervention"].with_context(**sans_tech.action_nouvelle_intervention()["context"]))
        f.type = "reparation"
        f.lot_id = self.lot
        f.user_id = tech
        f.save()
        self.assertEqual((sans_tech.user_id, sans_tech.statut_entretien), (tech, "planifie"))
        domaines = self.env["pilotage.indicateur"]._domaines()
        self.assertEqual(dans("reparations_planifiees"), sans_tech | assignee | remplacer)
        self.assertEqual(dans("appels_ouverts"), commande)
        ind = self._ind("reparations_planifiees")
        self.assertEqual(ind.section, "entretiens")
        cartes = self.env["pilotage.indicateur"].search([("section", "=", "entretiens")])
        self.assertEqual(cartes[:2].mapped("code"), ["entretiens_ouverts", "reparations_planifiees"],
                         "juste sous Entretiens planifiés à faire")
        action = ind.action_ouvrir()
        self.assertEqual(action["context"], {"search_default_reparations_planifiees": 1})
        self.assertNotIn("help", action)
        # Resolue : elle quitte la carte
        assignee.stage_id = self.env["helpdesk.stage"].create({"name": "Résolu"})
        self.assertNotIn(assignee, self.env[model].search(domaine))

    def _livrer(self, commande):
        for pk in commande.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")):
            pk.action_assign()
            pk.move_ids.picked = True
            pk.with_context(skip_sms=True).button_validate()

    def test_ajuster_contrat(self):
        """Meme contrat : +1 machine et des pompes 3 mois plus tard, puis renouvellement."""
        stock = self.env.ref("stock.stock_location_stock")
        lots = self.env["stock.lot"]
        for nom in ("AJ-1", "AJ-2", "AJ-3"):
            lot = self.env["stock.lot"].create({"name": nom, "product_id": self.produit.id})
            self.env["stock.quant"]._update_available_quantity(self.produit, stock, 1, lot_id=lot)
            lots |= lot
        pompe = self.env["product.product"].create({"name": "Pompe", "is_storable": True})
        self.env["stock.quant"]._update_available_quantity(pompe, stock, 10)
        fin = fields.Datetime.now() + relativedelta(years=2)
        contrat = self.env["sale.order"].create({
            "partner_id": self.client.id, "type_commande": "location", "date_fin_location": fin,
            "order_line": [(0, 0, {"product_id": self.produit.id, "product_uom_qty": 1,
                                   "machine_lot_id": lots[0].id})]})
        contrat.action_confirm()
        self._livrer(contrat)
        self.assertEqual(contrat._machines_a_reprendre(), lots[0])
        arch = self.env["sale.order"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn("action_ajuster_contrat", arch)
        action = contrat.action_ajuster_contrat()
        Assistant = self.env["suivi.ajuster.contrat"].with_context(**action["context"])
        with self.assertRaises(UserError):
            Assistant.create({}).action_appliquer()
        with self.assertRaises(UserError):
            Assistant.create({"machine_ids": [(6, 0, lots[0].ids)]}).action_appliquer()   # deja louee
        assistant = Assistant.create({
            "machine_ids": [(6, 0, lots[1:].ids)],
            "accessoire_ids": [(0, 0, {"product_id": pompe.id, "quantite": 2})],
            "renouveler": True, "nouvelle_date_fin": fin + relativedelta(years=2),
            "note": "Renouvellement 2 ans"})
        self.assertEqual(assistant.machines_actuelles_ids, lots[0])
        resultat = assistant.action_appliquer()
        livraison = self.env["stock.picking"].browse(resultat["res_id"])
        self.assertEqual(resultat["res_model"], "stock.picking", "ouvre la nouvelle livraison")
        self.assertEqual(livraison.sale_id, contrat, "même contrat")
        self.assertEqual(set(livraison.move_ids.product_id.ids), {self.produit.id, pompe.id})
        self.assertEqual(len(contrat.order_line), 4, "1 machine + 2 machines + pompes")
        self.assertEqual(contrat.date_fin_location, fin + relativedelta(years=2), "renouvelé")
        self._livrer(contrat)
        self.assertEqual(contrat._machines_a_reprendre(), lots, "3 machines chez le client")
        self.assertIn("Renouvellement 2 ans", contrat.message_ids[0].body)
        # Renouvellement seul : on reste sur le contrat
        seul = Assistant.create({"renouveler": True, "nouvelle_date_fin": fin + relativedelta(years=3)})
        self.assertEqual(seul.action_appliquer()["res_model"], "sale.order")
        with self.assertRaises(UserError):
            Assistant.create({"renouveler": True, "nouvelle_date_fin": fin}).action_appliquer()  # avant la fin
        menu = self.env.ref("suivi_machines_pilotage.menu_pilotage_ajuster_contrat")
        self.assertEqual(menu.parent_id, self.env.ref("suivi_machines_pilotage.menu_pilotage_locations"))

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

    def test_entretien_planifie_via_intervention(self):
        """Josef planifie l'entretien depuis Interventions : le ticket ouvert de la machine devient « Planifié »."""
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
        self.assertEqual(self._ind("bris_mois").section, "entretiens")
        self.assertEqual(self._ind("machines_probleme").section, "entretiens")
        self.assertNotIn("qualite", Ind._expand_sections(None, []))
        self.assertEqual(self.env.ref("suivi_machines_pilotage.menu_pilotage_bris").parent_id,
                         self.env.ref("suivi_machines_pilotage.menu_pilotage_entretiens"))
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
            self.assertEqual(len(d["kpis"]), 7)
            self.assertEqual(len(d["semaines"]), 8)
            self.assertEqual(len(d["parc"]), 5)
            for cle in ("alertes", "techniciens", "progression", "problemes", "tournees", "bonjour", "date"):
                self.assertIn(cle, d)
        d = Ind.donnees_tableau_moderne("jour")
        kpi = {k["code"]: k for k in d["kpis"]}
        self.assertEqual(kpi["appels_ouverts"]["valeur"], Ind._compte("appels_ouverts"))
        self.assertGreaterEqual(kpi["appels_ouverts"]["valeur"], 1)
        self.assertTrue(all(a["nombre"] > 0 for a in d["alertes"]), "seulement ce qui est à traiter")
        # Tout est cliquable : chaque element ouvre une liste (sans le message HTML brut)
        tag = self.env["helpdesk.tag"].create({"name": "Fait du bruit"})
        tech = self.env["res.users"].create({"name": "Tech vue", "login": "tech_vue"})
        self.env["helpdesk.ticket"].create({"name": "Bruit", "code_client": "PIL1", "tag_ids": [(6, 0, tag.ids)],
                                            "user_id": tech.id, "date_planifiee": fields.Datetime.now()})
        d = Ind.donnees_tableau_moderne("semaine")
        codes = ([k["code"] for k in d["kpis"]] + [a["code"] for a in d["alertes"]]
                 + [t["code"] for t in d["techniciens"]] + [p["code"] for p in d["problemes"]]
                 + [s["code"] for s in d["semaines"]] + [r["code"] for r in d["tournees"]]
                 + [m["code"] for m in d["parc"]])
        self.assertIn("probleme:Fait du bruit", codes)
        self.assertIn("technicien:%s" % tech.id, codes)
        self.assertTrue(any(c.startswith("tache:") for c in codes))
        for code in codes:
            action = Ind.action_par_code(code)
            self.assertEqual(action["type"], "ir.actions.act_window", code)
            self.assertNotIn("help", action, code)
            domaine = action.get("domain") or []
            self.env[action["res_model"]].search_count(eval(domaine) if isinstance(domaine, str) else domaine)
        # Le chiffre « Livraisons & ramassages » ouvre les deux (pas seulement les livraisons)
        self.assertEqual(Ind.action_par_code("tournees_a_faire")["context"],
                         {"search_default_livraisons_a_faire": 1, "search_default_ramassages_a_faire": 1})
        bruit = Ind.action_par_code("probleme:Fait du bruit")
        self.assertEqual(self.env["helpdesk.ticket"].search_count(bruit["domain"]), 1)
        self.assertFalse(Ind.action_par_code("code_inconnu"))
        # Ventes du mois et clients (Contacts)
        prod = self.env["product.product"].create({"name": "Location machine", "type": "service", "list_price": 1500})
        so = self.env["sale.order"].create({"partner_id": self.client.id,
                                            "order_line": [(0, 0, {"product_id": prod.id, "price_unit": 1500})]})
        so.action_confirm()
        d = Ind.donnees_tableau_moderne("jour")
        kpi = {k["code"]: k for k in d["kpis"]}
        self.assertIn("1", kpi["ventes_mois"]["valeur"])
        self.assertIn("500", kpi["ventes_mois"]["valeur"])
        self.assertEqual(kpi["clients"]["valeur"], self.env["res.partner"].search_count([]),
                         "tous les contacts, comme l'application Contacts")
        self.assertIn(so, self.env["sale.order"].search(Ind.action_par_code("ventes_mois")["domain"]))
        clients = Ind.action_par_code("clients")
        self.assertEqual(clients["res_model"], "res.partner")
        self.assertIn(self.client, self.env["res.partner"].search(clients["domain"]))
        personne = self.env["res.partner"].create({"name": "Sans achat", "parent_id": self.client.id})
        self.assertIn(personne, self.env["res.partner"].search(clients["domain"]), "même sans achat")
        # Les deux vues dans le menu Tableau de bord
        racine = self.env.ref("suivi_machines_pilotage.menu_pilotage_tableau_racine")
        self.assertEqual([m.action for m in racine.child_id.sorted("sequence")], [
            self.env.ref("suivi_machines_pilotage.action_pilotage_vue_ensemble"),
            self.env.ref("suivi_machines_pilotage.action_pilotage_tableau_bord")])

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
        self.assertEqual(action["context"], {"search_default_nouveaux": 1})
        # Pris en charge (etape suivante) : il quitte la liste
        ticket.stage_id = en_cours
        self.assertEqual(Ind._compte("tickets_nouveaux"), avant)

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
        so = env["sale.order"].create({"partner_id": client.id, "type_commande": "location", "order_line": [
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
        etiquette = env["helpdesk.tag"].create({"name": "Ne refroidit pas", "color": 1})
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
        pk.button_validate()
        action = env["ir.actions.act_window"]._for_xml_id("suivi_machines_pilotage.action_pilotage_planifier_ramassage")
        self.assertIn(pk, env["stock.picking"].search(eval(action["domain"])))
        vue = env["stock.picking"].get_views(
            [(env.ref("suivi_machines_pilotage.view_pilotage_livraisons_faites_list").id, "list")])
        self.assertIn("action_planifier_ramassage", vue["views"]["list"]["arch"])
        self.assertEqual(pk.action_planifier_ramassage()["res_model"], "suivi.machines.planifier.ramassage")

        # Suivi de Josef : en retard / fait
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



@tagged("post_install", "-at_install")
class TestDonneesTest(TransactionCase):

    def test_generer_et_supprimer(self):
        env = self.env(context=dict(self.env.context, tracking_disable=True))
        client = env["res.partner"].create({"name": "Client test", "street": "1 rue", "city": "Québec"})
        categ = env["product.category"].create({"name": "Mach test", "suivi_machine": True})
        prod = env["product.product"].create({"name": "F test", "categ_id": categ.id, "is_storable": True,
                                              "tracking": "serial"})
        env["sale.order"].create({"partner_id": client.id})
        env["stock.lot"].create({"name": "TST-1", "product_id": prod.id})
        wiz = env["pilotage.donnees.test"].create({"nb_entretiens": 3, "nb_reparations": 4})
        wiz.action_generer()
        test = env.ref("suivi_machines_pilotage.tag_donnees_test")
        tickets = env["helpdesk.ticket"].search([("tag_ids", "in", test.ids)])
        self.assertEqual(len(tickets), 7)
        self.assertEqual(len(tickets.filtered("est_entretien")), 3)
        self.assertTrue(all(tickets.mapped("date_planifiee")))
        self.assertTrue(all(env["portail.tache"].search([("ticket_id", "in", tickets.ids)]).mapped("technicien_id")))
        self.assertEqual(len(env["portail.tache"].search([("ticket_id", "in", tickets.ids)])), 7)
        env["pilotage.donnees.test"].create({}).action_supprimer()
        self.assertFalse(env["helpdesk.ticket"].search([("tag_ids", "in", test.ids)]))
