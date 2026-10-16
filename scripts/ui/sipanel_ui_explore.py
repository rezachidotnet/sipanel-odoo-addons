"""Exploration helper for the UI acceptance test: logs in and dumps the DOM + screenshot of given URLs (clone only)."""
import os
import sys
from playwright.sync_api import sync_playwright

URL, PW, OUT = os.environ['UI_URL'], os.environ['UI_PASSWORD'], '/out/explore'
os.makedirs(OUT, exist_ok=True)
user = os.environ.get('UI_USER', 'ui_sales')
paths = os.environ.get('UI_PATHS', '/odoo/sales/new').split()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--disable-dev-shm-usage'])
    page = b.new_page(viewport={'width': 1440, 'height': 1000}, locale='fa-IR')
    page.set_default_timeout(240000)
    page.set_default_navigation_timeout(240000)
    r = page.request.post(URL + '/web/session/authenticate', data={'jsonrpc': '2.0', 'method': 'call', 'params': {
        'db': os.environ['UI_DB'], 'login': user, 'password': PW}})
    assert r.ok and 'error' not in r.json(), r.text()[:300]
    page.goto(URL + '/odoo', wait_until='domcontentloaded')
    page.wait_for_selector('.o_main_navbar', timeout=240000)
    for i, path in enumerate(paths):
        page.goto(URL + path, wait_until='domcontentloaded')
        page.wait_for_selector('.o_form_view, .o_list_view, .o_action', timeout=240000)
        page.wait_for_timeout(6000)
        page.screenshot(path=f'{OUT}/{user}_{i}.png', full_page=True)
        open(f'{OUT}/{user}_{i}.html', 'w').write(page.content())
        print('EXPLORED', user, path, page.url)
    b.close()
