# Copyright (c) 2025, Asofi and contributors
# For license information, please see license.txt

import frappe


def set_tenant_id(doc, method=None):
    """
    Auto-populate tenant_id from current user's tenant

    This hook runs before_insert for all DocTypes.
    It automatically sets tenant_id based on the authenticated user.

    Args:
            doc: Document being inserted
            method: Hook method name (before_insert, etc.)
    """
    # Skip if tenant_id already set
    if hasattr(doc, 'tenant_id') and doc.tenant_id and doc.tenant_id != "SYSTEM":
        return

    # Get current user's tenant_id
    user_tenant_id = get_user_tenant_id()

    # Set tenant_id
    if hasattr(doc, 'tenant_id'):
        doc.tenant_id = user_tenant_id

        # Also set tenant_id for all child tables
        sync_child_table_tenant_id(doc, user_tenant_id)


def sync_child_table_tenant_id(doc, tenant_id):
    """
    Sync tenant_id to all child table rows

    Args:
            doc: Parent document
            tenant_id: Tenant ID to set on child rows
    """
    try:
        for fieldname in doc.meta.get_table_fields():
            child_docs = doc.get(fieldname.fieldname) or []
            for child_doc in child_docs:
                if hasattr(child_doc, 'tenant_id'):
                    child_doc.tenant_id = tenant_id
    except Exception as e:
        frappe.log_error(f"Error syncing child table tenant_id: {str(e)}")


def get_user_tenant_id():
    """
    Get tenant_id for the current user

    Returns:
            str: Tenant ID or "SYSTEM" as default
    """
    user = frappe.session.user

    # Administrator bypass
    if user == "Administrator":
        return "SYSTEM"

    # Get tenant_id from User custom field
    try:
        tenant_id = frappe.db.get_value("User", user, "tenant_id")
        if tenant_id:
            return tenant_id
    except Exception:
        pass

    # Default to SYSTEM if no tenant found
    return "SYSTEM"


def get_tenant_from_email(email):
    """
    Get tenant_id from user email

    Args:
            email: User email address

    Returns:
            str: Tenant ID or None
    """
    try:
        tenant_id = frappe.db.get_value("User", email, "tenant_id")
        return tenant_id
    except Exception:
        return None
