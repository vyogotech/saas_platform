"""
Tenant roles.

Tenant admins get a System-Manager-like role set without a hand-kept list:
- "Tenant Admin" Role Profile = every desk role except those that can change a
  site-wide DocType (schema, code, global config/triggers, identity, platform),
  derived from DocPerm / Custom DocPerm and rebuilt on migrate.
- "Tenant User Manager" role = manage User records of the own tenant only
  (list filter + has_permission + validate_tenant_user guard).

Row-level data access stays scoped by the SQL rewriter, has_permission and the
Company User Permission.
"""

import frappe
from frappe import _
from frappe.permissions import AUTOMATIC_ROLES, add_permission, update_permission_property

from saas_platform.utils.tenant import get_tenant_id

TENANT_ADMIN_PROFILE = "Tenant Admin"
TENANT_USER_MANAGER = "Tenant User Manager"

# Records of these DocTypes act site-wide, so they cannot be scoped to a tenant.
# A role that can create/write/delete any of them is left out of the profile.
PLATFORM_DOCTYPES = (
    "DocType", "Custom Field", "Property Setter", "Server Script", "Client Script",
    "Report", "System Console", "Role", "Role Profile", "Custom DocPerm", "User",
    "Module Def", "System Settings", "Scheduled Job Type", "Website Settings",
    "Workspace", "Print Format", "Webhook", "Notification", "Tenant", "Plan",
)


def get_tenant_admin_roles():
    risky = set()
    for perm_doctype in ("DocPerm", "Custom DocPerm"):
        risky.update(frappe.get_all(
            perm_doctype,
            filters={"parent": ["in", PLATFORM_DOCTYPES]},
            or_filters={"create": 1, "write": 1, "delete": 1},
            pluck="role",
        ))
    roles = frappe.get_all(
        "Role",
        filters={"disabled": 0, "desk_access": 1, "name": ["not in", AUTOMATIC_ROLES]},
        pluck="name",
    )
    # Tenant User Manager writes User, but is scoped by validate_tenant_user
    return sorted((set(roles) - risky) | {TENANT_USER_MANAGER})


def sync_tenant_roles(app=None):
    """Create/refresh Tenant User Manager and the Tenant Admin profile. Idempotent (after_migrate)."""
    if not frappe.db.exists("Role", TENANT_USER_MANAGER):
        frappe.get_doc({"doctype": "Role", "role_name": TENANT_USER_MANAGER, "desk_access": 1}).insert(
            ignore_permissions=True
        )
    # permlevel 1 holds User.roles / role_profiles; which roles may be granted is checked in validate_tenant_user
    for permlevel, ptypes in ((0, ("read", "write", "create")), (1, ("read", "write"))):
        if not frappe.db.exists("Custom DocPerm", {"parent": "User", "role": TENANT_USER_MANAGER, "permlevel": permlevel}):
            add_permission("User", TENANT_USER_MANAGER, permlevel)
            for ptype in ptypes:
                update_permission_property("User", TENANT_USER_MANAGER, permlevel, ptype, 1)

    roles = get_tenant_admin_roles()
    if frappe.db.exists("Role Profile", TENANT_ADMIN_PROFILE):
        profile = frappe.get_doc("Role Profile", TENANT_ADMIN_PROFILE)
        if sorted(r.role for r in profile.roles) == roles:
            return
    else:
        profile = frappe.new_doc("Role Profile")
        profile.role_profile = TENANT_ADMIN_PROFILE
    profile.set("roles", [{"role": role} for role in roles])
    profile.save(ignore_permissions=True)


def validate_tenant_user(doc, method=None):
    """User.validate: tenant editors may only manage their own tenant's users and grant tenant roles."""
    tenant_id = get_tenant_id()
    if frappe.session.user == "Administrator" or tenant_id in (None, "SYSTEM"):
        return

    if doc.get("tenant_id") != tenant_id:
        frappe.throw(_("You can only manage users of your own tenant"), frappe.PermissionError)

    before = doc.get_doc_before_save()
    previous = {r.role for r in before.roles} if before else set()
    allowed = set(frappe.get_all(
        "Has Role", filters={"parenttype": "Role Profile", "parent": TENANT_ADMIN_PROFILE}, pluck="role"
    )) | set(AUTOMATIC_ROLES)
    granted = {r.role for r in doc.roles} - previous - allowed
    if granted:
        frappe.throw(_("Roles not available to tenants: {0}").format(", ".join(sorted(granted))), frappe.PermissionError)
