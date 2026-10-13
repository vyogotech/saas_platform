"""
Unit tests for report runner interceptor.
"""

import unittest
from unittest.mock import MagicMock, patch
from saas_platform.utils.report_interceptor import tenant_aware_report_run


class TestReportInterceptor(unittest.TestCase):

    @patch("saas_platform.utils.report_interceptor.original_run")
    @patch("saas_platform.utils.report_interceptor.frappe")
    def test_tenant_user_filter_injection(self, mock_frappe, mock_orig_run):
        mock_frappe.session.user = "tenant_user@example.com"
        mock_frappe.session.get.return_value = "tenant_123"
        mock_frappe.db.get_value.return_value = "Acme Corp"
        mock_orig_run.return_value = {"result": []}

        # Tenant user runs report with empty filters
        res = tenant_aware_report_run("General Ledger", filters={})

        mock_orig_run.assert_called_once()
        passed_filters = mock_orig_run.call_args[1]["filters"]
        self.assertEqual(passed_filters["tenant_id"], "tenant_123")
        self.assertEqual(passed_filters["company"], "Acme Corp")

    @patch("saas_platform.utils.report_interceptor.original_run")
    @patch("saas_platform.utils.report_interceptor.frappe")
    def test_administrator_bypass(self, mock_frappe, mock_orig_run):
        mock_frappe.session.user = "Administrator"
        mock_orig_run.return_value = {"result": []}

        filters = {"company": "Any Company"}
        tenant_aware_report_run("General Ledger", filters=filters)

        mock_orig_run.assert_called_once()
        passed_filters = mock_orig_run.call_args[1]["filters"]
        # Filters should remain unmodified for Administrator
        self.assertEqual(passed_filters, {"company": "Any Company"})
        self.assertNotIn("tenant_id", passed_filters)


if __name__ == "__main__":
    unittest.main()
