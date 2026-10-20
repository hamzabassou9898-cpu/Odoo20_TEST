import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useChart } from "@web/core/utils/chart_hook";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, t, useProps } from "@odoo/owl";

const GRILLE = { color: "#eef0f4" };
// Glisser une tache contre le bord droit (gauche) de l'ecran : periode suivante (precedente) apres ce delai
const MARGE_BORD = 70;
const DELAI_BORD = 700;
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
                             technicien_id: 0, type_tache: "", bord: "" });
        this.glissee = null;
        this.minuterieBord = null;
        this.surBord = (ev) => this.glisserVersBord(ev);
        onWillStart(() => this.charger());
        // Fin du glisser n'importe ou (la carte d'origine peut avoir disparu en changeant de semaine)
        this.surFin = () => setTimeout(() => this.finGlisser());
        onMounted(() => {
            window.addEventListener("dragover", this.surBord);
            window.addEventListener("dragend", this.surFin);
            window.addEventListener("drop", this.surFin);
        });
        onWillUnmount(() => {
            window.removeEventListener("dragover", this.surBord);
            window.removeEventListener("dragend", this.surFin);
            window.removeEventListener("drop", this.surFin);
            this.arreterBord();
        });
    }

    async charger(jour = null) {
        this.state.chargement = true;
        // Seule la derniere demande s'affiche (un changement de semaine en cours ne remplace pas la suivante)
        const numero = (this.numeroChargement = (this.numeroChargement || 0) + 1);
        try {
            const donnees = await this.orm.call("portail.tache", "donnees_planning", [
                jour || false, this.state.periode, this.state.technicien_id || false, this.state.type_tache || false,
            ]);
            if (numero === this.numeroChargement) {
                this.state.donnees = donnees;
            }
        } finally {
            if (numero === this.numeroChargement) {
                this.state.chargement = false;
            }
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

    /** Cartes d'une case (technicien x jour) : index construit une fois par chargement, pas a chaque survol. */
    cartes(ligne, jour) {
        const donnees = this.state.donnees;
        if (this.indexDonnees !== donnees) {
            this.indexDonnees = donnees;
            this.indexCartes = new Map();
            for (const carte of donnees.cartes) {
                const cle = `${carte.technicien_id}-${carte.jour}`;
                if (!this.indexCartes.has(cle)) {
                    this.indexCartes.set(cle, []);
                }
                this.indexCartes.get(cle).push(carte);
            }
        }
        return this.indexCartes.get(`${ligne.id}-${jour.iso}`) || [];
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
        this.arreterBord();
        if (!carte || (carte.technicien_id === ligne.id && carte.jour === jour.iso)) {
            return;
        }
        try {
            await this.orm.call("portail.tache", "deplacer_planning", [carte.id, ligne.id, jour.iso]);
            this.notification.add(`« ${carte.titre} » → ${ligne.nom}, ${jour.titre}`, { type: "success" });
        } finally {
            // On reste sur la periode ou la tache vient d'etre posee
            await this.charger(jour.iso);
        }
    }

    finGlisser() {
        this.glissee = null;
        this.state.survol = "";
        this.arreterBord();
    }

    /** Tache tenue contre un bord de l'ecran : on passe a la periode suivante / precedente, et on continue
     * tant qu'elle y reste ; la tache se depose ensuite dans la nouvelle semaine. */
    glisserVersBord(ev) {
        if (!this.glissee) {
            return;
        }
        const bord = ev.clientX >= window.innerWidth - MARGE_BORD ? "suivante"
            : ev.clientX <= MARGE_BORD ? "precedente" : "";
        if (bord === this.state.bord) {
            return;
        }
        this.arreterBord();
        this.state.bord = bord;
        if (bord) {
            this.minuterieBord = setTimeout(() => this.changerDeSemaine(bord), DELAI_BORD);
        }
    }

    async changerDeSemaine(bord) {
        this.minuterieBord = null;
        const jeton = this.jetonBord;
        if (!this.glissee || this.state.bord !== bord) {
            return;
        }
        await this.charger(this.state.donnees[bord]);
        // Toujours contre le meme bord (et pas lachee entre-temps) : on continue
        if (jeton === this.jetonBord && this.glissee && this.state.bord === bord) {
            this.minuterieBord = setTimeout(() => this.changerDeSemaine(bord), DELAI_BORD * 2);
        }
    }

    arreterBord() {
        clearTimeout(this.minuterieBord);
        this.minuterieBord = null;
        this.jetonBord = (this.jetonBord || 0) + 1;
        this.state.bord = "";
    }

    async ouvrir(carte) {
        const action = await this.orm.call("portail.tache", "action_ouvrir", [[carte.id]]);
        if (action) {
            await this.actionService.doAction(action);
        }
    }
}

registry.category("actions").add("suivi_pilotage_planning", PlanningSemaine);
