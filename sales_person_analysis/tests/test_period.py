# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from frappe.tests import UnitTestCase

from sales_person_analysis.api import period as period_mod
from sales_person_analysis.api.period import (
	allowed_month_nums,
	allowed_quarters,
	hierarchy_options,
	month_labels,
	normalize_half,
	normalize_quarter,
	parse_month_list,
	parse_week_list,
	resolve_months,
)


class TestPeriodNormalize(UnitTestCase):
	def test_normalize_half_variants(self):
		self.assertIsNone(normalize_half(None))
		self.assertIsNone(normalize_half(""))
		self.assertIsNone(normalize_half("All"))
		self.assertIsNone(normalize_half("all halves"))
		self.assertIsNone(normalize_half("H3"))
		self.assertEqual(normalize_half("h1"), "H1")
		self.assertEqual(normalize_half(" H2 "), "H2")

	def test_normalize_quarter_variants(self):
		self.assertIsNone(normalize_quarter(None))
		self.assertIsNone(normalize_quarter("All"))
		self.assertIsNone(normalize_quarter("all quarters"))
		self.assertIsNone(normalize_quarter("Q5"))
		self.assertEqual(normalize_quarter("q3"), "Q3")


class TestPeriodAllowedSets(UnitTestCase):
	def test_allowed_quarters_by_half(self):
		self.assertEqual(allowed_quarters("H1"), ["Q1", "Q2"])
		self.assertEqual(allowed_quarters("H2"), ["Q3", "Q4"])
		self.assertEqual(allowed_quarters(None), ["Q1", "Q2", "Q3", "Q4"])
		self.assertEqual(allowed_quarters("HX"), [])

	def test_allowed_months_all_combos(self):
		self.assertEqual(allowed_month_nums(None, None), list(range(1, 13)))
		self.assertEqual(allowed_month_nums("H1", None), [1, 2, 3, 4, 5, 6])
		self.assertEqual(allowed_month_nums("H2", None), [7, 8, 9, 10, 11, 12])
		self.assertEqual(allowed_month_nums(None, "Q1"), [1, 2, 3])
		self.assertEqual(allowed_month_nums(None, "Q2"), [4, 5, 6])
		self.assertEqual(allowed_month_nums(None, "Q3"), [7, 8, 9])
		self.assertEqual(allowed_month_nums(None, "Q4"), [10, 11, 12])
		self.assertEqual(allowed_month_nums("H1", "Q2"), [4, 5, 6])
		self.assertEqual(allowed_month_nums("H2", "Q4"), [10, 11, 12])


class TestPeriodParse(UnitTestCase):
	def test_parse_month_list_abbr_and_numbers(self):
		self.assertEqual(parse_month_list(["Jan", "Mar"]), [1, 3])
		self.assertEqual(parse_month_list(["1", "12", "99"]), [1, 12])
		self.assertEqual(parse_month_list("Feb,Apr"), [2, 4])
		self.assertEqual(parse_month_list('["Jul","Aug"]'), [7, 8])
		self.assertEqual(parse_month_list(None), [])
		self.assertEqual(parse_month_list("All Months"), [])
		self.assertEqual(parse_month_list("all"), [])

	def test_parse_week_list(self):
		self.assertEqual(parse_week_list([1, 5, 6, 0]), [1, 5])
		self.assertEqual(parse_week_list("2,4"), [2, 4])
		self.assertEqual(parse_week_list('["3","5"]'), [3, 5])
		self.assertEqual(parse_week_list("All Weeks"), [])
		self.assertEqual(parse_week_list(""), [])
		self.assertEqual(parse_week_list(3), [3])

	def test_as_list_edge_cases(self):
		self.assertEqual(period_mod._as_list(None), [])
		self.assertEqual(period_mod._as_list([]), [])
		self.assertEqual(period_mod._as_list(("a", "", None)), ["a"])
		self.assertEqual(period_mod._as_list(7), [7])


class TestResolveMonths(UnitTestCase):
	def test_contradictions_empty(self):
		self.assertEqual(resolve_months("H1", "Q3", None), [])
		self.assertEqual(resolve_months("H2", "Q1", ["Jan"]), [])
		self.assertEqual(resolve_months("H1", "Q1", ["Jul"]), [])

	def test_unconstrained(self):
		self.assertIsNone(resolve_months("All", "All", []))
		self.assertIsNone(resolve_months(None, None, None))
		self.assertIsNone(resolve_months("All", None, "All Months"))

	def test_half_or_quarter_alone(self):
		self.assertEqual(resolve_months("H2", "All", []), [7, 8, 9, 10, 11, 12])
		self.assertEqual(resolve_months(None, "Q2", []), [4, 5, 6])

	def test_selected_months_intersect(self):
		self.assertEqual(resolve_months("H2", "Q3", ["Aug", "Sep", "Oct"]), [8, 9])
		self.assertEqual(resolve_months(None, None, ["Jan", "Dec"]), [1, 12])
		self.assertEqual(resolve_months("H1", None, [1, 2, 8]), [1, 2])


class TestHierarchyOptions(UnitTestCase):
	def test_h1_drops_invalid_quarter(self):
		opts = hierarchy_options(half="H1", quarter="Q3")
		self.assertEqual(opts["half"], "H1")
		self.assertEqual(opts["quarter"], "All")
		self.assertEqual(opts["quarters"], ["All", "Q1", "Q2"])
		self.assertEqual(opts["months"], ["Jan", "Feb", "Mar", "Apr", "May", "Jun"])

	def test_h2_q4_months(self):
		opts = hierarchy_options(half="H2", quarter="Q4")
		self.assertEqual(opts["months"], ["Oct", "Nov", "Dec"])
		self.assertEqual(opts["weeks"], [1, 2, 3, 4, 5])

	def test_defaults(self):
		opts = hierarchy_options()
		self.assertEqual(opts["halves"], ["All", "H1", "H2"])
		self.assertEqual(opts["half"], "All")
		self.assertEqual(opts["quarter"], "All")
		self.assertEqual(len(opts["months"]), 12)

	def test_month_labels(self):
		self.assertEqual(month_labels([1, 12, 99]), ["Jan", "Dec"])
