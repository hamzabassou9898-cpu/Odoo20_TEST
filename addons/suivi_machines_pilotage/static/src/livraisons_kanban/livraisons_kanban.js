import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";

/** Appels de service : bons de livraison en haut des colonnes. A faire : « Livraison & installation / Reprise » ;
 * valides : Resolu ; annules : Annule. Ce sont les bons eux-memes (pas des tickets) : un clic ouvre le bon. */
export class LivraisonsAFaire extends Component {
    static template = "suivi_machines_pilotage.LivraisonsAFaire";
    props = useProps({ donnees: t.object() });

    setup() {
        this.actionService = useService("action");
    }

    ouvrir(bon) {
        return this.actionService.doAction({
            type: "ir.actions.act_window", res_model: "stock.picking", res_id: bon.id,
            views: [[false, "form"]],
        });
    }

    toutVoir() {
        return this.actionService.doAction(this.props.donnees.action);
    }
}

patch(KanbanRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.list.resModel !== "helpdesk.ticket") {
            return;
        }
        const orm = useService("orm");
        this.livraisons = proxy({ donnees: null });
        // Sans attendre : le kanban s'affiche tout de suite, les bons arrivent juste apres
        const charger = async () => {
            try {
                this.livraisons.donnees = await orm.call("stock.picking", "livraisons_kanban_assistance", []);
            } catch {
                this.livraisons.donnees = null;
            }
        };
        onWillStart(() => {
            charger();
        });
        onWillUpdateProps(() => {
            charger();
        });
    },

    /** Composant passe par le prototype (et non par « components ») : les kanbans qui heritent de celui-ci
     * (ex. l'Assistance Enterprise) ont copie leur liste de composants avant ce complement. */
    get composantLivraisons() {
        return LivraisonsAFaire;
    },

    /** Bons a montrer dans cette colonne (groupe par etape) : a faire, valides (Resolu) ou annules (Annule). */
    livraisonsDuGroupe(group) {
        const zones = this.livraisons?.donnees?.zones;
        if (!zones || this.props.list.groupByField?.name !== "stage_id") {
            return null;
        }
        return zones.find((zone) => zone.etape_ids.includes(group.value)) || null;
    },
});
