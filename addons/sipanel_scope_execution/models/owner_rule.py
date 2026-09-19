# -*- coding: utf-8 -*-
"""Owner registry: which owner creates demand for an anchor product (GAP-D01, C8-D01, BQ-05, BQ-07, SV-13)."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

ROUTE_KIND = [('stock_rule', 'Stock rule (sale_stock)'), ('kit_explosion', 'Kit explosion (sale_mrp)'),
              ('purchase_service', 'Purchase service (sale_purchase)'), ('project_task', 'Project / task (sale_project)'), ('none', 'None')]


class SipanelExecutionOwnerRule(models.Model):
    _name = 'sipanel.execution.owner.rule'
    _description = 'SIPANEL execution owner rule'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    product_id = fields.Many2one('product.product', ondelete='restrict', help="Blank = default rule")
    product_tmpl_id = fields.Many2one('product.template', ondelete='restrict')
    service_tracking = fields.Selection([('no', 'no'), ('task_global_project', 'task_global_project'), ('task_in_project', 'task_in_project'), ('project_only', 'project_only')])
    route_kind = fields.Selection(ROUTE_KIND, required=True, default='none')
    owner = fields.Selection([('native_line_owner', 'NATIVE_LINE_OWNER'), ('component_bridge_owner', 'COMPONENT_BRIDGE_OWNER')], required=True)
    native_hook = fields.Char(readonly=True, compute='_compute_native_hook')

    @api.depends('route_kind')
    def _compute_native_hook(self):
        hooks = {'stock_rule': 'sale_stock.sale.order.line._action_launch_stock_rule', 'kit_explosion': 'sale_mrp._get_qty_procurement / _bom_find(phantom)',
                 'purchase_service': 'sale_purchase._purchase_service_generation', 'project_task': 'sale_project._timesheet_service_generation', 'none': ''}
        for r in self:
            r.native_hook = hooks.get(r.route_kind, '')

    @api.constrains('owner', 'route_kind', 'service_tracking')
    def _check_owner(self):
        for r in self:
            if r.owner == 'component_bridge_owner' and r.route_kind not in ('none', 'project_task'):
                raise ValidationError(self.env._("COMPONENT_BRIDGE_OWNER requires route_kind NONE or PROJECT_TASK (project_only)."))
            if r.owner == 'component_bridge_owner' and r.route_kind == 'project_task' and r.service_tracking not in (False, 'project_only'):
                raise ValidationError(self.env._("COMPONENT_BRIDGE_OWNER with a project route allows only service_tracking=project_only (BQ-07)."))

    @api.model
    def resolve(self, product, company=None):
        """product -> template -> service_tracking/route default. Returns owner or False."""
        company = company or self.env.company
        product = product.with_company(company) if product else product
        domain = [('company_id', '=', company.id)]
        rules = self.search(domain)
        if product:
            r = rules.filtered(lambda r: r.product_id == product)[:1]
            if r:
                return r.owner
            r = rules.filtered(lambda r: r.product_tmpl_id == product.product_tmpl_id and not r.product_id)[:1]
            if r:
                return r.owner
            tracking = product.service_tracking if 'service_tracking' in product._fields else 'no'
            r = rules.filtered(lambda r: not r.product_id and not r.product_tmpl_id and r.service_tracking == tracking)[:1]
            if r:
                return r.owner
        r = rules.filtered(lambda r: not r.product_id and not r.product_tmpl_id and not r.service_tracking)[:1]
        return r.owner if r else False
