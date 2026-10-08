# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Premiere verification tout de suite apres l'installation."""
    from .models.declencheurs import declencher
    declencher(env)
