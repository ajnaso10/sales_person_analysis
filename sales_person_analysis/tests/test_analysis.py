# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, getdate, today

from sales_person_analysis.api.analysis import (
	get_customer_wise_sales,
	get_filter_options,
	get_period_options,
)
from sales_person_analysis.api.period import week_of_month, week_of_month_sql
from sales_person_analysis.tests import utils as tu


class TestAnalysisAPI(IntegrationTestCase):
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

	def _require_setup(self):
		if not self.company:
			self.skipTest("No company configured")
		item, customer = tu.first_item_and_customer()
		if not item or not customer:
			self.skipTest("Need Item and Customer")
		return item, customer

	def test_invalid_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			get_customer_wise_sales({"doctype": "Purchase Invoice", "year": getdate().year})

	def test_year_required(self):
		with self.assertRaises(frappe.ValidationError):
			get_customer_wise_sales({"doctype": "Sales Invoice"})

	def test_filters_as_json_string(self):
		if not self.company:
			self.skipTest("No company configured")
		result = get_customer_wise_sales(
			frappe.as_json({"doctype": "Sales Invoice", "year": 2099, "page": 1, "page_size": 5})
		)
		self.assertEqual(result["customer_count"], 0)

	def test_filter_options_si_and_so(self):
		if not self.company:
			self.skipTest("No company configured")
		for doctype in ("Sales Invoice", "Sales Order"):
			opts = get_filter_options(doctype)
			self.assertEqual(opts["company"], self.company)
			self.assertTrue(opts["currency"])
			self.assertIsInstance(opts["sales_persons"], list)
			self.assertIsInstance(opts["item_groups"], list)
			self.assertIn(getdate().year, opts["years"])
			self.assertEqual(opts["period"]["weeks"], [1, 2, 3, 4, 5, 6])
			self.assertEqual(opts["period"]["week_start"], 1)
			self.assertTrue(opts["period"].get("week_labels"))

	def test_get_period_options_whitelist(self):
		opts = get_period_options(half="H1", quarter="Q3")
		self.assertEqual(opts["half"], "H1")
		self.assertEqual(opts["quarter"], "All")
		self.assertNotIn("Q3", opts["quarters"])
		self.assertEqual(opts["weeks"], [1, 2, 3, 4, 5, 6])

		labeled = get_period_options(half="H2", quarter="Q4", year=2026)
		self.assertEqual(labeled["week_labels"]["Oct"]["1"], "Week 1 (1-3 Oct)")
		self.assertEqual(labeled["week_labels"]["Oct"]["5"], "Week 5 (25-31 Oct)")
		self.assertNotIn("6", labeled["week_labels"]["Oct"])

	def test_empty_result_far_future_year(self):
		if not self.company:
			self.skipTest("No company configured")
		result = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": 2099, "page": 1, "page_size": 20}
		)
		self.assertEqual(result["rows"], [])
		self.assertEqual(result["grand_total"], 0)
		self.assertEqual(result["customer_count"], 0)
		self.assertEqual(result["doctype"], "Sales Invoice")

	def test_contradictory_period_empty(self):
		if not self.company:
			self.skipTest("No company configured")
		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate().year,
				"half": "H1",
				"quarter": "Q3",
				"page": 1,
			}
		)
		self.assertEqual(result["customer_count"], 0)
		self.assertEqual(result["grand_total"], 0)

	def test_salesperson_no_double_count(self):
		item, customer = self._require_setup()
		sp_a = tu.ensure_sales_person("_SPA Cov A")
		sp_b = tu.ensure_sales_person("_SPA Cov B")
		posting_date = today()
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=1000,
			sales_persons=[sp_a, sp_b],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))

		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(posting_date).year,
				"sales_persons": [sp_a, sp_b],
				"page": 1,
				"page_size": 100,
			}
		)
		amount = tu.amount_for_customer(result, customer)
		self.assertIsNotNone(amount)
		self.assertAlmostEqual(amount, flt(si.base_net_total), places=2)

	def test_single_salesperson_match_any(self):
		item, customer = self._require_setup()
		sp_a = tu.ensure_sales_person("_SPA Cov SingleA")
		sp_b = tu.ensure_sales_person("_SPA Cov SingleB")
		posting_date = today()
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=250,
			sales_persons=[sp_a, sp_b],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))

		for sp in (sp_a, sp_b):
			result = get_customer_wise_sales(
				{
					"doctype": "Sales Invoice",
					"year": getdate(posting_date).year,
					"sales_persons": [sp],
					"page": 1,
					"page_size": 100,
				}
			)
			self.assertAlmostEqual(
				tu.amount_for_customer(result, customer), flt(si.base_net_total), places=2
			)

	def test_draft_excluded(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov Draft")
		posting_date = add_days(today(), -2)
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=777,
			sales_persons=[sp],
			submit=False,
		)
		self.addCleanup(lambda: frappe.delete_doc("Sales Invoice", si.name, force=True, ignore_permissions=True))

		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(posting_date).year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 50,
			}
		)
		self.assertIsNone(tu.amount_for_customer(result, customer))

	def test_cancelled_excluded(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov Cancel")
		posting_date = add_days(today(), -3)
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=888,
			sales_persons=[sp],
		)
		si.cancel()
		self.addCleanup(
			lambda: frappe.delete_doc("Sales Invoice", si.name, force=True, ignore_permissions=True)
		)

		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(posting_date).year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 50,
			}
		)
		self.assertIsNone(tu.amount_for_customer(result, customer))

	def test_item_group_line_amounts(self):
		item, customer = self._require_setup()
		posting_date = today()
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=2,
			rate=100,
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		line_net = flt(frappe.db.get_value("Sales Invoice Item", {"parent": si.name}, "base_net_amount"))

		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(posting_date).year,
				"item_groups": [item.item_group],
				"page": 1,
				"page_size": 50,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(result, customer), line_net, places=2)

	def test_multi_item_group_partial_sum(self):
		item, customer = self._require_setup()
		other = tu.second_item_different_group(item.item_group)
		if not other:
			self.skipTest("Need a second item in another group")

		posting_date = today()
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=100,
			extra_items=[{"item_code": other.name, "qty": 1, "rate": 200}],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))

		line_a = flt(
			frappe.db.get_value(
				"Sales Invoice Item", {"parent": si.name, "item_code": item.name}, "base_net_amount"
			)
		)
		result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(posting_date).year,
				"item_groups": [item.item_group],
				"page": 1,
				"page_size": 100,
			}
		)
		amount = tu.amount_for_customer(result, customer)
		self.assertIsNotNone(amount)
		self.assertAlmostEqual(amount, line_a, places=2)
		self.assertLess(amount, flt(si.base_net_total) + 0.01)

	def test_sales_order_mode_with_data(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov SO")
		txn_date = today()
		so = tu.make_so(
			company_name=self.company,
			customer=customer,
			item=item.name,
			transaction_date=txn_date,
			qty=1,
			rate=150,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Order", so.name))

		result = get_customer_wise_sales(
			{
				"doctype": "Sales Order",
				"year": getdate(txn_date).year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 50,
			}
		)
		self.assertEqual(result["doctype"], "Sales Order")
		amount = tu.amount_for_customer(result, customer)
		self.assertIsNotNone(amount)
		self.assertAlmostEqual(amount, flt(so.base_net_total), places=2)

	def test_si_and_so_not_combined(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov Mode")
		d = today()
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=d,
			qty=1,
			rate=111,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		so = tu.make_so(
			company_name=self.company,
			customer=customer,
			item=item.name,
			transaction_date=d,
			qty=1,
			rate=222,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Order", so.name))

		si_result = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": getdate(d).year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(si_result, customer), flt(si.base_net_total), places=2)

		so_result = get_customer_wise_sales(
			{
				"doctype": "Sales Order",
				"year": getdate(d).year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(so_result, customer), flt(so.base_net_total), places=2)
		self.assertNotAlmostEqual(flt(si.base_net_total), flt(so.base_net_total), places=2)

	def test_month_half_quarter_filters(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov Period")
		# Force mid-August date in current year for Q3/H2
		year = getdate().year
		posting_date = f"{year}-08-15"
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=posting_date,
			qty=1,
			rate=333,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))

		matched = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": year,
				"half": "H2",
				"quarter": "Q3",
				"months": ["Aug"],
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(matched, customer), flt(si.base_net_total), places=2)

		missed = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": year,
				"months": ["Jan"],
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertIsNone(tu.amount_for_customer(missed, customer))

	def test_week_of_month_filter(self):
		item, customer = self._require_setup()
		sp = tu.ensure_sales_person("_SPA Cov Week")
		year = getdate().year
		# Sunday-start weeks: the 15th is week 3 and the 29th is week 5 in every month,
		# so 29 Sep stays on the week-5 filter. The 2nd is week 1 unless the 1st is Saturday.
		early = getdate(f"{year}-09-02")
		mid = getdate(f"{year}-09-15")
		late = getdate(f"{year}-09-29")
		early_week = week_of_month(early)
		self.assertEqual(week_of_month(mid), 3)
		self.assertEqual(week_of_month(late), 5)
		self.assertIn(early_week, (1, 2))
		si_w3 = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=f"{year}-09-15",
			qty=1,
			rate=410,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si_w3.name))
		si_w1 = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=f"{year}-09-02",
			qty=1,
			rate=420,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si_w1.name))

		only_w3 = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": year,
				"months": ["Sep"],
				"weeks": [3],
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(only_w3, customer), flt(si_w3.base_net_total), places=2)

		only_w1 = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": year,
				"months": ["Sep"],
				"weeks": [early_week],
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(only_w1, customer), flt(si_w1.base_net_total), places=2)

		week5_day = f"{year}-09-29"
		si_w5 = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=week5_day,
			qty=1,
			rate=430,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si_w5.name))
		only_w5 = get_customer_wise_sales(
			{
				"doctype": "Sales Invoice",
				"year": year,
				"months": ["Sep"],
				"weeks": [5],
				"sales_persons": [sp],
				"page": 1,
				"page_size": 20,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(only_w5, customer), flt(si_w5.base_net_total), places=2)

	def test_calendar_week_sql_matches_python_for_2026(self):
		"""Run the MariaDB week expression for every day of 2026, including Oct and Aug."""
		cases = {
			"2026-10-03": 1,
			"2026-10-04": 2,
			"2026-10-10": 2,
			"2026-10-11": 3,
			"2026-10-31": 5,
			"2026-08-01": 1,
			"2026-08-02": 2,
			"2026-08-30": 6,
			"2026-08-31": 6,
		}
		for day, week in cases.items():
			self.assertEqual(week_of_month(day), week, day)

		expr = week_of_month_sql("d")
		rows = frappe.db.sql(
			f"""
			WITH RECURSIVE days AS (
				SELECT DATE('2026-01-01') AS d
				UNION ALL
				SELECT DATE_ADD(d, INTERVAL 1 DAY) FROM days WHERE d < DATE('2026-12-31')
			)
			SELECT d, {expr} AS week_no
			FROM days
			"""
		)
		self.assertEqual(len(rows), 365)
		for day, week_no in rows:
			key = str(day)[:10]
			self.assertEqual(int(week_no), week_of_month(key), key)
			if key in cases:
				self.assertEqual(int(week_no), cases[key], key)

	def test_grand_total_matches_sum_and_pagination(self):
		if not self.company:
			self.skipTest("No company configured")
		# Use live data: grand total must equal sum of all exported rows
		full = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "export": 1, "page": 1}
		)
		page = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "page": 1, "page_size": 2}
		)
		self.assertEqual(full["grand_total"], page["grand_total"])
		self.assertEqual(full["customer_count"], page["customer_count"])
		if full["customer_count"] > 2:
			self.assertEqual(len(page["rows"]), 2)
			self.assertGreater(page["total_pages"], 1)
			page2 = get_customer_wise_sales(
				{"doctype": "Sales Invoice", "year": getdate().year, "page": 2, "page_size": 2}
			)
			self.assertNotEqual(page["rows"][0]["customer"], page2["rows"][0]["customer"])
		row_sum = sum(flt(r["amount"]) for r in full["rows"])
		self.assertAlmostEqual(row_sum, flt(full["grand_total"]), places=2)

	def test_export_returns_all_matching_rows(self):
		if not self.company:
			self.skipTest("No company configured")
		paged = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "page": 1, "page_size": 1}
		)
		exported = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "export": 1, "page": 1}
		)
		if paged["customer_count"] > 1:
			self.assertEqual(len(exported["rows"]), exported["customer_count"])
			self.assertGreater(len(exported["rows"]), len(paged["rows"]))

	def test_sort_descending_by_amount(self):
		if not self.company:
			self.skipTest("No company configured")
		result = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "page": 1, "page_size": 10}
		)
		amounts = [flt(r["amount"]) for r in result["rows"]]
		self.assertEqual(amounts, sorted(amounts, reverse=True))

	def test_page_size_clamped(self):
		if not self.company:
			self.skipTest("No company configured")
		result = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "page": 1, "page_size": 9999}
		)
		self.assertLessEqual(result["page_size"], 200)
		result_zero = get_customer_wise_sales(
			{"doctype": "Sales Invoice", "year": getdate().year, "page": 0, "page_size": 0}
		)
		self.assertEqual(result_zero["page"], 1)
		self.assertGreaterEqual(result_zero["page_size"], 1)
