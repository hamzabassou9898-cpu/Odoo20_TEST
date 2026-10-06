# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Active le suivi sur la catégorie de produits des machines."""
    env["product.category"].search([("name", "=", "Machines & équipements")]).write(
        {"suivi_machine": True})
