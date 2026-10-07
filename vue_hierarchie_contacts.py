#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ouvre l'application Contacts directement en vue Hierarchie
(entreprise mere -> commerces -> contacts-personnes).
Les autres vues (liste, kanban...) restent accessibles par les boutons en haut a droite.

Relançable sans risque. Pour revenir a la liste par defaut : ANNULER = True.
Usage : python3 vue_hierarchie_contacts.py
"""
import sys
import xmlrpc.client

# ===================== À REMPLIR =====================
URL      = "http://localhost:8070"
DB       = "test_v20"
USERNAME = "admin"
PASSWORD = "admin"
ANNULER  = False   # True = remettre la liste en premier
# =====================================================

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie DB / USERNAME / PASSWORD."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)

def kw(model, method, args, opts=None):
    return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})

action = kw("ir.model.data", "search_read", [[["module", "=", "contacts"], ["name", "=", "action_contacts"]]],
            {"fields": ["res_id"]})
vue = kw("ir.model.data", "search_read", [[["module", "=", "contacts"], ["name", "=", "res_partner_view_hierarchy"]]],
         {"fields": ["res_id"]})
if not action or not vue:
    print("Application Contacts ou vue Hierarchie introuvable."); sys.exit(1)
action_id, vue_id = action[0]["res_id"], vue[0]["res_id"]

existant = kw("ir.actions.act_window.view", "search",
              [[["act_window_id", "=", action_id], ["view_mode", "=", "hierarchy"]]])
if ANNULER:
    if existant:
        kw("ir.actions.act_window.view", "unlink", [existant])
    print("Contacts s'ouvre de nouveau en liste.")
else:
    vals = {"act_window_id": action_id, "view_mode": "hierarchy", "view_id": vue_id, "sequence": -1}
    if existant:
        kw("ir.actions.act_window.view", "write", [existant, vals])
    else:
        kw("ir.actions.act_window.view", "create", [vals])
    print("Contacts s'ouvre maintenant en vue Hierarchie.")
