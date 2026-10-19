# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Calendar period hierarchy helpers (Year → Half → Quarter → Month → Week-of-month).

Week numbering matches Sales by Customer: FLOOR((DAY(date)-1)/7)+1 (days 1–7 → week 1).
Only weeks 1–5 are offered; week 6 never matches a real calendar day.
"""

from __future__ import annotations

from frappe.utils import cint

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
WEEK_OPTIONS = (1, 2, 3, 4, 5)


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


def hierarchy_options(half=None, quarter=None) -> dict:
	"""Options for cascading UI controls."""
	half_n = normalize_half(half)
	quarter_n = normalize_quarter(quarter)
	quarters = allowed_quarters(half_n)
	if quarter_n and quarter_n not in quarters:
		quarter_n = None
	months = allowed_month_nums(half_n, quarter_n)
	return {
		"halves": ["All", "H1", "H2"],
		"quarters": ["All", *quarters],
		"months": month_labels(months),
		"weeks": list(WEEK_OPTIONS),
		"half": half_n or "All",
		"quarter": quarter_n or "All",
	}


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
