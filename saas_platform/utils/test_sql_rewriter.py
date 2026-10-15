"""
Unit tests for SQL AST Rewriter and Multi-Tenant Query Isolation.
"""

import unittest
from unittest.mock import patch
try:
    import frappe
except ImportError:
    import sys
    import types

    class _MockDict(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError:
                raise AttributeError(k)
        def __setattr__(self, k, v):
            self[k] = v
        def __delattr__(self, k):
            try:
                del self[k]
            except KeyError:
                raise AttributeError(k)

    class _MockDB:
        def get_value(self, *args, **kwargs):
            return None

    class _MockFrappeModule(types.ModuleType):
        @property
        def session(self):
            return getattr(self.local, "session", None)
        @session.setter
        def session(self, val):
            self.local.session = val
        @property
        def flags(self):
            return getattr(self.local, "flags", None)
        @flags.setter
        def flags(self, val):
            self.local.flags = val

    mock_frappe = _MockFrappeModule("frappe")
    mock_frappe.PermissionError = type("PermissionError", (Exception,), {})
    mock_frappe._dict = _MockDict
    flags = _MockDict(in_migrate=False, in_install=False, in_patch=False)
    session = _MockDict(user=None, data=_MockDict())
    mock_frappe.local = _MockDict(flags=flags, session=session)
    mock_frappe.db = _MockDB()
    mock_frappe.get_cached_value = lambda *a, **k: None
    mock_frappe.log_error = lambda *a, **k: None
    mock_frappe.log = lambda *a, **k: None
    mock_frappe._ = lambda msg: msg

    mock_model = types.ModuleType("frappe.model")
    mock_naming = types.ModuleType("frappe.model.naming")
    mock_naming.get_default_naming_series = lambda doctype: None
    mock_naming.getseries = lambda key, digits: "00001"
    mock_naming.revert_series_if_last = lambda key, name, doc=None: None
    mock_model.naming = mock_naming
    mock_frappe.model = mock_model

    mock_db_pkg = types.ModuleType("frappe.database")
    mock_db_mod = types.ModuleType("frappe.database.database")
    class _MockDatabase:
        _saas_platform_patched = False
        def _transform_query(self, query, values):
            return query, values
    mock_db_mod.Database = _MockDatabase
    mock_db_pkg.database = mock_db_mod
    mock_frappe.database = mock_db_pkg

    sys.modules["frappe"] = mock_frappe
    sys.modules["frappe.model"] = mock_model
    sys.modules["frappe.model.naming"] = mock_naming
    sys.modules["frappe.database"] = mock_db_pkg
    sys.modules["frappe.database.database"] = mock_db_mod
    frappe = mock_frappe

from saas_platform.utils.sql_rewriter import (
    SYSTEM_ONLY,
    TenantIsolationError,
    _rewrite_query_cached,
    rewrite_sql_for_tenant,
)


class TestSqlRewriter(unittest.TestCase):
    """Test suite for AST-based SQL query rewriting across various SQL structures."""

    def setUp(self):
        self.tenant_id = "acme_tenant_01"

    def test_simple_select(self):
        sql = "SELECT * FROM `tabCustomer`"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabCustomer`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("OR `tabCustomer`.tenant_id = 'SYSTEM'", rewritten)
        # No IS NULL branch: it leaks NULL-extended rows of outer joins
        self.assertNotIn("IS NULL", rewritten)

    def test_select_with_existing_where(self):
        sql = "SELECT name FROM `tabCustomer` WHERE disabled = 0"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("disabled = 0", rewritten)
        self.assertIn("`tabCustomer`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_table_alias(self):
        sql = "SELECT c.name FROM `tabCustomer` c WHERE c.disabled = 0"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`c`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_table_with_space_in_name(self):
        sql = "SELECT account, SUM(debit) FROM `tabGL Entry` WHERE docstatus = 1 GROUP BY account"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabGL Entry`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("GROUP BY account", rewritten)

    def test_inner_join(self):
        sql = """
        SELECT si.name, sii.item_code 
        FROM `tabSales Invoice` si 
        JOIN `tabSales Invoice Item` sii ON sii.parent = si.name 
        WHERE si.docstatus = 1
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`si`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("`sii`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_left_join_preserves_outer_semantics(self):
        sql = """
        SELECT si.name, c.customer_name 
        FROM `tabSales Invoice` si 
        LEFT JOIN `tabCustomer` c ON c.name = si.customer 
        WHERE si.docstatus = 1
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        # c condition must be in the ON clause for LEFT JOIN
        self.assertIn("ON c.name = si.customer AND (`c`.tenant_id = 'acme_tenant_01'", rewritten)
        # si condition must be in the WHERE clause
        self.assertIn("WHERE si.docstatus = 1 AND (`si`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_subquery_in_where(self):
        sql = """
        SELECT name FROM `tabCustomer` 
        WHERE name IN (SELECT customer FROM `tabSales Invoice` WHERE grand_total > 1000)
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabCustomer`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("`tabSales Invoice`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_cte_query(self):
        sql = """
        WITH monthly_sales AS (
            SELECT posting_date, SUM(grand_total) as total 
            FROM `tabSales Invoice` 
            GROUP BY posting_date
        ) 
        SELECT * FROM monthly_sales
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabSales Invoice`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_union_query(self):
        sql = """
        SELECT name, customer FROM `tabSales Invoice` 
        UNION ALL 
        SELECT name, supplier FROM `tabPurchase Invoice`
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabSales Invoice`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("`tabPurchase Invoice`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_system_tables_are_exempt(self):
        sql = "SELECT name FROM `tabDocType` WHERE issingle = 0"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertNotIn("tenant_id", rewritten)

    def test_bypass_conditions(self):
        sql = "SELECT * FROM `tabCustomer`"

        # 1. Administrator bypass
        with patch.dict(frappe.local.session, {"user": "Administrator"}):
            self.assertEqual(rewrite_sql_for_tenant(sql), sql)

        # 2. in_migrate bypass
        with patch.dict(frappe.local.flags, {"in_migrate": True}):
            self.assertEqual(rewrite_sql_for_tenant(sql), sql)

        # 3. Non-SELECT query bypass
        insert_sql = "INSERT INTO `tabCustomer` (name) VALUES ('Test')"
        self.assertEqual(rewrite_sql_for_tenant(insert_sql), insert_sql)

    def test_lru_cache_hit(self):
        sql = "SELECT name, customer_name FROM `tabCustomer` WHERE disabled = 0"
        res1 = _rewrite_query_cached(sql, self.tenant_id)
        res2 = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIs(res1, res2)

    def test_erpnext_general_ledger_query(self):
        sql = """
        SELECT
            name as gl_entry, posting_date, account, party_type, party,
            voucher_type, voucher_no, cost_center, debit, credit
        FROM `tabGL Entry`
        WHERE company = %(company)s AND posting_date BETWEEN %(from_date)s AND %(to_date)s
        ORDER BY account, posting_date
        LIMIT 50 OFFSET 100
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabGL Entry`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("LIMIT 50", rewritten)
        self.assertIn("OFFSET 100", rewritten)
        self.assertIn("ORDER BY account, posting_date", rewritten)

    def test_nested_subqueries(self):
        sql = """
        SELECT name FROM `tabCustomer`
        WHERE name IN (
            SELECT customer FROM `tabSales Invoice`
            WHERE name IN (
                SELECT parent FROM `tabSales Invoice Item` WHERE rate > 500
            )
        )
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabCustomer`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("`tabSales Invoice`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("`tabSales Invoice Item`.tenant_id = 'acme_tenant_01'", rewritten)

    def test_right_join(self):
        sql = """
        SELECT si.name, c.customer_name 
        FROM `tabSales Invoice` si 
        RIGHT JOIN `tabCustomer` c ON c.name = si.customer
        """
        # Filter in ON does not restrict the preserved side of a RIGHT JOIN -> refuse
        with self.assertRaises(TenantIsolationError):
            _rewrite_query_cached(sql, self.tenant_id)

    # =========================================================================
    # POSTGRESQL DIALECT TESTS
    # =========================================================================

    def test_postgres_simple_select(self):
        sql = 'SELECT * FROM "tabCustomer"'
        rewritten = _rewrite_query_cached(sql, self.tenant_id, dialect="postgres")
        self.assertIn('"tabCustomer".tenant_id = \'acme_tenant_01\'', rewritten)
        self.assertIn('OR "tabCustomer".tenant_id = \'SYSTEM\'', rewritten)

    def test_postgres_transpiles_backticks(self):
        sql = "SELECT name, customer_name FROM `tabCustomer` WHERE disabled = 0"
        rewritten = _rewrite_query_cached(sql, self.tenant_id, dialect="postgres")
        # Should output valid Postgres double quotes, not MySQL backticks
        self.assertIn('"tabCustomer"', rewritten)
        self.assertIn('"tabCustomer".tenant_id = \'acme_tenant_01\'', rewritten)
        self.assertNotIn("`", rewritten)

    def test_postgres_left_join(self):
        sql = """
        SELECT si.name, c.customer_name 
        FROM `tabSales Invoice` si 
        LEFT JOIN `tabCustomer` c ON c.name = si.customer
        WHERE si.docstatus = 1
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id, dialect="postgres")
        self.assertIn('ON c.name = si.customer AND ("c".tenant_id = \'acme_tenant_01\'', rewritten)
        self.assertIn('WHERE si.docstatus = 1 AND ("si".tenant_id = \'acme_tenant_01\'', rewritten)

    # =========================================================================
    # NORMAL SCENARIOS & LIVE EXECUTION TESTS
    # =========================================================================

    def test_case_when_and_having_clause(self):
        sql = """
        SELECT 
            customer,
            SUM(CASE WHEN age <= 30 THEN outstanding ELSE 0 END) as bucket_0_30,
            SUM(CASE WHEN age > 30 THEN outstanding ELSE 0 END) as bucket_31_plus
        FROM `tabSales Invoice`
        GROUP BY customer
        HAVING SUM(outstanding) > 0
        """
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        self.assertIn("`tabSales Invoice`.tenant_id = 'acme_tenant_01'", rewritten)
        self.assertIn("HAVING SUM(outstanding) > 0", rewritten)

    def test_ddl_and_dml_passthrough(self):
        # Write and DDL statements must pass through untouched
        statements = [
            "INSERT INTO `tabCustomer` (name, tenant_id) VALUES ('CUST-01', 't1')",
            "UPDATE `tabCustomer` SET customer_name = 'Updated' WHERE name = 'CUST-01'",
            "DELETE FROM `tabCustomer` WHERE name = 'CUST-01'",
            "ALTER TABLE `tabCustomer` ADD COLUMN custom_col VARCHAR(100)",
            "SHOW COLUMNS FROM `tabCustomer`",
            "DESCRIBE `tabCustomer`",
            "SET time_zone = '+00:00'",
        ]
        for stmt in statements:
            self.assertEqual(rewrite_sql_for_tenant(stmt), stmt)

    def test_live_sqlite_multi_tenant_isolation(self):
        """Simulates an active database to verify that Tenant A NEVER sees Tenant B data."""
        import sqlite3

        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE `tabSales Invoice` (name TEXT PRIMARY KEY, customer TEXT, grand_total REAL, tenant_id TEXT)")
        cur.execute("INSERT INTO `tabSales Invoice` VALUES ('INV-A1', 'Acme Cust 1', 100.0, 'tenant_a')")
        cur.execute("INSERT INTO `tabSales Invoice` VALUES ('INV-A2', 'Acme Cust 2', 200.0, 'tenant_a')")
        cur.execute("INSERT INTO `tabSales Invoice` VALUES ('INV-B1', 'Beta Cust 1', 500.0, 'tenant_b')")
        cur.execute("INSERT INTO `tabSales Invoice` VALUES ('INV-SYS', 'Shared Platform Inv', 50.0, 'SYSTEM')")
        cur.execute("INSERT INTO `tabSales Invoice` VALUES ('INV-LEGACY', 'Legacy Pre-Migration Inv', 25.0, NULL)")
        con.commit()

        # 1. Tenant A query
        sql = "SELECT name, customer, grand_total, tenant_id FROM `tabSales Invoice`"
        q_a = _rewrite_query_cached(sql, "tenant_a")
        cur.execute(q_a)
        rows_a = cur.fetchall()
        names_a = [r[0] for r in rows_a]

        # Tenant A MUST see Tenant A and SYSTEM records, not NULL ones
        self.assertIn("INV-A1", names_a)
        self.assertIn("INV-A2", names_a)
        self.assertIn("INV-SYS", names_a)
        self.assertNotIn("INV-LEGACY", names_a)
        # Tenant A MUST NEVER see Tenant B
        self.assertNotIn("INV-B1", names_a)

        # 2. Tenant B query
        q_b = _rewrite_query_cached(sql, "tenant_b")
        cur.execute(q_b)
        rows_b = cur.fetchall()
        names_b = [r[0] for r in rows_b]

        # Tenant B MUST see Tenant B and SYSTEM records
        self.assertIn("INV-B1", names_b)
        self.assertIn("INV-SYS", names_b)
        # Tenant B MUST NEVER see Tenant A
        self.assertNotIn("INV-A1", names_b)
        self.assertNotIn("INV-A2", names_b)

        # 3. Aggregations (SUM) accuracy
        sum_sql = "SELECT SUM(grand_total) FROM `tabSales Invoice`"
        cur.execute(_rewrite_query_cached(sum_sql, "tenant_a"))
        total_a = cur.fetchone()[0]
        # Tenant A total: 100 + 200 + 50 (sys) = 350.0
        self.assertEqual(total_a, 350.0)

        cur.execute(_rewrite_query_cached(sum_sql, "tenant_b"))
        total_b = cur.fetchone()[0]
        # Tenant B total: 500 + 50 (sys) = 550.0
        self.assertEqual(total_b, 550.0)

        # Unfiltered raw query (Administrator view): 100 + 200 + 500 + 50 + 25 = 875.0
        cur.execute(sum_sql)
        total_admin = cur.fetchone()[0]
        self.assertEqual(total_admin, 875.0)

        con.close()

    # =========================================================================
    # REGRESSIONS FROM REVIEW
    # =========================================================================

    def test_tenant_id_is_escaped_not_injected(self):
        rewritten = _rewrite_query_cached("SELECT name FROM `tabItem`", "x' OR '1'='1")
        self.assertNotIn("OR '1' = '1'", rewritten)

    def test_placeholders_survive_rewrite(self):
        sql = "SELECT name FROM `tabItem` WHERE name IN %(items)s AND item_group = %s LIMIT %s"
        rewritten = _rewrite_query_cached(sql, self.tenant_id)
        for placeholder in ("%(items)s", "= %s", "LIMIT %s"):
            self.assertIn(placeholder, rewritten)

    def test_tables_without_tenant_column_are_skipped(self):
        # tabSeries is not a DocType, so the migration patch never added tenant_id to it
        sql = "SELECT current FROM `tabSeries` WHERE name = %s FOR UPDATE"
        rewritten = _rewrite_query_cached(sql, self.tenant_id, "mysql", frozenset({"tabItem"}))
        self.assertNotIn("tenant_id", rewritten)

    def test_system_only_scope(self):
        rewritten = _rewrite_query_cached("SELECT name FROM `tabItem`", SYSTEM_ONLY)
        self.assertIn("`tabItem`.tenant_id = 'SYSTEM'", rewritten)
        self.assertNotIn("system-only", rewritten)

    def _as_tenant_user(self, tenant_id):
        return patch.multiple(
            frappe.local,
            session=frappe._dict(user="tenant_user@example.com", data=frappe._dict(tenant_id=tenant_id)),
            saas_tenant_tables=frozenset({"tabItem"}),
            create=True,
        )

    def test_tenant_read_from_persisted_session_data(self):
        with self._as_tenant_user(self.tenant_id):
            rewritten = rewrite_sql_for_tenant("SELECT name FROM `tabItem`")
        self.assertIn(f"`tabItem`.tenant_id = '{self.tenant_id}'", rewritten)

    def test_unparseable_query_on_tenant_table_fails_closed(self):
        with self._as_tenant_user(self.tenant_id), patch.object(frappe, "log_error"):
            with self.assertRaises(TenantIsolationError):
                rewrite_sql_for_tenant("SELECT name FROM `tabItem` WHERE (((")

    def test_unparseable_query_on_other_tables_passes(self):
        sql = "SELECT 1 FROM `tabSeries` WHERE ((("
        with self._as_tenant_user(self.tenant_id):
            self.assertEqual(rewrite_sql_for_tenant(sql), sql)


if __name__ == "__main__":
    unittest.main()


