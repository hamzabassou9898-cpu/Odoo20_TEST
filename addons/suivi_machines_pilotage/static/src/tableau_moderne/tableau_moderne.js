import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

const DELAI_RAFRAICHIR = 120000;

/** Pilotage : vue d'ensemble moderne (la vue « Toutes les cartes » reste disponible). */
export class TableauModerne extends Component {
    static template = "suivi_machines_pilotage.TableauModerne";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = proxy({ donnees: null, periode: "jour", chargement: true, majA: "" });
        onWillStart(() => this.charger("jour"));
        // Rafraichissement automatique toutes les 2 minutes, seulement quand l'onglet est visible
        // (et tout de suite en revenant sur l'onglet si le dernier date de plus de 2 minutes)
        this.surVisibilite = () => {
            if (!document.hidden && Date.now() - (this.dernierChargement || 0) >= DELAI_RAFRAICHIR) {
                this.rafraichir();
            }
        };
        onMounted(() => {
            this.minuteur = setInterval(() => this.rafraichir(), DELAI_RAFRAICHIR);
            document.addEventListener("visibilitychange", this.surVisibilite);
        });
        onWillUnmount(() => {
            clearInterval(this.minuteur);
            document.removeEventListener("visibilitychange", this.surVisibilite);
        });
    }

    rafraichir() {
        if (!document.hidden && !this.enCours) {
            return this.charger(this.state.periode, true);
        }
    }

    async charger(periode, silencieux = false) {
        if (!silencieux) {
            this.state.chargement = true;
        }
        this.state.periode = periode;
        this.enCours = true;
        this.dernierChargement = Date.now();
        try {
            const donnees = await this.orm.call("pilotage.indicateur", "donnees_tableau_moderne", [periode]);
            this.state.donnees = this.completer(donnees);
            const maintenant = new Date();
            this.state.majA = maintenant.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
        } finally {
            this.enCours = false;
            this.state.chargement = false;
        }
    }

    /** Listes manquantes (serveur pas encore a jour pendant une mise a jour) : vides, jamais d'erreur. */
    completer(d) {
        d = d || {};
        const listes = ["alertes", "techniciens", "problemes", "semaines", "tournees"];
        for (const cle of listes) {
            d[cle] = d[cle] || [];
        }
        d.blocs = Object.assign({ appels: [], locations: [], facturation: [], inventaire: [] }, d.blocs || {});
        d.progression = d.progression || { total: 0, faits: 0, retards: 0, pourcentage: 0 };
        if (d.stock) {
            for (const cle of ["statuts", "disponibles", "categories", "mouvements"]) {
                d.stock[cle] = d.stock[cle] || [];
            }
        }
        if (!d.semaines.length) {
            d.semaines = [{ libelle: "", code: "", nombre: 0 }];
        }
        return d;
    }

    async ouvrir(code) {
        const action = await this.orm.call("pilotage.indicateur", "action_par_code", [code]);
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    ouvrirAction(xmlid) {
        return this.actionService.doAction(xmlid);
    }

    largeur(n, total) {
        return total ? `${Math.round((100 * n) / total)}%` : "0%";
    }

    anneau(p) {
        const fait = p.total ? (100 * p.faits) / p.total : 0;
        const retard = p.total ? (100 * p.retards) / p.total : 0;
        return `background: conic-gradient(#22c55e 0 ${fait}%, #ef4444 ${fait}% ${fait + retard}%, #e5e7eb ${fait + retard}% 100%);`;
    }
}

registry.category("actions").add("suivi_pilotage_tableau_moderne", TableauModerne);
