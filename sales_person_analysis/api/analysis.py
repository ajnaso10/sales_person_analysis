# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Customer-wise sales APIs for Sales Person Wise Analysis.

Amount rules
------------
- No item-group filter: SUM(parent.base_net_total) per customer.
- With item-group filter: SUM(child.base_net_amount) for matching Item.item_group rows only.
- Salesperson filter uses EXISTS on Sales Team so multi-person documents are counted once.
- SI and SO amounts are never combined in one result set.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from sales_person_analysis.api.period import (
	hierarchy_options,
	parse_week_list,
	resolve_months,
	week_of_month_sql,
)
from sales_person_analysis.constants import (
	ALLOWED_DOCTYPES,
	DEFAULT_PAGE_SIZE,
	MAX_EXPORT_ROWS,
)

DOCTYPE_META = {
	"Sales Invoice": {
		"date_field": "posting_date",
		"item_doctype": "Sales Invoice Item",
		"has_is_return": True,
	},
	"Sales Order": {
		"date_field": "transaction_date",
		"item_doctype": "Sales Order Item",
		"has_is_return": False,
	},
}


@frappe.whitelist()
def get_filter_options(doctype: str = "Sales Invoice"):
	"""Return sales persons, item groups, years, and period hierarchy options."""
	doctype = _validate_doctype(doctype)
	frappe.has_permission(doctype, "read", throw=True)
	company = _get_company()

	return {
		"company": company,
		"currency": frappe.get_cached_value("Company", company, "default_currency") or "",
		"sales_persons": _get_sales_persons(),
		"item_groups": _get_item_groups(),
		"years": _get_years(doctype, company),
		"period": hierarchy_options(year=getdate().year),
	}


@frappe.whitelist()
def get_period_options(half=None, quarter=None, year=None):
	"""Cascading Half → Quarter → Month options, plus week labels for year."""
	return hierarchy_options(half=half, quarter=quarter, year=year)


@frappe.whitelist()
def get_customer_wise_sales(filters=None):
	"""Paginated customer-wise sales for the selected document type and filters."""
	filters = frappe._dict(frappe.parse_json(filters) if isinstance(filters, str) else (filters or {}))
	doctype = _validate_doctype(filters.get("doctype") or "Sales Invoice")
	frappe.has_permission(doctype, "read", throw=True)
	company = _get_company()

	page = max(cint(filters.get("page") or 1), 1)
	page_size = cint(filters.get("page_size") or DEFAULT_PAGE_SIZE)
	page_size = min(max(page_size, 1), 200)
	export = cint(filters.get("export"))

	year = cint(filters.get("year"))
	if not year:
		frappe.throw(_("Year is required"))

	month_nums = resolve_months(filters.get("half"), filters.get("quarter"), filters.get("months"))
	if month_nums is not None and not month_nums:
		return _empty_result(company, doctype, page, page_size)

	weeks = parse_week_list(filters.get("weeks"))
	sales_persons = _parse_names(filters.get("sales_persons"))
	item_groups = _parse_names(filters.get("item_groups"))

	meta = DOCTYPE_META[doctype]
	conditions, values = _base_conditions(doctype, company, meta, year, month_nums, weeks, sales_persons)

	if item_groups:
		rows, grand_total, customer_count = _query_with_item_groups(
			doctype, meta, conditions, values, item_groups, page, page_size, export
		)
	else:
		rows, grand_total, customer_count = _query_parent_totals(
			doctype, conditions, values, page, page_size, export
		)

	currency = frappe.get_cached_value("Company", company, "default_currency") or ""
	return {
		"company": company,
		"currency": currency,
		"doctype": doctype,
		"rows": rows,
		"grand_total": flt(grand_total),
		"customer_count": cint(customer_count),
		"page": page,
		"page_size": page_size if not export else len(rows),
		"total_pages": max(1, (cint(customer_count) + page_size - 1) // page_size) if page_size else 1,
	}


def _empty_result(company, doctype, page, page_size):
	currency = frappe.get_cached_value("Company", company, "default_currency") or ""
	return {
		"company": company,
		"currency": currency,
		"doctype": doctype,
		"rows": [],
		"grand_total": 0.0,
		"customer_count": 0,
		"page": page,
		"page_size": page_size,
		"total_pages": 1,
	}


def _validate_doctype(doctype: str) -> str:
	doctype = (doctype or "").strip()
	if doctype not in ALLOWED_DOCTYPES:
		frappe.throw(_("Document Type must be Sales Invoice or Sales Order"))
	return doctype


def _get_company() -> str:
	company = frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw(_("Please set a default Company in your user defaults"))
	return company


def _get_sales_persons() -> list[str]:
	rows = frappe.get_all(
		"Sales Person",
		filters={"enabled": 1},
		fields=["name"],
		order_by="name asc",
		limit=500,
	)
	return [r.name for r in rows]


def _get_item_groups() -> list[str]:
	rows = frappe.get_all(
		"Item Group",
		fields=["name"],
		order_by="name asc",
		limit=1000,
	)
	return [r.name for r in rows]


def _get_years(doctype: str, company: str) -> list[int]:
	date_field = DOCTYPE_META[doctype]["date_field"]
	current_year = getdate().year
	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT YEAR(`{date_field}`) AS y
		FROM `tab{doctype}`
		WHERE docstatus = 1 AND company = %s AND `{date_field}` IS NOT NULL
		ORDER BY y DESC
		""",
		(company,),
	)
	years = [cint(r[0]) for r in rows if r and r[0]]
	if current_year not in years:
		years.insert(0, current_year)
	return years or [current_year]


def _parse_names(value) -> list[str]:
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.strip().startswith("[") else [value]
	if not isinstance(value, list | tuple):
		return []
	return [str(v).strip() for v in value if v and str(v).strip()]


def _base_conditions(doctype, company, meta, year, month_nums, weeks, sales_persons):
	date_field = meta["date_field"]
	conditions = [
		"doc.docstatus = 1",
		"doc.company = %(company)s",
		f"YEAR(doc.`{date_field}`) = %(year)s",
	]
	values = {"company": company, "year": year, "parenttype": doctype}

	if meta["has_is_return"]:
		conditions.append("IFNULL(doc.is_return, 0) = 0")

	if month_nums is not None:
		conditions.append(f"MONTH(doc.`{date_field}`) IN %(months)s")
		values["months"] = month_nums

	if weeks:
		# Sunday-start week-of-month (WEEK_START_DAYOFWEEK). See period.week_of_month_sql.
		conditions.append(f"{week_of_month_sql(f'doc.`{date_field}`')} IN %(weeks)s")
		values["weeks"] = weeks

	if sales_persons:
		conditions.append(
			"""
			EXISTS (
				SELECT 1 FROM `tabSales Team` st
				WHERE st.parent = doc.name
					AND st.parenttype = %(parenttype)s
					AND st.sales_person IN %(sales_persons)s
			)
			"""
		)
		values["sales_persons"] = sales_persons

	return conditions, values


def _query_parent_totals(doctype, conditions, values, page, page_size, export):
	where_sql = " AND ".join(conditions)
	count_row = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM (
			SELECT doc.customer
			FROM `tab{doctype}` doc
			WHERE {where_sql}
			GROUP BY doc.customer
		) t
		""",
		values,
	)
	customer_count = cint(count_row[0][0]) if count_row else 0

	total_row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(doc.base_net_total), 0)
		FROM `tab{doctype}` doc
		WHERE {where_sql}
		""",
		values,
	)
	grand_total = flt(total_row[0][0]) if total_row else 0.0

	limit_sql, values = _limit_clause(values, page, page_size, export, customer_count)
	rows = frappe.db.sql(
		f"""
		SELECT
			doc.customer AS customer,
			MAX(doc.customer_name) AS customer_name,
			SUM(doc.base_net_total) AS amount
		FROM `tab{doctype}` doc
		WHERE {where_sql}
		GROUP BY doc.customer
		ORDER BY amount DESC, customer_name ASC
		{limit_sql}
		""",
		values,
		as_dict=True,
	)
	return _format_rows(rows), grand_total, customer_count


def _query_with_item_groups(doctype, meta, conditions, values, item_groups, page, page_size, export):
	item_doctype = meta["item_doctype"]
	conditions = [*conditions, "item.item_group IN %(item_groups)s"]
	values = {**values, "item_groups": item_groups}
	where_sql = " AND ".join(conditions)

	from_sql = f"""
		FROM `tab{doctype}` doc
		INNER JOIN `tab{item_doctype}` item_row
			ON item_row.parent = doc.name AND item_row.parenttype = %(parenttype)s
		INNER JOIN `tabItem` item ON item.name = item_row.item_code
	"""

	count_row = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM (
			SELECT doc.customer
			{from_sql}
			WHERE {where_sql}
			GROUP BY doc.customer
		) t
		""",
		values,
	)
	customer_count = cint(count_row[0][0]) if count_row else 0

	total_row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(item_row.base_net_amount), 0)
		{from_sql}
		WHERE {where_sql}
		""",
		values,
	)
	grand_total = flt(total_row[0][0]) if total_row else 0.0

	limit_sql, values = _limit_clause(values, page, page_size, export, customer_count)
	rows = frappe.db.sql(
		f"""
		SELECT
			doc.customer AS customer,
			MAX(doc.customer_name) AS customer_name,
			SUM(item_row.base_net_amount) AS amount
		{from_sql}
		WHERE {where_sql}
		GROUP BY doc.customer
		ORDER BY amount DESC, customer_name ASC
		{limit_sql}
		""",
		values,
		as_dict=True,
	)
	return _format_rows(rows), grand_total, customer_count


def _limit_clause(values, page, page_size, export, customer_count):
	if export:
		values = {**values, "limit": min(customer_count or MAX_EXPORT_ROWS, MAX_EXPORT_ROWS), "offset": 0}
	else:
		values = {**values, "limit": page_size, "offset": (page - 1) * page_size}
	return "LIMIT %(limit)s OFFSET %(offset)s", values


def _format_rows(rows):
	formatted = []
	for row in rows:
		formatted.append(
			{
				"customer": row.customer,
				"customer_name": row.customer_name or row.customer or _("(No Customer)"),
				"amount": flt(row.amount),
			}
		)
	return formatted
