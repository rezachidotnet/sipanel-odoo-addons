# -*- coding: utf-8 -*-
from odoo import fields, models


class SipanelQuoteScope(models.Model):
    _inherit = 'sipanel.quote.scope'

    project_id = fields.Many2one('project.project', ondelete='restrict', help="Execution project (dimension Project).")
    execution_demand_ids = fields.One2many('sipanel.execution.demand', 'quote_scope_id')
