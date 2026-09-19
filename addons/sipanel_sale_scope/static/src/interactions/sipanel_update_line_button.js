import { patch } from "@web/core/utils/patch";
import { SaleUpdateLineButton } from "@sale_management/interactions/sale_update_line_button";

/**
 * GAP-C02 / GAP-S04: bind the portal quantity transition of a Scope anchor line to the
 * current sealed revision (revision id + seal hash rendered as data attributes).
 */
patch(SaleUpdateLineButton.prototype, {
    _sipanelBinding(el) {
        const container = el.closest("[data-sipanel-revision-id]");
        if (!container) {
            return {};
        }
        return {
            sipanel_revision_id: container.dataset.sipanelRevisionId,
            sipanel_seal_hash: container.dataset.sipanelSealHash,
        };
    },
    async onQuantityChange(ev, currentTargetEl) {
        const quantity = parseInt(currentTargetEl.value);
        await this.waitFor(this.callUpdateLineRoute(this.orderDetail.orderId, {
            access_token: this.orderDetail.token,
            input_quantity: quantity >= 0 ? quantity : false,
            line_id: currentTargetEl.dataset.lineId,
            ...this._sipanelBinding(currentTargetEl),
        }));
        this.refreshOrderUI();
    },
    async onUpdateLineClick(ev, currentTargetEl) {
        await this.waitFor(this.callUpdateLineRoute(this.orderDetail.orderId, {
            access_token: this.orderDetail.token,
            line_id: currentTargetEl.dataset.lineId,
            remove: currentTargetEl.dataset.remove,
            ...this._sipanelBinding(currentTargetEl),
        }));
        this.refreshOrderUI();
    },
});
