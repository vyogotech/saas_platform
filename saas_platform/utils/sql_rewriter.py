"""
SQL AST Rewriter for Multi-Tenant Data Isolation in SaaS Platform.
Dynamically injects tenant_id predicates into SQL queries executed by frappe.db.sql.

Fails closed: a SELECT touching a tenant table that cannot be scoped raises
TenantIsolationError instead of running unfiltered.
"""

import functools
import re

import frappe
import sqlglot
from sqlglot import exp

from saas_platform.utils.tenant import get_tenant_id, in_internal_query, internal_query



# Tables exempt from tenant filtering (platform & system metadata)
SYSTEM_TABLES = frozenset({
    "tabUser", "tabRole", "tabDocType", "tabDocField", "tabDocPerm",
    "tabModule Def", "tabPlan", "tabSessions",
    "tabSystem Settings", "tabWebsite Settings", "tabError Log",
    "tabActivity Log", "tabVersion", "tabCustom Field", "tabProperty Setter",
    "tabSingles", "tabInstalled Applications", "tabPatch Log", "tabDefaultValue"
})

# Scope for sessions that may only see shared rows (Guest, users without a tenant).
# Cannot collide with a real tenant_id.
SYSTEM_ONLY = "\x00system-only"

# Versioned: bump when the cached value's meaning changes, so workers still running older
# code during a deploy never read (or overwrite) entries written by newer code.
TENANT_TABLES_CACHE_KEY = "saas_platform:tenant_tables:v2"

# Parameter placeholder regex for PyMySQL / Frappe format (e.g. %(param)s and %s)
PARAM_RE = re.compile(r"%\([a-zA-Z0-9_]+\)s|%s")

# Leading comments / parentheses before the statement keyword
LEADING_NOISE_RE = re.compile(r"^(?:\s+|/\*.*?\*/|--[^\n]*\n|#[^\n]*\n|\()*", re.DOTALL)

# Frappe table references: `tabSales Invoice`, "tabSales Invoice", tabItem
TABLE_REF_RE = re.compile(r"[`\"](tab[^`\"]+)[`\"]|\b(tab[A-Za-z0-9_]+)\b")


class TenantIsolationError(frappe.PermissionError):
    """Raised when a query cannot be safely scoped to the current tenant."""


def get_db_dialect() -> str:
    """Return 'postgres' or 'mysql' depending on current Frappe database configuration."""
    db_type = getattr(getattr(frappe, "db", None), "db_type", None)
    if not db_type:
        db_type = getattr(getattr(frappe, "conf", None), "get", lambda k, d=None: d)("db_type", "mariadb")
    return "postgres" if db_type == "postgres" else "mysql"


def _load_tenant_tables():
    schema = "current_schema()" if get_db_dialect() == "postgres" else "database()"
    with internal_query():
        rows = frappe.db.sql(
            "select table_name from information_schema.columns "
            f"where table_schema = {schema} and column_name = 'tenant_id'"
        )
    return sorted(r[0] for r in rows)


def get_tenant_tables() -> frozenset:
    """Tables the rewriter scopes: has the tenant_id column and is not a system table."""
    tables = getattr(frappe.local, "saas_tenant_tables", None)
    if tables is None:
        # Redis holds the raw schema list; SYSTEM_TABLES is applied here so code changes take effect at once
        cached = frappe.cache.get_value(TENANT_TABLES_CACHE_KEY, generator=_load_tenant_tables)
        tables = frozenset(cached) - SYSTEM_TABLES
        frappe.local.saas_tenant_tables = tables
    return tables


def clear_tenant_tables_cache(app=None):
    """after_migrate: schema may have gained tenant_id columns."""
    frappe.cache.delete_value(TENANT_TABLES_CACHE_KEY)
    frappe.local.saas_tenant_tables = None


def _is_tenant_table(name: str, tenant_tables) -> bool:
    if not name.startswith("tab") or name in SYSTEM_TABLES:
        return False
    return tenant_tables is None or name in tenant_tables


def _tenant_predicate(alias: str, tenant_id: str) -> exp.Expression:
    """(`alias`.tenant_id = '<tenant>' OR `alias`.tenant_id = 'SYSTEM'), built as AST (no string SQL)."""
    def col():
        return exp.column("tenant_id", table=exp.to_identifier(alias, quoted=True))

    shared = exp.EQ(this=col(), expression=exp.Literal.string("SYSTEM"))
    if tenant_id == SYSTEM_ONLY:
        return exp.Paren(this=shared)
    own = exp.EQ(this=col(), expression=exp.Literal.string(tenant_id))
    return exp.Paren(this=exp.or_(own, shared))


@functools.lru_cache(maxsize=2048)
def _rewrite_query_cached(sql: str, tenant_id: str, dialect: str = "mysql", tenant_tables: frozenset | None = None) -> str:
    """
    Parse SQL AST using sqlglot and inject tenant_id condition.
    Cached by (query, tenant_id, dialect, tenant_tables).
    tenant_tables=None treats every non-system `tab*` table as tenant-scoped.
    """
    params = []

    def _mask_param(match):
        params.append(match.group(0))
        return f"__FP_{len(params)-1}__"

    masked_sql = PARAM_RE.sub(_mask_param, sql)

    # If the SQL contains backticks (standard Frappe convention), parse with mysql dialect
    read_dialect = "mysql" if "`" in masked_sql else dialect
    parsed = sqlglot.parse_one(masked_sql, read=read_dialect)

    for select in list(parsed.find_all(exp.Select)):
        from_arg = select.args.get("from_")
        joins = select.args.get("joins") or []

        scoped_tables = []
        if from_arg and isinstance(from_arg.this, exp.Table):
            scoped_tables.append(from_arg.this)
        scoped_tables.extend(j.this for j in joins if isinstance(j.this, exp.Table))
        if not any(_is_tenant_table(t.name, tenant_tables) for t in scoped_tables):
            continue

        # RIGHT/FULL joins flip which side is preserved; a filter in ON does not
        # restrict the preserved side, so these cannot be scoped safely.
        if any((j.side or "").upper() in ("RIGHT", "FULL") for j in joins):
            raise TenantIsolationError("RIGHT/FULL JOIN on tenant tables is not supported; use LEFT JOIN")

        # 1. Handle FROM table
        if from_arg and isinstance(from_arg.this, exp.Table):
            tbl = from_arg.this
            if _is_tenant_table(tbl.name, tenant_tables):
                select.where(_tenant_predicate(tbl.alias or tbl.name, tenant_id), copy=False)

        # 2. Handle JOIN tables
        for join in joins:
            if not isinstance(join.this, exp.Table):
                continue
            tbl = join.this
            if not _is_tenant_table(tbl.name, tenant_tables):
                continue
            cond = _tenant_predicate(tbl.alias or tbl.name, tenant_id)
            if (join.side or "").upper() == "LEFT":
                # Nullable side: filter in ON to preserve outer join semantics
                existing_on = join.args.get("on")
                join.set("on", exp.and_(existing_on, cond) if existing_on else cond)
            else:
                select.where(cond, copy=False)

    generated = parsed.sql(dialect=dialect)

    if params:
        generated = re.sub(r"__FP_(\d+)__", lambda m: params[int(m.group(1))], generated)

    return generated


def _references_tenant_table(query: str, tenant_tables) -> bool:
    for quoted, bare in TABLE_REF_RE.findall(query):
        if _is_tenant_table(quoted or bare, tenant_tables):
            return True
    return False


def get_rewrite_scope():
    """None (no filtering), SYSTEM_ONLY, or the tenant_id to scope queries to."""
    flags = frappe.flags
    if (
        getattr(flags, "in_migrate", False)
        or getattr(flags, "in_install", False)
        or getattr(flags, "ignore_tenant_filter", False)
        or in_internal_query()
    ):
        return None

    user = getattr(frappe.session, "user", None) if frappe.session else None
    if user == "Administrator":
        return None
    if not user or user == "Guest":
        return SYSTEM_ONLY

    tenant_id = get_tenant_id()
    if tenant_id == "SYSTEM":
        return None
    return tenant_id or SYSTEM_ONLY


def rewrite_sql_for_tenant(query: str) -> str:
    """
    Inspect execution context and rewrite query if running under a tenant scope.
    """
    # Only inspect SELECT or WITH (CTE) queries
    head = LEADING_NOISE_RE.sub("", query, count=1)[:6].lower()
    if not (head.startswith("select") or head.startswith("with")):
        return query

    tenant_id = get_rewrite_scope()
    if tenant_id is None:
        return query

    tenant_tables = get_tenant_tables()
    dialect = get_db_dialect()

    try:
        return _rewrite_query_cached(query, tenant_id, dialect, tenant_tables)
    except TenantIsolationError:
        raise
    except Exception as e:
        if not _references_tenant_table(query, tenant_tables):
            return query
        frappe.log_error(
            f"Failed to rewrite query for tenant {tenant_id!r}: {e}\nQuery: {query[:1000]}",
            "Tenant SQL Rewriter Error"
        )
        raise TenantIsolationError("Query could not be scoped to the current tenant") from e


def install_db_patch():
    """Wrap Database._transform_query with tenant rewriting. Idempotent; also run from before_request/before_job."""
    from frappe.database.database import Database

    if getattr(Database, "_saas_platform_patched", False):
        return

    _orig_transform_query = Database._transform_query

    def _tenant_aware_transform_query(self, query, values):
        query, values = _orig_transform_query(self, query, values)
        if isinstance(query, str):
            query = rewrite_sql_for_tenant(query)
        return query, values

    Database._transform_query = _tenant_aware_transform_query
    Database._saas_platform_patched = True
