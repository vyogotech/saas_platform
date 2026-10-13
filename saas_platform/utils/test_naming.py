"""
Unit tests for tenant-isolated naming series with composite tenant-company namespacing.
"""

import time
import unittest
from unittest.mock import MagicMock, patch
import sys
import types

try:
    import frappe
except ImportError:
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


from saas_platform.utils.naming import (
    namespace_naming_series,
    get_tenant_prefix,
    get_tenant_code,
    get_company_abbr,
    set_display_number,
    get_clean_display_name,
    clear_naming_cache,
    patch_frappe_naming,
)



class MockDoc:
    def __init__(self, doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company=None, tenant_id=None, name=None):
        self.doctype = doctype
        self.naming_series = naming_series
        self.company = company
        self.tenant_id = tenant_id
        self.name = name
        self.amended_from = None
        self.display_number = None

    def set(self, key, value):
        setattr(self, key, value)


class TestTenantNamingSeries(unittest.TestCase):

    def setUp(self):
        clear_naming_cache()
        # Act as a tenant user; restored after each test
        for patcher in (
            patch.dict(frappe.local.flags, {"in_migrate": False, "in_install": False, "in_patch": False}),
            patch.dict(frappe.local.session, {
                "user": "tenant_user@example.com",
                "data": frappe._dict(tenant_id="tenant_1"),
            }),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_composite_prefix_with_company_abbr(self):
        """Doc with company uses composite {tenant_code}-{abbr}- prefix"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        # tenant_1 -> TENANT1, company -> ACM => TENANT1-ACM-
        self.assertEqual(doc.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

    def test_idempotency_no_double_prefixing(self):
        """Re-saving doc does not double-prepend composite prefix"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="TENANT1-ACM-ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

    def test_smart_prefixing_no_double_company_abbr(self):
        """If user already configured 'ACM-...' in naming_series, only prepend tenant_code"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACM-ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        # Must NOT produce TENANT1-ACM-ACM-...
        self.assertEqual(doc.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

    def test_duplicate_company_abbr_across_tenants_collision_free(self):
        """
        CRITICAL NFR TEST: Two different tenants having identical Company.abbr ('ACM')
        must receive distinct series prefixes and never collide.
        """
        doc_a = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp", tenant_id="tenant_1")
        doc_b = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Motors", tenant_id="tenant_2")

        # Both companies return identical abbreviation "ACM"
        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc_a)
            namespace_naming_series(doc_b)

        # Verify distinct prefixes
        self.assertEqual(doc_a.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")
        self.assertEqual(doc_b.naming_series, "TENANT2-ACM-ACC-SINV-.YYYY.-")
        self.assertNotEqual(doc_a.naming_series, doc_b.naming_series)

    def test_fallback_to_tenant_code_without_company(self):
        """If company has no abbr or is missing, use clean tenant code"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.object(frappe, "get_cached_value", return_value=None), \
             patch.object(frappe.db, "get_value", return_value=None):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "TENANT1-ACC-SINV-.YYYY.-")

    def test_company_abbr_sanitization(self):
        """Company abbreviation with spaces, hyphens, and symbols must be sanitized to uppercase alphanumeric (max 8 chars)"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Special Corp")

        # Dirty abbreviation: lowercase, hyphen, ampersand, space, long length
        with patch.object(frappe, "get_cached_value", return_value=" ac-m & 123456789 "):
            namespace_naming_series(doc)

        # Expected: sanitized to "ACM12345" (first 8 uppercase alphanumeric chars)
        self.assertEqual(doc.naming_series, "TENANT1-ACM12345-ACC-SINV-.YYYY.-")

    def test_company_abbr_fallback_to_tenant_default_company(self):
        """When doc has no company field, resolve default company abbr for tenant_id from database"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company=None)

        def mock_db_get_value(doctype, filters, fieldname):
            if doctype == "Company" and isinstance(filters, dict) and filters.get("tenant_id") == "tenant_1":
                return "HQ"
            return None

        with patch.object(frappe, "get_cached_value", return_value=None), \
             patch.object(frappe.db, "get_value", side_effect=mock_db_get_value):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "TENANT1-HQ-ACC-SINV-.YYYY.-")

    def test_multiple_companies_same_tenant_distinct_series(self):
        """A single tenant operating multiple companies must get distinct series per company"""
        doc_retail = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Retail")
        doc_wholesale = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Wholesale")

        def mock_cached_value(dt, name, field):
            if name == "Acme Retail":
                return "RET"
            elif name == "Acme Wholesale":
                return "WHS"
            return None

        with patch.object(frappe, "get_cached_value", side_effect=mock_cached_value):
            namespace_naming_series(doc_retail)
            namespace_naming_series(doc_wholesale)

        self.assertEqual(doc_retail.naming_series, "TENANT1-RET-ACC-SINV-.YYYY.-")
        self.assertEqual(doc_wholesale.naming_series, "TENANT1-WHS-ACC-SINV-.YYYY.-")
        self.assertNotEqual(doc_retail.naming_series, doc_wholesale.naming_series)

    def test_smart_prefixing_case_insensitivity_and_dots(self):
        """User pre-configured series with lowercase abbr or dot separator must not duplicate abbreviation"""
        doc_lower = MockDoc(doctype="Sales Invoice", naming_series="acm-ACC-SINV-.YYYY.-", company="Acme Corp")
        doc_dot = MockDoc(doctype="Sales Invoice", naming_series="ACM.ACC.SINV.#####", company="Acme Corp")
        doc_prefixed = MockDoc(doctype="Sales Invoice", naming_series="TENANT1-ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc_lower)
            namespace_naming_series(doc_dot)
            namespace_naming_series(doc_prefixed)

        self.assertEqual(doc_lower.naming_series, "TENANT1-acm-ACC-SINV-.YYYY.-")
        self.assertEqual(doc_dot.naming_series, "TENANT1-ACM.ACC.SINV.#####")
        # Already prefixed with tenant code: idempotency ensures no re-prefixing
        self.assertEqual(doc_prefixed.naming_series, "TENANT1-ACC-SINV-.YYYY.-")

    def test_clear_naming_cache_invalidation(self):
        """When company abbreviation changes, clear_naming_cache invalidates LRU cache and reflects new abbr"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")

        abbr_state = {"val": "ACM"}
        with patch.object(frappe, "get_cached_value", side_effect=lambda dt, dn, f: abbr_state["val"]):
            namespace_naming_series(doc)
            self.assertEqual(doc.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

            # Company updates abbreviation in ERPNext UI
            abbr_state["val"] = "ACME"

            # Without cache clear, LRU cache returns old abbreviation
            doc2 = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")
            namespace_naming_series(doc2)
            self.assertEqual(doc2.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

            # Invalidate cache
            clear_naming_cache()

            # Now returns new abbreviation
            doc3 = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")
            namespace_naming_series(doc3)
            self.assertEqual(doc3.naming_series, "TENANT1-ACME-ACC-SINV-.YYYY.-")

    def test_default_naming_series_resolution(self):
        """If naming_series is initially None or empty, fetch default and prefix it"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"), \
             patch("saas_platform.utils.naming.get_default_naming_series", return_value="ACC-SINV-.YYYY.-"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "TENANT1-ACM-ACC-SINV-.YYYY.-")

    def test_administrator_bypass(self):
        """Administrator should not have naming_series altered"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.dict(frappe.local.session, {"user": "Administrator"}):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_system_tenant_bypass(self):
        """SYSTEM tenant_id should not have naming_series altered"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")
        frappe.session.data["tenant_id"] = "SYSTEM"

        namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_system_doctypes_bypass(self):
        """System doctypes like User, Tenant, Role must not be namespaced"""
        doc = MockDoc(doctype="User", naming_series="USER-.YYYY.-")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "USER-.YYYY.-")

    def test_amended_documents_bypass(self):
        """Amended documents should not have naming_series modified"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")
        doc.amended_from = "TENANT1-ACM-ACC-SINV-2026-00001"

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_migration_bypass(self):
        """Database migrations must not be affected"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.dict(frappe.local.flags, {"in_migrate": True}):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_set_display_number(self):
        """set_display_number strips internal tenant_code, preserving company abbreviation for customer display"""
        doc = MockDoc(doctype="Sales Invoice", name="TENANT1-ACM-ACC-SINV-2026-00001", company="Acme Corp")

        set_display_number(doc)

        # Customer sees their company abbr + series, NOT the internal tenant_1 code
        self.assertEqual(doc.display_number, "ACM-ACC-SINV-2026-00001")

    def test_get_clean_display_name(self):
        """get_clean_display_name helper returns clean number for print formats"""
        self.assertEqual(get_clean_display_name("TENANT1-ACM-ACC-SINV-2026-00001"), "ACM-ACC-SINV-2026-00001")
        self.assertEqual(get_clean_display_name("TENANT2-BET-PO-2026-00099"), "BET-PO-2026-00099")
        self.assertEqual(get_clean_display_name("TENANT1-ACC-SINV-2026-00001"), "ACC-SINV-2026-00001")
        self.assertEqual(get_clean_display_name("SIMPLE_NAME"), "SIMPLE_NAME")

    def test_performance_lru_caching(self):
        """
        NFR PERFORMANCE TEST: Prefix resolution must be sub-millisecond (< 0.005ms per call)
        utilizing in-memory LRU caching to eliminate DB queries during document inserts.
        """
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM") as mock_lookup:
            # First call warms cache
            get_tenant_prefix(doc, "tenant_1")
            self.assertEqual(mock_lookup.call_count, 1)

            # Next 10,000 calls must hit LRU cache with zero DB lookups
            start = time.perf_counter()
            for _ in range(10000):
                get_tenant_prefix(doc, "tenant_1")
            elapsed = time.perf_counter() - start

            # Zero additional DB calls
            self.assertEqual(mock_lookup.call_count, 1)
            # 10,000 lookups should take less than 30ms total (< 0.003ms each)
            self.assertLess(elapsed, 0.03, f"10,000 lookups took {elapsed:.4f}s, expected < 0.03s")

    def test_live_tab_series_counter_isolation_with_duplicate_abbr(self):
        """
        Simulates tabSeries counter updates for two tenants sharing duplicate Company.abbr 'ACM'.
        Demonstrates zero collisions, zero sequence gaps, and distinct primary keys.
        """
        import sqlite3

        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE `tabSeries` (name TEXT PRIMARY KEY, current INT)")
        cur.execute("CREATE TABLE `tabSales Invoice` (name TEXT PRIMARY KEY, customer TEXT, tenant_id TEXT, display_number TEXT)")
        con.commit()

        def simulate_getseries(key, digits):
            cur.execute("SELECT current FROM `tabSeries` WHERE name = ?", (key,))
            row = cur.fetchone()
            if row:
                current = row[0] + 1
                cur.execute("UPDATE `tabSeries` SET current = ? WHERE name = ?", (current, key))
            else:
                current = 1
                cur.execute("INSERT INTO `tabSeries` VALUES (?, 1)", (key,))
            con.commit()
            return ("%0" + str(digits) + "d") % current

        # Tenant 1, Tenant 2, and Tenant 3 all share Company.abbr = 'ACM'
        tenants = ["tenant_1", "tenant_2", "tenant_3"]
        tenant_docs = {t: [] for t in tenants}

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            # Interleaved creation pattern: T1, T2, T3, T2, T1, T3, etc.
            sequence_order = [
                "tenant_1", "tenant_2", "tenant_3",
                "tenant_2", "tenant_1", "tenant_3",
                "tenant_3", "tenant_1", "tenant_2",
                "tenant_1", "tenant_3", "tenant_2",
                "tenant_2", "tenant_3", "tenant_1",
            ]

            for t_id in sequence_order:
                # Act as tenant
                frappe.session.data["tenant_id"] = t_id
                doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-2026-", company="Acme Corp", tenant_id=t_id)

                # 1. Hook before_naming: prepends {tenant_code}-{abbr}-
                namespace_naming_series(doc)

                # 2. Frappe autoname simulation: counter fetched from tabSeries
                counter = simulate_getseries(doc.naming_series, 5)
                doc.name = f"{doc.naming_series}{counter}"

                # 3. Hook before_save: populates customer-facing display_number
                set_display_number(doc)

                tenant_docs[t_id].append(doc)

                # Insert into DB: verifies ZERO primary key collisions
                cur.execute(
                    "INSERT INTO `tabSales Invoice` VALUES (?, ?, ?, ?)",
                    (doc.name, f"Customer for {t_id}", t_id, doc.display_number)
                )
            con.commit()

        # Verify each of the 3 tenants has 5 continuous, unbroken invoices starting from 00001
        for t_id in tenants:
            docs = tenant_docs[t_id]
            t_code = get_tenant_code(t_id)
            self.assertEqual(len(docs), 5)

            for idx, doc in enumerate(docs, start=1):
                expected_num = f"{idx:05d}"
                # Internal DB PK has tenant code prefix
                expected_db_name = f"{t_code}-ACM-ACC-SINV-2026-{expected_num}"
                self.assertEqual(doc.name, expected_db_name)

                # Customer display number is clean ACM-ACC-SINV-2026-XXXXX (identical across all 3 tenants!)
                expected_display = f"ACM-ACC-SINV-2026-{expected_num}"
                self.assertEqual(doc.display_number, expected_display)
                self.assertEqual(get_clean_display_name(doc.name), expected_display)

        # All 15 rows exist in database with ZERO collisions
        cur.execute("SELECT COUNT(*) FROM `tabSales Invoice`")
        self.assertEqual(cur.fetchone()[0], 15)
        con.close()

    def test_get_company_abbr_edge_cases(self):
        """Direct tests for get_company_abbr edge cases and error resiliency"""
        # None arguments
        self.assertEqual(get_company_abbr(None, None), "")
        self.assertEqual(get_company_abbr(None, "SYSTEM"), "")

        # Doc without company attribute falls back to tenant default in DB
        doc = MockDoc(doctype="Item", company=None)
        with patch.object(frappe, "get_cached_value", return_value=None), \
             patch.object(frappe.db, "get_value", return_value="TNTCO"):
            self.assertEqual(get_company_abbr(doc, "tenant_1"), "TNTCO")

        # Database error handled gracefully (returns empty string without crashing)
        clear_naming_cache()
        with patch.object(frappe, "get_cached_value", side_effect=Exception("DB connection error")), \
             patch.object(frappe.db, "get_value", side_effect=Exception("DB connection error")):
            self.assertEqual(get_company_abbr(doc, "tenant_1"), "")

    def test_patch_frappe_naming_getseries(self):
        """tenant_aware_getseries automatically namespaces un-prefixed keys"""
        import sys
        import types

        mock_naming = types.ModuleType("frappe.model.naming")
        mock_orig_getseries = MagicMock(return_value="00001")
        mock_naming.getseries = mock_orig_getseries
        mock_orig_revert = MagicMock()
        mock_naming.revert_series_if_last = mock_orig_revert
        mock_model = types.ModuleType("frappe.model")
        mock_model.naming = mock_naming
        frappe.model = mock_model


        import saas_platform.utils.naming as naming_mod

        with patch.dict(sys.modules, {"frappe.model": mock_model, "frappe.model.naming": mock_naming}), \
             patch.multiple(naming_mod, _naming_patched=False, _orig_getseries=None, _orig_revert_series_if_last=None), \
             patch.object(frappe, "get_cached_value", return_value="ACM"), \
             patch.object(frappe.db, "get_value", return_value="ACM"):
            patch_frappe_naming()


            # Call getseries with unprefixed key: "PO-.YYYY.-"
            mock_naming.getseries("PO-.YYYY.-", 5)
            mock_orig_getseries.assert_called_with("TENANT1-ACM-PO-.YYYY.-", 5)

            # Call getseries with already prefixed key: "TENANT1-ACM-PO-.YYYY.-"
            mock_orig_getseries.reset_mock()
            mock_naming.getseries("TENANT1-ACM-PO-.YYYY.-", 5)
            mock_orig_getseries.assert_called_with("TENANT1-ACM-PO-.YYYY.-", 5)

            # Call revert_series_if_last with unprefixed key
            mock_naming.revert_series_if_last("PO-.YYYY.-", "PO-2026-00001")
            mock_orig_revert.assert_called_with("TENANT1-ACM-PO-.YYYY.-", "PO-2026-00001", doc=None)

            # Administrator bypass
            with patch.dict(frappe.local.session, {"user": "Administrator"}):
                mock_orig_getseries.reset_mock()
                mock_naming.getseries("PO-.YYYY.-", 5)
                mock_orig_getseries.assert_called_with("PO-.YYYY.-", 5)


if __name__ == "__main__":
    unittest.main()
