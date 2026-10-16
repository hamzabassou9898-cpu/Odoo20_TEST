/** @odoo-module **/
/* Horloge des activites (en haut a droite) : la liste s'ouvre avec seulement « Mes activites » (toutes,
 * y compris celles a venir), sans le filtre « en retard ou du jour » ajoute par Odoo. */
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { patch } from "@web/core/utils/patch";

patch(ActivityMenu.prototype, {
    executeActivityAction(group, domain, views, context, newWindow) {
        if (context.search_default_activities_overdue && context.search_default_activities_today) {
            context = { ...context };
            delete context.search_default_activities_overdue;
            delete context.search_default_activities_today;
        }
        return super.executeActivityAction(group, domain, views, context, newWindow);
    },
});
