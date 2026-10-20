/** @odoo-module **/
/* Page du client : chaque case du formulaire d'ouverture de compte s'enregistre toute seule des qu'il la
 * remplit (meme principe que le contrat de location). Seule la case modifiee est envoyee, les envois
 * partent l'un apres l'autre : un envoi plus ancien ne peut jamais effacer ce que le client vient de taper. */
let fileEnvois = Promise.resolve();

function enregistrerChamp(formulaire, champ) {
    const donnees = new FormData();
    for (const nom of ["csrf_token", "access_token"]) {
        const cache = formulaire.querySelector(`input[name="${nom}"]`);
        if (cache) {
            donnees.append(nom, cache.value);
        }
    }
    donnees.append(champ.name, champ.value);
    fileEnvois = fileEnvois
        .catch(() => {})
        .then(() => fetch(formulaire.action, { method: "POST", body: donnees, credentials: "same-origin" }));
    return fileEnvois;
}

document.addEventListener("change", (ev) => {
    const champ = ev.target.closest(".o_ouverture_saisie");
    const formulaire = champ && champ.name && document.getElementById("ouverture_client_form");
    if (formulaire && (champ.type !== "radio" || champ.checked)) {
        enregistrerChamp(formulaire, champ);
    }
});
