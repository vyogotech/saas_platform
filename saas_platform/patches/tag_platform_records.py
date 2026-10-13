"""
Tag level-1 (platform billing) records PLATFORM so no tenant can see them.

Before this, the platform's Customer / Subscription per tenant and everything booked under
the platform Company carried tenant_id SYSTEM, which every tenant can read.
"""

import frappe

from saas_platform.utils.tenant import PLATFORM_TENANT, get_platform_company


def execute():
    for subscription in frappe.get_all("Tenant", filters={"subscription": ["is", "set"]}, pluck="subscription"):
        party = frappe.db.get_value("Subscription", subscription, "party")
        frappe.db.set_value("Subscription", subscription, "tenant_id", PLATFORM_TENANT, update_modified=False)
        if party:
            frappe.db.set_value("Customer", party, "tenant_id", PLATFORM_TENANT, update_modified=False)

    if frappe.db.exists("Subscription Plan", "Free Plan"):
        frappe.db.set_value("Subscription Plan", "Free Plan", "tenant_id", PLATFORM_TENANT, update_modified=False)

    company = get_platform_company()
    if not company:
        return
    frappe.db.set_value("Company", company, "tenant_id", PLATFORM_TENANT, update_modified=False)

    # Every DocType table with both columns: invoices, GL / ledger entries, accounts, warehouses, ...
    tables = frappe.db.sql_list(
        """select c.table_name from information_schema.columns c
        join information_schema.columns t on t.table_schema = c.table_schema and t.table_name = c.table_name
        where c.table_schema = database() and c.column_name = 'company' and t.column_name = 'tenant_id'"""
    )
    for table in tables:
        frappe.db.set_value(
            table[3:], {"company": company, "tenant_id": "SYSTEM"}, "tenant_id", PLATFORM_TENANT, update_modified=False
        )
