"""
Tenant-Isolated Naming Series for SaaS Platform.
Ensures document naming series and counters in tabSeries are namespaced per tenant,
preventing sequence gaps, primary key collisions, and cross-tenant volume leaks.
"""

try:
    import frappe
    from frappe.model.naming import get_default_naming_series
except ImportError:
    class _MockFlags:
        in_migrate = False
        in_install = False
        in_patch = False

    class _MockSession:
        user = None
        data = {}

        @classmethod
        def get(cls, key, default=None):
            return cls.data.get(key, default)

    class _MockDB:
        @staticmethod
        def get_value(*args, **kwargs):
            return None

    class _MockFrappe:
        flags = _MockFlags()
        session = _MockSession()
        db = _MockDB()

        @staticmethod
        def get_cached_value(*args, **kwargs):
            return None

    frappe = _MockFrappe()

    def get_default_naming_series(doctype):
        return None


SYSTEM_DOCTYPES = {
    "User", "Role", "DocType", "DocField", "DocPerm", "Module Def",
    "Domain", "Domain Settings", "Tenant", "Plan", "Subscription Plan",
    "Subscription", "Subscription Plan Detail", "Customer", "Workspace",
    "Workflow", "Print Format", "Email Template", "System Settings",
    "Website Settings", "Portal Settings", "Error Log", "Activity Log",
    "Version", "Communication", "Comment", "File", "Custom Field",
    "Property Setter", "Singles", "Patch Log", "DefaultValue", "Sessions"
}


def get_tenant_prefix(doc=None, tenant_id=None) -> str:
    """
    Determine the prefix for namespacing naming series.
    Prefers the Company abbreviation (e.g. ACM, BET), falling back to a tenant slug.
    """
    if not tenant_id and doc:
        tenant_id = getattr(doc, "tenant_id", None)
    if not tenant_id:
        tenant_id = frappe.session.get("tenant_id") if hasattr(frappe, "session") and hasattr(frappe.session, "get") else None

    if not tenant_id or tenant_id == "SYSTEM":
        return ""

    tenant_prefix = None

    # 1. Try company on the document
    if doc and getattr(doc, "company", None):
        try:
            tenant_prefix = frappe.get_cached_value("Company", doc.company, "abbr")
        except Exception:
            pass
        if not tenant_prefix:
            try:
                tenant_prefix = frappe.db.get_value("Company", doc.company, "abbr")
            except Exception:
                pass

    # 2. Try looking up Company linked to tenant_id
    if not tenant_prefix:
        try:
            tenant_prefix = frappe.db.get_value("Company", {"tenant_id": tenant_id}, "abbr")
        except Exception:
            pass

    # 3. Fallback to tenant_id slug
    if not tenant_prefix:
        clean_slug = tenant_id.replace("-", "").replace("_", "")
        tenant_prefix = clean_slug[:4].upper()

    return tenant_prefix.strip().upper()


def namespace_naming_series(doc, method=None):
    """
    Hooked to 'before_naming'.
    Prepends tenant prefix (e.g. 'ACM-') to doc.naming_series before make_autoname runs.
    Ensures independent counters in tabSeries and unique primary keys.
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
        tenant_id = frappe.session.get("tenant_id") if hasattr(frappe, "session") and hasattr(frappe.session, "get") else None

    if not tenant_id or tenant_id == "SYSTEM":
        return

    tenant_prefix = get_tenant_prefix(doc, tenant_id)
    if not tenant_prefix:
        return

    prefix_tag = f"{tenant_prefix}-"

    # Check if doc has naming_series field
    if hasattr(doc, "naming_series"):
        series = doc.naming_series
        if not series:
            try:
                series = get_default_naming_series(doc.doctype)
            except Exception:
                series = None

        if series:
            if not series.startswith(prefix_tag):
                doc.naming_series = f"{prefix_tag}{series}"


def set_display_number(doc, method=None):
    """
    Hooked to 'before_save' or 'after_insert'.
    Populates customer-facing display_number by stripping the internal tenant prefix.
    """
    if not doc.name:
        return

    tenant_id = getattr(doc, "tenant_id", None) or (
        frappe.session.get("tenant_id") if hasattr(frappe, "session") and hasattr(frappe.session, "get") else None
    )
    if not tenant_id or tenant_id == "SYSTEM":
        return

    tenant_prefix = get_tenant_prefix(doc, tenant_id)
    if not tenant_prefix:
        return

    prefix_tag = f"{tenant_prefix}-"
    if doc.name.startswith(prefix_tag):
        clean_name = doc.name[len(prefix_tag):]
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
    Example: 'ACM-ACC-SINV-2026-00001' -> 'ACC-SINV-2026-00001'
    """
    name = getattr(doc_or_name, "name", doc_or_name) if doc_or_name else ""
    if not name or not isinstance(name, str):
        return name

    if tenant_prefix:
        prefix_tag = f"{tenant_prefix}-"
        if name.startswith(prefix_tag):
            return name[len(prefix_tag):]

    # If tenant prefix not supplied, detect pattern: 2-6 uppercase letters followed by dash
    parts = name.split("-", 1)
    if len(parts) == 2 and 2 <= len(parts[0]) <= 6 and parts[0].isupper():
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

    try:
        try:
            import frappe.model.naming as frappe_naming
        except (ImportError, AttributeError):
            import sys
            frappe_naming = sys.modules.get("frappe.model.naming")

        if not frappe_naming:
            return

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

            tenant_id = (
                frappe.session.get("tenant_id")
                if hasattr(frappe, "session") and hasattr(frappe.session, "get")
                else None
            )
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

            tenant_id = (
                frappe.session.get("tenant_id")
                if hasattr(frappe, "session") and hasattr(frappe.session, "get")
                else (getattr(doc, "tenant_id", None) if doc else None)
            )
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
    except Exception:
        pass

