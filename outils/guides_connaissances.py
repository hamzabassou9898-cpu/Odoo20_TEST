# GUIDES DE L'UTILISATION dans l'application Connaissances (Knowledge) — sans module.
# Cree (ou met a jour) l'article « Guide de l'utilisation » et un sous-article par guide, avec les
# captures (base de demonstration, aucune vraie donnee) et des EXEMPLES REELS pris dans cette base
# (ex. la banniere qui a le plus de commerces) : les vraies donnees restent dans Odoo, jamais sur GitHub.
# Renomme aussi l'application Connaissances en « Guide de l'utilisation ».
#
#   rm -rf ~/o20 && git clone -q --depth 1 -b claude/amazing-brahmagupta-fkhf41 \
#       https://github.com/hamzabassou9898-cpu/Odoo20_TEST.git ~/o20 \
#   && odoo-bin shell --no-http --log-level=warn < ~/o20/outils/guides_connaissances.py
#
# Relancable : les articles sont mis a jour (le texte d'un guide est remplace par la version du depot).
import base64
import os
import re
from collections import Counter

from markupsafe import escape

DOSSIER = os.environ.get("GUIDES", os.path.expanduser("~/o20/outils/guides"))
NOM_APPLICATION = "Guide de l'utilisation"
RACINE = ("Guide de l'utilisation", "📘")
GUIDES = [  # (dossier, titre de l'article, icone)
    ("contacts", "Contacts", "👥"),
]

if "knowledge.article" not in env:
    raise SystemExit("ARRÊT : l'application Connaissances (Knowledge) n'est pas installée dans cette base.")
Article = env["knowledge.article"].sudo().with_context(active_test=False)
champs = Article._fields


# ---------------------------------------------------------------- exemples reels de cette base
def exemples():
    """Exemples pris dans la base : la banniere qui a le plus de commerces (avec code client), un de ses
    commerces. Valeurs de la demonstration si la base n'en a pas."""
    Partner = env["res.partner"].sudo()
    valeurs = {"banniere": "Dépanneurs Bonjour", "nb": "4", "commerces": "ses commerces",
               "commerce": "Dépanneur Bonjour Sainte-Foy", "code": "MON502", "ville": "Québec"}
    nombres = Counter(Partner.search([("parent_id", "!=", False), ("type", "=", "delivery"),
                                      ("ref", "!=", False)]).mapped("parent_id.id"))
    if nombres:
        banniere = Partner.browse(nombres.most_common(1)[0][0])
        commerces = banniere.child_ids.filtered(lambda c: c.type == "delivery" and c.ref).sorted("name")
        exemple = commerces[:1]
        noms = commerces[:4].mapped("name")
        valeurs.update({
            "banniere": banniere.name, "nb": str(len(commerces)),
            "commerces": ", ".join(noms) + (" et %d autres" % (len(commerces) - 4) if len(commerces) > 4 else ""),
            "commerce": exemple.name, "code": exemple.ref, "ville": exemple.city or ""})
    return {cle: str(escape(valeur)) for cle, valeur in valeurs.items()}


# ---------------------------------------------------------------- articles
def article(nom, icone, parent=None, sequence=0):
    domaine = [("name", "=", nom), ("parent_id", "=", parent.id if parent else False)]
    record = Article.search(domaine, limit=1)
    valeurs = {"name": nom, "icon": icone, "sequence": sequence}
    if parent:
        valeurs["parent_id"] = parent.id
    elif "internal_permission" in champs:
        valeurs["internal_permission"] = "write"   # article de l'espace de travail, visible par tous
    if "full_width" in champs:
        valeurs["full_width"] = True
    valeurs = {cle: valeur for cle, valeur in valeurs.items() if cle in champs}
    if record:
        record.write(valeurs)
        return record, False
    return Article.create(valeurs), True


def images(record, dossier, corps):
    """Captures du guide en pieces jointes de l'article ; {{img:nom}} -> /web/image/<id>."""
    Attachment = env["ir.attachment"].sudo()
    champ_contenu = "raw" if "raw" in Attachment._fields else "datas"   # Odoo 20 : « raw »

    def remplacer(match):
        nom = match.group(1)
        chemin = os.path.join(dossier, "img", nom)
        with open(chemin, "rb") as fichier:
            donnees = fichier.read()
        piece = Attachment.search([("res_model", "=", "knowledge.article"), ("res_id", "=", record.id),
                                   ("name", "=", nom)], limit=1)
        if piece:
            piece.write({champ_contenu: donnees if champ_contenu == "raw" else base64.b64encode(donnees)})
        else:
            piece = Attachment.create({"name": nom, champ_contenu: donnees if champ_contenu == "raw" else base64.b64encode(donnees), "res_model": "knowledge.article",
                                       "res_id": record.id, "mimetype": "image/png", "public": True})
        return "/web/image/%s" % piece.id

    return re.sub(r"\{\{img:([^}]+)\}\}", remplacer, corps)


def remplir(corps, valeurs):
    return re.sub(r"\{\{(\w+)\}\}", lambda m: valeurs.get(m.group(1), m.group(0)), corps)


valeurs = exemples()
print("\nExemples de cette base : banniere « %(banniere)s » (%(nb)s commerces), commerce « %(commerce)s » "
      "(code %(code)s)" % valeurs)
racine, cree = article(*RACINE)
print("%s : %s" % ("Créé" if cree else "Mis à jour", racine.name))
liens = []
for sequence, (dossier, titre, icone) in enumerate(GUIDES, start=1):
    chemin = os.path.join(DOSSIER, dossier)
    record, cree = article(titre, icone, racine, sequence)
    with open(os.path.join(chemin, "article.html"), encoding="utf-8") as fichier:
        corps = fichier.read()
    record.write({"body": images(record, chemin, remplir(corps, valeurs))})
    liens.append((record, titre, icone))
    print("  %s : %s" % ("Créé" if cree else "Mis à jour", titre))

# Accueil : les guides, avec un lien vers chacun
with open(os.path.join(DOSSIER, "accueil.html"), encoding="utf-8") as fichier:
    accueil = fichier.read()
cartes = "".join(
    '<li style="margin:6px 0;font-size:17px;"><a href="/knowledge/article/%s">%s %s</a></li>'
    % (record.id, icone, escape(titre)) for record, titre, icone in liens)
racine.write({"body": accueil.replace("{{guides}}", cartes)})

# L'application Connaissances s'appelle « Guide de l'utilisation » (dans toutes les langues installees)
menu = env.ref("knowledge.knowledge_menu_root", raise_if_not_found=False) or env["ir.ui.menu"].sudo().search(
    [("parent_id", "=", False), ("web_icon", "=like", "knowledge,%")], limit=1)
if menu:
    for code, _nom in env["res.lang"].get_installed():
        menu.sudo().with_context(lang=code).name = NOM_APPLICATION
    print("Application renommée : %s" % NOM_APPLICATION)
else:
    print("Menu de l'application Connaissances introuvable : nom inchangé.")

env.cr.commit()
print("\nTERMINÉ : %d guide(s) dans « %s »." % (len(liens), racine.name))
