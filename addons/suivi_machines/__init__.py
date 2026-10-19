# -*- coding: utf-8 -*-
from . import controllers
from . import models


def post_init_hook(env):
    """Active le suivi sur la catégorie de produits des machines ; retire la fiche contact faite à la main."""
    env["product.category"].search([("name", "=", "Machines & équipements")]).write(
        {"suivi_machine": True})
    retirer_vue_contact_a_la_main(env)


def retirer_vue_contact_a_la_main(env):
    """Fiche contact : la vue ajoutee a la main dans la base (« res.partner.form.autres.informations ») est
    remplacee par celle du module ; la garder afficherait deux fois le code client et l'onglet. Les champs
    x_nom_legal, x_autres_numeros et x_code_societe deviennent ceux du module (valeurs gardees).
    Appele a l'installation (production) et a la mise a jour 20.0.1.50.0 (bases ou le module etait deja la)."""
    vues = env["ir.ui.view"].with_context(active_test=False).search(
        [("name", "=", "res.partner.form.autres.informations"), ("model", "=", "res.partner")])
    a_la_main = vues.filtered(lambda v: not env["ir.model.data"].search_count(
        [("model", "=", "ir.ui.view"), ("res_id", "=", v.id),
         ("module", "not in", ("__export__", "studio_customization"))]))
    a_la_main.unlink()
