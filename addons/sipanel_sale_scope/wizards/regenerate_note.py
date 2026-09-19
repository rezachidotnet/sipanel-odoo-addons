# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SipanelWizardRegenerateNote(models.TransientModel):
    _name = 'sipanel.wizard.regenerate.note'
    _description = 'Regenerate customer note with diff preview'

    revision_id = fields.Many2one('sipanel.quote.scope.revision', required=True)
    current_note = fields.Text(compute='_compute_preview')
    generated_note = fields.Text(compute='_compute_preview')
    decision = fields.Selection([('accept', 'Replace final note with generated text'), ('keep', 'Keep final note and mark reviewed')], required=True, default='accept')

    @api.depends('revision_id')
    def _compute_preview(self):
        for w in self:
            w.current_note = w.revision_id.final_note
            w.generated_note = w.revision_id._build_generated_note()

    def action_apply(self):
        self.ensure_one()
        if self.decision == 'accept':
            self.revision_id.action_generate_note(accept=True)
        else:
            self.revision_id.action_generate_note(accept=False)
            self.revision_id.action_mark_note_reviewed()
        return {'type': 'ir.actions.act_window_close'}
