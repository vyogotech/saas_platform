"""Tenant management utilities"""
import frappe
from frappe import _
import contextlib
import random
import string

# Records the platform keeps about tenants (level-1 billing: our Customer, Subscription and
# invoices per tenant, the platform Company). Never visible to tenants: the tenant scope is
# "own tenant_id OR 'SYSTEM'", and SYSTEM stays for reference data shared by everyone.
PLATFORM_TENANT = "PLATFORM"


def on_session_creation(login_manager):
    """
    Post-login hook to set tenant_id in session.
    Called after user successfully logs in.
    """
    user = login_manager.user

    # Administrator always gets SYSTEM tenant_id
    if user == "Administrator":
        frappe.session.data["tenant_id"] = "SYSTEM"
        _persist_session()
        frappe.log("Session created for Administrator with tenant_id=SYSTEM")
        return

    # Get tenant_id from User document
    try:
        user_doc = frappe.get_doc("User", user)
        tenant_id = getattr(user_doc, 'tenant_id', None)

        if tenant_id:
            # session.data is what Frappe persists; top-level session keys are lost on the next request
            frappe.session.data["tenant_id"] = tenant_id
            _persist_session()
            frappe.log(
                f"Session created for {user} with tenant_id={tenant_id}")
        else:
            frappe.log(f"Warning: User {user} has no tenant_id assigned")
    except Exception as e:
        frappe.log_error(f"Failed to get tenant_id for user {user}: {str(e)}")


def _persist_session():
    # The session row and cache are written before on_session_creation runs; save again
    # so later requests read tenant_id from the session instead of re-querying User.
    if session_obj := getattr(frappe.local, "session_obj", None):
        session_obj.update(force=True)


def set_tenant_id(doc, method=None):
    """Automatically set tenant_id when documents are created"""
    # During tenant provisioning (run as Administrator), tag everything created
    # for the tenant: Company, chart of accounts, cost centers, warehouses, ...
    acting_tenant = getattr(frappe.local, "saas_acting_tenant", None)

    # Skip system doctypes that shouldn't have tenant isolation
    system_doctypes = [
        'Usera', 'Role', 'DocType', 'DocField', 'DocPerm', 'Module Def',
        'Domain', 'Domain Settings', 'Tenant', 'Plan', 'aSubscription Plan',
        'aCustomer',
        'Workspace', 'Workflow', 'Print Format', 'Email Template',
        'System Settings', 'Website Settings', 'Portal Settings',
        'Error Log', 'Activity Log', 'Version', 'Communication',
        'Comment', 'File', 'Session', 'aToken Cache'
    ]

    if doc.doctype in system_doctypes:
        return

    # Skip if tenant_id is already set
    if getattr(doc, 'tenant_id', None):
        return

    if frappe.session.user == "Administrator":
        # Administrator / scheduler (e.g. Subscription invoices): inherit the Company's tenant,
        # so platform billing stays PLATFORM and a tenant's own scheduled docs stay theirs
        tenant_id = acting_tenant or _company_tenant(doc)
    else:
        tenant_id = acting_tenant or get_tenant_id()

    # Set tenant_id if found
    if tenant_id:
        doc.tenant_id = tenant_id


def _company_tenant(doc):
    company = doc.get("company")
    tenant_id = frappe.get_cached_value("Company", company, "tenant_id") if company else None
    return tenant_id if tenant_id and tenant_id != "SYSTEM" else None


def get_platform_company():
    """The Company the platform bills tenants from (site config override, else global default)."""
    return frappe.conf.get("saas_platform_company") or frappe.defaults.get_global_default("company")


def persist_tenant_id(doc, method=None):
    """
    Write doc.tenant_id to the row and its child rows.

    tenant_id is a raw ALTER TABLE column, not a DocField, so Frappe's ORM never
    includes it in INSERT/UPDATE. Without this every row keeps DEFAULT 'SYSTEM'.
    Runs on after_insert / on_update / on_update_after_submit so child rows added
    in later saves are tagged too.
    """
    tenant_id = doc.get("tenant_id")
    if not tenant_id or tenant_id == "SYSTEM" or doc.meta.istable:
        return

    from saas_platform.utils.sql_rewriter import get_tenant_tables

    tables = get_tenant_tables()
    if f"tab{doc.doctype}" in tables:
        frappe.db.set_value(doc.doctype, doc.name, "tenant_id", tenant_id, update_modified=False)

    for df in doc.meta.get_table_fields():
        if f"tab{df.options}" in tables:
            frappe.db.set_value(
                df.options,
                {"parent": doc.name, "parenttype": doc.doctype, "parentfield": df.fieldname},
                "tenant_id", tenant_id, update_modified=False,
            )


@contextlib.contextmanager
def acting_tenant(tenant_id):
    """Tag documents created inside this block with tenant_id (tenant provisioning)."""
    previous = getattr(frappe.local, "saas_acting_tenant", None)
    frappe.local.saas_acting_tenant = tenant_id
    try:
        yield
    finally:
        frappe.local.saas_acting_tenant = previous


def generate_tenant_id():
    """Generate a unique tenant ID"""
    while True:
        # Generate a random 8-character alphanumeric ID
        tenant_id = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=8))

        # Check if it already exists
        if not frappe.db.exists("Tenant", {"tenant_id": tenant_id}):
            return tenant_id


@contextlib.contextmanager
def internal_query():
    """Run platform lookups without tenant SQL rewriting (prevents recursion)."""
    depth = getattr(frappe.local, "saas_internal_depth", 0)
    frappe.local.saas_internal_depth = depth + 1
    try:
        yield
    finally:
        frappe.local.saas_internal_depth = depth


def in_internal_query():
    return getattr(frappe.local, "saas_internal_depth", 0) > 0


def get_tenant_id():
    """
    Get the current user's tenant_id.

    on_session_creation is the only writer of session.data["tenant_id"]. Requests
    without it (background jobs, where frappe.set_user creates an empty session, or
    sessions created before that hook was deployed) fall back to the User record;
    the result is memoised on frappe.local, keyed by user, never written to the session.
    """
    session = frappe.session
    user = session.user if session else None
    if not user or user == "Guest":
        return None

    data = session.get("data") or {}
    tenant_id = data.get("tenant_id")
    if tenant_id:
        return tenant_id

    cached = getattr(frappe.local, "saas_tenant_ctx", None)
    if cached and cached[0] == user:
        return cached[1]

    with internal_query():
        tenant_id = frappe.db.get_value("User", user, "tenant_id") or None
    frappe.local.saas_tenant_ctx = (user, tenant_id)
    return tenant_id


def get_tenant_company(tenant_id):
    """Company provisioned for tenant_id. Looked up only by tenant_id, never by name."""
    if not tenant_id or tenant_id == "SYSTEM":
        return None
    with internal_query():
        return frappe.db.get_value("Company", {"tenant_id": tenant_id}, "name", order_by="creation asc")


def bind_user_to_tenant_company(user, tenant_id):
    """Restrict user to their tenant's Company via User Permission (enforced on report filters)."""
    company = get_tenant_company(tenant_id)
    if not company:
        frappe.throw(_("No Company found for tenant {0}").format(tenant_id))

    if not frappe.db.exists("User Permission", {"user": user, "allow": "Company", "for_value": company}):
        frappe.get_doc({
            "doctype": "User Permission",
            "user": user,
            "allow": "Company",
            "for_value": company,
            "is_default": 1,
        }).insert(ignore_permissions=True)
    return company


def on_user_insert(doc, method=None):
    """Users created inside a tenant inherit tenant_id via set_tenant_id; bind their Company."""
    tenant_id = doc.get("tenant_id")
    if tenant_id and tenant_id != "SYSTEM":
        bind_user_to_tenant_company(doc.name, tenant_id)


def apply_tenant_filter(doc, method=None):
    """Apply tenant filter to queries"""
    tenant_id = get_tenant_id()

    if tenant_id:
        # Allow access to SYSTEM tenant data and own tenant data
        return f"(`tabtenantid` = '{tenant_id}' OR `tab{doc.doctype}`.`tenant_id` = 'SYSTEM' OR `tab{doc.doctype}`.`tenant_id` IS NULL)"

    return None


def get_permission_query_conditions(user, doctype):
    """
    Return SQL conditions for filtering documents by tenant_id.
    Administrator can see all documents.
    Other users can only see their tenant's data + SYSTEM data.
    """
    # Administrator can see everything
    if user == "Administrator":
        return None

    # Users: tenant user managers only see their own tenant's users
    if doctype == "User":
        tenant_id = get_tenant_id()
        if tenant_id in (None, "SYSTEM"):
            return None
        return f"`tabUser`.`tenant_id` = {frappe.db.escape(tenant_id)}"

    # System doctypes don't get filtered
    system_doctypes = [
        'Role', 'DocType', 'DocField', 'DocPerm', 'Module Def',
        'Domain', 'Domain Settings', 'Plan',
        'Workspace', 'Workflow', 'Print Format', 'Email Template',
        'System Settings', 'Website Settings', 'Portal Settings',
        'Error Log', 'Activity Log', 'Version', 'Communication',
        'Comment', 'File', 'Custom Field'
    ]

    if doctype in system_doctypes:
        return None

    # Get user's tenant_id
    tenant_id = get_tenant_id()

    if not tenant_id:
        # User has no tenant - they can only see SYSTEM data
        return f"(`tab{doctype}`.`tenant_id` = 'SYSTEM' OR `tab{doctype}`.`tenant_id` IS NULL)"

    # User can see their own tenant's data + SYSTEM data
    return f"(`tab{doctype}`.`tenant_id` = {frappe.db.escape(tenant_id)} OR `tab{doctype}`.`tenant_id` = 'SYSTEM' OR `tab{doctype}`.`tenant_id` IS NULL)"


def setup_user_tenant(app=None):
    """Complete setup for user-tenant linking. Adds Custom Field to User and sets Administrator tenant."""
    # 1. Add Custom Field to User
    if not frappe.db.exists("Custom Field", "User-tenant_id"):
        custom_field = frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "User",
            "fieldname": "tenant_id",
            "fieldtype": "Data",
            "label": "Tenant ID",
            "insert_after": "enabled",
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "in_list_view": 1,
            "in_standard_filter": 1,
            "description": "The tenant this user belongs to. SYSTEM = Platform administrator."
        })
        custom_field.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.log("Created Custom Field 'tenant_id' for User DocType")

    # 2. Set Administrator tenant_id
    frappe.db.set_value("User", "Administrator", "tenant_id",
                        "SYSTEM", update_modified=False)
    frappe.db.commit()
    frappe.log("Set Administrator tenant_id = SYSTEM")


def verify_tenant():
    """Verify tenant provisioning end-to-end (used in CI verification)."""
    import time
    unique_suffix = str(int(time.time()))[-4:]
    tenant_name = f"Verify Tenant {unique_suffix}"
    subdomain = f"verify{unique_suffix}"
    admin_email = f"verify{unique_suffix}@test.com"

    tenant = frappe.get_doc({
        "doctype": "Tenant",
        "tenant_name": tenant_name,
        "subdomain": subdomain,
        "admin_email": admin_email,
        "status": "Active"
    })
    tenant.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"Successfully verified tenant creation in SNE: {tenant.name} ({tenant.tenant_id})")
    assert frappe.db.exists("Tenant", tenant.name)
    assert frappe.db.exists("Company", {"tenant_id": tenant.tenant_id})
    assert frappe.db.exists("User", {"email": admin_email})
    return tenant.name
