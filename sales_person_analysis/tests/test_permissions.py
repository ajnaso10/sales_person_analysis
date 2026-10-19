# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from sales_person_analysis.api.analysis import get_customer_wise_sales, get_filter_options
from sales_person_analysis.tests import utils as tu


class TestAnalysisPermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = tu.company()
		if cls.company:
			frappe.defaults.set_user_default("Company", cls.company)

	def test_missing_company_throws(self):
		with patch(
			"sales_person_analysis.api.analysis.frappe.defaults.get_user_default",
			return_value=None,
		):
			with self.assertRaises(frappe.ValidationError):
				get_filter_options("Sales Invoice")

	def test_read_permission_enforced(self):
		with patch("sales_person_analysis.api.analysis.frappe.has_permission") as mocked:
			mocked.side_effect = frappe.PermissionError
			with self.assertRaises(frappe.PermissionError):
				get_filter_options("Sales Invoice")
			with self.assertRaises(frappe.PermissionError):
				get_customer_wise_sales({"doctype": "Sales Invoice", "year": getdate().year})

	def test_guest_cannot_call_without_permission(self):
		# Whitelisted methods still check has_permission; Guest lacks SI read.
		frappe.set_user("Guest")
		try:
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
				get_customer_wise_sales({"doctype": "Sales Invoice", "year": getdate().year})
		finally:
			frappe.set_user("Administrator")
