# -*- coding: utf-8 -*-
"""UI acceptance test (owner 2026-10-16), run by `sipanel_qlines_clone_validate.sh uirun` on a CLONE only.

A normal salesperson (ui_sales) creates, in the web UI only, a new quotation that reproduces SI-26/2546 and prints the
fa PDF; a Sales Manager (ui_manager) does the manager tasks (System sheet row, default terms, aluminium price extra).
Every step is recorded in /out/ui_report.json: ok / blocked (exact reason) / failed, with a screenshot /out/NN_*.png.
Login goes through /web/session/authenticate: on the clone the website login form stays hidden (its captcha script
cannot load without internet) - this is the only step not done through the visible UI.
"""
import json
import os
import re
import time
import traceback

from playwright.sync_api import sync_playwright

URL, PW, DB, OUT = os.environ['UI_URL'], os.environ['UI_PASSWORD'], os.environ['UI_DB'], '/out'
STEPS = os.environ.get('UI_STEPS', 'all').split(',')
T = 240000
REPORT = {'steps': [], 'started': time.strftime('%Y-%m-%d %H:%M:%S')}
N = [0]

# SI-26/2546 as approved (owner 2026-10-16)
CUSTOMER = 'شرکت آزمون رابط کاربری'
PROJECT = 'ویلای تفریحی طالقان'
SYSTEM = 'استندینگ سیم'
SECTION_1 = 'سیستم پوشش سقف و دیوار استندینگ سیم'
SECTION_2 = 'متعلقات'
NOTE = 'شامل: متعلقات استاندارد سیستم'
LINES = [  # (section before, product search, description, qty, price)
    ('SIP-000074', 'سیستم پوشش سقف و دیوار استندینگ سیم (فقط تأمین)', '206', '88000000'),
    ('SIP-000076', 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۵۸ سانتی‌متر (فقط تأمین)', '108.47', '43800000'),
    ('SIP-000076', 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا ۲۰ سانتی‌متر (فقط تأمین)', '54.23', '14600000'),
    ('SIP-000077', 'آبرو ورق گالوانیزه ۱.۵ میلیمتر (فقط تأمین)', '18', '67000000'),
]
PAYMENT_TERM = '۷۰٪ پیش‌پرداخت'


def step(name, fn, *args):
    N[0] += 1
    rec = {'n': N[0], 'step': name, 'status': 'ok', 'detail': None}
    page = args[0] if args else None
    try:
        rec['detail'] = fn(*args)
    except Blocked as exc:
        rec.update(status='blocked', detail=str(exc))
    except Exception as exc:                          # noqa: BLE001 - recorded, the run goes on where it can
        rec.update(status='failed', detail=f'{type(exc).__name__}: {exc}'[:1500], trace=traceback.format_exc()[-2500:])
        if page is not None:
            try:
                open(f'{OUT}/{N[0]:02d}_{slug(name)}_dom.html', 'w').write(page.content())
            except Exception:                          # noqa: BLE001
                pass
    if page is not None:
        try:
            page.screenshot(path=f'{OUT}/{N[0]:02d}_{slug(name)}.png', full_page=True)
            rec['screenshot'] = f'{N[0]:02d}_{slug(name)}.png'
        except Exception:                              # noqa: BLE001
            pass
    REPORT['steps'].append(rec)
    print(f"STEP {rec['n']:02d} {rec['status'].upper():7} {name}: {str(rec['detail'])[:300]}", flush=True)
    if rec['status'] == 'failed' and os.environ.get('UI_STOP_ON_FAIL'):
        json.dump(REPORT, open(f'{OUT}/ui_report.json', 'w'), ensure_ascii=False, indent=1)
        os._exit(3)
    return rec


class Blocked(Exception):
    """The step cannot be done through the UI with this user (exact reason in the message)."""


def slug(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')[:40]


def login(browser, user):
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='fa-IR', accept_downloads=True)
    page = ctx.new_page()
    page.set_default_timeout(90000)
    page.set_default_navigation_timeout(T)
    r = page.request.post(URL + '/web/session/authenticate', data={'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': DB, 'login': user, 'password': PW}})
    assert r.ok and 'error' not in r.json(), r.text()[:300]
    page.goto(URL + '/odoo', wait_until='domcontentloaded')
    page.wait_for_selector('.o_main_navbar')
    idle(page)
    return page


def idle(page, ms=600):
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(ms)


def field(page, name, scope='.o_form_view'):
    return page.locator(f'{scope} div[name="{name}"]').first


def m2o(page, name, text, pick=None, scope='.o_form_view'):
    inp = field(page, name, scope).locator('input').first
    inp.click()
    inp.fill(text)
    menu = page.locator('.o-autocomplete--dropdown-menu').first
    menu.wait_for()
    page.wait_for_timeout(800)
    items = menu.locator('.o-autocomplete--dropdown-item')
    target = items.filter(has_text=pick or text).first
    target.click()
    idle(page)


def type_into(page, name, value, scope='.o_form_view'):
    inp = field(page, name, scope).locator('input, textarea').first
    inp.click()
    inp.fill(value)
    inp.press('Tab')
    idle(page, 300)


def tab(page, name):
    page.locator(f'.o_notebook a.nav-link[name="{name}"]').first.click()
    idle(page, 400)


def save(page):
    btn = page.locator('.o_form_button_save').first
    if btn.is_visible():
        btn.click()
        idle(page, 1000)
    errors = page.locator('.o_notification.border-danger, .o_dialog .modal-body').all_inner_texts()
    return errors


def row_add(page, which):
    """which = 0 product, 1 section, 2 note (the links under the order lines)."""
    page.locator('div[name="order_line"] .o_field_x2many_list_row_add a').nth(which).click()
    idle(page, 500)
    return page.locator('div[name="order_line"] tr.o_selected_row').first


# ---------------------------------------------------------------- salesperson
def s_open_new(page):
    page.goto(URL + '/odoo/sales/new', wait_until='domcontentloaded')
    page.wait_for_selector('.o_form_view div[name="partner_id"]')
    idle(page)
    return page.url


def s_customer(page):
    inp = field(page, 'partner_id').locator('input').first
    inp.click()
    inp.fill(CUSTOMER)
    page.locator('.o-autocomplete--dropdown-menu').first.wait_for()
    page.wait_for_timeout(800)
    page.locator('.o-autocomplete--dropdown-item').filter(has_text='ایجاد').first.click()   # quick create «ایجاد "..."»
    idle(page)
    return field(page, 'partner_id').locator('input').first.input_value()


def s_customer_lang(page):
    """Production stores a global default res.partner.lang = en_US (ir.default id 1): a customer created from the
    quotation is English, so the quotation would print in English. The salesperson sets Persian on the customer."""
    f = field(page, 'partner_id')
    f.hover()
    f.locator('.o_external_button').first.click()           # opens the customer (the quotation is saved first)
    page.wait_for_selector('.o_form_view div[name="lang"]')
    idle(page, 800)
    lang = page.locator('.o_form_view div[name="lang"] input').first
    was = lang.input_value()
    now = was
    for attempt in range(3):                          # the select menu sometimes closes before the click lands
        lang.click()
        page.locator('.o_select_menu_item').filter(has_text=re.compile('فارسی|Persian')).first.wait_for()
        page.wait_for_timeout(400)
        page.locator('.o_select_menu_item').filter(has_text=re.compile('فارسی|Persian')).first.click()
        idle(page, 600)
        now = lang.input_value()
        if 'فارسی' in now or 'Persian' in now:
            break
    if not ('فارسی' in now or 'Persian' in now):
        raise AssertionError(f'customer language still {now!r}')
    page.screenshot(path=f'{OUT}/{N[0]:02d}_customer_language.png', full_page=True)
    page.locator('.o_form_button_save').first.click()
    idle(page, 1000)
    page.locator('.o_back_button a').first.click()          # back to the quotation (breadcrumb)
    page.wait_for_selector('.o_form_view div[name="sipanel_requested_system_id"]')
    idle(page, 800)
    return {'language_before': was, 'language_after': now, 'quotation': page.url}


def s_header(page):
    m2o(page, 'payment_term_id', PAYMENT_TERM)
    type_into(page, 'sipanel_delivery_days', '45')
    bank = field(page, 'sipanel_show_bank_account').locator('input').first
    if bank.is_checked():
        bank.uncheck()
    return {'payment_term': field(page, 'payment_term_id').locator('input').first.input_value(),
            'bank_line': bank.is_checked()}


def s_project(page):
    type_into(page, 'sipanel_project_name', PROJECT)
    m2o(page, 'sipanel_requested_system_id', SYSTEM)
    return field(page, 'sipanel_requested_system_id').locator('input').first.input_value()


def s_percentages(page):
    type_into(page, 'sipanel_installation_pct', '10')
    type_into(page, 'sipanel_shop_drawing_pct', '2')
    disc = page.locator('.o_form_view div[name="sipanel_shop_drawing_discount"]')
    if not disc.count():
        raise Blocked('the shop drawings discount field is not on the quotation form for a salesperson')
    type_into(page, 'sipanel_shop_drawing_discount', '100')
    return {f: field(page, f).locator('input').first.input_value()
            for f in ('sipanel_installation_pct', 'sipanel_shop_drawing_pct', 'sipanel_shop_drawing_discount')}


def s_section(page, text):
    row = row_add(page, 1)
    inp = row.locator('td[name="product_template_id"] .o_field_product_label_section_and_note_cell input, '
                      'td[name="product_template_id"] .o_field_product_label_section_and_note_cell textarea').first
    inp.fill(text)
    idle(page, 400)
    return text


def s_note(page, text):
    row = row_add(page, 2)
    inp = row.locator('td[name="product_template_id"] .o_field_product_label_section_and_note_cell input, '
                      'td[name="product_template_id"] .o_field_product_label_section_and_note_cell textarea').first
    inp.fill(text)
    idle(page, 400)
    return text


def s_line(page, code, description, qty, price):
    row = row_add(page, 0)
    prod = row.locator('td[name="product_template_id"] input.o_input, td[name="product_id"] input.o_input').first
    for attempt in range(3):                          # the autocomplete sometimes misses a fill(): type it
        prod.click()
        prod.fill('')
        prod.press_sequentially(code, delay=60)
        try:
            page.locator('.o-autocomplete--dropdown-item').filter(has_text=code).first.wait_for(timeout=15000)
            break
        except Exception:                             # noqa: BLE001
            page.keyboard.press('Escape')
            idle(page, 500)
    page.locator('.o-autocomplete--dropdown-item').filter(has_text=code).first.click()
    idle(page, 1500)
    configured = None
    try:                                             # the product has the material option: Odoo's configurator opens
        page.wait_for_selector('.o_sale_product_configurator_dialog', timeout=20000)
    except Exception:                                # noqa: BLE001 - product without options
        pass
    dialog = page.locator('.o_sale_product_configurator_dialog')
    if dialog.count():
        idle(page, 800)
        page.screenshot(path=f'{OUT}/{N[0]:02d}_configurator.png')
        checked = dialog.locator('input[type=radio]:checked').first
        configured = {'dialog': re.sub(r'\s+', ' ', dialog.first.inner_text())[:300],
                      'selected': checked.evaluate('e => e.closest("li, div, label").innerText') if checked.count() else None}
        page.locator('button[name="sale_product_configurator_confirm_button"]').first.click()
        page.wait_for_selector('.o_sale_product_configurator_dialog', state='detached')
        idle(page, 1200)
    last = page.locator('div[name="order_line"] tr.o_data_row:not(.o_is_line_section):not(.o_is_line_note)').last
    if not page.locator('div[name="order_line"] tr.o_selected_row').count():
        last.locator('td[name="product_uom_qty"]').click()          # back into the line after the configurator
        idle(page, 800)
    row = page.locator('div[name="order_line"] tr.o_selected_row').first
    open(f'{OUT}/{N[0]:02d}_row_dom.html', 'w').write(row.inner_html())
    desc = row.locator('td[name="product_template_id"] textarea, td[name="product_id"] textarea').first
    if desc.count() and not desc.is_visible():         # no description yet: the «add a description» button shows it
        row.locator('#labelVisibilityButtonId, button.fa-bars').first.click()
        idle(page, 400)
    current = desc.input_value() if desc.count() else ''
    keep = [l for l in current.split('\n') if ':' in l]              # the native "<attribute>: <value>" line(s)
    if desc.count():
        desc.fill('\n'.join([description] + keep))
    q = row.locator('td[name="product_uom_qty"] input').first
    q.fill(qty)
    p = row.locator('td[name="price_unit"] input').first
    p.fill(price)
    p.press('Tab')
    idle(page, 800)
    return {'configurator': configured, 'description_before': current}


def s_tech_sheet(page):
    tab(page, 'sipanel_tech_sheet')
    page.wait_for_selector('.o_form_view div[name="sipanel_tech_spec_ids"] .o_data_row')
    idle(page, 800)
    liner = page.locator('.o_form_view div[name="sipanel_liner_thickness"]').first
    rows = page.locator('.o_form_view div[name="sipanel_tech_spec_ids"] .o_data_row').count()
    img = page.locator('.o_form_view div[name="sipanel_tech_image"] img').count()
    value = liner.locator('input').first
    return {'rows': rows, 'image': img, 'liner': value.input_value() if value.count() else liner.inner_text()[:80]}


def s_save(page):
    errs = save(page)
    dirty = page.locator('.o_form_status_indicator_buttons:visible').count()
    if errs and any(e.strip() for e in errs):
        raise AssertionError(f'save failed: {errs}')
    return {'url': page.url, 'unsaved': bool(dirty), 'name': page.locator('.o_form_view div[name="name"]').inner_text()}


def s_lines_summary(page):
    tab(page, 'order_lines')
    rows = page.locator('div[name="order_line"] tr.o_data_row')
    out = [re.sub(r'\s+', ' ', rows.nth(i).inner_text())[:200] for i in range(rows.count())]
    totals = re.sub(r'\s+', ' ', field(page, 'tax_totals').inner_text())
    return {'rows': out, 'totals': totals}


def s_print(page):
    """The «چاپ» (Print) button of the quotation header: the PDF of the quotation report is downloaded."""
    btn = page.locator('.o_form_view .o_statusbar_buttons button[name="sale.action_report_saleorder"]').first
    with page.expect_download(timeout=T) as dl:
        btn.click()
    path = f'{OUT}/ui_quotation_fa_IR.pdf'
    dl.value.save_as(path)
    return {'pdf': path, 'suggested': dl.value.suggested_filename}


# ---------------------------------------------------------------- Sales Manager
def m_system_sheet(page):
    """Sales Manager: System technical sheet row edit (row 2 description gets a marker, then is restored)."""
    page.goto(URL + '/odoo/sales', wait_until='domcontentloaded')
    page.wait_for_selector('.o_list_view, .o_kanban_view')
    idle(page)
    # menus a Sales Manager sees (is there one for the Systems / analytic accounts?)
    menus = page.locator('.o_main_navbar .o_menu_sections').inner_text()
    conf = page.locator('.o_main_navbar .o_menu_sections .dropdown-toggle').filter(has_text='پیکربندی')
    config_items = None
    if conf.count():
        conf.first.click()
        page.wait_for_timeout(700)
        config_items = re.sub(r'\s+', ' | ', page.locator('.o-dropdown--menu').first.inner_text())
        page.screenshot(path=f'{OUT}/{N[0]:02d}_manager_configuration_menu.png')
        page.keyboard.press('Escape')
    facet = page.locator('.o_searchview_facet').filter(has_text='پیش‌فاکتورهای من')
    if facet.count():                                   # default filter «my quotations»
        facet.first.locator('.o_facet_remove').click()
        idle(page, 800)
    page.locator('.o_searchview_input').first.fill('SI-26/2546')
    page.keyboard.press('Enter')
    idle(page, 1200)
    page.locator('.o_data_row, .o_kanban_record').filter(has_text='SI-26/2546').first.click()
    page.wait_for_selector('.o_form_view div[name="sipanel_requested_system_id"]')
    idle(page)
    sysf = field(page, 'sipanel_requested_system_id')
    sysf.hover()
    link = sysf.locator('.o_external_button, button.o_external_button, a.o_form_uri').first
    no_menu = None
    if not link.count():
        # the Requested System field is no_open (sipanel_quotation_project_info) and no menu lists the Systems for
        # a Sales Manager: the only way left is a direct link to the analytic account
        no_menu = 'no menu and no link from the quotation: opened by a direct link to the analytic account'
        sid = int(os.environ.get('UI_SYSTEM_ID', '2316'))      # SIPANEL System «Standing Seam» (P8b)
        page.goto(f'{URL}/odoo/action-analytic.action_analytic_account_form/{sid}', wait_until='domcontentloaded')
    else:
        link.click()
    idle(page, 1500)
    try:
        page.wait_for_selector('.o_form_view div[name="plan_id"], .modal .o_form_view, .o_error_dialog, '
                               '.o_notification', timeout=60000)
    except Exception:                                 # noqa: BLE001
        pass
    if not page.locator('.o_form_view div[name="plan_id"]').count():
        err = ' '.join(page.locator('.o_error_dialog, .o_notification, .modal-body').all_inner_texts())[:400]
        raise Blocked(f'{no_menu or "link"}; the System (analytic account) form does not open for a Sales Manager: '
                      f'it reads analytic lines (account.analytic.line), which a Sales Manager may not read '
                      f'(Access Denied by ACLs). Message: {err or "none shown, form not rendered"}')
    scope = '.modal .o_form_view' if page.locator('.modal .o_form_view').count() else '.o_form_view'
    tabs = page.locator(f'{scope} .o_notebook a.nav-link[name="sipanel_tech_sheet"]')
    if not tabs.count():
        raise Blocked(f'the System form has no Technical sheet tab for this user (menus: {menus})')
    tabs.first.click()
    idle(page, 600)
    rows = page.locator(f'{scope} div[name="sipanel_tech_spec_ids"] .o_data_row')
    n = rows.count()
    cell = rows.nth(1).locator('td[name="description"]')
    before = cell.inner_text()
    cell.click()
    ta = rows.nth(1).locator('td[name="description"] textarea, td[name="description"] input').first
    ta.fill(before + ' [UI-TEST]')
    ta.press('Tab')
    btn = page.locator(f'{scope.replace(" .o_form_view", "")} .o_form_button_save, .modal-footer .o_form_button_save').first
    btn.click()
    idle(page, 1500)
    page.screenshot(path=f'{OUT}/{N[0]:02d}_manager_sheet_edited.png', full_page=True)
    # restore (still the UI)
    if scope.startswith('.modal'):
        page.locator('.modal .o_notebook a.nav-link[name="sipanel_tech_sheet"]').first.click()
    rows = page.locator(f'{scope} div[name="sipanel_tech_spec_ids"] .o_data_row')
    edited = rows.nth(1).locator('td[name="description"]').inner_text()
    rows.nth(1).locator('td[name="description"]').click()
    ta = rows.nth(1).locator('td[name="description"] textarea, td[name="description"] input').first
    ta.fill(before)
    ta.press('Tab')
    page.locator(f'{scope.replace(" .o_form_view", "")} .o_form_button_save, .modal-footer .o_form_button_save').first.click()
    idle(page, 1500)
    return {'path': no_menu or 'link from the quotation', 'menus_visible': menus, 'configuration_menu': config_items, 'rows': n, 'edited_to': edited[-40:], 'restored': True, 'opened_in': scope}


def m_terms(page):
    """Sales Manager: default terms (res.company.invoice_terms) - Settings > Sales / Invoicing > Terms & Conditions."""
    page.goto(URL + '/odoo/settings', wait_until='domcontentloaded')
    try:
        page.wait_for_selector('.o_setting_container, .o_settings_container, .o_error_dialog, .o_dialog, '
                               '.o_view_nocontent, .o_action_manager .o_content', timeout=120000)
    except Exception:                                 # noqa: BLE001
        pass
    idle(page, 3000)
    if not page.locator('.o_setting_container, .o_settings_container, div[name="invoice_terms"]').count():
        text = re.sub(r'\s+', ' ', page.locator('body').inner_text())[:300]
        raise Blocked(f'Settings are not available to a Sales Manager (Odoo: Administration / Settings group); '
                      f'the default terms live in Settings > Invoicing > Default Terms & Conditions. Page: {text}')
    return 'settings reachable'


def m_aluminium(page):
    """Sales Manager: aluminium price extra on the roof product (set 1,000,000, then reset to 0)."""
    page.goto(URL + '/odoo/action-sale.product_template_action', wait_until='domcontentloaded')
    page.wait_for_selector('.o_searchview_input')
    idle(page)
    page.locator('.o_searchview_input').first.fill('SIP-000074')
    page.keyboard.press('Enter')
    idle(page, 1500)
    if page.locator('.o_switch_view.o_list').count():
        page.locator('.o_switch_view.o_list').first.click()
        idle(page, 800)
    page.locator('.o_data_row, .o_kanban_record').first.click()
    page.wait_for_selector('.o_form_view div[name="name"]')
    idle(page)
    page.locator('.o_notebook a.nav-link[name="variants"]').first.click()
    idle(page, 600)
    conf = page.locator('div[name="attribute_line_ids"] .o_data_row').filter(has_text='جنس ورق رویه')
    if not conf.count():
        raise Blocked('the material attribute line is not shown on the product (Attributes & Variants)')
    btn = conf.first.locator('button[name="action_open_attribute_values"], button:has-text("پیکربندی"), button:has-text("Configure")')
    if not btn.count():
        raise Blocked('no "Configure" button on the attribute line (needed to edit the price extra)')
    btn.first.click()
    page.wait_for_selector('.o_list_view div[name="price_extra"], .o_list_view td[name="price_extra"]')
    idle(page, 800)
    page.locator('.o_data_row').filter(has_text='آلومینیوم').first.click()       # opens the value's form
    page.wait_for_selector('.o_form_view div[name="price_extra"]')
    idle(page, 600)

    if not page.locator('.o_form_view div[name="price_extra"] input').count():
        raise Blocked('the price extra of a material value is read-only for a Sales Manager: writing '
                      'product.template.attribute.value needs the group Product / Create (product.group_product_manager), '
                      'which Sales / Administrator does not include')

    def set_extra(value):
        inp = page.locator('.o_form_view div[name="price_extra"] input').first
        inp.click()
        inp.fill(value)
        inp.press('Tab')
        page.locator('.o_form_button_save').first.click()
        idle(page, 1200)
        return page.locator('.o_form_view div[name="price_extra"] input').first.input_value()
    set_to = set_extra('1000000')
    page.screenshot(path=f'{OUT}/{N[0]:02d}_manager_aluminium_set.png', full_page=True)
    reset_to = set_extra('0')
    return {'set_to': set_to, 'reset_to': reset_to}


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--disable-dev-shm-usage'])
        if 'all' in STEPS or 'sales' in STEPS:
            page = login(browser, 'ui_sales')
            step('salesperson: new quotation', s_open_new, page)
            step('salesperson: customer (quick create)', s_customer, page)
            step('salesperson: customer language Persian (default is English)', s_customer_lang, page)
            step('salesperson: payment term, delivery 45 days, bank line off', s_header, page)
            step('salesperson: project name + Requested System', s_project, page)
            step('salesperson: installation 10 %, shop drawings 2 % / 100 %', s_percentages, page)
            step('salesperson: section roof + wall', s_section, page, SECTION_1)
            step('salesperson: roof line (material galvanized)', s_line, page, *LINES[0])
            step('salesperson: section accessories', s_section, page, SECTION_2)
            step('salesperson: flashing 58 cm', s_line, page, *LINES[1])
            step('salesperson: flashing 20 cm', s_line, page, *LINES[2])
            step('salesperson: gutter', s_line, page, *LINES[3])
            step('salesperson: note', s_note, page, NOTE)
            step('salesperson: save', s_save, page)
            step('salesperson: technical sheet tab (liner 0.7)', s_tech_sheet, page)
            step('salesperson: lines and totals', s_lines_summary, page)
            step('salesperson: print fa PDF', s_print, page)
            page.context.close()
        if 'all' in STEPS or 'manager' in STEPS:
            page = login(browser, 'ui_manager')
            step('manager: edit a row of the System technical sheet', m_system_sheet, page)
            step('manager: default terms text', m_terms, page)
            step('manager: aluminium price extra (set, then reset)', m_aluminium, page)
            page.context.close()
        browser.close()
    REPORT['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(REPORT, open(f'{OUT}/ui_report.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
