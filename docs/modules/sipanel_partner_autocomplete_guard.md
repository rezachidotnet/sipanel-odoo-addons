# sipanel_partner_autocomplete_guard

**Status:** installed in Production `sipanel` since 2026-09-14, version 19.0.1.0.0. Added to source control on
2026-10-07: until then it existed only in `/opt/odoo/addons` and was in no repository. The directory
`addons/sipanel_partner_autocomplete_guard/` is byte-identical to the deployed copy (sha256 below). This README lives
outside the module so that stays true.

## What it does

It inherits `res.partner` and overrides `autocomplete_by_name(query, query_country_id, timeout=15)` to return `[]`.
The native `partner_autocomplete` module uses that method to suggest companies while a user types a partner name.
The suggestions come from Odoo's external IAP service. With the override, no request leaves the server and the
name field behaves like a plain input. Nothing else changes: no fields, data, views, security or other methods.

## Why

The manifest summary says: "Bypass unavailable external partner name autocomplete". The IAP autocomplete service is
not usable from this installation. Typing a partner name would otherwise wait for an external call that cannot
succeed (up to the 15 s timeout) or raise errors in the form. The original change request is not on record; this
reason comes from the manifest and the code. The 2026-09-15 product preflight reviewed it after installation:
"No product, stock, accounting or analytic impact".

## Removing it

Uninstalling restores the native IAP name autocomplete, so only do it once the IAP service is reachable and wanted.
`partner_autocomplete` itself stays installed. The module has no data to migrate.

## Deployed copy (sha256, 2026-10-07)

```
5fd10918e1361ad65b4b41bcd8fb525e659267f47c8c4334ae52530e58908e9e  __init__.py
8c1f8712bfa8b5f1b1ed4c7c8e3ecef253f081d707d2f9548809c5a262b3152e  __manifest__.py
83e0e9d99c0dea80780aa7507e04489cd4b374c580550835be358bed2f993833  models/__init__.py
df611c92136f3147927cdf9d73570e7e5a5bdc298478978b0163497426eeab8c  models/res_partner.py
```
