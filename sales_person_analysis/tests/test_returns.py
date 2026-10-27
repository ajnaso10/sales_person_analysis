# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Submitted credit notes reduce VAT-inclusive Sales Invoice totals.

Amounts on a credit note are already negative. The page adds them. Drafts and
cancelled credit notes stay out. Sales Order has no return document.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, getdate, today

from sales_person_analysis.api.analysis import get_customer_wise_sales, inclusive_line_amount
from sales_person_analysis.api.period import NUM_TO_MONTH_ABBR, week_of_month
from sales_person_analysis.tests import utils as tu


def _expected_item_amount(doc, item_code: str) -> float:
	row_name, net = frappe.db.get_value(
		"Sales Invoice Item",
		{"parent": doc.name, "item_code": item_code},
		["name", "base_net_amount"],
	)
	return inclusive_line_amount(
		net,
		tu.customer_tax_amount(doc.name, "Sales Invoice", row_name),
		doc.base_net_total,
		tu.customer_tax_amount(doc.name, "Sales Invoice"),
		doc.base_grand_total,
	)


def _past_day(months_back: int, day: int):
	"""A day in a month that has already ended, so posting dates are not in the future."""
	anchor = getdate(add_months(getdate(today()), -months_back))
	return anchor.replace(day=day)


class TestSalesReturns(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = tu.company()
		cls._previous_company_default = tu.current_user_company()
		if cls.company:
			frappe.defaults.set_user_default("company", cls.company)
			frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		if getattr(cls, "company", None):
			tu.restore_user_company(getattr(cls, "_previous_company_default", None))
			frappe.db.commit()
		super().tearDownClass()

	def _prepare(self, customer_name: str, sales_person: str):
		if not self.company:
			self.skipTest("No company configured")
		item, _customer = tu.first_item_and_customer()
		if not item:
			self.skipTest("Need an Item")
		return item, tu.ensure_customer(customer_name), tu.ensure_sales_person(sales_person)

	def _query(self, posting_date, sales_person, **extra):
		day = getdate(posting_date)
		filters = {
			"doctype": "Sales Invoice",
			"year": day.year,
			"sales_persons": [sales_person],
			"page": 1,
			"page_size": 50,
		}
		filters.update(extra)
		return get_customer_wise_sales(filters)

	def test_partial_return_same_week_reduces_total_and_export(self):
		item, customer, sp = self._prepare("_SPA Return Same Week", "_SPA Return Same Week SP")
		day = _past_day(1, 10)
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=day,
			qty=4,
			rate=250,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		credit = tu.make_return_against(
			si.name,
			posting_date=day,
			qty_by_item={item.name: 1},
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", credit.name))

		self.assertEqual(credit.docstatus, 1)
		self.assertEqual(credit.is_return, 1)
		self.assertLess(flt(credit.base_grand_total), 0)
		expected = flt(si.base_grand_total) + flt(credit.base_grand_total)
		# Subtracting the negative total again would inflate the figure.
		self.assertNotAlmostEqual(expected, flt(si.base_grand_total) - flt(credit.base_grand_total), places=2)

		week = week_of_month(day)
		result = self._query(
			day,
			sp,
			months=[NUM_TO_MONTH_ABBR[day.month]],
			weeks=[week],
			export=1,
		)
		amount = tu.amount_for_customer(result, customer)
		self.assertAlmostEqual(amount, expected, places=2)
		self.assertAlmostEqual(flt(result["grand_total"]), expected, places=2)
		self.assertEqual(result["customer_count"], 1)
		self.assertEqual(len(result["rows"]), 1)

	def test_return_uses_its_own_week_and_month(self):
		item, customer, sp = self._prepare("_SPA Return Period", "_SPA Return Period SP")
		early = _past_day(2, 2)
		later_week = _past_day(2, 16)
		later_month = _past_day(1, 10)
		self.assertEqual(early.month, later_week.month)
		self.assertNotEqual(week_of_month(early), week_of_month(later_week))
		self.assertNotEqual((early.year, early.month), (later_month.year, later_month.month))

		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=early,
			qty=4,
			rate=100,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		week_credit = tu.make_return_against(
			si.name,
			posting_date=later_week,
			qty_by_item={item.name: 1},
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", week_credit.name))
		month_credit = tu.make_return_against(
			si.name,
			posting_date=later_month,
			qty_by_item={item.name: 1},
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", month_credit.name))
		self.assertLess(flt(week_credit.base_grand_total), 0)
		self.assertLess(flt(month_credit.base_grand_total), 0)

		early_month = [NUM_TO_MONTH_ABBR[early.month]]
		invoice_only = self._query(early, sp, months=early_month, weeks=[week_of_month(early)])
		self.assertAlmostEqual(
			tu.amount_for_customer(invoice_only, customer), flt(si.base_grand_total), places=2
		)

		week_only = self._query(later_week, sp, months=early_month, weeks=[week_of_month(later_week)])
		week_amount = tu.amount_for_customer(week_only, customer)
		self.assertIsNotNone(week_amount)
		self.assertAlmostEqual(week_amount, flt(week_credit.base_grand_total), places=2)
		self.assertLess(week_amount, 0)
		self.assertEqual(week_only["customer_count"], 1)

		month_without_week = self._query(early, sp, months=early_month)
		self.assertAlmostEqual(
			tu.amount_for_customer(month_without_week, customer),
			flt(si.base_grand_total) + flt(week_credit.base_grand_total),
			places=2,
		)

		only_return_month = self._query(later_month, sp, months=[NUM_TO_MONTH_ABBR[later_month.month]])
		month_amount = tu.amount_for_customer(only_return_month, customer)
		self.assertIsNotNone(month_amount)
		self.assertAlmostEqual(month_amount, flt(month_credit.base_grand_total), places=2)
		self.assertLess(month_amount, 0)
		self.assertAlmostEqual(flt(only_return_month["grand_total"]), month_amount, places=2)

	def test_item_group_return_keeps_mixed_vat_rates(self):
		item, customer, sp = self._prepare("_SPA Return VAT", "_SPA Return VAT SP")
		other = tu.second_item_different_group(item.item_group)
		if not other:
			self.skipTest("Need a second item in another group")
		account = tu.tax_account(self.company)
		cc = tu.cost_center(self.company)
		if not account or not cc:
			self.skipTest("Need a Tax or Chargeable account and a cost center")

		vat_template = tu.ensure_item_tax_template(self.company, account, "_SPA VAT 15", 15)
		zero_template = tu.ensure_item_tax_template(self.company, account, "_SPA Zero VAT", 0)
		day = _past_day(1, 8)
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=day,
			qty=2,
			rate=100,
			sales_persons=[sp],
			item_tax_template=vat_template,
			extra_items=[
				{
					"item_code": other.name,
					"qty": 2,
					"rate": 200,
					"item_tax_template": zero_template,
				}
			],
			taxes=[
				{
					"charge_type": "On Net Total",
					"account_head": account,
					"description": "VAT 15",
					"rate": 15,
					"cost_center": cc,
				}
			],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		credit = tu.make_return_against(
			si.name,
			posting_date=day,
			qty_by_item={item.name: 1, other.name: 1},
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", credit.name))

		taxed_row = frappe.db.get_value(
			"Sales Invoice Item", {"parent": credit.name, "item_code": item.name}, "name"
		)
		zero_row = frappe.db.get_value(
			"Sales Invoice Item", {"parent": credit.name, "item_code": other.name}, "name"
		)
		self.assertLess(tu.customer_tax_amount(credit.name, "Sales Invoice", taxed_row), 0)
		self.assertAlmostEqual(tu.customer_tax_amount(credit.name, "Sales Invoice", zero_row), 0, places=2)
		self.assertLess(flt(credit.base_grand_total), 0)

		expected_taxed = _expected_item_amount(si, item.name) + _expected_item_amount(credit, item.name)
		expected_zero = _expected_item_amount(si, other.name) + _expected_item_amount(credit, other.name)
		self.assertGreater(_expected_item_amount(si, item.name), 0)
		self.assertLess(_expected_item_amount(credit, item.name), 0)
		self.assertLess(_expected_item_amount(credit, other.name), 0)

		filters = {
			"doctype": "Sales Invoice",
			"year": day.year,
			"sales_persons": [sp],
			"page": 1,
			"page_size": 50,
		}
		full = get_customer_wise_sales(filters)
		net_total = flt(si.base_grand_total) + flt(credit.base_grand_total)
		self.assertAlmostEqual(tu.amount_for_customer(full, customer), net_total, places=2)

		taxed = get_customer_wise_sales({**filters, "item_groups": [item.item_group]})
		zero = get_customer_wise_sales({**filters, "item_groups": [other.item_group]})
		taxed_amount = tu.amount_for_customer(taxed, customer)
		zero_amount = tu.amount_for_customer(zero, customer)
		self.assertAlmostEqual(taxed_amount, expected_taxed, places=2)
		self.assertAlmostEqual(zero_amount, expected_zero, places=2)
		self.assertAlmostEqual(taxed_amount + zero_amount, net_total, places=2)
		# A net-share of the credit note's VAT would put tax on the zero-rated return line.
		self.assertNotAlmostEqual(
			_expected_item_amount(credit, other.name),
			flt(
				frappe.db.get_value(
					"Sales Invoice Item", {"parent": credit.name, "item_code": other.name}, "base_net_amount"
				)
			)
			* flt(credit.base_grand_total)
			/ flt(credit.base_net_total),
			places=2,
		)

	def test_draft_and_cancelled_returns_are_ignored(self):
		item, customer, sp = self._prepare("_SPA Return Status", "_SPA Return Status SP")
		day = _past_day(1, 12)
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=day,
			qty=1,
			rate=80,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		credit = tu.make_return_against(
			si.name,
			posting_date=day,
			sales_persons=[sp],
			submit=False,
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", credit.name))
		self.assertEqual(credit.docstatus, 0)
		self.assertLess(flt(credit.base_grand_total), 0)
		self.assertAlmostEqual(
			tu.amount_for_customer(self._query(day, sp), customer), flt(si.base_grand_total), places=2
		)

		credit.submit()
		credit.reload()
		self.assertEqual(credit.docstatus, 1)
		self.assertAlmostEqual(
			tu.amount_for_customer(self._query(day, sp), customer),
			flt(si.base_grand_total) + flt(credit.base_grand_total),
			places=2,
		)

		credit.cancel()
		credit.reload()
		self.assertEqual(credit.docstatus, 2)
		self.assertAlmostEqual(
			tu.amount_for_customer(self._query(day, sp), customer), flt(si.base_grand_total), places=2
		)

	def test_sales_order_is_not_reduced_by_a_credit_note(self):
		item, customer, sp = self._prepare("_SPA Return SO", "_SPA Return SO SP")
		day = getdate(today())
		so = tu.make_so(
			company_name=self.company,
			customer=customer,
			item=item.name,
			transaction_date=day,
			qty=1,
			rate=175,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Order", so.name))
		si = tu.make_si(
			company_name=self.company,
			customer=customer,
			item=item.name,
			posting_date=day,
			qty=1,
			rate=175,
			sales_persons=[sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", si.name))
		credit = tu.make_return_against(si.name, posting_date=day, sales_persons=[sp])
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", credit.name))
		self.assertLess(flt(credit.base_grand_total), 0)

		orders = get_customer_wise_sales(
			{
				"doctype": "Sales Order",
				"year": day.year,
				"sales_persons": [sp],
				"page": 1,
				"page_size": 50,
			}
		)
		self.assertAlmostEqual(tu.amount_for_customer(orders, customer), flt(so.base_grand_total), places=2)

		invoices = self._query(day, sp)
		self.assertAlmostEqual(
			tu.amount_for_customer(invoices, customer),
			flt(si.base_grand_total) + flt(credit.base_grand_total),
			places=2,
		)
