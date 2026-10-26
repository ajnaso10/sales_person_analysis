# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Calendar period hierarchy helpers (Year → Half → Quarter → Month → Week-of-month).

Weeks are calendar weeks inside the month, Sunday-Saturday by default
(`WEEK_START_DAYOFWEEK` in constants; MariaDB DAYOFWEEK, 1=Sunday). Week 1
contains the 1st and ends the day before the next week start. A month spans
up to 6 such weeks, so weeks 1-6 are offered.

The MariaDB filter (Sunday start) is equivalent to:

    FLOOR((DAY(d) - 1 + (DAYOFWEEK(DATE_SUB(d, INTERVAL DAY(d) - 1 DAY)) - 1)) / 7) + 1

`week_of_month_sql()` writes that with MOD so changing the week-start constant
to Monday (2) stays correct when the 1st falls before the week start.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime

from frappe.utils import cint

from sales_person_analysis import constants

MONTH_ABBR_TO_NUM = {
	"Jan": 1,
	"Feb": 2,
	"Mar": 3,
	"Apr": 4,
	"May": 5,
	"Jun": 6,
	"Jul": 7,
	"Aug": 8,
	"Sep": 9,
	"Oct": 10,
	"Nov": 11,
	"Dec": 12,
}

NUM_TO_MONTH_ABBR = {v: k for k, v in MONTH_ABBR_TO_NUM.items()}

HALF_TO_MONTHS = {
	"H1": (1, 2, 3, 4, 5, 6),
	"H2": (7, 8, 9, 10, 11, 12),
}

QUARTER_TO_MONTHS = {
	"Q1": (1, 2, 3),
	"Q2": (4, 5, 6),
	"Q3": (7, 8, 9),
	"Q4": (10, 11, 12),
}

HALF_TO_QUARTERS = {
	"H1": ("Q1", "Q2"),
	"H2": ("Q3", "Q4"),
}

ALL_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
ALL_MONTHS = tuple(range(1, 13))
WEEK_OPTIONS = (1, 2, 3, 4, 5, 6)


def _week_start(week_start: int | None = None) -> int:
	start = constants.WEEK_START_DAYOFWEEK if week_start is None else week_start
	start = int(start)
	if start < 1 or start > 7:
		raise ValueError("Week start must be a DAYOFWEEK value from 1 (Sunday) to 7 (Saturday)")
	return start


def _as_date(value) -> date:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	return date.fromisoformat(str(value).strip()[:10])


def _dayofweek(value: date) -> int:
	"""MariaDB DAYOFWEEK: 1=Sunday ... 7=Saturday."""
	return (value.weekday() + 1) % 7 + 1


def week_of_month(value, week_start: int | None = None) -> int:
	"""Week-of-month (1-6) using WEEK_START_DAYOFWEEK unless week_start is passed.

	The 1st is always in week 1. Each later week starts on WEEK_START_DAYOFWEEK
	(Sunday by default) and runs seven days, clipped to the month.
	"""
	current = _as_date(value)
	start = _week_start(week_start)
	first = current.replace(day=1)
	offset = (_dayofweek(first) - start + 7) % 7
	return (current.day - 1 + offset) // 7 + 1


def week_of_month_sql(date_expr: str) -> str:
	"""MariaDB expression equivalent to week_of_month() for a date SQL expression.

	`date_expr` must be a trusted column or literal, not user input. The week
	start is WEEK_START_DAYOFWEEK (1=Sunday). For Sunday the offset
	MOD(DAYOFWEEK(first) - 1 + 7, 7) equals DAYOFWEEK(first) - 1.
	"""
	start = _week_start()
	first = f"DATE_SUB({date_expr}, INTERVAL DAY({date_expr}) - 1 DAY)"
	offset = f"MOD(DAYOFWEEK({first}) - {start} + 7, 7)"
	return f"FLOOR((DAY({date_expr}) - 1 + {offset}) / 7) + 1"


def week_ranges(year: int, month: int) -> dict[int, tuple[int, int]]:
	"""Map week-of-month → (first day, last day) for days that exist in the month."""
	last_day = calendar.monthrange(int(year), int(month))[1]
	found: dict[int, tuple[int, int]] = {}
	for day in range(1, last_day + 1):
		week = week_of_month(date(int(year), int(month), day))
		if week not in found:
			found[week] = (day, day)
		else:
			found[week] = (found[week][0], day)
	return found


def format_week_label(year: int, month: int, week: int) -> str | None:
	"""Label such as 'Week 1 (1-3 Oct)', or None when that week has no days."""
	span = week_ranges(year, month).get(int(week))
	abbr = NUM_TO_MONTH_ABBR.get(int(month))
	if not span or not abbr:
		return None
	start, end = span
	if start == end:
		return f"Week {int(week)} ({start} {abbr})"
	return f"Week {int(week)} ({start}-{end} {abbr})"


def week_labels_for_year(year: int) -> dict[str, dict[str, str]]:
	"""Per-month chip labels keyed by month abbreviation and week number string."""
	labels: dict[str, dict[str, str]] = {}
	for month in ALL_MONTHS:
		abbr = NUM_TO_MONTH_ABBR[month]
		month_labels: dict[str, str] = {}
		for week in week_ranges(year, month):
			label = format_week_label(year, month, week)
			if label:
				month_labels[str(week)] = label
		labels[abbr] = month_labels
	return labels


def normalize_half(value) -> str | None:
	if not value or str(value).strip().lower() in {"all", "all halves", ""}:
		return None
	half = str(value).strip().upper()
	return half if half in HALF_TO_MONTHS else None


def normalize_quarter(value) -> str | None:
	if not value or str(value).strip().lower() in {"all", "all quarters", ""}:
		return None
	quarter = str(value).strip().upper()
	return quarter if quarter in QUARTER_TO_MONTHS else None


def allowed_quarters(half: str | None) -> list[str]:
	if half:
		return list(HALF_TO_QUARTERS.get(half, ()))
	return list(ALL_QUARTERS)


def allowed_month_nums(half: str | None, quarter: str | None) -> list[int]:
	allowed: set[int] | None = None
	if half:
		allowed = set(HALF_TO_MONTHS[half])
	if quarter:
		q_months = set(QUARTER_TO_MONTHS[quarter])
		allowed = q_months if allowed is None else allowed & q_months
	if allowed is None:
		return list(ALL_MONTHS)
	return sorted(allowed)


def parse_month_list(value) -> list[int]:
	"""Parse month abbreviations or numbers from list / JSON / CSV."""
	items = _as_list(value)
	months: list[int] = []
	for item in items:
		text = str(item).strip()
		if text in MONTH_ABBR_TO_NUM:
			months.append(MONTH_ABBR_TO_NUM[text])
		elif cint(text) in range(1, 13):
			months.append(cint(text))
	return sorted(set(months))


def parse_week_list(value) -> list[int]:
	items = _as_list(value)
	weeks = [cint(w) for w in items if cint(w) in WEEK_OPTIONS]
	return sorted(set(weeks))


def resolve_months(half, quarter, months) -> list[int] | None:
	"""Return month numbers to filter, or None when unconstrained.

	Intersects Half ∩ Quarter ∩ selected months. Empty list means no valid months.
	"""
	half = normalize_half(half)
	quarter = normalize_quarter(quarter)

	if quarter and half and quarter not in HALF_TO_QUARTERS.get(half, ()):
		return []

	base = allowed_month_nums(half, quarter)
	selected = parse_month_list(months)

	if not half and not quarter and not selected:
		return None

	if selected:
		return sorted(set(selected) & set(base))

	# half and/or quarter must be set (earlier branch returns when all empty)
	return base


def month_labels(month_nums: list[int]) -> list[str]:
	return [NUM_TO_MONTH_ABBR[m] for m in month_nums if m in NUM_TO_MONTH_ABBR]


def hierarchy_options(half=None, quarter=None, year=None) -> dict:
	"""Options for cascading UI controls.

	When year is set, week_labels gives the date span of each week in that
	year ('Week 1 (1-3 Oct)') for months that contain the week.
	"""
	half_n = normalize_half(half)
	quarter_n = normalize_quarter(quarter)
	quarters = allowed_quarters(half_n)
	if quarter_n and quarter_n not in quarters:
		quarter_n = None
	months = allowed_month_nums(half_n, quarter_n)
	payload = {
		"halves": ["All", "H1", "H2"],
		"quarters": ["All", *quarters],
		"months": month_labels(months),
		"weeks": list(WEEK_OPTIONS),
		"week_start": constants.WEEK_START_DAYOFWEEK,
		"half": half_n or "All",
		"quarter": quarter_n or "All",
	}
	year_n = cint(year)
	if year_n:
		payload["week_labels"] = week_labels_for_year(year_n)
	return payload


def _as_list(value) -> list:
	if not value:
		return []
	if isinstance(value, list | tuple):
		return [v for v in value if v not in (None, "")]
	if isinstance(value, str):
		text = value.strip()
		if not text or text.lower() in {"all", "all months", "all weeks"}:
			return []
		if text.startswith("["):
			import frappe

			parsed = frappe.parse_json(text)
			if isinstance(parsed, list):
				return [v for v in parsed if v not in (None, "")]
		return [part.strip() for part in text.split(",") if part.strip()]
	return [value]
