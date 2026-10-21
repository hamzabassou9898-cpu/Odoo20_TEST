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
                // Deja signe (ex. dans un autre onglet) : on le dit clairement, sans recharger la page tout seul
                afficherDejaSigne();
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

/** Page restee ouverte alors que le formulaire est deja signe : bandeau bien visible en haut. */
function afficherDejaSigne() {
    afficherEtat("Ce formulaire est déjà signé.", "text-warning");
    if (document.getElementById("ouverture_deja_signe")) {
        return;
    }
    const bandeau = document.createElement("div");
    bandeau.id = "ouverture_deja_signe";
    bandeau.className = "alert alert-warning d-flex flex-wrap align-items-center justify-content-between gap-2";
    bandeau.style.cssText = "position: sticky; top: 0; z-index: 10;";
    const texte = document.createElement("span");
    texte.textContent = "Ce formulaire a déjà été signé (peut-être dans un autre onglet). Vos dernières modifications n'ont pas été enregistrées.";
    const bouton = document.createElement("a");
    bouton.className = "btn btn-primary btn-sm";
    bouton.href = window.location.pathname + window.location.search;
    bouton.textContent = "Voir la demande signée";
    bandeau.append(texte, bouton);
    const carte = document.querySelector(".o_ouverture_page .col-lg-9 .card") || document.body;
    carte.prepend(bandeau);
    bandeau.scrollIntoView({ behavior: "smooth", block: "start" });
}

/** Cases obligatoires vides : en rouge, et la liste au-dessus de la signature. Choix (Forme, Paiement...) :
 * le groupe est rempli des qu'une case est cochee. */
let tentativeSignature = false;   // apres un clic sur « Accepter et signer » : toutes les cases vides en rouge

function enRouge(champ) {
    return tentativeSignature || champ.dataset.touche === "1";
}

function verifierObligatoires() {
    const vides = [];
    const groupesVus = new Set();
    for (const champ of document.querySelectorAll(".o_ouverture_saisie[data-obligatoire]")) {
        if (champ.type === "radio") {
            if (groupesVus.has(champ.name)) {
                continue;
            }
            groupesVus.add(champ.name);
            const groupe = document.querySelectorAll(`.o_ouverture_saisie[type="radio"][name="${champ.name}"]`);
            const vide = ![...groupe].some((c) => c.checked);
            for (const c of groupe) {
                const etiquette = c.closest("label");
                if (etiquette) {
                    etiquette.style.color = vide && tentativeSignature ? "#dc3545" : "";
                }
            }
            if (vide) {
                vides.push(champ);
            }
            continue;
        }
        const vide = !champ.value.trim();
        const rouge = vide && enRouge(champ);
        champ.classList.toggle("o_ouverture_manquant", rouge);
        champ.style.background = rouge ? "#fdecec" : "#f3f7ff";
        champ.style.borderBottomColor = rouge ? "#dc3545" : "#2f6fd1";
        champ.title = rouge ? "Case obligatoire : à remplir avant de signer" : "";
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

// Case obligatoire quittee vide : en rouge tout de suite
document.addEventListener("focusout", (ev) => {
    const champ = ev.target.closest(".o_ouverture_saisie[data-obligatoire]");
    if (champ && champ.type !== "radio") {
        champ.dataset.touche = "1";
        verifierObligatoires();
    }
});

for (const evenement of ["input", "change"]) {
    document.addEventListener(evenement, (ev) => {
        if (ev.target.closest(".o_ouverture_saisie[data-obligatoire]")) {
            verifierObligatoires();
        }
    });
}

// Avant la signature : cases obligatoires remplies (sinon on montre la premiere) et derniere reponse enregistree
document.addEventListener("click", async (ev) => {
    const bouton = ev.target.closest("#signature .o_portal_sign_submit");
    if (!bouton || bouton.dataset.ouvertureVerifie) {
        return;
    }
    tentativeSignature = true;
    const vides = verifierObligatoires();
    ev.preventDefault();
    ev.stopImmediatePropagation();
    if (vides.length) {
        // On montre au client ce qu'il a oublie : la liste, puis la premiere case
        const bloc = document.getElementById("ouverture_manquants");
        if (bloc) {
            bloc.classList.replace("alert-warning", "alert-danger");
            bloc.querySelector(".o_ouverture_intro_manquants").textContent =
                vides.length === 1 ? "Il manque une case obligatoire (en rouge) : " : `Il manque ${vides.length} cases obligatoires (en rouge) : `;
        }
        vides[0].scrollIntoView({ behavior: "smooth", block: "center" });
        vides[0].focus({ preventScroll: true });
        return;
    }
    await fileEnvois;
    bouton.dataset.ouvertureVerifie = "1";
    bouton.click();
    delete bouton.dataset.ouvertureVerifie;
}, true);

document.addEventListener("DOMContentLoaded", () => {
    verifierObligatoires();
    // Demande signee : on montre le message de confirmation en haut, meme si le navigateur voulait
    // revenir en bas de la page (la ou le client vient de signer)
    const confirmation = document.getElementById("ouverture_confirmation");
    if (confirmation) {
        if ("scrollRestoration" in history) {
            history.scrollRestoration = "manual";
        }
        window.scrollTo(0, 0);
        confirmation.scrollIntoView({ block: "start" });
    }
});

/* Onglet du formulaire reste ouvert pendant que la demande est signee ailleurs (autre onglet, lien du
 * courriel, « Page du client ») : en revenant sur l'onglet, il le voit et montre la demande signee. */
async function verifierSiSigneAilleurs() {
    const formulaire = document.getElementById("ouverture_client_form");
    if (document.hidden || !formulaire || !document.querySelector(".o_ouverture_saisie")) {
        return;   // page deja signee (rien a remplir) ou onglet cache
    }
    const jeton = formulaire.querySelector('input[name="access_token"]');
    const url = formulaire.action.replace(/\/champ$/, "/etat");
    try {
        const reponse = await fetch(url, {
            method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: { access_token: jeton ? jeton.value : "" } }),
        });
        const donnees = await reponse.json();
        if (donnees.result && donnees.result.modifiable === false) {
            window.location.reload();
        }
    } catch {
        // pas de connexion : on reessaiera au prochain retour sur l'onglet
    }
}
document.addEventListener("visibilitychange", verifierSiSigneAilleurs);
window.addEventListener("focus", verifierSiSigneAilleurs);
