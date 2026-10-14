/** @odoo-module **/
/* Page du client : les cases du contrat (initiales, compagnie, caution, proprietaire de l'immeuble)
 * s'enregistrent toutes seules des qu'il les remplit ; il signe ensuite avec « Accepter et signer ». */
function enregistrerContrat(formulaire) {
    return fetch(formulaire.action, { method: "POST", body: new FormData(formulaire), credentials: "same-origin" });
}

document.addEventListener("change", (ev) => {
    const champ = ev.target.closest(".o_contrat_saisie");
    const formulaire = champ && document.getElementById("contrat_client_form");
    if (formulaire) {
        enregistrerContrat(formulaire);
    }
});
