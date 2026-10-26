# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from datetime import date, timedelta
from unittest.mock import patch

from frappe.tests import UnitTestCase

from sales_person_analysis.api import period as period_mod
from sales_person_analysis.api.period import (
	allowed_month_nums,
	allowed_quarters,
	format_week_label,
	hierarchy_options,
	month_labels,
	normalize_half,
	normalize_quarter,
	parse_month_list,
	parse_week_list,
	resolve_months,
	week_labels_for_year,
	week_of_month,
	week_of_month_sql,
	week_ranges,
)
from sales_person_analysis.constants import WEEK_START_DAYOFWEEK


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
		self.assertEqual(parse_week_list([1, 5, 6, 0, 7]), [1, 5, 6])
		self.assertEqual(parse_week_list("2,4"), [2, 4])
		self.assertEqual(parse_week_list('["3","5"]'), [3, 5])
		self.assertEqual(parse_week_list("All Weeks"), [])
		self.assertEqual(parse_week_list(""), [])
		self.assertEqual(parse_week_list(3), [3])
		self.assertEqual(parse_week_list("6"), [6])

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
		self.assertEqual(opts["weeks"], [1, 2, 3, 4, 5, 6])
		self.assertEqual(opts["week_start"], 1)

	def test_defaults(self):
		opts = hierarchy_options()
		self.assertEqual(opts["halves"], ["All", "H1", "H2"])
		self.assertEqual(opts["half"], "All")
		self.assertEqual(opts["quarter"], "All")
		self.assertEqual(len(opts["months"]), 12)

	def test_month_labels(self):
		self.assertEqual(month_labels([1, 12, 99]), ["Jan", "Dec"])


def _sunday_calendar_week(current: date) -> int:
	"""Independent oracle: weeks start on the Sunday on or before the 1st."""
	first = current.replace(day=1)
	days_since_sunday = (first.weekday() + 1) % 7
	origin = first - timedelta(days=days_since_sunday)
	return (current - origin).days // 7 + 1


def _sql_week_arithmetic(current: date, week_start: int = 1) -> int:
	"""Python evaluation of week_of_month_sql (FLOOR / MOD / DAYOFWEEK)."""
	first = current.replace(day=1)
	dayofweek = (first.weekday() + 1) % 7 + 1
	offset = (dayofweek - week_start + 7) % 7
	return (current.day - 1 + offset) // 7 + 1


def _documented_sunday_sql(current: date) -> int:
	"""The Sunday form without MOD: offset = DAYOFWEEK(first) - 1."""
	first = current.replace(day=1)
	dayofweek = (first.weekday() + 1) % 7 + 1
	offset = dayofweek - 1
	return (current.day - 1 + offset) // 7 + 1


class TestWeekOfMonth(UnitTestCase):
	def test_week_start_constant_is_sunday(self):
		self.assertEqual(WEEK_START_DAYOFWEEK, 1)

	def test_october_2026_client_ranges(self):
		# 1 Oct 2026 is Thursday. Week 1 is Thu-Sat, then Sunday-Saturday blocks.
		expected = {
			date(2026, 10, 3): 1,
			date(2026, 10, 4): 2,
			date(2026, 10, 10): 2,
			date(2026, 10, 11): 3,
			date(2026, 10, 31): 5,
		}
		for current, week in expected.items():
			self.assertEqual(week_of_month(current), week, current)
		self.assertEqual(
			week_ranges(2026, 10),
			{
				1: (1, 3),
				2: (4, 10),
				3: (11, 17),
				4: (18, 24),
				5: (25, 31),
			},
		)
		self.assertEqual(format_week_label(2026, 10, 1), "Week 1 (1-3 Oct)")
		self.assertEqual(format_week_label(2026, 10, 2), "Week 2 (4-10 Oct)")
		self.assertEqual(format_week_label(2026, 10, 3), "Week 3 (11-17 Oct)")
		self.assertEqual(format_week_label(2026, 10, 4), "Week 4 (18-24 Oct)")
		self.assertEqual(format_week_label(2026, 10, 5), "Week 5 (25-31 Oct)")
		self.assertIsNone(format_week_label(2026, 10, 6))

	def test_august_2026_needs_week_6(self):
		# 1 Aug 2026 is Saturday, so the month has a one-day week 1 and a week 6.
		self.assertEqual(week_of_month("2026-08-01"), 1)
		self.assertEqual(week_of_month("2026-08-02"), 2)
		self.assertEqual(week_of_month("2026-08-30"), 6)
		self.assertEqual(week_of_month("2026-08-31"), 6)
		self.assertEqual(format_week_label(2026, 8, 1), "Week 1 (1 Aug)")
		self.assertEqual(format_week_label(2026, 8, 2), "Week 2 (2-8 Aug)")
		self.assertEqual(format_week_label(2026, 8, 6), "Week 6 (30-31 Aug)")

	def test_sql_expression_matches_python_for_every_day_of_2026(self):
		sql = week_of_month_sql("d")
		self.assertEqual(
			sql,
			"FLOOR((DAY(d) - 1 + MOD(DAYOFWEEK(DATE_SUB(d, INTERVAL DAY(d) - 1 DAY)) - 1 + 7, 7)) / 7) + 1",
		)
		current = date(2026, 1, 1)
		end = date(2026, 12, 31)
		seen = set()
		while current <= end:
			week = week_of_month(current)
			self.assertEqual(week, _sunday_calendar_week(current), current)
			self.assertEqual(week, _sql_week_arithmetic(current, WEEK_START_DAYOFWEEK), current)
			self.assertEqual(week, _documented_sunday_sql(current), current)
			self.assertGreaterEqual(week, 1)
			self.assertLessEqual(week, 6)
			seen.add(week)
			current += timedelta(days=1)
		self.assertEqual(seen, {1, 2, 3, 4, 5, 6})

	def test_monday_start_is_the_week_start_constant(self):
		# 2 Aug 2026 is Sunday: week 2 when weeks start Sunday, week 1 when they start Monday.
		self.assertEqual(week_of_month("2026-08-02"), 2)
		self.assertEqual(week_of_month("2026-08-02", week_start=2), 1)
		self.assertEqual(week_of_month("2026-08-03", week_start=2), 2)
		with patch("sales_person_analysis.constants.WEEK_START_DAYOFWEEK", 2):
			self.assertEqual(week_of_month("2026-08-02"), 1)
			sql = week_of_month_sql("d")
			self.assertIn("MOD(DAYOFWEEK(DATE_SUB(d, INTERVAL DAY(d) - 1 DAY)) - 2 + 7, 7)", sql)
			self.assertEqual(week_of_month("2026-08-02"), _sql_week_arithmetic(date(2026, 8, 2), 2))

	def test_week_labels_for_october_and_august_2026(self):
		labels = week_labels_for_year(2026)
		self.assertEqual(labels["Oct"]["1"], "Week 1 (1-3 Oct)")
		self.assertNotIn("6", labels["Oct"])
		self.assertEqual(labels["Aug"]["6"], "Week 6 (30-31 Aug)")
		opts = hierarchy_options(half="H2", quarter="Q4", year=2026)
		self.assertEqual(opts["week_labels"]["Oct"]["5"], "Week 5 (25-31 Oct)")
		self.assertNotIn("week_labels", hierarchy_options())
