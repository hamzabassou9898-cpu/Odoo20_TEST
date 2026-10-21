/** @odoo-module **/
/* Page du client : chaque case du formulaire d'ouverture de compte s'enregistre toute seule des qu'il la
 * remplit (meme principe que le contrat de location). Seule la case modifiee est envoyee, les envois
 * partent l'un apres l'autre : un envoi plus ancien ne peut jamais effacer ce que le client vient de taper.
 * Cases obligatoires (s'il y en a) : en rouge tant qu'elles sont vides, liste a jour en direct, et la
 * signature attend qu'elles soient remplies (le bouton de signature d'Odoo reste bloque apres une erreur). */
let fileEnvois = Promise.resolve();

function afficherEtat(texte, classe) {
    const etat = document.getElementById("ouverture_etat_enregistrement");
    if (etat) {
        etat.textContent = texte;
        etat.className = `small mt-2 ${classe}`;
    }
}

function enregistrerChamp(formulaire, champ) {
    const donnees = new FormData();
    for (const nom of ["csrf_token", "access_token"]) {
        const cache = formulaire.querySelector(`input[name="${nom}"]`);
        if (cache) {
            donnees.append(nom, cache.value);
        }
    }
    donnees.append(champ.name, champ.value);
    afficherEtat("Enregistrement…", "text-muted");
    fileEnvois = fileEnvois
        .catch(() => {})
        .then(() => fetch(formulaire.action, { method: "POST", body: donnees, credentials: "same-origin" }))
        .then((reponse) => {
            if (reponse.status === 409) {
                // Deja signe (autre onglet) : on le dit, sans recharger la page pendant que le client ecrit
                afficherEtat("Ce formulaire est déjà signé : rechargez la page pour voir la demande signée.", "text-warning");
            } else if (!reponse.ok) {
                throw new Error(String(reponse.status));
            } else {
                afficherEtat("✓ Vos réponses sont enregistrées.", "text-success");
            }
        })
        .catch(() => {
            afficherEtat("Réponse non enregistrée : vérifiez votre connexion puis réessayez.", "text-danger");
        });
    return fileEnvois;
}

/** Cases obligatoires vides : en rouge, et la liste au-dessus de la signature. */
function verifierObligatoires() {
    const vides = [];
    for (const champ of document.querySelectorAll(".o_ouverture_saisie[data-obligatoire]")) {
        const vide = !champ.value.trim();
        champ.classList.toggle("o_ouverture_manquant", vide);
        champ.style.background = vide ? "#fdecec" : "#f3f7ff";
        champ.style.borderBottomColor = vide ? "#dc3545" : "#2f6fd1";
        if (vide) {
            vides.push(champ);
        }
    }
    const bloc = document.getElementById("ouverture_manquants");
    if (bloc) {
        bloc.classList.toggle("d-none", !vides.length);
        const liste = bloc.querySelector(".o_ouverture_liste_manquants");
        if (liste) {
            liste.textContent = vides.map((c) => c.dataset.obligatoire).join(", ");
        }
    }
    return vides;
}

document.addEventListener("change", (ev) => {
    const champ = ev.target.closest(".o_ouverture_saisie");
    const formulaire = champ && champ.name && document.getElementById("ouverture_client_form");
    if (formulaire && (champ.type !== "radio" || champ.checked)) {
        enregistrerChamp(formulaire, champ);
    }
});

document.addEventListener("input", (ev) => {
    if (ev.target.closest(".o_ouverture_saisie[data-obligatoire]")) {
        verifierObligatoires();
    }
});

// Avant la signature : cases obligatoires remplies (sinon on montre la premiere) et derniere reponse enregistree
document.addEventListener("click", async (ev) => {
    const bouton = ev.target.closest("#signature .o_portal_sign_submit");
    if (!bouton || bouton.dataset.ouvertureVerifie) {
        return;
    }
    const vides = verifierObligatoires();
    ev.preventDefault();
    ev.stopImmediatePropagation();
    if (vides.length) {
        vides[0].scrollIntoView({ behavior: "smooth", block: "center" });
        vides[0].focus();
        return;
    }
    await fileEnvois;
    bouton.dataset.ouvertureVerifie = "1";
    bouton.click();
    delete bouton.dataset.ouvertureVerifie;
}, true);

document.addEventListener("DOMContentLoaded", verifierObligatoires);
