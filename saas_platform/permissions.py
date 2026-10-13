# Copyright (c) 2025, Asofi and contributors
# For license information, please see license.txt

import frappe


def get_tenant_query(user):
    """
    Permission query condition for tenant isolation

    Filters all queries to show only:
    1. Records belonging to user's tenant
    2. Records with tenant_id = "SYSTEM" (shared data)

    Args:
            user: Current user email

    Returns:
            str: SQL WHERE condition
    """
    # Administrator bypass - can see everything
    if user == "Administrator":
        return ""

    # Get user's tenant_id
    try:
        user_tenant_id = frappe.db.get_value("User", user, "tenant_id")

        if not user_tenant_id:
            # User has no tenant - only show SYSTEM data
            return "`tabDocType`.tenant_id = 'SYSTEM'"

        # Show user's tenant data + SYSTEM shared data
        return f"`tabDocType`.tenant_id IN ('{user_tenant_id}', 'SYSTEM')"

    except Exception as e:
        frappe.log_error(f"Error in get_tenant_query: {str(e)}")
        # Fail secure - show nothing on error
        return "`tabDocType`.tenant_id = ''"


def get_tenant_query_for_doctype(doctype):
    """
    Generate tenant query condition for a specific DocType

    Args:
            doctype: DocType name

    Returns:
            str: SQL WHERE condition with proper table name
    """
    user = frappe.session.user

    # Administrator bypass
    if user == "Administrator":
        return ""

    # Get user's tenant_id
    try:
        user_tenant_id = frappe.db.get_value("User", user, "tenant_id")

        if not user_tenant_id:
            return f"`tab{doctype}`.tenant_id = 'SYSTEM'"

        # Show user's tenant data + SYSTEM shared data
        return f"`tab{doctype}`.tenant_id IN ('{user_tenant_id}', 'SYSTEM')"

    except Exception as e:
        frappe.log_error(f"Error in get_tenant_query_for_doctype: {str(e)}")
        return f"`tab{doctype}`.tenant_id = ''"


def has_permission(doc, ptype, user):
    """
    Additional permission check for documents

    Args:
            doc: Document object
            ptype: Permission type (read, write, create, etc.)
            user: User email

    Returns:
            bool: True if user has permission
    """
    # Administrator bypass
    if user == "Administrator":
        return True

    # Unsaved docs and doctypes without the raw tenant_id column, or shared (SYSTEM) data
    # (SYSTEM users, e.g. Administrator, are platform accounts, not shared data)
    doc_tenant = getattr(doc, "tenant_id", None)
    if not doc_tenant or (doc_tenant == "SYSTEM" and doc.doctype != "User"):
        return True

    try:
        if user == frappe.session.user:
            from saas_platform.utils.tenant import get_tenant_id
            user_tenant_id = get_tenant_id()
        else:
            user_tenant_id = frappe.db.get_value("User", user, "tenant_id")

        # Platform staff see every tenant; everyone else only their own
        return user_tenant_id == "SYSTEM" or doc_tenant == user_tenant_id

    except Exception as e:
        frappe.log_error(f"Error in has_permission: {str(e)}")
        return False
