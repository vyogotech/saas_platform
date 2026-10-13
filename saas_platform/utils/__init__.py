# Utils package for saas_platform
from .tenant import set_tenant_id, generate_tenant_id, get_tenant_id, apply_tenant_filter, setup_user_tenant



from .sql_rewriter import rewrite_sql_for_tenant, _rewrite_query_cached
from .naming import (
    namespace_naming_series,
    get_tenant_prefix,
    get_tenant_code,
    get_clean_display_name,
    set_display_number,
    patch_frappe_naming,
    clear_naming_cache,
)

__all__ = ['set_tenant_id', 'generate_tenant_id',
           'get_tenant_id', 'apply_tenant_filter', 'setup_user_tenant',
           'rewrite_sql_for_tenant', '_rewrite_query_cached',
           'namespace_naming_series', 'get_tenant_prefix',
           'get_tenant_code', 'get_clean_display_name',
           'set_display_number', 'patch_frappe_naming',
           'clear_naming_cache']



