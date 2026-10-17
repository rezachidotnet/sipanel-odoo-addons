# -*- coding: utf-8 -*-
"""UI acceptance test (owner 2026-10-16, re-test 2026-10-17), run by `sipanel_qlines_clone_validate.sh uirun` on a
CLONE only.

A normal salesperson (ui_sales) creates, in the web UI only, a new quotation that reproduces SI-26/2546 - products
picked, nothing typed in the descriptions (the product names are the titles, owner 2026-10-17) - and prints the fa PDF
from a Persian interface, then from an English interface (the PDF must not change). In the English interface the same
salesperson makes a quotation for an English customer with the same products (English titles). The Persian interface
is scanned for labels still in English. A Sales Manager (ui_manager) tries the manager tasks (System sheet row, default
terms, aluminium price extra) - owner decision 2026-10-17: they stay admin-only, so "blocked" is the expected result.
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

def users_info():
    """Written by sipanel_ui_test_users.py (test set-up): product codes as a salesperson finds them."""
    try:
        for line in open(f'{OUT}/users.log', encoding='utf-8'):
            if line.startswith('SIPANEL_UI_USERS '):
                return json.loads(line[len('SIPANEL_UI_USERS '):])
    except OSError:
        pass
    return {}


INFO = users_info()
FLASH20 = INFO.get('products', {}).get('FLASH20', {}).get('code', 'FLASH20')
LINES = [  # (product code, qty, unit price expected) - owner 2026-10-17: no description typed, the product name is the title
    ('SIP-000074', '206', 88_000_000),
    ('SIP-000076', '108.47', 43_800_000),
    (FLASH20, '54.23', 14_600_000),
    ('SIP-000077', '18', 67_000_000),
]
UI = {  # texts that depend on the interface language
    'fa': {'create': 'ایجاد', 'payment': '۷۰٪ پیش‌پرداخت', 'system': 'استندینگ سیم'},
    'en': {'create': 'Create', 'payment': '70% in advance', 'system': 'Standing Seam'},
}
LANG_RE = {'fa': re.compile('فارسی|Persian'), 'en': re.compile(r'English \(US\)')}
CUSTOMER_EN = 'UI Test English Customer'
PROJECT_EN = 'UI English titles check'
QUOTATION = {}


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


def s_customer(page, name=CUSTOMER, ui='fa'):
    inp = field(page, 'partner_id').locator('input').first
    inp.click()
    inp.fill(name)
    page.locator('.o-autocomplete--dropdown-menu').first.wait_for()
    page.wait_for_timeout(800)
    page.locator('.o-autocomplete--dropdown-item').filter(has_text=UI[ui]['create']).first.click()   # quick create
    idle(page)
    return field(page, 'partner_id').locator('input').first.input_value()


def s_customer_lang(page, want='fa'):
    """Owner 2026-10-17, item 3: the default contact language is fa_IR, so a customer quick-created from the quotation
    is Persian; the salesperson only checks it (fa) or sets English for an English customer (en)."""
    f = field(page, 'partner_id')
    f.hover()
    f.locator('.o_external_button').first.click()           # opens the customer (the quotation is saved first)
    page.wait_for_selector('.o_form_view div[name="lang"]')
    idle(page, 800)
    lang = page.locator('.o_form_view div[name="lang"] input').first
    was = lang.input_value()
    now = was
    for attempt in range(3 if not LANG_RE[want].search(was) else 0):   # the select menu sometimes closes early
        lang.click()
        page.locator('.o_select_menu_item').filter(has_text=LANG_RE[want]).first.wait_for()
        page.wait_for_timeout(400)
        page.locator('.o_select_menu_item').filter(has_text=LANG_RE[want]).first.click()
        idle(page, 600)
        now = lang.input_value()
        if LANG_RE[want].search(now):
            break
    if not LANG_RE[want].search(now):
        raise AssertionError(f'customer language still {now!r}')
    page.screenshot(path=f'{OUT}/{N[0]:02d}_customer_language.png', full_page=True)
    btn = page.locator('.o_form_button_save').first
    if btn.is_visible():                              # nothing to save when the default language was the right one
        btn.click()
        idle(page, 1000)
    page.locator('.o_back_button a').first.click()          # back to the quotation (breadcrumb)
    page.wait_for_selector('.o_form_view div[name="sipanel_requested_system_id"]')
    idle(page, 800)
    return {'language_default': was, 'default_is_persian': bool(LANG_RE['fa'].search(was)), 'language_after': now,
            'changed': was != now, 'quotation': page.url}


def s_header(page, ui='fa'):
    m2o(page, 'payment_term_id', UI[ui]['payment'])
    type_into(page, 'sipanel_delivery_days', '45')
    bank = field(page, 'sipanel_show_bank_account').locator('input').first
    if bank.is_checked():
        bank.uncheck()
    # owner 2026-10-17, item 5: validity 8 days by default (native setting) - read, not typed
    return {'payment_term': field(page, 'payment_term_id').locator('input').first.input_value(),
            'bank_line': bank.is_checked(),
            'date_order': field(page, 'date_order').locator('input').first.input_value(),
            'validity_date': field(page, 'validity_date').locator('input').first.input_value(),
            'validity_shamsi': field(page, 'validity_date_shamsi').inner_text().strip()}


def s_project(page, project=PROJECT, ui='fa'):
    type_into(page, 'sipanel_project_name', project)
    m2o(page, 'sipanel_requested_system_id', UI[ui]['system'])
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


def number(text):
    return float((text or '0').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٬٫', '0123456789,.')).replace(',', '') or 0)


def s_line(page, code, qty, price):
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
    q = row.locator('td[name="product_uom_qty"] input').first
    q.fill(qty)
    q.press('Tab')
    idle(page, 800)
    row = page.locator('div[name="order_line"] tr.o_selected_row').first
    if not row.count():
        page.locator('div[name="order_line"] tr.o_data_row:not(.o_is_line_section):not(.o_is_line_note)').last.locator(
            'td[name="price_unit"]').click()
        idle(page, 600)
        row = page.locator('div[name="order_line"] tr.o_selected_row').first
    p = row.locator('td[name="price_unit"] input').first
    auto = number(p.input_value())
    typed = abs(auto - price) > 0.5                   # the list price is the expected price: nothing to type
    if typed:
        p.fill(str(price))
        p.press('Tab')
        idle(page, 800)
    label = row.locator('td[name="product_template_id"], td[name="product_id"]').first.inner_text()
    return {'configurator': configured, 'price_from_product': auto, 'price_typed': typed,
            'line_label': re.sub(r'\s+', ' ', label)[:200], 'description_typed': False}


def s_tech_sheet(page):
    tab(page, 'sipanel_tech_sheet')
    page.wait_for_selector('.o_form_view div[name="sipanel_tech_spec_ids"] .o_data_row')
    idle(page, 800)
    liner = page.locator('.o_form_view div[name="sipanel_liner_thickness"]').first
    rows = page.locator('.o_form_view div[name="sipanel_tech_spec_ids"] .o_data_row').count()
    img = page.locator('.o_form_view div[name="sipanel_tech_image"] img').count()
    value = liner.locator('input').first
    helptext = page.locator('.o_form_view div[name="sipanel_tech_sheet_help"]')
    return {'rows': rows, 'image': img, 'liner': value.input_value() if value.count() else liner.inner_text()[:80],
            'help': re.sub(r'\s+', ' ', helptext.first.inner_text()) if helptext.count() else None}


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


def s_print(page, name='ui_quotation_fa_IR_ui-fa.pdf', url=None):
    """The «چاپ» / Print button of the quotation header: the PDF of the quotation report is downloaded."""
    if url:
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_selector('.o_form_view div[name="partner_id"]')
        idle(page, 1000)
    btn = page.locator('.o_form_view .o_statusbar_buttons button[name="sale.action_report_saleorder"]').first
    with page.expect_download(timeout=T) as dl:
        btn.click()
    path = f'{OUT}/{name}'
    dl.value.save_as(path)
    return {'pdf': path, 'suggested': dl.value.suggested_filename, 'quotation': page.url}


def s_remember(page, key):
    QUOTATION[key] = page.url
    return page.url


LATIN = re.compile('[A-Za-z]')
PERSIAN_RE = re.compile('[\u0600-\u06FF]')


def s_english_labels(page):
    """Owner 2026-10-17, item 6: labels of the quotation form still in English in the Persian interface (every tab).
    Codes, units, the company and product names are data, not labels: only labels, tabs, column titles and buttons."""
    found = {}
    for tab_name in ('order_lines', 'sipanel_tech_sheet', 'other_information'):
        tabs = page.locator(f'.o_notebook a.nav-link[name="{tab_name}"]')
        if tabs.count():
            tabs.first.click()
            idle(page, 500)
        texts = page.locator('.o_form_view .o_form_label, .o_form_view .o_notebook .nav-link, '
                             '.o_form_view th, .o_form_view .o_statusbar_buttons button, '
                             '.o_form_view div[name="sipanel_tech_sheet_help"]').all_inner_texts()
        for t in texts:
            t = ' '.join(t.split())
            if t and LATIN.search(t) and not PERSIAN_RE.search(t) and t not in ('PDF',):
                found.setdefault(t, tab_name)
    tab(page, 'order_lines')
    return {'english_labels': found, 'count': len(found)}


def s_ui_language(page, want='en'):
    """The salesperson switches the interface language in the user menu (Preferences), as a user would."""
    page.locator('.o_user_menu .dropdown-toggle, .o_user_menu button').first.click()
    page.wait_for_timeout(600)
    item = page.locator('.o-dropdown--menu [data-menu="settings"], .o-dropdown--menu .dropdown-item').filter(
        has_text=re.compile('تنظیمات|Preferences|ترجیحات')).first
    item.click()
    page.wait_for_selector('.modal .o_form_view div[name="lang"], .o_form_view div[name="lang"]')
    idle(page, 800)
    scope = '.modal .o_form_view' if page.locator('.modal .o_form_view div[name="lang"]').count() else '.o_form_view'
    lang = page.locator(f'{scope} div[name="lang"] input').first
    was = lang.input_value()
    for attempt in range(3):
        lang.click()
        page.locator('.o_select_menu_item').filter(has_text=LANG_RE[want]).first.wait_for()
        page.wait_for_timeout(400)
        page.locator('.o_select_menu_item').filter(has_text=LANG_RE[want]).first.click()
        idle(page, 600)
        if LANG_RE[want].search(lang.input_value()):
            break
    now = lang.input_value()
    page.screenshot(path=f'{OUT}/{N[0]:02d}_preferences_language.png', full_page=True)
    page.locator('.modal-footer button.btn-primary, .modal .o_form_button_save, .o_form_button_save').first.click()
    page.wait_for_timeout(2500)
    page.wait_for_selector('.o_main_navbar')
    idle(page, 1500)
    return {'interface_before': was, 'interface_after': now, 'html_lang': page.evaluate('document.documentElement.lang')}


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
            step('salesperson: customer language (default Persian)', s_customer_lang, page, 'fa')
            step('salesperson: payment term, delivery 45 days, bank line off, validity', s_header, page)
            step('salesperson: project name + Requested System', s_project, page)
            step('salesperson: installation 10 %, shop drawings 2 % / 100 %', s_percentages, page)
            step('salesperson: section roof + wall', s_section, page, SECTION_1)
            step('salesperson: roof product (material galvanized)', s_line, page, *LINES[0])
            step('salesperson: section accessories', s_section, page, SECTION_2)
            step('salesperson: flashing 58 cm product', s_line, page, *LINES[1])
            step('salesperson: flashing 20 cm product', s_line, page, *LINES[2])
            step('salesperson: gutter product', s_line, page, *LINES[3])
            step('salesperson: note', s_note, page, NOTE)
            step('salesperson: save', s_save, page)
            step('salesperson: (quotation url)', s_remember, page, 'fa')
            step('salesperson: technical sheet tab (liner 0.7, help text)', s_tech_sheet, page)
            step('salesperson: lines and totals', s_lines_summary, page)
            step('salesperson: Persian interface - labels still in English', s_english_labels, page)
            step('salesperson: print fa PDF (Persian interface)', s_print, page, 'ui_quotation_fa_IR_ui-fa.pdf')
            step('salesperson: interface language English (Preferences)', s_ui_language, page, 'en')
            step('salesperson: print fa PDF again (English interface)', s_print, page, 'ui_quotation_fa_IR_ui-en.pdf',
                 QUOTATION.get('fa'))
            # English customer, same products: English titles
            step('salesperson (en): new quotation', s_open_new, page)
            step('salesperson (en): customer (quick create)', s_customer, page, CUSTOMER_EN, 'en')
            step('salesperson (en): customer language English', s_customer_lang, page, 'en')
            step('salesperson (en): payment term, delivery 45 days, validity', s_header, page, 'en')
            step('salesperson (en): project name + Requested System', s_project, page, PROJECT_EN, 'en')
            step('salesperson (en): installation 10 %, shop drawings 2 % / 100 %', s_percentages, page)
            for code, qty, price in LINES:
                step(f'salesperson (en): product {code}', s_line, page, code, qty, price)
            step('salesperson (en): save', s_save, page)
            step('salesperson (en): (quotation url)', s_remember, page, 'en')
            step('salesperson (en): lines and totals', s_lines_summary, page)
            step('salesperson (en): print en PDF (English interface)', s_print, page, 'ui_quotation_en_US_ui-en.pdf')
            step('salesperson: interface language back to Persian', s_ui_language, page, 'fa')
            step('salesperson: print en PDF again (Persian interface)', s_print, page, 'ui_quotation_en_US_ui-fa.pdf',
                 QUOTATION.get('en'))
            page.context.close()
        if 'all' in STEPS or 'manager' in STEPS:
            page = login(browser, 'ui_manager')
            # owner decision 2026-10-17 (option A): these stay admin tasks - "blocked" is the expected result
            step('manager: edit a row of the System technical sheet (expected: admin only)', m_system_sheet, page)
            step('manager: default terms text (expected: admin only)', m_terms, page)
            step('manager: aluminium price extra (expected: admin only)', m_aluminium, page)
            page.context.close()
        browser.close()
    REPORT['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(REPORT, open(f'{OUT}/ui_report.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
