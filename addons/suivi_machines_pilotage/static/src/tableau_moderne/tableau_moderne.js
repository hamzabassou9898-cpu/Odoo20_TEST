import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onMounted, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";

/** Pilotage : vue d'ensemble moderne (la vue « Toutes les cartes » reste disponible). */
export class TableauModerne extends Component {
    static template = "suivi_machines_pilotage.TableauModerne";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = proxy({ donnees: null, periode: "jour", chargement: true, majA: "" });
        onWillStart(() => this.charger("jour"));
        // Rafraichissement automatique toutes les 2 minutes
        onMounted(() => {
            this.minuteur = setInterval(() => this.charger(this.state.periode, true), 120000);
        });
        onWillUnmount(() => clearInterval(this.minuteur));
    }

    async charger(periode, silencieux = false) {
        if (!silencieux) {
            this.state.chargement = true;
        }
        this.state.periode = periode;
        try {
            this.state.donnees = await this.orm.call("pilotage.indicateur", "donnees_tableau_moderne", [periode]);
            const maintenant = new Date();
            this.state.majA = maintenant.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
        } finally {
            this.state.chargement = false;
        }
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
