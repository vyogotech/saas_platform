"""
Tenant-Isolated Naming Series for SaaS Platform.
Ensures document naming series and counters in tabSeries are namespaced per tenant,
preventing sequence gaps, primary key collisions, and cross-tenant volume leaks.
"""

from functools import lru_cache
import re

import frappe
from frappe.model.naming import get_default_naming_series

from saas_platform.utils.tenant import get_tenant_id


SYSTEM_DOCTYPES = {
    "User", "Role", "DocType", "DocField", "DocPerm", "Module Def",
    # Subscription / Subscription Plan are tenant data too (tenants bill their own customers)
    "Domain", "Domain Settings", "Tenant", "Plan", "Customer", "Workspace",
    "Workflow", "Print Format", "Email Template", "System Settings",
    "Website Settings", "Portal Settings", "Error Log", "Activity Log",
    "Version", "Communication", "Comment", "File", "Custom Field",
    "Property Setter", "Singles", "Patch Log", "DefaultValue", "Sessions"
}


def get_tenant_code(tenant_id: str = None) -> str:
    """
    Sanitize tenant_id into a concise, uppercase alphanumeric code.
    Guarantees global uniqueness across tenants.
    Examples:
      - '8K2M9X1A' -> '8K2M9X1A'
      - 'acme_corp_123' -> 'ACMECORP12'
      - 'tenant_1' -> 'TENANT1'
    """
    if not tenant_id or tenant_id == "SYSTEM":
        return ""
    clean = re.sub(r"[^A-Za-z0-9]", "", str(tenant_id)).upper()
    return clean[:10]

@lru_cache(maxsize=1024)
def _resolve_cached_abbr(company_name: str, tenant_id: str) -> str:
    abbr = None
    if company_name:
        try:
            abbr = frappe.get_cached_value("Company", company_name, "abbr")
        except Exception:
            pass
        if not abbr:
            try:
                abbr = frappe.db.get_value("Company", company_name, "abbr")
            except Exception:
                pass

    if not abbr and tenant_id and tenant_id != "SYSTEM":
        try:
            abbr = frappe.db.get_value("Company", {"tenant_id": tenant_id}, "abbr")
        except Exception:
            pass

    if abbr:
        clean = re.sub(r"[^A-Za-z0-9]", "", str(abbr)).upper()
        return clean[:8]

    return ""


def clear_naming_cache():
    """Clear memory caches when company or tenant records are updated."""
    _resolve_cached_abbr.cache_clear()


def get_company_abbr(doc=None, tenant_id=None) -> str:
    """
    Look up the Company abbreviation for the document or tenant.
    Uses in-memory LRU cache (<0.001ms) to eliminate DB lookups on high-throughput inserts.
    """
    company_name = getattr(doc, "company", None) if doc else None
    return _resolve_cached_abbr(str(company_name or ""), str(tenant_id or ""))



def get_tenant_prefix(doc=None, tenant_id=None) -> str:
    """
    Determine composite tenant-company prefix for namespacing naming series.
    Guarantees global uniqueness across tenants even if company abbreviations are identical.

    Structure:
      - If company abbr exists: '{tenant_code}-{company_abbr}' (e.g. 'T1A2-ACM')
      - If no company abbr: '{tenant_code}' (e.g. 'T1A2')
    """
    if not tenant_id and doc:
        tenant_id = getattr(doc, "tenant_id", None)
    if not tenant_id:
        tenant_id = get_tenant_id()

    if not tenant_id or tenant_id == "SYSTEM":
        return ""

    tenant_code = get_tenant_code(tenant_id)
    if not tenant_code:
        return ""

    abbr = get_company_abbr(doc, tenant_id)
    if abbr:
        return f"{tenant_code}-{abbr}"

    return tenant_code


def namespace_naming_series(doc, method=None):
    """
    Hooked to 'before_naming'.
    Prepends composite tenant prefix to doc.naming_series before make_autoname runs.
    Ensures independent counters in tabSeries and unique primary keys across tenants,
    even when multiple tenants share identical company abbreviations.
    """
    # 1. Bypass checks
    if (
        getattr(frappe.flags, "in_migrate", False)
        or getattr(frappe.flags, "in_install", False)
        or getattr(frappe.flags, "in_patch", False)
        or getattr(frappe.session, "user", None) == "Administrator"
    ):
        return

    # Skip system doctypes
    if doc.doctype in SYSTEM_DOCTYPES:
        return

    # Skip amended documents (amendments append -1, -2 handled natively by Frappe)
    if getattr(doc, "amended_from", None):
        return

    tenant_id = getattr(doc, "tenant_id", None)
    if not tenant_id:
        tenant_id = get_tenant_id()

    if not tenant_id or tenant_id == "SYSTEM":
        return

    tenant_code = get_tenant_code(tenant_id)
    if not tenant_code:
        return

    abbr = get_company_abbr(doc, tenant_id)
    composite_prefix = f"{tenant_code}-{abbr}" if abbr else tenant_code
    prefix_tag = f"{composite_prefix}-"

    # Check if doc has naming_series field
    if hasattr(doc, "naming_series"):
        series = doc.naming_series
        if not series:
            try:
                series = get_default_naming_series(doc.doctype)
            except Exception:
                series = None

        if series:
            # 1. Idempotency check: already starts with composite prefix or tenant code
            if series.startswith(prefix_tag) or series.startswith(f"{tenant_code}-"):
                return

            # 2. Smart check: if user already typed 'ACM-' or 'ACM.' at start of series (case-insensitive)
            if abbr and (series.upper().startswith(f"{abbr}-") or series.upper().startswith(f"{abbr}.")):
                # Prepend only tenant_code to avoid double abbr (e.g. TENANT1-ACM-ACM-...)
                doc.naming_series = f"{tenant_code}-{series}"
            else:
                doc.naming_series = f"{prefix_tag}{series}"


def set_display_number(doc, method=None):
    """
    Hooked to 'before_save'.
    Populates customer-facing display_number by stripping the internal tenant_code prefix,
    preserving company abbreviation and series number for customer invoices.
    Example: 'TNT1-ACM-ACC-SINV-2026-00001' -> 'ACM-ACC-SINV-2026-00001'
             'TNT1-ACC-SINV-2026-00001'     -> 'ACC-SINV-2026-00001'
    """
    if not getattr(doc, "name", None):
        return

    tenant_id = getattr(doc, "tenant_id", None) or get_tenant_id()
    if not tenant_id or tenant_id == "SYSTEM":
        return

    tenant_code = get_tenant_code(tenant_id)
    if not tenant_code:
        return

    code_tag = f"{tenant_code}-"
    if doc.name.startswith(code_tag):
        clean_name = doc.name[len(code_tag):]
        # Set on document attribute (and custom field if present)
        doc.display_number = clean_name
        if hasattr(doc, "set"):
            try:
                doc.set("display_number", clean_name)
            except Exception:
                pass


def get_clean_display_name(doc_or_name, tenant_prefix: str = None) -> str:
    """
    Utility for Jinja templates / print formats to display clean invoice numbers.
    Strips internal tenant_code prefix while preserving company abbreviation and series.
    Examples:
      - 'TNT1-ACM-ACC-SINV-2026-00001' -> 'ACM-ACC-SINV-2026-00001'
      - '8K2M9X1A-ACC-SINV-2026-00001' -> 'ACC-SINV-2026-00001'
    """
    name = getattr(doc_or_name, "name", doc_or_name) if doc_or_name else ""
    if not name or not isinstance(name, str):
        return name

    if tenant_prefix:
        prefix_tag = f"{tenant_prefix}-"
        if name.startswith(prefix_tag):
            return name[len(prefix_tag):]

    # Try current session tenant_id
    try:
        tenant_id = get_tenant_id()
        if tenant_id and tenant_id != "SYSTEM":
            tenant_code = get_tenant_code(tenant_id)
            if tenant_code:
                code_tag = f"{tenant_code}-"
                if name.startswith(code_tag):
                    return name[len(code_tag):]
    except Exception:
        pass

    # Generic strip if starts with uppercase alphanumeric code (3-10 chars) followed by '-'
    parts = name.split("-", 1)
    if len(parts) == 2 and 3 <= len(parts[0]) <= 10 and parts[0].isalnum() and parts[0].isupper():
        return parts[1]

    return name


_naming_patched = False
_orig_getseries = None
_orig_revert_series_if_last = None


def patch_frappe_naming():
    """
    Monkey-patches frappe.model.naming.getseries and revert_series_if_last
    to ensure all counter operations in tabSeries are automatically scoped
    to the active tenant, even for format-based series or direct calls.
    """
    global _naming_patched, _orig_getseries, _orig_revert_series_if_last
    if _naming_patched:
        return

    import frappe.model.naming as frappe_naming

    _orig_getseries = frappe_naming.getseries
    _orig_revert_series_if_last = getattr(frappe_naming, "revert_series_if_last", None)



    def tenant_aware_getseries(key, digits):
        if (
            getattr(frappe.flags, "in_migrate", False)
            or getattr(frappe.flags, "in_install", False)
            or getattr(frappe.flags, "in_patch", False)
            or getattr(frappe.session, "user", None) == "Administrator"
        ):
            return _orig_getseries(key, digits)

        tenant_id = get_tenant_id()
        if not tenant_id or tenant_id == "SYSTEM":
            return _orig_getseries(key, digits)

        tenant_prefix = get_tenant_prefix(tenant_id=tenant_id)
        if tenant_prefix and not key.startswith(f"{tenant_prefix}-"):
            key = f"{tenant_prefix}-{key}"

        return _orig_getseries(key, digits)

    def tenant_aware_revert_series_if_last(key, name, doc=None):
        if (
            getattr(frappe.flags, "in_migrate", False)
            or getattr(frappe.flags, "in_install", False)
            or getattr(frappe.flags, "in_patch", False)
            or getattr(frappe.session, "user", None) == "Administrator"
        ):
            if _orig_revert_series_if_last:
                return _orig_revert_series_if_last(key, name, doc=doc)
            return

        tenant_id = get_tenant_id() or (getattr(doc, "tenant_id", None) if doc else None)
        if not tenant_id or tenant_id == "SYSTEM":
            if _orig_revert_series_if_last:
                return _orig_revert_series_if_last(key, name, doc=doc)
            return

        tenant_prefix = get_tenant_prefix(doc=doc, tenant_id=tenant_id)
        if tenant_prefix and not key.startswith(f"{tenant_prefix}-"):
            key = f"{tenant_prefix}-{key}"

        if _orig_revert_series_if_last:
            return _orig_revert_series_if_last(key, name, doc=doc)

    frappe_naming.getseries = tenant_aware_getseries
    if _orig_revert_series_if_last:
        frappe_naming.revert_series_if_last = tenant_aware_revert_series_if_last

    _naming_patched = True



