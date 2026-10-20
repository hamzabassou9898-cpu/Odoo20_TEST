/** @odoo-module **/
/* Vue Hierarchie (Contacts...) : le menu de recherche a ses 3 colonnes, Filtres / Regrouper par / Favoris.
 * La hierarchie ne sait pas regrouper : choisir un regroupement (ex. Ville) ouvre la vue Liste groupee ;
 * revenir a la hierarchie retire le regroupement. */
import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useBus, useService } from "@web/core/utils/hooks";
import { hierarchyView } from "@web_hierarchy/hierarchy_view";
import { HierarchyController } from "@web_hierarchy/hierarchy_controller";

hierarchyView.searchMenuTypes = ["filter", "groupBy", "favorite"];

patch(HierarchyController.prototype, {
    setup() {
        super.setup(...arguments);
        const searchModel = this.env.searchModel;
        if (!searchModel) {
            return;
        }
        const action = useService("action");
        const vueListe = () => (this.env.config.viewSwitcherEntries || []).some((v) => v.type === "list");
        onMounted(() => {
            for (const facet of searchModel.facets.filter((f) => f.type === "groupBy")) {
                searchModel.deactivateGroup(facet.groupId);
            }
        });
        useBus(searchModel, "update", () => {
            if (searchModel.groupBy.length && vueListe()) {
                action.switchView("list");
            }
        });
    },
});
