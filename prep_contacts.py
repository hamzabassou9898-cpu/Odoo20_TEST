#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nettoie la liste Excel des clients et produit :
  - contacts_data.json      -> lu par import_contacts.py (import Odoo)
  - contacts_relecture.xlsx -> meme contenu, a relire / corriger dans Excel

Seules les colonnes "profil de contact" sont gardees. Les machines, accessoires,
contrats et ventes historiques ne vont PAS dans la fiche contact.

Usage : python3 prep_contacts.py "VOLCAN_LISTE_DUNE_CENTAINE_DE_CLIENTS.xlsx"
(necessite openpyxl : pip install openpyxl)
"""
import json
import os
import re
import sys
from collections import OrderedDict

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
INDICATIF = "418"   # indicatif ajoute aux numeros a 7 chiffres

# Index des colonnes de la feuille "POUR VOLCAN"
C = dict(saison=18, type=19, banniere=20, nom_legal=21,
         anciens=22, no_client=23, nom=24, notes=25, adresse=27, ville=28,
         cp=29, tel=30, autres_tel=31, contact=32, courriel=33, region=34,
         terme=35, route=36, livraison=59, prix=60)

# ---------- Bannieres : (societe parente, statut / sous-banniere) ----------
BANNIERES = {
    "HARNOIS CORPO": ("Harnois", "Corpo"),
    "HARNOIS AFFILIÉ": ("Harnois", "Affilié"),
    "FILGO CORPO": ("Filgo", "Corpo"),
    "FILGO AFFILIÉ": ("Filgo", "Affilié"),
    "PARKLAND MARCHÉ EXPRESS": ("Parkland", "Marché Express"),
    "PARKLAND DÉPAN EXPRESS": ("Parkland", "Dépan Express"),
    "BEAUSOIR": ("Beausoir", None),
    "SAGAMIE": ("Sagamie", None),
    "MARCO BERGERON": ("Marco Bergeron", None),
    "JEAN COUTU": ("Jean Coutu", None),
    "CANADIAN TIRE": ("Canadian Tire", None),
    "VAPOSHOP": ("Vaposhop", None),
}

# ---------- Termes de paiement -> (condition de paiement, remarque) ----------
TERMES = {
    "PPA": ("PPA", None),
    "PPA (BEAUDRY)": ("PPA", "Beaudry"),
    "PAS PPA (BEAUDRY)": (None, "PAS PPA (Beaudry)"),
    "NET 7 JOURS": ("Net 7 jours", None),
    "LIVRAISON/ NET 7 JOURS": ("Net 7 jours", "Paiement à la livraison / net 7 jours"),
    "CHÈQUE": ("Chèque", None),
    "DÉPÔT BANCAIRE": ("Dépôt bancaire", None),
}

# ---------- Prix -> liste de prix ----------
PRIX = {
    "RÉGULIER": "Prix régulier", "SPÉCIAUX": "Prix spéciaux",
    "GASPÉSIE": "Prix Gaspésie", "HARNOIS": "Prix Harnois",
    "PARKLAND": "Prix Parkland", "JEAN COUTU": "Prix Jean Coutu",
    "HIVER": "Prix hiver",
}

# ---------- Etiquette "Ville (secteur)" ----------
# Anciennes villes devenues secteurs de Quebec
SECTEURS_QUEBEC = {"beauport", "charlesbourg", "sainte-foy", "vanier", "val-bélair",
                   "lac st-charles"}
# Commerces notes seulement "Québec" : secteur d'apres l'adresse
SECTEUR_PAR_REF = {
    "MON134": "Vieux-Québec", "MON174": "Vieux-Québec",     # rue Sous-le-Fort
    "MON279": "Saint-Roch", "MON285": "Saint-Roch",         # St-Vallier O. / St-Joseph E.
    "MON220": "Saint-Sauveur",                              # 600, St-Vallier Ouest
    "MON241": "Limoilou",                                   # 3e rue
    "MON291": "Sainte-Foy",                                 # avenue des Hôtels
    "MON944": "Lebourgneuf",                                # boul. des Galeries
}


def endroit(ville, ref):
    """'Charlesbourg' -> 'Québec (Charlesbourg)' ; 'Lévis (St-Nicolas)' inchange."""
    if not ville:
        return None
    if ville.lower() in SECTEURS_QUEBEC:
        return f"Québec ({ville})"
    if ville == "Québec" and ref in SECTEUR_PAR_REF:
        return f"Québec ({SECTEUR_PAR_REF[ref]})"
    return ville


FONCTIONS = {
    "prop": "Propriétaire", "proprio": "Propriétaire", "gér": "Gérant(e)",
    "dir": "Direction", "directeur": "Directeur", "resto": "Restaurant",
    "comm": "Commandes", "compt": "Comptabilité", "ass": "Assistant(e)",
    "resp": "Responsable", "coord": "Coordination", "admin": "Administration",
    "chef": "Chef", "fille": "Fille de la propriétaire",
    "casse-croûte": "Casse-croûte",
}


def txt(v):
    """Valeur de cellule -> texte propre (None si vide)."""
    if v is None:
        return None
    if isinstance(v, float):
        v = str(int(v)) if v.is_integer() else str(v)
    v = str(v).replace("\xa0", " ").strip()
    return v or None


def one_line(v):
    v = txt(v)
    return re.sub(r"\s+", " ", v) if v else None


def norm_tel(num):
    """'667-2653' -> '418-667-2653' ; garde 418/581/819/... s'ils sont presents."""
    d = re.sub(r"\D", "", num)
    if len(d) == 7:
        d = INDICATIF + d
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) != 10:
        return None
    return f"{d[:3]}-{d[3:6]}-{d[6:]}"


TEL_RE = re.compile(r"(?:\d{3}\s*-+\s*)?\d{3}\s*-+\s*\d{4}")


def extraire_tels(texte):
    """Liste de (numero normalise, libelle) depuis un texte libre."""
    out = []
    if not texte:
        return out
    for ligne in texte.split("\n"):
        matches = list(TEL_RE.finditer(ligne))
        for i, m in enumerate(matches):
            fin = matches[i + 1].start() if i + 1 < len(matches) else len(ligne)
            libelle = ligne[m.end():fin].strip(" ()")
            n = norm_tel(m.group())
            if n:
                out.append((n, libelle))
    return out


def extension(texte):
    """'469-3676(#105-cuisine)' -> poste du 1er numero, s'il suit directement."""
    m = re.match(r"\s*(?:\d{3}\s*-+\s*)?\d{3}\s*-+\s*\d{4}\s*#\s*(\d+)", texte or "")
    return m.group(1) if m else None


def extraire_courriels(texte):
    return re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*", texte or "")


def decouper_hors_parentheses(s):
    """Coupe sur ',' et ' et ' en ignorant le contenu des parentheses."""
    morceaux, prof, cur, i = [], 0, "", 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            prof += 1
        elif ch == ")":
            prof = max(0, prof - 1)
        if prof == 0 and (ch == "," or s[i:i + 4] == " et "):
            morceaux.append(cur)
            cur = ""
            i += 4 if ch == " " else 1
            continue
        cur += ch
        i += 1
    morceaux.append(cur)
    return [m.strip() for m in morceaux if m.strip()]


def fonction(code):
    code = code.strip().strip(".").strip()
    return FONCTIONS.get(code.lower(), code)


def extraire_contacts(texte):
    """'M. Alain Contant(prop), Mme Émilie X(resto)' -> liste de personnes."""
    texte = one_line(texte)
    if not texte:
        return []
    personnes = []
    for m in decouper_hors_parentheses(texte):
        fonc = None
        pm = re.search(r"\(([^)]*)\)\s*\w?$", m)
        if pm:
            fonc = pm.group(1)
            m = m[:pm.start()].strip()
        titre = None
        tm = re.match(r"^(?:Mme\.?\s*|M(?:\.\s*|\s+))", m)
        if tm:
            titre = "Madame" if m.startswith("Mme") else "Monsieur"
            m = m[tm.end():].strip()
        # "Mme Annie, compt" / "M. Éric Huard, directeur" : fonction du precedent
        if not titre and personnes and m and m[0].islower():
            personnes[-1]["fonction"] = fonction(m)
            continue
        if not m:
            continue
        personnes.append({"nom": m[0].upper() + m[1:], "titre": titre,
                          "fonction": fonction(fonc) if fonc else None})
    return personnes


def cle_banniere(v):
    return one_line(v).upper() if v else None


def nettoyer_region(v):
    v = one_line(v)
    return re.sub(r"\s*/\s*", " – ", v) if v else None


def nom_commun(noms):
    """Noms des lignes d'un meme # client -> (nom fiche, emplacements)."""
    noms = list(OrderedDict.fromkeys(noms))
    if len(noms) == 1:
        return noms[0], []
    base = [re.sub(r"\s*\([^)]*\)\s*$", "", n).strip() for n in noms]
    nom = min(base, key=len)
    if all(b.upper() == nom.upper() for b in base):
        empl = [n[len(b):].strip(" ()") for n, b in zip(noms, base) if n != b]
        return nom, [e for e in empl if e]
    return noms[0], noms[1:]


def main(src):
    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb.worksheets[0]
    lignes = [r for r in ws.iter_rows(min_row=2, values_only=True)
              if txt(r[C["nom"]]) or txt(r[C["no_client"]])]

    groupes = OrderedDict()
    for r in lignes:
        ref = txt(r[C["no_client"]]) or txt(r[C["nom"]])
        groupes.setdefault(ref, []).append(r)

    clients, avert = [], []
    for ref, rows in groupes.items():
        r0 = rows[0]

        def premier(col, rows=rows):
            for r in rows:
                if txt(r[C[col]]):
                    return txt(r[C[col]])
            return None

        # Nom : 1re ligne = nom ; lignes suivantes = consignes (notes)
        noms, notes = [], []
        for r in rows:
            parts = txt(r[C["nom"]]).split("\n")
            noms.append(re.sub(r"\s+", " ", parts[0]).strip())
            notes += [p.strip(" *") for p in parts[1:] if p.strip(" *")]
        nom, emplacements = nom_commun(noms)

        for r in rows:
            n = one_line(r[C["notes"]])
            if n and n not in notes:
                notes.append(n)

        ban_key = cle_banniere(premier("banniere"))
        parent, statut = (None, None)
        if ban_key:
            if ban_key not in BANNIERES:
                avert.append(f"{ref}: banniere inconnue {ban_key!r}")
            parent, statut = BANNIERES.get(ban_key, (ban_key.title(), None))

        tel_txt = premier("tel")
        autres_txt = premier("autres_tel")
        tels = extraire_tels(tel_txt) + extraire_tels(autres_txt)
        phone = tels[0][0] if tels else None
        ext = extension(tel_txt)
        if phone and ext:
            phone += f" #{ext}"

        courriels = list(OrderedDict.fromkeys(extraire_courriels(premier("courriel"))))

        terme_brut = one_line(premier("terme"))
        terme, terme_note = (None, None)
        if terme_brut:
            k = terme_brut.upper()
            if k not in TERMES:
                avert.append(f"{ref}: terme inconnu {terme_brut!r}")
            terme, terme_note = TERMES.get(k, (None, terme_brut))

        prix_brut = one_line(premier("prix"))
        pricelist = PRIX.get(prix_brut.upper()) if prix_brut else None
        if prix_brut and not pricelist:
            avert.append(f"{ref}: prix inconnu {prix_brut!r}")



        contacts = extraire_contacts(premier("contact"))
        # Rattacher les cellulaires "cell-Prenom" a la bonne personne
        for p in contacts:
            prenom = p["nom"].split()[0].lower()
            for n, lib in tels:
                if prenom and prenom in lib.lower() and "cel" in lib.lower():
                    p["mobile"] = n
                    break

        route = one_line(premier("route"))
        if route:
            route = f"Route {route}" if route.isdigit() else route.capitalize()

        # Ce qui n'a pas de champ natif dans Odoo -> en tete des notes
        entete = []
        nom_legal = one_line(premier("nom_legal"))
        if nom_legal and nom_legal.upper() != nom.upper():
            entete.append(f"Nom légal : {nom_legal}")
        if one_line(premier("anciens")):
            entete.append(f"Anciens # client : {one_line(premier('anciens'))}")
        # detail utile seulement s'il y a plus qu'un simple numero (postes, 2e numero...)
        if one_line(tel_txt) and (len(extraire_tels(tel_txt)) > 1
                                  or TEL_RE.sub("", one_line(tel_txt)).strip(" ()-")):
            entete.append(f"Téléphone (détail) : {one_line(tel_txt)}")
        if one_line(autres_txt):
            entete.append(f"Autres numéros : {one_line(autres_txt)}")
        if len(courriels) > 1:
            entete.append("Autres courriels : " + ", ".join(courriels[1:]))
        if terme_note:
            entete.append(f"Paiement : {terme_note}")
        if statut:
            entete.append(f"Bannière : {statut}")
        if route:
            entete.append(f"Route livraison : {route}")
        if (one_line(premier("livraison")) or "").upper() == "FRAIS":
            entete.append("Frais de livraison à facturer")
        if emplacements:
            entete.append("Emplacements : " + " ; ".join(emplacements))
        notes = entete + notes

        clients.append(OrderedDict(
            ref=ref,
            nom=nom,
            parent=parent,
            statut_banniere=statut,
            street=one_line(premier("adresse")),
            city=one_line(premier("ville")),
            endroit=endroit(one_line(premier("ville")), ref),
            zip=one_line(premier("cp")),
            phone=phone,
            email=courriels[0] if courriels else None,
            terme=terme,
            pricelist=pricelist,
            region=nettoyer_region(premier("region")),
            route=route,
            saison=premier("saison"),
            type=premier("type"),
            notes=notes,
            contacts=contacts,
            nb_lignes=len(rows),
        ))

    with open(os.path.join(HERE, "contacts_data.json"), "w", encoding="utf-8") as f:
        json.dump(clients, f, ensure_ascii=False, indent=1)

    # Version Excel pour relecture
    out = openpyxl.Workbook()
    sh = out.active
    sh.title = "Clients"
    cols = [("ref", "Référence (# client)"), ("nom", "Nom"),
            ("parent", "Société parente (bannière)"), ("statut_banniere", "Statut bannière"),
            ("street", "Rue"), ("city", "Ville"), ("zip", "Code postal"),
            ("endroit", "Étiquette Ville (secteur)"),
            ("phone", "Téléphone"), ("email", "Courriel"), ("terme", "Conditions de paiement"),
            ("pricelist", "Liste de prix"),
            ("notes", "Notes"), ("contacts", "Contacts-personnes"),
            ("nb_lignes", "Nb lignes Excel (machines)")]
    sh.append([c[1] for c in cols])
    for cl in clients:
        row = []
        for k, _ in cols:
            v = cl[k]
            if k == "notes":
                v = "\n".join(v)
            elif k == "contacts":
                v = "\n".join(" ".join(filter(None, [p["titre"], p["nom"],
                              f"({p['fonction']})" if p["fonction"] else None,
                              p.get("mobile")])) for p in v)
            row.append(v)
        sh.append(row)
    sh.freeze_panes = "C2"
    for col in sh.columns:
        sh.column_dimensions[col[0].column_letter].width = 22
    out.save(os.path.join(HERE, "contacts_relecture.xlsx"))

    print(f"{len(lignes)} lignes Excel -> {len(clients)} fiches clients, "
          f"{sum(len(c['contacts']) for c in clients)} contacts-personnes, "
          f"{len({c['parent'] for c in clients if c['parent']})} societes parentes.")
    for a in avert:
        print("AVERTISSEMENT", a)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
