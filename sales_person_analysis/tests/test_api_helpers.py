# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from unittest.mock import patch

from frappe.tests import UnitTestCase
from frappe.utils import flt

from sales_person_analysis.api import analysis as analysis_mod
from sales_person_analysis.api.analysis import DOCTYPE_META
from sales_person_analysis.api.period import week_of_month_sql
from sales_person_analysis.constants import MAX_EXPORT_ROWS, WEEK_START_DAYOFWEEK


class TestApiHelpers(UnitTestCase):
	def test_validate_doctype_allowlist(self):
		self.assertEqual(analysis_mod._validate_doctype("Sales Invoice"), "Sales Invoice")
		self.assertEqual(analysis_mod._validate_doctype(" Sales Order "), "Sales Order")
		with self.assertRaises(Exception):
			analysis_mod._validate_doctype("Purchase Invoice")
		with self.assertRaises(Exception):
			analysis_mod._validate_doctype("")

	def test_parse_names(self):
		self.assertEqual(analysis_mod._parse_names(None), [])
		self.assertEqual(analysis_mod._parse_names(""), [])
		self.assertEqual(analysis_mod._parse_names("Haroon"), ["Haroon"])
		self.assertEqual(analysis_mod._parse_names('["A","B"]'), ["A", "B"])
		self.assertEqual(analysis_mod._parse_names(["A", "", " B "]), ["A", "B"])
		self.assertEqual(analysis_mod._parse_names(123), [])

	def test_doctype_meta(self):
		self.assertEqual(DOCTYPE_META["Sales Invoice"]["date_field"], "posting_date")
		self.assertTrue(DOCTYPE_META["Sales Invoice"]["has_is_return"])
		self.assertEqual(DOCTYPE_META["Sales Order"]["date_field"], "transaction_date")
		self.assertFalse(DOCTYPE_META["Sales Order"]["has_is_return"])

	def test_limit_clause_pagination(self):
		sql, values = analysis_mod._limit_clause({"x": 1}, page=3, page_size=20, export=0, customer_count=100)
		self.assertIn("LIMIT", sql)
		self.assertEqual(values["limit"], 20)
		self.assertEqual(values["offset"], 40)

	def test_limit_clause_export_caps(self):
		sql, values = analysis_mod._limit_clause({}, page=1, page_size=20, export=1, customer_count=50)
		self.assertEqual(values["limit"], 50)
		self.assertEqual(values["offset"], 0)

		_, values = analysis_mod._limit_clause({}, page=1, page_size=20, export=1, customer_count=999999)
		self.assertEqual(values["limit"], MAX_EXPORT_ROWS)

		_, values = analysis_mod._limit_clause({}, page=1, page_size=20, export=1, customer_count=0)
		self.assertEqual(values["limit"], MAX_EXPORT_ROWS)

	def test_format_rows(self):
		rows = analysis_mod._format_rows(
			[
				frappe_dict(customer="C1", customer_name="Cust One", amount=10.5),
				frappe_dict(customer="C2", customer_name=None, amount=None),
			]
		)
		self.assertEqual(rows[0]["customer_name"], "Cust One")
		self.assertEqual(flt(rows[0]["amount"]), 10.5)
		self.assertEqual(rows[1]["customer_name"], "C2")
		self.assertEqual(flt(rows[1]["amount"]), 0.0)

	def test_base_conditions_include_return_and_filters(self):
		meta = DOCTYPE_META["Sales Invoice"]
		conditions, values = analysis_mod._base_conditions(
			"Sales Invoice",
			"Co",
			meta,
			year=2026,
			month_nums=[8, 9],
			weeks=[1, 5],
			sales_persons=["SP1"],
		)
		joined = " ".join(conditions)
		week_sql = week_of_month_sql("doc.`posting_date`")
		self.assertIn("docstatus = 1", joined)
		self.assertIn("is_return", joined)
		self.assertIn("MONTH", joined)
		self.assertIn(week_sql, joined)
		self.assertIn("DAYOFWEEK", joined)
		self.assertIn(f"- {WEEK_START_DAYOFWEEK} + 7", week_sql)
		self.assertNotIn("(DAY(doc.`posting_date`) - 1) / 7", joined)
		self.assertIn("EXISTS", joined)
		self.assertEqual(values["company"], "Co")
		self.assertEqual(values["year"], 2026)
		self.assertEqual(values["months"], [8, 9])
		self.assertEqual(values["weeks"], [1, 5])
		self.assertEqual(values["sales_persons"], ["SP1"])

	def test_base_conditions_so_no_is_return(self):
		meta = DOCTYPE_META["Sales Order"]
		conditions, _values = analysis_mod._base_conditions(
			"Sales Order", "Co", meta, year=2026, month_nums=None, weeks=[], sales_persons=[]
		)
		joined = " ".join(conditions)
		self.assertNotIn("is_return", joined)
		self.assertIn("transaction_date", joined)
		self.assertNotIn("DAYOFWEEK", joined)

	def test_get_company_prefers_user_default(self):
		with (
			patch(
				"sales_person_analysis.api.analysis.frappe.defaults.get_user_default",
				return_value="User Co",
			) as get_default,
			patch(
				"sales_person_analysis.api.analysis.frappe.db.get_single_value",
			) as get_single,
		):
			self.assertEqual(analysis_mod._get_company(), "User Co")
		get_default.assert_called_once_with("Company")
		get_single.assert_not_called()

	def test_get_company_falls_back_to_global_defaults(self):
		with (
			patch(
				"sales_person_analysis.api.analysis.frappe.defaults.get_user_default",
				return_value=None,
			),
			patch(
				"sales_person_analysis.api.analysis.frappe.db.get_single_value",
				return_value="Global Co",
			) as get_single,
		):
			self.assertEqual(analysis_mod._get_company(), "Global Co")
		get_single.assert_called_once_with("Global Defaults", "default_company")

	def test_get_company_throws_when_unset(self):
		with (
			patch(
				"sales_person_analysis.api.analysis.frappe.defaults.get_user_default",
				return_value="",
			),
			patch(
				"sales_person_analysis.api.analysis.frappe.db.get_single_value",
				return_value=None,
			),
		):
			with self.assertRaises(Exception):
				analysis_mod._get_company()

	def test_get_years_falls_back_to_current(self):
		from frappe.utils import getdate

		with patch("sales_person_analysis.api.analysis.frappe.db.sql", return_value=[]):
			years = analysis_mod._get_years("Sales Invoice", "Any Co")
		self.assertEqual(years, [getdate().year])

	def test_inclusive_line_amount_keeps_mixed_rates(self):
		# Item A net 100 + 15 tax, item B net 200 + 0 tax, grand 315.
		# A net share of the invoice tax would be 105 and 210.
		taxed = analysis_mod.inclusive_line_amount(100, 15, 300, 15, 315)
		zero_rated = analysis_mod.inclusive_line_amount(200, 0, 300, 15, 315)
		self.assertAlmostEqual(taxed, 115)
		self.assertAlmostEqual(zero_rated, 200)
		self.assertAlmostEqual(taxed + zero_rated, 315)
		self.assertNotAlmostEqual(taxed, 105)
		self.assertNotAlmostEqual(zero_rated, 210)

	def test_inclusive_line_amount_scales_grand_total_discount(self):
		# Cash / non-trade discount leaves item nets and item tax unchanged
		# and reduces base_grand_total. 10% off 315 -> 283.5.
		taxed = analysis_mod.inclusive_line_amount(100, 15, 300, 15, 283.5)
		zero_rated = analysis_mod.inclusive_line_amount(200, 0, 300, 15, 283.5)
		self.assertAlmostEqual(taxed, 103.5)
		self.assertAlmostEqual(zero_rated, 180)
		self.assertAlmostEqual(taxed + zero_rated, 283.5)

	def test_inclusive_line_amount_no_tax_and_zero_base(self):
		self.assertAlmostEqual(analysis_mod.inclusive_line_amount(200, 0, 200, 0, 200), 200)
		self.assertAlmostEqual(analysis_mod.inclusive_line_amount(100, 15, 100, 15, 115), 115)
		self.assertAlmostEqual(analysis_mod.inclusive_line_amount(0, 0, 0, 0, 0), 0)
		self.assertAlmostEqual(analysis_mod.inclusive_line_amount(10, 0, 0, 0, 0), 10)

	def test_parent_amount_sql_is_vat_inclusive(self):
		sql = analysis_mod._parent_amount_sql()
		self.assertIn("base_grand_total", sql)
		self.assertNotIn("base_net_total", sql)
		self.assertNotIn("base_rounded_total", sql)

	def test_item_inclusive_sql_uses_item_wise_tax(self):
		joins = analysis_mod._item_tax_joins()
		expr = analysis_mod._item_inclusive_amount_sql()
		self.assertIn("tabItem Wise Tax Detail", joins)
		self.assertIn("!= 'Valuation'", joins)
		self.assertIn("doc_tax", joins)
		self.assertIn("item_tax", joins)
		self.assertIn("base_grand_total", expr)
		self.assertIn("base_net_amount", expr)
		self.assertIn("base_net_total", expr)

	def test_parent_query_sums_base_grand_total(self):
		captured = []

		def fake_sql(query, *args, **kwargs):
			captured.append(query)
			if "COUNT" in query:
				return [(0,)]
			if "COALESCE" in query:
				return [(0,)]
			return []

		with patch("sales_person_analysis.api.analysis.frappe.db.sql", side_effect=fake_sql):
			analysis_mod._query_parent_totals(
				"Sales Invoice",
				["doc.docstatus = 1"],
				{"parenttype": "Sales Invoice"},
				1,
				20,
				0,
			)
		joined = " ".join(captured)
		self.assertIn("doc.base_grand_total", joined)
		self.assertNotIn("base_net_total", joined)

	def test_item_group_query_sums_inclusive_lines(self):
		captured = []

		def fake_sql(query, *args, **kwargs):
			captured.append(query)
			if "COUNT" in query:
				return [(0,)]
			if "COALESCE" in query:
				return [(0,)]
			return []

		with patch("sales_person_analysis.api.analysis.frappe.db.sql", side_effect=fake_sql):
			analysis_mod._query_with_item_groups(
				"Sales Invoice",
				analysis_mod.DOCTYPE_META["Sales Invoice"],
				["doc.docstatus = 1"],
				{"parenttype": "Sales Invoice"},
				["Products"],
				1,
				20,
				0,
			)
		joined = " ".join(captured)
		self.assertIn("tabItem Wise Tax Detail", joined)
		self.assertIn("!= 'Valuation'", joined)
		self.assertIn("doc.base_grand_total", joined)
		self.assertNotIn("SUM(item_row.base_net_amount)", joined)


def frappe_dict(**kwargs):
	import frappe

	return frappe._dict(kwargs)
