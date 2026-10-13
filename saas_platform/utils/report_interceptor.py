"""
Report Interceptor for SaaS Platform.
Ensures report filters (company, tenant_id) are strictly bound to the authenticated tenant.
"""

try:
    import frappe
    from frappe.desk.query_report import run as original_run
except ImportError:
    class _MockFrappe:
        @staticmethod
        def whitelist():
            return lambda fn: fn

        @staticmethod
        def read_only():
            return lambda fn: fn

        @staticmethod
        def parse_json(val):
            import json
            return json.loads(val) if isinstance(val, str) else val

        class session:
            user = None

            @staticmethod
            def get(key, default=None):
                return None

        class db:
            @staticmethod
            def get_value(*args, **kwargs):
                return None

    frappe = _MockFrappe()

    def original_run(*args, **kwargs):
        return {}



@frappe.whitelist()
@frappe.read_only()
def tenant_aware_report_run(
    report_name: str,
    filters: str | dict | None = None,
    user: str | None = None,
    ignore_prepared_report: bool = False,
    custom_columns: str | list | None = None,
    is_tree: bool = False,
    parent_field: str | None = None,
    are_default_filters: bool = True,
    js_filters: str | list | None = None,
):
    """
    Wraps frappe.desk.query_report.run to lock company and tenant_id filters to the current tenant.
    """
    if isinstance(filters, str):
        filters = frappe.parse_json(filters) or {}
    elif filters is None:
        filters = {}

    current_user = user or frappe.session.user

    if current_user != "Administrator":
        tenant_id = frappe.session.get("tenant_id")
        if tenant_id and tenant_id != "SYSTEM":
            # 1. Enforce tenant_id in report filters
            filters["tenant_id"] = tenant_id

            # 2. Enforce tenant's Company in report filters
            user_company = frappe.db.get_value("Company", {"tenant_id": tenant_id}, "name")
            if user_company:
                filters["company"] = user_company

    return original_run(
        report_name=report_name,
        filters=filters,
        user=user,
        ignore_prepared_report=ignore_prepared_report,
        custom_columns=custom_columns,
        is_tree=is_tree,
        parent_field=parent_field,
        are_default_filters=are_default_filters,
        js_filters=js_filters,
    )
