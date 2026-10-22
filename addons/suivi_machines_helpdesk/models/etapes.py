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


def ou(termes):
    """Domaine « l'un ou l'autre » a partir d'une liste de termes."""
    return ["|"] * (len(termes) - 1) + list(termes)


def domaine_nom(mot, champ="name"):
    return ou([(champ, "ilike", m) for m in mots(mot)])


def domaine_ferme(champ="stage_id.name"):
    return ou([(champ, "ilike", m) for m in MOTS_FERME])
