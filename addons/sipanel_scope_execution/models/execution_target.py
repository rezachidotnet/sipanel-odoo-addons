# -*- coding: utf-8 -*-
"""Target link between a demand and a native document (GAP-D05; C8-D03; SV-08)."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

TARGET_MODELS = [('purchase.order.line', 'Purchase order line'), ('stock.move', 'Stock move'), ('stock.picking', 'Transfer'),
                 ('mrp.production', 'Manufacturing order'), ('project.task', 'Task'), ('project.project', 'Project'),
                 ('stock.reference', 'Stock reference'), ('account.analytic.line', 'Analytic line'), ('hr.expense', 'Expense')]


class SipanelExecutionTarget(models.Model):
    _name = 'sipanel.execution.target'
    _description = 'SIPANEL execution target link'

    demand_id = fields.Many2one('sipanel.execution.demand', required=True, readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='demand_id.company_id', store=True)
    target_model = fields.Selection(TARGET_MODELS, required=True, readonly=True)
    target_res_id = fields.Many2oneReference(model_field='target_model', required=True, readonly=True)
    link_kind = fields.Selection([('created', 'Created'), ('linked_existing', 'Linked existing'), ('native_anchor_covered', 'Native anchor covered')], required=True, readonly=True)
    allocated_qty = fields.Float(digits=(16, 6), readonly=True)
    uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict')
    stock_reference_id = fields.Many2one('stock.reference', readonly=True, ondelete='restrict')
    reversal_of_id = fields.Many2one('sipanel.execution.target', readonly=True, ondelete='restrict')
    origin_label = fields.Char(readonly=True)
    target_display = fields.Char(compute='_compute_target_display')

    _target_unique = models.Constraint('UNIQUE(demand_id, target_model, target_res_id, link_kind)', 'Duplicate target link.')

    @api.depends('target_model', 'target_res_id')
    def _compute_target_display(self):
        for t in self:
            rec = self.env[t.target_model].browse(t.target_res_id).exists() if t.target_model else None
            t.target_display = rec.display_name if rec else ''

    @api.constrains('target_model', 'target_res_id')
    def _check_target(self):
        for t in self:
            rec = self.env[t.target_model].sudo().browse(t.target_res_id).exists()
            if not rec:
                raise ValidationError(self.env._("Target %s/%s does not exist.", t.target_model, t.target_res_id))
            if 'company_id' in rec._fields and rec.company_id and rec.company_id != t.company_id:
                raise ValidationError(self.env._("Target belongs to another company."))

    def target_record(self):
        self.ensure_one()
        return self.env[self.target_model].browse(self.target_res_id)
