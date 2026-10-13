import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

/** Pilotage : planning de la semaine (techniciens x jours), glisser-deposer des taches. */
export class PlanningSemaine extends Component {
    static template = "suivi_machines_pilotage.PlanningSemaine";
    props = useProps(standardActionServiceProps);

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.state = proxy({ donnees: null, chargement: true, survol: "" });
        this.glissee = null;
        onWillStart(() => this.charger());
    }

    async charger(jour = null) {
        this.state.chargement = true;
        try {
            this.state.donnees = await this.orm.call("portail.tache", "donnees_planning", [jour || false]);
        } finally {
            this.state.chargement = false;
        }
    }

    cartes(ligne, jour) {
        return this.state.donnees.cartes.filter((c) => c.technicien_id === ligne.id && c.jour === jour.iso);
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
        if (!carte || (carte.technicien_id === ligne.id && carte.jour === jour.iso)) {
            return;
        }
        try {
            await this.orm.call("portail.tache", "deplacer_planning", [carte.id, ligne.id, jour.iso]);
            this.notification.add(`« ${carte.titre} » → ${ligne.nom}, ${jour.titre}`, { type: "success" });
        } finally {
            await this.charger(this.state.donnees.lundi);
        }
    }

    finGlisser() {
        this.glissee = null;
        this.state.survol = "";
    }

    async ouvrir(carte) {
        const action = await this.orm.call("portail.tache", "action_ouvrir", [[carte.id]]);
        if (action) {
            await this.actionService.doAction(action);
        }
    }
}

registry.category("actions").add("suivi_pilotage_planning", PlanningSemaine);
