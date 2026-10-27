# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Customer-wise sales APIs for Sales Person Wise Analysis.

Who can see rows is decided by Sales Person Analysis Settings (role scope),
not by where a Sales Person sits in the tree. See api.scope.

Amount rules
------------
- Amounts are VAT-inclusive and in company currency (base_*).
- No item-group filter: SUM(parent.base_grand_total) per customer.
  base_grand_total is the customer total after exclusive and inclusive tax.
  The rounded payable (base_rounded_total) is not used.
- With an item-group filter: each matching item row is base_net_amount plus
  that row's Item Wise Tax Detail amounts, scaled by
  base_grand_total / (base_net_total + the document's customer tax) so a
  document's rows sum to its base_grand_total. Mixed tax rates stay on the
  rows that were taxed. See inclusive_line_amount(). Sales Taxes and Charges
  has no category column in ERPNext v16, so sales tax rows are not filtered
  by tax category.
- Salesperson filter uses EXISTS on Sales Team so multi-person documents are
  counted once. Amounts are not weighted by allocated_percentage.
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
from sales_person_analysis.api.scope import (
	enforce_sales_person_filter,
	public_restriction,
	restriction_context,
)
from sales_person_analysis.constants import (
	ALLOWED_DOCTYPES,
	DEFAULT_PAGE_SIZE,
	MAX_EXPORT_ROWS,
)

# Guard for a document whose net and customer tax are both zero.
_TAX_EPSILON = 1e-7

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
	ctx = _scope_or_throw()
	company = _get_company()
	if ctx["restricted"]:
		sales_persons = list(ctx["allowed_sales_persons"])
		year_sales_persons = sales_persons
	else:
		sales_persons = _get_sales_persons()
		year_sales_persons = None

	return {
		"company": company,
		"currency": frappe.get_cached_value("Company", company, "default_currency") or "",
		"sales_persons": sales_persons,
		"item_groups": _get_item_groups(),
		"years": _get_years(doctype, company, year_sales_persons),
		"period": hierarchy_options(year=getdate().year),
		"restriction": public_restriction(ctx),
	}


@frappe.whitelist()
def get_period_options(half=None, quarter=None, year=None):
	"""Cascading Half → Quarter → Month options, plus week labels for year."""
	return hierarchy_options(half=half, quarter=quarter, year=year)


@frappe.whitelist()
def get_customer_wise_sales(filters=None):
	"""Paginated customer-wise sales for the selected document type and filters."""
	filters = frappe._dict(frappe.parse_json(filters) if isinstance(filters, str) else (filters or {}))
	# Ignore a client-supplied allow-list. Export uses this same method.
	filters.pop("allowed_sales_persons", None)
	doctype = _validate_doctype(filters.get("doctype") or "Sales Invoice")

	page = max(cint(filters.get("page") or 1), 1)
	page_size = cint(filters.get("page_size") or DEFAULT_PAGE_SIZE)
	page_size = min(max(page_size, 1), 200)
	export = cint(filters.get("export"))

	year = cint(filters.get("year"))
	if not year:
		frappe.throw(_("Year is required"))

	# Apply the role scope before the empty-period shortcut, so a user with
	# no mapped role cannot hide behind an empty filter combination.
	sales_persons = enforce_sales_person_filter(_parse_names(filters.get("sales_persons")))
	company = _get_company()

	month_nums = resolve_months(filters.get("half"), filters.get("quarter"), filters.get("months"))
	if month_nums is not None and not month_nums:
		return _empty_result(company, doctype, page, page_size)

	weeks = parse_week_list(filters.get("weeks"))
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
	# get_user_default("Company") reads the scrubbed key "company" on Frappe v16.
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if not company:
		frappe.throw(_("Please set a default Company in your user defaults"))
	return company


def _scope_or_throw():
	ctx = restriction_context()
	if ctx["error"]:
		frappe.throw(ctx["error"], frappe.PermissionError)
	return ctx


def _get_sales_persons() -> list[str]:
	# db.get_all skips DocPerm. See All includes System Manager, who has no
	# Sales Person permission row in stock ERPNext.
	rows = frappe.db.get_all(
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


def _get_years(doctype: str, company: str, sales_persons: list[str] | None = None) -> list[int]:
	date_field = DOCTYPE_META[doctype]["date_field"]
	current_year = getdate().year
	conditions = [
		"docstatus = 1",
		"company = %s",
		f"`{date_field}` IS NOT NULL",
	]
	values: list = [company]
	if sales_persons is not None:
		# Restricted users only see years that contain their own documents.
		conditions.append(
			f"""EXISTS (
				SELECT 1 FROM `tabSales Team` st
				WHERE st.parent = `tab{doctype}`.name
					AND st.parenttype = %s
					AND st.sales_person IN %s
			)"""
		)
		values.extend([doctype, tuple(sales_persons) or ("",)])
	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT YEAR(`{date_field}`) AS y
		FROM `tab{doctype}`
		WHERE {" AND ".join(conditions)}
		ORDER BY y DESC
		""",
		tuple(values),
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


def inclusive_line_amount(
	base_net_amount,
	item_tax,
	base_net_total,
	invoice_tax,
	base_grand_total,
) -> float:
	"""Company-currency VAT-inclusive amount for one item row.

	Item rows have no tax-inclusive amount. Add that row's own Item Wise Tax
	Detail amounts (stored in company currency), then scale so the rows of
	one document sum to base_grand_total.

	A flat share of the invoice tax by net amount would put VAT on a
	zero-rated line when another line is taxed. Item-wise tax avoids that.
	The scale picks up cash / non-trade Grand Total discounts and inclusive-tax
	rounding dust, which change base_grand_total without being written back
	onto item nets. Net-total discounts are already inside base_net_amount.
	"""
	item_pre = flt(base_net_amount) + flt(item_tax)
	invoice_pre = flt(base_net_total) + flt(invoice_tax)
	if abs(invoice_pre) < _TAX_EPSILON:
		return item_pre
	return item_pre * flt(base_grand_total) / invoice_pre


def _parent_amount_sql() -> str:
	"""VAT-inclusive document total in company currency."""
	return "doc.base_grand_total"


def _item_tax_joins() -> str:
	"""Per-row and per-document sums of customer taxes, in company currency.

	Document tax is joined on the parent, not the item row: a zero-rated
	line may have no Item Wise Tax Detail row, and its scale still has to
	include the other lines' tax. Sales Taxes and Charges has no category
	column in ERPNext v16, so the join does not filter on one.
	"""
	return """
		LEFT JOIN (
			SELECT
				iwt.parent,
				iwt.item_row,
				SUM(iwt.amount) AS tax_amount
			FROM `tabItem Wise Tax Detail` iwt
			INNER JOIN `tabSales Taxes and Charges` stc
				ON stc.name = iwt.tax_row
				AND stc.parent = iwt.parent
				AND stc.parenttype = %(parenttype)s
			WHERE iwt.parenttype = %(parenttype)s
			GROUP BY iwt.parent, iwt.item_row
		) item_tax
			ON item_tax.parent = doc.name
			AND item_tax.item_row = item_row.name
		LEFT JOIN (
			SELECT
				iwt.parent,
				SUM(iwt.amount) AS tax_amount
			FROM `tabItem Wise Tax Detail` iwt
			INNER JOIN `tabSales Taxes and Charges` stc
				ON stc.name = iwt.tax_row
				AND stc.parent = iwt.parent
				AND stc.parenttype = %(parenttype)s
			WHERE iwt.parenttype = %(parenttype)s
			GROUP BY iwt.parent
		) doc_tax
			ON doc_tax.parent = doc.name
	"""


def _item_inclusive_amount_sql() -> str:
	"""SQL twin of inclusive_line_amount()."""
	item_pre = "(item_row.base_net_amount + IFNULL(item_tax.tax_amount, 0))"
	invoice_pre = "(doc.base_net_total + IFNULL(doc_tax.tax_amount, 0))"
	return f"""
		CASE
			WHEN ABS({invoice_pre}) < 0.0000001 THEN {item_pre}
			ELSE {item_pre} * doc.base_grand_total / {invoice_pre}
		END
	"""


def _query_parent_totals(doctype, conditions, values, page, page_size, export):
	where_sql = " AND ".join(conditions)
	amount_sql = _parent_amount_sql()
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
		SELECT COALESCE(SUM({amount_sql}), 0)
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
			SUM({amount_sql}) AS amount
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
	amount_sql = _item_inclusive_amount_sql()

	from_sql = f"""
		FROM `tab{doctype}` doc
		INNER JOIN `tab{item_doctype}` item_row
			ON item_row.parent = doc.name AND item_row.parenttype = %(parenttype)s
		INNER JOIN `tabItem` item ON item.name = item_row.item_code
		{_item_tax_joins()}
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
		SELECT COALESCE(SUM({amount_sql}), 0)
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
			SUM({amount_sql}) AS amount
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
