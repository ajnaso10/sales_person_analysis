# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

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

	def test_get_years_falls_back_to_current(self):
		from unittest.mock import patch

		from frappe.utils import getdate

		with patch("sales_person_analysis.api.analysis.frappe.db.sql", return_value=[]):
			years = analysis_mod._get_years("Sales Invoice", "Any Co")
		self.assertEqual(years, [getdate().year])


def frappe_dict(**kwargs):
	import frappe

	return frappe._dict(kwargs)
