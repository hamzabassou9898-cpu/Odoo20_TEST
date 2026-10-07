# ---------------------------------------------------------------- Connexion (commun)
import sys
import xmlrpc.client

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(DB, USERNAME, PASSWORD, {})
if not uid:
    print("Authentification echouee - verifie URL / DB / USERNAME / PASSWORD (cle API)."); sys.exit(1)
models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object", allow_none=True)


def kw(model, method, args, opts=None):
    try:
        return models.execute_kw(DB, uid, PASSWORD, model, method, args, opts or {})
    except xmlrpc.client.Fault as e:
        if "cannot marshal None" in e.faultString:   # methode sans valeur de retour
            return None
        raise


def champs(model):
    return kw(model, "fields_get", [[]], {"attributes": ["type"]})


def modele_existe(model):
    return bool(kw("ir.model", "search", [[["model", "=", model]]]))


# Chaque enregistrement importe recoit un identifiant externe MODULE.cle :
# une relance retrouve l'enregistrement au lieu de le recreer.
def ref_get(cle, model):
    r = kw("ir.model.data", "search_read", [[["module", "=", MODULE], ["name", "=", cle]]],
           {"fields": ["res_id", "model"]})
    if r and r[0]["model"] == model and kw(model, "search", [[["id", "=", r[0]["res_id"]]]],
                                            {"context": {"active_test": False}}):
        return r[0]["res_id"]
    if r:
        kw("ir.model.data", "unlink", [[r[0]["id"]]])
    return None


def ref_set(cle, model, res_id):
    kw("ir.model.data", "create", [{"module": MODULE, "name": cle, "model": model,
                                    "res_id": res_id, "noupdate": True}])


def ecrire_ou_creer(cle, model, vals, chercher=None):
    """Met a jour l'enregistrement de cle, sinon celui trouve par `chercher`, sinon le cree."""
    rid = ref_get(cle, model)
    if not rid and chercher:
        ids = kw(model, "search", [chercher], {"limit": 1, "context": {"active_test": False}})
        if ids:
            rid = ids[0]
            ref_set(cle, model, rid)
    if rid:
        kw(model, "write", [[rid], vals])
        return rid, False
    rid = kw(model, "create", [vals])
    ref_set(cle, model, rid)
    return rid, True


def par_nom(model, nom, vals=None, domaine=None):
    """Trouve par nom (ou cree) un enregistrement simple."""
    if not nom:
        return False
    ids = kw(model, "search", [[["name", "=", nom]] + (domaine or [])], {"limit": 1,
                                                                         "context": {"active_test": False}})
    return ids[0] if ids else kw(model, "create", [dict(vals or {}, name=nom)])


def activer_langue(code):
    lang = kw("res.lang", "search_read", [[["code", "=", code], ["active", "in", [True, False]]]],
              {"fields": ["active"]})
    if lang and not lang[0]["active"]:
        wiz = kw("base.language.install", "create", [{"lang_ids": [(6, 0, [lang[0]["id"]])]}])
        kw("base.language.install", "lang_install", [[wiz]])
        print(f"Langue activee : {code}")
    return bool(lang)


def etat_pays(pays_code, etat_code):
    pays = kw("res.country", "search", [[["code", "=", pays_code]]]) if pays_code else []
    etat = (kw("res.country.state", "search", [[["code", "=", etat_code], ["country_id", "=", pays[0]]]])
            if pays and etat_code else [])
    return (pays[0] if pays else False), (etat[0] if etat else False)


def activer_listes_de_prix():
    RS = champs("res.config.settings")
    if "group_product_pricelist" in RS and not kw(
            "res.config.settings", "default_get", [["group_product_pricelist"]]).get("group_product_pricelist"):
        wiz = kw("res.config.settings", "create", [{"group_product_pricelist": True}])
        kw("res.config.settings", "execute", [[wiz]])
        print("Option 'Listes de prix' activee")


def liste_de_prix(nom, devise_nom=None):
    if not nom:
        return False
    ids = kw("product.pricelist", "search", [[["name", "=", nom]]], {"context": {"active_test": False}})
    if ids:
        return ids[0]
    vals = {"name": nom}
    dev = kw("res.currency", "search", [[["name", "=", devise_nom]]]) if devise_nom else []
    if dev:
        vals["currency_id"] = dev[0]
    return kw("product.pricelist", "create", [vals])
