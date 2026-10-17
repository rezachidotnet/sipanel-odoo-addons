# -*- coding: utf-8 -*-
from odoo import models

# Owner decision 2026-10-17, item 4: the printed quotation depends on the document, never on the printing user.
# Odoo renders each document body in the document language (data-oe-lang), but the PDF header and footer
# (letterhead) frame in the language of the user who prints: under a Persian interface the frame is right-to-left
# (RTL page direction and stylesheet) and the letterhead is mirrored (UI acceptance test 2026-10-16). Both approved
# quotation PDFs (fa_IR and en_US documents) have the left-to-right frame - the letterhead was designed with it, the
# Persian texts in it stay right-to-left - so the frame of a quotation is always rendered left-to-right. The header
# and footer contents are already rendered in the document language inside the body (t-lang) and are not changed.
LETTERHEAD_FRAME_LANG = 'en_US'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _prepare_html(self, html, report_model=False):
        if report_model == 'sale.order':
            bodies, res_ids, header, footer, args = super()._prepare_html(html, report_model=report_model)
            frame = super(IrActionsReport, self.with_context(lang=LETTERHEAD_FRAME_LANG))._prepare_html(
                html, report_model=report_model)
            # bodies keep their own document language (rendered from data-oe-lang either way)
            return bodies, res_ids, frame[2], frame[3], args
        return super()._prepare_html(html, report_model=report_model)
