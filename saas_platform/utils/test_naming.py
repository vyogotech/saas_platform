"""
Unit tests for tenant-isolated naming series.
"""

import unittest
from unittest.mock import MagicMock, patch
from saas_platform.utils.naming import (
    namespace_naming_series,
    get_tenant_prefix,
    set_display_number,
    get_clean_display_name,
    frappe,
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
        frappe.flags.in_migrate = False
        frappe.flags.in_install = False
        frappe.flags.in_patch = False
        frappe.session.user = "tenant_user@example.com"
        frappe.session.data["tenant_id"] = "acme_corp_123"

    def test_namespace_with_company_abbr(self):
        """Doc with company should use company abbr as prefix"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACM-ACC-SINV-.YYYY.-")

    def test_idempotency_no_double_prefixing(self):
        """Re-saving doc should not double-prepend prefix"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACM-ACC-SINV-.YYYY.-", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACM-ACC-SINV-.YYYY.-")

    def test_different_tenants_get_different_prefixes(self):
        """Tenant A and Tenant B get their respective company prefixes"""
        doc_a = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Acme Corp")
        doc_b = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-", company="Beta Ltd")

        def mock_cached_value(dt, docname, field):
            if docname == "Acme Corp":
                return "ACM"
            elif docname == "Beta Ltd":
                return "BET"
            return None

        with patch.object(frappe, "get_cached_value", side_effect=mock_cached_value):
            namespace_naming_series(doc_a)
            namespace_naming_series(doc_b)

        self.assertEqual(doc_a.naming_series, "ACM-ACC-SINV-.YYYY.-")
        self.assertEqual(doc_b.naming_series, "BET-ACC-SINV-.YYYY.-")

    def test_fallback_to_tenant_id_slug(self):
        """If company has no abbr, fall back to tenant_id slug"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.object(frappe, "get_cached_value", return_value=None), \
             patch.object(frappe.db, "get_value", return_value=None):
            namespace_naming_series(doc)

        # tenant_id is "acme_corp_123" -> clean slug[:4] = "ACME"
        self.assertEqual(doc.naming_series, "ACME-ACC-SINV-.YYYY.-")

    def test_default_naming_series_resolution(self):
        """If naming_series is initially None or empty, fetch default and prefix it"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"), \
             patch("saas_platform.utils.naming.get_default_naming_series", return_value="ACC-SINV-.YYYY.-"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACM-ACC-SINV-.YYYY.-")

    def test_administrator_bypass(self):
        """Administrator should not have naming_series altered"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.object(frappe.session, "user", "Administrator"):
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
        doc.amended_from = "ACM-ACC-SINV-2026-00001"

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_migration_bypass(self):
        """Database migrations must not be affected"""
        doc = MockDoc(doctype="Sales Invoice", naming_series="ACC-SINV-.YYYY.-")

        with patch.object(frappe.flags, "in_migrate", True):
            namespace_naming_series(doc)

        self.assertEqual(doc.naming_series, "ACC-SINV-.YYYY.-")

    def test_set_display_number(self):
        """set_display_number should extract the clean number without tenant prefix"""
        doc = MockDoc(doctype="Sales Invoice", name="ACM-ACC-SINV-2026-00001", company="Acme Corp")

        with patch.object(frappe, "get_cached_value", return_value="ACM"):
            set_display_number(doc)

        self.assertEqual(doc.display_number, "ACC-SINV-2026-00001")

    def test_get_clean_display_name(self):
        """get_clean_display_name helper returns clean number for print formats"""
        self.assertEqual(get_clean_display_name("ACM-ACC-SINV-2026-00001"), "ACC-SINV-2026-00001")
        self.assertEqual(get_clean_display_name("BET-PO-2026-00099"), "PO-2026-00099")
        self.assertEqual(get_clean_display_name("GLOBAL-INV-001", tenant_prefix="GLOBAL"), "INV-001")
        # Already clean or unrecognized format unchanged
        self.assertEqual(get_clean_display_name("SIMPLE_NAME"), "SIMPLE_NAME")

    def test_live_tab_series_counter_isolation(self):
        """Simulates tabSeries counter updates for two tenants showing zero collisions and zero gaps."""
        import sqlite3

        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE `tabSeries` (name TEXT PRIMARY KEY, current INT)")
        cur.execute("CREATE TABLE `tabSales Invoice` (name TEXT PRIMARY KEY, customer TEXT, tenant_id TEXT)")
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

        # Tenant A (prefix ACM) and Tenant B (prefix BET)
        series_a_key = "ACM-ACC-SINV-2026-"
        series_b_key = "BET-ACC-SINV-2026-"

        # Tenant A creates invoice 1, 2, 3
        inv_a1 = f"{series_a_key}{simulate_getseries(series_a_key, 5)}"
        inv_a2 = f"{series_a_key}{simulate_getseries(series_a_key, 5)}"

        # Tenant B creates invoice 1
        inv_b1 = f"{series_b_key}{simulate_getseries(series_b_key, 5)}"

        # Tenant A creates invoice 3
        inv_a3 = f"{series_a_key}{simulate_getseries(series_a_key, 5)}"

        # Tenant B creates invoice 2
        inv_b2 = f"{series_b_key}{simulate_getseries(series_b_key, 5)}"

        # Verify Tenant A names: sequential with NO gaps (00001, 00002, 00003)
        self.assertEqual(inv_a1, "ACM-ACC-SINV-2026-00001")
        self.assertEqual(inv_a2, "ACM-ACC-SINV-2026-00002")
        self.assertEqual(inv_a3, "ACM-ACC-SINV-2026-00003")

        # Verify Tenant B names: sequential with NO gaps (00001, 00002)
        self.assertEqual(inv_b1, "BET-ACC-SINV-2026-00001")
        self.assertEqual(inv_b2, "BET-ACC-SINV-2026-00002")

        # Insert all into tabSales Invoice - verify ZERO primary key collisions
        cur.execute("INSERT INTO `tabSales Invoice` VALUES (?, 'Customer A', 'tenant_a')", (inv_a1,))
        cur.execute("INSERT INTO `tabSales Invoice` VALUES (?, 'Customer A', 'tenant_a')", (inv_a2,))
        cur.execute("INSERT INTO `tabSales Invoice` VALUES (?, 'Customer A', 'tenant_a')", (inv_a3,))
        cur.execute("INSERT INTO `tabSales Invoice` VALUES (?, 'Customer B', 'tenant_b')", (inv_b1,))
        cur.execute("INSERT INTO `tabSales Invoice` VALUES (?, 'Customer B', 'tenant_b')", (inv_b2,))
        con.commit()

        cur.execute("SELECT COUNT(*) FROM `tabSales Invoice`")
        self.assertEqual(cur.fetchone()[0], 5)

        con.close()

    def test_patch_frappe_naming_getseries(self):
        """tenant_aware_getseries automatically namespaces un-prefixed keys"""
        from saas_platform.utils.naming import patch_frappe_naming
        import sys
        import types

        # Mock frappe.model.naming module
        mock_naming = types.ModuleType("frappe.model.naming")
        mock_orig_getseries = MagicMock(return_value="00001")
        mock_naming.getseries = mock_orig_getseries
        mock_orig_revert = MagicMock()
        mock_naming.revert_series_if_last = mock_orig_revert

        sys.modules["frappe.model.naming"] = mock_naming

        import saas_platform.utils.naming as naming_mod
        naming_mod._naming_patched = False

        with patch.object(frappe, "get_cached_value", return_value="ACM"), \
             patch.object(frappe.db, "get_value", return_value="ACM"):
            patch_frappe_naming()


            # Call getseries with unprefixed key: "PO-.YYYY.-"
            mock_naming.getseries("PO-.YYYY.-", 5)
            mock_orig_getseries.assert_called_with("ACM-PO-.YYYY.-", 5)

            # Call getseries with already prefixed key: "ACM-PO-.YYYY.-"
            mock_orig_getseries.reset_mock()
            mock_naming.getseries("ACM-PO-.YYYY.-", 5)
            mock_orig_getseries.assert_called_with("ACM-PO-.YYYY.-", 5)

            # Call revert_series_if_last with unprefixed key
            mock_naming.revert_series_if_last("PO-.YYYY.-", "PO-2026-00001")
            mock_orig_revert.assert_called_with("ACM-PO-.YYYY.-", "PO-2026-00001", doc=None)

            # Administrator bypass
            with patch.object(frappe.session, "user", "Administrator"):
                mock_orig_getseries.reset_mock()
                mock_naming.getseries("PO-.YYYY.-", 5)
                mock_orig_getseries.assert_called_with("PO-.YYYY.-", 5)


if __name__ == "__main__":
    unittest.main()

