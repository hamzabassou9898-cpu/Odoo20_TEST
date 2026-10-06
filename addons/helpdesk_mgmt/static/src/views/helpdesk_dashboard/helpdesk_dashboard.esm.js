import {Component, onWillStart, onWillUnmount, proxy} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
// Odoo 20 : SIZES a ete deplace dans ui_utils
import {SIZES} from "@web/core/ui/ui_utils";
import {ViewButton} from "@web/views/view_button/view_button";

export class HelpdeskDashboard extends Component {
    static template = "helpdesk_mgmt.HelpdeskDashboard";
    static components = {ViewButton};
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.uiService = useService("ui");
        this.state = proxy({
            gridTemplateColumns: this._getGridTemplateColumns(),
        });
        this._onResize = () => this.updateGridTemplateColumns();
        window.addEventListener("resize", this._onResize);
        onWillUnmount(() => window.removeEventListener("resize", this._onResize));
        onWillStart(async () => {
            this.helpdeskData = await this.orm.call(
                "helpdesk.ticket.team",
                "retrieve_dashboard"
            );
        });
    }
    clickParams(section) {
        if (section.action) {
            return {name: section.action, type: "action"};
        }
        return {};
    }

    _getGridTemplateColumns() {
        switch (this.uiService.size) {
            case SIZES.XS:
                return 2;
            case SIZES.VSM:
                return 3;
            case SIZES.XXL:
                return 6;
            default:
                return 4;
        }
    }

    updateGridTemplateColumns() {
        this.state.gridTemplateColumns = this._getGridTemplateColumns();
    }
}
