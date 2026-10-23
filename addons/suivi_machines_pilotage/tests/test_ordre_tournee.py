# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta

import pytz

from odoo.tests import TransactionCase, tagged

FUSEAU = pytz.timezone("America/Toronto")


@tagged("post_install", "-at_install")
class TestOrdreTournee(TransactionCase):
    """Planning : le superviseur choisit l'ordre de la tournee (1, 2, 3, sans heure) et les heures fixes ;
    le technicien voit le meme ordre sur son portail."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, skip_sms=True))
        cls.client = cls.env["res.partner"].create({"name": "Client tournée"})
        cls.tech = cls._technicien("Tech Tournée", "tech_tournee")
        cls.autre = cls._technicien("Tech Autre", "tech_autre_tournee")
        # Une journee lointaine : le test ne depend pas des taches deja presentes
        cls.jour = datetime.now(FUSEAU).date() + timedelta(days=60)
        cls.tickets = cls.env["helpdesk.ticket"]
        for nom, heure in (("Alpha", 8), ("Bravo", 10), ("Charlie", 15)):
            cls.tickets |= cls.env["helpdesk.ticket"].create({
                "name": nom, "partner_id": cls.client.id, "type_demande": "reparation", "user_id": cls.tech.id,
                "date_planifiee": cls._utc(cls.jour, heure)})
        cls.Tache = cls.env["portail.tache"]

    @classmethod
    def _technicien(cls, nom, login):
        if "est_technicien" not in cls.env["res.partner"]._fields:
            return cls.env["res.users"].create({"name": nom, "login": login})
        user = cls.env["res.users"].create({"name": nom, "login": login,
                                            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])]})
        user.partner_id.est_technicien = True
        return user

    @staticmethod
    def _utc(jour, heure, minute=0):
        return FUSEAU.localize(datetime.combine(jour, time(heure, minute))).astimezone(pytz.UTC).replace(tzinfo=None)

    def _taches(self):
        return self.Tache.search([("ticket_id", "in", self.tickets.ids)])

    def _case(self):
        """Cartes de la case du technicien, dans l'ordre affiche : [(titre, pastille)]."""
        donnees = self.Tache.donnees_planning(self.jour.isoformat())
        return [(c["titre"], c["pastille"]) for c in donnees["cartes"]
                if c["technicien_id"] == self.tech.id and c["jour"] == self.jour.isoformat()]

    def test_sans_ordre_par_heure(self):
        """Pas encore d'ordre choisi : les taches suivent l'heure prevue, numerotees 1, 2, 3."""
        self.assertEqual(self._case(), [("Alpha", "1"), ("Bravo", "2"), ("Charlie", "3")])

    def test_glisser_une_tache_sur_une_autre(self):
        """Deposee sur une carte : elle prend sa place ; deposee dans la case : a la fin de la tournee."""
        alpha, bravo, charlie = (self._taches().filtered(lambda t, n=n: t.titre == n) for n in ("Alpha", "Bravo", "Charlie"))
        self.Tache.deplacer_planning(charlie.id, self.tech.id, self.jour.isoformat(), alpha.id)
        self.assertEqual(self._case(), [("Charlie", "1"), ("Alpha", "2"), ("Bravo", "3")])
        self.assertEqual(self.tickets.filtered(lambda t: t.name == "Charlie").ordre_tournee, 1, "gardé sur le ticket")
        self.Tache.deplacer_planning(charlie.id, self.tech.id, self.jour.isoformat())
        self.assertEqual(self._case(), [("Alpha", "1"), ("Bravo", "2"), ("Charlie", "3")])
        # Vers un autre technicien, deposee sur sa seule tache : avant elle
        autre = self.env["helpdesk.ticket"].create({
            "name": "Delta", "partner_id": self.client.id, "type_demande": "reparation", "user_id": self.autre.id,
            "date_planifiee": self._utc(self.jour, 7)})
        delta = self.Tache.search([("ticket_id", "=", autre.id)])
        self.Tache.deplacer_planning(bravo.id, self.autre.id, self.jour.isoformat(), delta.id)
        self.assertEqual(self.tickets.filtered(lambda t: t.name == "Bravo").user_id, self.autre)
        self.assertEqual(self._case(), [("Alpha", "1"), ("Charlie", "2")])

    def test_nouvelle_tache_a_la_fin(self):
        """Une tache arrivee apres que l'ordre a ete choisi passe apres les taches placees."""
        alpha = self._taches().filtered(lambda t: t.titre == "Alpha")
        self.Tache.deplacer_planning(alpha.id, self.tech.id, self.jour.isoformat())
        self.env["helpdesk.ticket"].create({
            "name": "Écho", "partner_id": self.client.id, "type_demande": "reparation", "user_id": self.tech.id,
            "date_planifiee": self._utc(self.jour, 6)})
        self.assertEqual([t for t, _p in self._case()], ["Bravo", "Charlie", "Alpha", "Écho"])

    def test_journee_ordre_et_heure_fixe(self):
        """Fenetre « Journée » : l'ordre des lignes devient la tournee ; « Heure fixe » donne l'heure de la date."""
        Journee = self.env["pilotage.journee"]
        action = Journee.action_ouvrir(self.tech.id, self.jour.isoformat())
        self.assertEqual(action["res_model"], "pilotage.journee")
        journee = Journee.with_context(action["context"]).create({})
        self.assertEqual(journee.ligne_ids.mapped("client"), ["Client tournée"] * 3)
        lignes = {l.tache_ref: l for l in journee.ligne_ids}
        taches = {t.titre: t for t in self._taches()}
        # Charlie en premier ; Bravo a 14 h 30, heure fixe
        lignes[taches["Charlie"].id].sequence = 0
        lignes[taches["Bravo"].id].write({"heure_fixe": True, "heure": 14.5})
        journee.action_enregistrer()
        self.assertEqual(self._case(), [("Charlie", "1"), ("Alpha", "2"), ("Bravo", "14h30")])
        bravo = self.tickets.filtered(lambda t: t.name == "Bravo")
        self.assertTrue(bravo.heure_fixe)
        self.assertEqual(bravo.date_planifiee, self._utc(self.jour, 14, 30))
        self.env.user.tz = "America/Toronto"
        self.Tache.invalidate_model()
        tache = self.Tache.search([("ticket_id", "=", bravo.id)])
        self.assertIn("14 h 30", tache.date_affichage, "heure montrée au technicien")
        self.assertNotIn(" h ", self.Tache.search([("ticket_id", "=", self.tickets[0].id)]).date_affichage,
                         "sans heure fixe : pas d'heure")

    def test_conflit_meme_heure(self):
        for ticket in self.tickets[:2]:
            ticket.write({"heure_fixe": True, "date_planifiee": self._utc(self.jour, 14)})
        donnees = self.Tache.donnees_planning(self.jour.isoformat())
        conflits = {c["titre"] for c in donnees["cartes"] if c["conflit"]}
        self.assertEqual(conflits, {"Alpha", "Bravo"})

    def test_technicien_ne_change_pas_l_ordre(self):
        """Le technicien (portail) voit l'ordre mais ne peut pas le changer."""
        tache = self._taches()[:1]
        with self.assertRaises(Exception):
            tache.with_user(self.tech).write({"ordre_tournee": 5})
        with self.assertRaises(Exception):
            self.env["pilotage.journee"].with_user(self.tech).create({"jour": self.jour})
        # Le portail suit l'ordre du Planning
        charlie = self._taches().filtered(lambda t: t.titre == "Charlie")
        self.Tache.deplacer_planning(charlie.id, self.tech.id, self.jour.isoformat(), self._taches()[0].id)
        ordre = self._taches()._trier_tournee()
        self.assertEqual(ordre.mapped("titre"), ["Charlie", "Alpha", "Bravo"])
        self.assertEqual(list(ordre._pastilles_tournee().values()), ["1", "2", "3"])
