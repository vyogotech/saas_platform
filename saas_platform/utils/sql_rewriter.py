"""
SQL AST Rewriter for Multi-Tenant Data Isolation in SaaS Platform.
Dynamically injects tenant_id predicates into SQL queries executed by frappe.db.sql.
"""

import functools
import re
import sqlglot
from sqlglot import exp

try:
    import frappe
except ImportError:
    class _MockFlags:
        in_migrate = False
        in_install = False
        ignore_tenant_filter = False

    class _MockSession:
        user = None
        data = {}

        @classmethod
        def get(cls, key, default=None):
            return cls.data.get(key, default)

    class _MockFrappe:
        flags = _MockFlags()
        session = _MockSession()

        @staticmethod
        def log_error(*args, **kwargs):
            pass

    frappe = _MockFrappe()

# Tables exempt from tenant filtering (platform & system metadata)
SYSTEM_TABLES = {
    "tabUser", "tabRole", "tabDocType", "tabDocField", "tabDocPerm",
    "tabModule Def", "tabTenant", "tabPlan", "tabSubscription Plan",
    "tabSubscription", "tabSubscription Plan Detail", "tabSessions",
    "tabSystem Settings", "tabWebsite Settings", "tabError Log",
    "tabActivity Log", "tabVersion", "tabCustom Field", "tabProperty Setter",
    "tabSingles", "tabInstalled Applications", "tabPatch Log", "tabDefaultValue"
}


# Parameter placeholder regex for PyMySQL / Frappe format (e.g. %(param)s and %s)
PARAM_RE = re.compile(r"%\([a-zA-Z0-9_]+\)s|%s")


def get_db_dialect() -> str:
    """Return 'postgres' or 'mysql' depending on current Frappe database configuration."""
    db_type = getattr(getattr(frappe, "db", None), "db_type", None)
    if not db_type:
        db_type = getattr(getattr(frappe, "conf", None), "get", lambda k, d=None: d)("db_type", "mariadb")
    return "postgres" if db_type == "postgres" else "mysql"


@functools.lru_cache(maxsize=2048)
def _rewrite_query_cached(sql: str, tenant_id: str, dialect: str = "mysql") -> str:
    """
    Parse SQL AST using sqlglot and inject tenant_id condition.
    Cached by (query, tenant_id, dialect) for high performance (<0.05ms on cache hit).
    Supports both MariaDB/MySQL (`quote`) and PostgreSQL ("quote").
    """
    params = []
    def _mask_param(match):
        params.append(match.group(0))
        return f"__FP_{len(params)-1}__"

    masked_sql = PARAM_RE.sub(_mask_param, sql)

    # If the SQL contains backticks (standard Frappe convention), parse with mysql dialect
    read_dialect = "mysql" if "`" in masked_sql else dialect
    parsed = sqlglot.parse_one(masked_sql, read=read_dialect)

    quote_char = '"' if dialect == "postgres" else '`'

    for select in parsed.find_all(exp.Select):
        # 1. Handle FROM table
        from_arg = select.args.get("from_")
        if from_arg and isinstance(from_arg.this, exp.Table):
            tbl = from_arg.this
            tbl_name = tbl.name
            alias = tbl.alias or tbl_name
            if tbl_name.startswith("tab") and tbl_name not in SYSTEM_TABLES:
                cond = sqlglot.parse_one(
                    f"({quote_char}{alias}{quote_char}.tenant_id = '{tenant_id}' OR {quote_char}{alias}{quote_char}.tenant_id = 'SYSTEM' OR {quote_char}{alias}{quote_char}.tenant_id IS NULL)",
                    read=dialect
                )
                select.where(cond, copy=False)

        # 2. Handle JOIN tables
        for join in select.args.get("joins", []):
            if isinstance(join.this, exp.Table):
                tbl = join.this
                tbl_name = tbl.name
                alias = tbl.alias or tbl_name
                if tbl_name.startswith("tab") and tbl_name not in SYSTEM_TABLES:
                    cond = sqlglot.parse_one(
                        f"({quote_char}{alias}{quote_char}.tenant_id = '{tenant_id}' OR {quote_char}{alias}{quote_char}.tenant_id = 'SYSTEM' OR {quote_char}{alias}{quote_char}.tenant_id IS NULL)",
                        read=dialect
                    )
                    is_outer = (join.side or "").upper() in ("LEFT", "RIGHT", "FULL")
                    if is_outer:
                        existing_on = join.args.get("on")
                        if existing_on:
                            join.set("on", exp.and_(existing_on, cond))
                        else:
                            join.set("on", cond)
                    else:
                        select.where(cond, copy=False)

    generated = parsed.sql(dialect=dialect)

    if params:
        generated = re.sub(r"__FP_(\d+)__", lambda m: params[int(m.group(1))], generated)

    return generated


def rewrite_sql_for_tenant(query: str) -> str:
    """
    Inspect execution context and rewrite query if running under an active tenant session.
    """
    # 1. Bypass checks: Administrator, database migrations, installation, or test flags
    if (
        getattr(frappe.flags, "in_migrate", False)
        or getattr(frappe.flags, "in_install", False)
        or getattr(frappe.flags, "ignore_tenant_filter", False)
        or getattr(frappe.session, "user", None) == "Administrator"
    ):
        return query

    # 2. Check session tenant
    tenant_id = getattr(frappe.session, "data", {}).get("tenant_id") if hasattr(frappe.session, "data") else None
    if not tenant_id:
        tenant_id = frappe.session.get("tenant_id") if hasattr(frappe, "session") and hasattr(frappe.session, "get") else None

    if not tenant_id or tenant_id == "SYSTEM":
        return query

    # 3. Only inspect SELECT or WITH (CTE) queries
    stripped = query.strip().lstrip("(").lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        return query

    dialect = get_db_dialect()

    try:
        return _rewrite_query_cached(query, tenant_id, dialect=dialect)
    except Exception as e:
        frappe.log_error(
            f"Failed to rewrite query for tenant {tenant_id}: {str(e)}\nQuery: {query[:300]}",
            "Tenant SQL Rewriter Error"
        )
        return query
