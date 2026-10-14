/** @odoo-module **/
/* Page du client : les cases du contrat (initiales, compagnie, caution, proprietaire de l'immeuble)
 * s'enregistrent toutes seules des qu'il les remplit ; il signe ensuite avec « Accepter et signer ».
 * Seule la case modifiee est envoyee, et les envois partent l'un apres l'autre : un envoi plus ancien
 * ne peut jamais effacer ce que le client vient de taper. */
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
    const champ = ev.target.closest(".o_contrat_saisie");
    const formulaire = champ && champ.name && document.getElementById("contrat_client_form");
    if (formulaire && (champ.type !== "radio" || champ.checked)) {
        enregistrerChamp(formulaire, champ);
    }
});
