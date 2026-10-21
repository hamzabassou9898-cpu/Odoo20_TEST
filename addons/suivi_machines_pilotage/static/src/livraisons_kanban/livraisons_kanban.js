import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";

/** Appels de service : bons de livraison a faire, en haut de la colonne « Livraison & installation / Reprise ».
 * Ce sont les bons eux-memes (pas des tickets) : un clic ouvre le bon ; valide, il n'apparait plus. */
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

KanbanRenderer.components = { ...KanbanRenderer.components, LivraisonsAFaire };

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

    /** Donnees a montrer dans cette colonne (seulement groupe par etape, sur l'etape des livraisons). */
    livraisonsDuGroupe(group) {
        const donnees = this.livraisons?.donnees;
        if (!donnees?.total || this.props.list.groupByField?.name !== "stage_id") {
            return null;
        }
        return donnees.etape_ids.includes(group.value) ? donnees : null;
    },
});
