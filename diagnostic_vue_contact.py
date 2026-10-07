#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic : ou se trouve le cadre "Code client" dans la fiche contact ?
Usage : python3 diagnostic_vue_contact.py   (ne modifie rien)"""
import re
import xmlrpc.client

URL, DB, USERNAME, PASSWORD = "http://localhost:8070", "test_v20", "admin", "admin"

uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USERNAME, PASSWORD, {})
m = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)
kw = lambda mod, meth, args, **o: m.execute_kw(DB, uid, PASSWORD, mod, meth, args, o)

print("Langue de l'utilisateur :", kw("res.users", "read", [[uid], ["lang"]])[0]["lang"])
vues = kw("ir.ui.view", "search_read", [[["name", "=", "res.partner.form.autres.informations"]]],
          fields=["id", "active", "priority", "inherit_id", "mode"], context={"active_test": False})
print("Vues 'autres informations' :", vues)
for lang in ("en_US", "fr_CA"):
    for v in vues:
        arch = kw("ir.ui.view", "read", [[v["id"]], ["arch_db"]], context={"lang": lang})[0]["arch_db"]
        print(f"--- arch ({lang}) contient le cadre : {'Code client' in arch or 'CODE CLIENT' in arch}")
        print(arch[:700])

form = kw("res.partner", "get_views", [[[False, "form"]]])["views"]["form"]["arch"]
i = form.find('name="ref"')
print("\n--- Vue finale : nb de champs ref =", form.count('name="ref"'))
for mt in re.finditer(r'name="ref"', form):
    print("...", form[max(0, mt.start() - 600):mt.start() + 150].replace("\n", " "), "...\n")
j = form.find('name="image_1920"')
print("--- autour de image_1920 :", form[max(0, j - 300):j + 900].replace("\n", " "))
