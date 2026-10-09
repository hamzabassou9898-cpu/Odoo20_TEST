import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

/** Pilotage : vue d'ensemble moderne (la vue « Toutes les cartes » reste disponible). */
export class TableauModerne extends Component {
    static template = "suivi_machines_pilotage.TableauModerne";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = proxy({ donnees: null, periode: "jour", chargement: true });
        onWillStart(() => this.charger("jour"));
    }

    async charger(periode) {
        this.state.chargement = true;
        this.state.periode = periode;
        this.state.donnees = await this.orm.call("pilotage.indicateur", "donnees_tableau_moderne", [periode]);
        this.state.chargement = false;
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
