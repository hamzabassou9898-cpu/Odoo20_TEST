# -*- coding: utf-8 -*-
"""Mots reconnus dans le nom d'une etape de l'Assistance, en francais ET en anglais : Odoo cree ses
etapes en anglais (New, Solved, Cancelled) et l'interface les affiche traduites (Nouveau, Resolu...).
Les actions planifiees tournent souvent en anglais : chercher un seul mot francais ne suffit pas."""

SYNONYMES = {
    "nouveau": ("nouveau", "new"),
    "résolu": ("résolu", "resolu", "solved"),
    "annul": ("annul", "cancel"),
    "clôtur": ("clôtur", "clotur", "closed"),
    "réparation": ("réparation", "reparation", "repair"),
    "entretien": ("entretien", "maintenance"),
}
# Etapes qui ferment un ticket (Resolu, Cloture, Annule)
MOTS_FERME = SYNONYMES["résolu"] + SYNONYMES["clôtur"] + SYNONYMES["annul"]
REGEX_FERME = "(%s)" % "|".join(MOTS_FERME)
REGEX_ANNULE = "(%s)" % "|".join(SYNONYMES["annul"])


def mots(mot):
    return SYNONYMES.get(mot, (mot,))


def contient(nom, mot):
    """Le nom d'etape contient-il le mot (ou un de ses equivalents) ?"""
    nom = (nom or "").lower()
    return any(m in nom for m in mots(mot))


def est_ferme(nom):
    nom = (nom or "").lower()
    return any(m in nom for m in MOTS_FERME)


# Monroy nomme ses etapes en francais : c'est ce nom qui compte. Une etape copiee d'une etape native garde
# sa traduction anglaise (ex. « Solved ») : lue en anglais (tache planifiee), elle fermait le ticket a tort.
LANGUES_ETAPES = ("fr_CA", "fr_FR")


def nom_etape(etape):
    """Nom de l'etape en francais si la langue est installee, sinon dans la langue courante."""
    if not etape:
        return ""
    installees = {code for code, _nom in etape.env["res.lang"].get_installed()}
    for code in LANGUES_ETAPES:
        if code in installees:
            return etape.with_context(lang=code).name or ""
    return etape.name or ""


def etapes_selon(Etape, test):
    """Etapes (archivees comprises) dont le nom francais passe le test : une seule regle pour toutes les
    recherches, quelle que soit la langue de l'utilisateur ou de la tache planifiee."""
    return Etape.with_context(active_test=False).search([]).filtered(lambda etape: test(nom_etape(etape)))


def etapes_contenant(Etape, mot):
    """Etapes actives dont le nom francais contient le mot (ou un equivalent), dans l'ordre des etapes."""
    return Etape.search([]).filtered(lambda etape: contient(nom_etape(etape), mot))


def domaine_ouvert(champ="stage_id"):
    """Pas d'etape, ou une etape qui ne ferme pas le ticket."""
    return ["|", (champ, "=", False), "!", (champ + ".etape_fermee", "=", True)]


def domaine_nouveau(champ="stage_id"):
    """Pas encore d'etape, ou l'etape « Nouveau »."""
    return ["|", (champ, "=", False), (champ + ".etape_nouvelle", "=", True)]
