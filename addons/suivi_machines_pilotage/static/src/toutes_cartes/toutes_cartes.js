import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";

/** « Toutes les cartes » : bouton « Vue d'ensemble » en haut a droite (l'inverse du bouton de la Vue d'ensemble). */
export class ToutesCartesController extends KanbanController {
    static template = "suivi_machines_pilotage.ToutesCartes";

    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    ouvrirVueEnsemble() {
        return this.actionService.doAction("suivi_machines_pilotage.action_pilotage_vue_ensemble");
    }
}

registry.category("views").add("pilotage_toutes_cartes", { ...kanbanView, Controller: ToutesCartesController });
