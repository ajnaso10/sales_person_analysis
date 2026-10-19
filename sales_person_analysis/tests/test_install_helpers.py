# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from frappe.tests import UnitTestCase

from sales_person_analysis import install


class TestInstallHelpers(UnitTestCase):
	def test_link_exists(self):
		rows = [{"type": "Link", "link_to": "Sales Analytics"}, {"type": "Card Break"}]
		self.assertTrue(install._link_exists(rows, "Sales Analytics"))
		self.assertFalse(install._link_exists(rows, "Missing"))

	def test_insert_links_after_match(self):
		rows = [
			{"type": "Link", "link_to": "Sales Analytics", "label": "Sales Analytics"},
			{"type": "Link", "link_to": "Other", "label": "Other"},
		]
		new_rows = [{"type": "Link", "link_to": "sales-person-wise-analysis"}]
		result = install._insert_links_after(rows, ("Sales Analytics",), new_rows)
		self.assertEqual(result[1]["link_to"], "sales-person-wise-analysis")
		self.assertEqual(result[2]["link_to"], "Other")

	def test_insert_links_after_fallback_append(self):
		rows = [{"type": "Link", "link_to": "X"}]
		new_rows = [{"type": "Link", "link_to": "Y"}]
		result = install._insert_links_after(rows, ("Missing",), new_rows)
		self.assertEqual(result[-1]["link_to"], "Y")

	def test_insert_links_after_string_after(self):
		rows = [{"type": "Link", "link_to": "A", "label": "A"}]
		result = install._insert_links_after(rows, "A", [{"type": "Link", "link_to": "B"}])
		self.assertEqual([r["link_to"] for r in result], ["A", "B"])

	def test_workspace_and_sidebar_row_shapes(self):
		link = {"label": "L", "link_to": "sales-person-wise-analysis", "link_type": "Page"}
		ws = install._workspace_link_row(link)
		self.assertEqual(ws["type"], "Link")
		self.assertEqual(ws["is_query_report"], 0)
		sb = install._sidebar_link_row(link)
		self.assertEqual(sb["child"], 1)
