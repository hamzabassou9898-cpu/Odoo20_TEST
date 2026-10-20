import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useChart } from "@web/core/utils/chart_hook";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";

const GRILLE = { color: "#eef0f4" };
const AXE = { color: "#94a3b8", font: { size: 11 } };

/** Un graphique Chart.js (natif Odoo) : redessine seulement quand ses donnees changent. */
export class GraphiquePlanning extends Component {
    static template = "suivi_machines_pilotage.GraphiquePlanning";
    props = useProps({ type: t.string(), donnees: t.object() });

    setup() {
        this.chart = useChart(() => this.config());
    }

    config() {
        const d = this.props.donnees;
        const legende = { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, font: { size: 12 } } };
        if (this.props.type === "charge") {
            return {
                type: "bar",
                data: { labels: d.etiquettes, datasets: d.series.map((s) => ({
                    label: s.nom, data: s.valeurs, backgroundColor: s.couleur, borderRadius: 4, maxBarThickness: 12,
                })) },
                options: { maintainAspectRatio: false, plugins: { legend: legende },
                    scales: { x: { grid: { display: false }, ticks: AXE },
                              y: { beginAtZero: true, ticks: { ...AXE, precision: 0 }, grid: GRILLE } } },
            };
        }
        if (this.props.type === "repartition") {
            return {
                type: "doughnut",
                data: { labels: d.map((r) => r.nom), datasets: [{
                    data: d.map((r) => r.valeur), backgroundColor: d.map((r) => r.couleur), borderColor: "#fff",
                }] },
                options: { maintainAspectRatio: false, cutout: "60%", plugins: { legend: { display: false } } },
            };
        }
        const ligne = (label, data, couleur) => ({
            label, data, borderColor: couleur, backgroundColor: couleur, pointBackgroundColor: "#fff",
            pointBorderColor: couleur, pointRadius: 3.5, pointBorderWidth: 2, borderWidth: 2.5, tension: 0,
        });
        return {
            type: "line",
            data: { labels: d.etiquettes, datasets: [
                ligne("Planifiées", d.planifiees, "#a78bfa"), ligne("Faites", d.faites, "#ec4899"),
            ] },
            options: { maintainAspectRatio: false, plugins: { legend: legende },
                scales: { x: { grid: { display: false }, ticks: AXE },
                          y: { beginAtZero: true, ticks: { ...AXE, precision: 0 }, grid: GRILLE } } },
        };
    }
}

/** Pilotage : planning (jour, semaine, mois) techniciens x jours, indicateurs, graphiques, glisser-deposer. */
export class PlanningSemaine extends Component {
    static template = "suivi_machines_pilotage.PlanningSemaine";
    static components = { GraphiquePlanning };
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.state = proxy({ donnees: null, chargement: true, survol: "", periode: "semaine",
                             technicien_id: 0, type_tache: "" });
        this.glissee = null;
        onWillStart(() => this.charger());
    }

    async charger(jour = null) {
        this.state.chargement = true;
        try {
            this.state.donnees = await this.orm.call("portail.tache", "donnees_planning", [
                jour || false, this.state.periode, this.state.technicien_id || false, this.state.type_tache || false,
            ]);
        } finally {
            this.state.chargement = false;
        }
    }

    changerPeriode(periode) {
        this.state.periode = periode;
        return this.charger(this.state.donnees?.reference);
    }

    filtrer(champ, ev) {
        const valeur = ev.target.value;
        this.state[champ] = champ === "technicien_id" ? parseInt(valeur || 0) : valeur;
        return this.charger(this.state.donnees?.reference);
    }

    largeurGrille() {
        const n = this.state.donnees.jours.length;
        const colonne = n > 7 ? "minmax(42px, 1fr)" : "minmax(120px, 1fr)";
        return `grid-template-columns: 190px repeat(${n}, ${colonne});`;
    }

    cartes(ligne, jour) {
        return this.state.donnees.cartes.filter((c) => c.technicien_id === ligne.id && c.jour === jour.iso);
    }

    debutGlisser(ev, carte) {
        this.glissee = carte;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(carte.id));
    }

    survoler(ev, ligne, jour) {
        if (this.glissee) {
            ev.preventDefault();
            this.state.survol = `${ligne.id}-${jour.iso}`;
        }
    }

    async deposer(ev, ligne, jour) {
        ev.preventDefault();
        const carte = this.glissee;
        this.glissee = null;
        this.state.survol = "";
        if (!carte || (carte.technicien_id === ligne.id && carte.jour === jour.iso)) {
            return;
        }
        try {
            await this.orm.call("portail.tache", "deplacer_planning", [carte.id, ligne.id, jour.iso]);
            this.notification.add(`« ${carte.titre} » → ${ligne.nom}, ${jour.titre}`, { type: "success" });
        } finally {
            await this.charger(this.state.donnees.debut);
        }
    }

    finGlisser() {
        this.glissee = null;
        this.state.survol = "";
    }

    async ouvrir(carte) {
        const action = await this.orm.call("portail.tache", "action_ouvrir", [[carte.id]]);
        if (action) {
            await this.actionService.doAction(action);
        }
    }
}

registry.category("actions").add("suivi_pilotage_planning", PlanningSemaine);
