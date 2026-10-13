__version__ = "0.0.1"

# Monkey-patch Database._transform_query for transparent tenant SQL rewriting
try:
    from frappe.database.database import Database
    from saas_platform.utils.sql_rewriter import rewrite_sql_for_tenant

    if not getattr(Database, "_saas_platform_patched", False):
        _orig_transform_query = Database._transform_query

        def _tenant_aware_transform_query(self, query, values):
            query, values = _orig_transform_query(self, query, values)
            if isinstance(query, str):
                query = rewrite_sql_for_tenant(query)
            return query, values

        Database._transform_query = _tenant_aware_transform_query
        Database._saas_platform_patched = True
except Exception:
    pass

