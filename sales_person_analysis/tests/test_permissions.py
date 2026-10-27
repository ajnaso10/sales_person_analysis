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
		cls._previous_company_default = tu.current_user_company()
		if cls.company:
			frappe.defaults.set_user_default("company", cls.company)
			# setUpClass already committed. Commit again so a later rollback
			# cannot drop this default before the class finishes.
			frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		if getattr(cls, "company", None):
			tu.restore_user_company(getattr(cls, "_previous_company_default", None))
			# Class cleanup rolls back the open transaction afterwards.
			frappe.db.commit()
		super().tearDownClass()

	def test_missing_company_throws(self):
		# Neither the user default nor Global Defaults supplies a company.
		real_single = frappe.db.get_single_value

		def no_global_company(doctype, fieldname, *args, **kwargs):
			if doctype == "Global Defaults" and fieldname == "default_company":
				return None
			return real_single(doctype, fieldname, *args, **kwargs)

		with (
			patch(
				"sales_person_analysis.api.analysis.frappe.defaults.get_user_default",
				return_value=None,
			),
			patch(
				"sales_person_analysis.api.analysis.frappe.db.get_single_value",
				side_effect=no_global_company,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				get_filter_options("Sales Invoice")

	def test_sales_invoice_read_is_not_the_gate(self):
		# Sales User and System Manager often have no Sales Invoice read.
		# Access is the role scope. Administrator is See All, so a patched
		# has_permission must not block the page.
		with patch(
			"sales_person_analysis.api.analysis.frappe.has_permission",
			side_effect=frappe.PermissionError,
		):
			if not self.company:
				self.skipTest("No company configured")
			options = get_filter_options("Sales Invoice")
			self.assertIn("sales_persons", options)
			result = get_customer_wise_sales(
				{"doctype": "Sales Invoice", "year": getdate().year, "page": 1, "page_size": 1}
			)
			self.assertEqual(result["doctype"], "Sales Invoice")

	def test_guest_cannot_call_without_permission(self):
		# Whitelisted methods still check has_permission; Guest lacks SI read.
		frappe.set_user("Guest")
		try:
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
				get_customer_wise_sales({"doctype": "Sales Invoice", "year": getdate().year})
		finally:
			frappe.set_user("Administrator")
