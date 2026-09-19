# -*- coding: utf-8 -*-
"""Read-only SQL view: baseline vs forecast vs commitment vs recognised, per scope (GAP-E09, BQ-06=A)."""
from odoo import fields, models, tools

COST_GROUP = 'sipanel_commercial_scope_core.group_scope_cost_viewer'


class SipanelScopeVariance(models.Model):
    _name = 'sipanel.scope.variance'
    _description = 'SIPANEL scope variance (baseline / forecast / commitment / recognised)'
    _auto = False
    _order = 'quote_scope_id'

    quote_scope_id = fields.Many2one('sipanel.quote.scope', readonly=True)
    order_id = fields.Many2one('sale.order', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    project_id = fields.Many2one('project.project', readonly=True)
    system_id = fields.Many2one('account.analytic.account', readonly=True)
    accepted_revision_id = fields.Many2one('sipanel.quote.scope.revision', readonly=True)
    baseline_cost = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    forecast_cost = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    committed_amount = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    recognised_cost = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    recognised_revenue = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    unallocated_cost = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    variance_amount = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    recognised_margin = fields.Monetary(currency_field='currency_id', readonly=True, groups=COST_GROUP)
    completeness = fields.Selection([('complete', 'Complete'), ('incomplete', 'Incomplete'), ('policy_missing', 'Policy missing')], readonly=True)

    # A SQL view reads committed-in-transaction rows: pending ORM writes (scope project, event allocations)
    # must be flushed first, and the ORM cache of the view must not survive a projection refresh (CD-11).
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        self.env.flush_all()
        self.invalidate_model()
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

    def fetch(self, field_names):
        self.env.flush_all()
        return super().fetch(field_names)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
            WITH cost AS (
                SELECT a.quote_scope_id, SUM(a.amount) AS recognised_cost
                FROM sipanel_actual_allocation a JOIN sipanel_actual_cost_event e ON e.id = a.event_id
                WHERE e.inclusion = 'included' AND e.layer = 'recognized' AND e.component_type <> 'revenue' AND a.allocation_basis <> 'unallocated'
                GROUP BY a.quote_scope_id),
            rev AS (
                SELECT a.quote_scope_id, SUM(a.amount) AS recognised_revenue
                FROM sipanel_actual_allocation a JOIN sipanel_actual_cost_event e ON e.id = a.event_id
                WHERE e.component_type = 'revenue' GROUP BY a.quote_scope_id),
            commit AS (
                SELECT d.quote_scope_id, SUM(COALESCE(pol.price_subtotal, 0)) AS committed_amount
                FROM sipanel_execution_target t JOIN sipanel_execution_demand d ON d.id = t.demand_id
                JOIN purchase_order_line pol ON t.target_model = 'purchase.order.line' AND pol.id = t.target_res_id
                JOIN purchase_order po ON po.id = pol.order_id
                WHERE po.state IN ('draft', 'sent', 'to approve', 'purchase') GROUP BY d.quote_scope_id),
            unalloc AS (
                SELECT e.project_id, SUM(e.unallocated_amount) AS unallocated_cost,
                       BOOL_OR(e.inclusion = 'policy_missing') AS policy_missing
                FROM sipanel_actual_cost_event e WHERE e.layer = 'recognized' AND e.component_type <> 'revenue' GROUP BY e.project_id),
            forecast AS (
                SELECT r.quote_scope_id, r.eligible_cost_total AS forecast_cost FROM sipanel_quote_scope_revision r WHERE r.state = 'working')
            SELECT s.id AS id, s.id AS quote_scope_id, s.order_id, s.company_id, c.currency_id, s.project_id, s.system_id,
                   s.accepted_revision_id,
                   ar.eligible_cost_total AS baseline_cost,
                   f.forecast_cost,
                   COALESCE(cm.committed_amount, 0) AS committed_amount,
                   COALESCE(cost.recognised_cost, 0) AS recognised_cost,
                   COALESCE(rev.recognised_revenue, 0) AS recognised_revenue,
                   COALESCE(u.unallocated_cost, 0) AS unallocated_cost,
                   CASE WHEN ar.eligible_cost_total IS NULL THEN NULL ELSE COALESCE(cost.recognised_cost, 0) - ar.eligible_cost_total END AS variance_amount,
                   COALESCE(rev.recognised_revenue, 0) - COALESCE(cost.recognised_cost, 0) AS recognised_margin,
                   CASE WHEN u.policy_missing THEN 'policy_missing'
                        WHEN COALESCE(u.unallocated_cost, 0) <> 0 THEN 'incomplete' ELSE 'complete' END AS completeness
            FROM sipanel_quote_scope s
            JOIN res_company c ON c.id = s.company_id
            LEFT JOIN sipanel_quote_scope_revision ar ON ar.id = s.accepted_revision_id
            LEFT JOIN forecast f ON f.quote_scope_id = s.id
            LEFT JOIN cost ON cost.quote_scope_id = s.id
            LEFT JOIN rev ON rev.quote_scope_id = s.id
            LEFT JOIN commit cm ON cm.quote_scope_id = s.id
            LEFT JOIN unalloc u ON u.project_id = s.project_id
            WHERE s.active = TRUE
            )""")
