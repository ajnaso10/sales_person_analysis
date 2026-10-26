# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Shared helpers for Sales Person Analysis tests."""

from __future__ import annotations

import frappe
from frappe.utils import flt


def company() -> str | None:
	"""A Company on this site.

	Does not read the user default or Global Defaults. Callers that need the
	session company set it themselves with set_user_default("company", ...).
	Frappe v16's get_user_default("Company") reads that lowercase key.
	"""
	rows = frappe.get_all("Company", pluck="name", limit=1, order_by="creation asc")
	return rows[0] if rows else None


def current_user_company():
	"""User-level `company` default only, ignoring Global Defaults."""
	value = frappe.defaults.get_defaults_for(frappe.session.user).get("company")
	if isinstance(value, list | tuple):
		return value[0] if len(value) == 1 else None
	return value


def restore_user_company(previous) -> None:
	"""Put back the user-level company default captured by current_user_company()."""
	if previous:
		frappe.defaults.set_user_default("company", previous)
	else:
		frappe.defaults.clear_user_default("company")


def ensure_customer(customer_name: str) -> str:
	"""A Customer used only by these tests, so site invoices cannot leak in.

	Customer autoname is a naming series, so the document name is returned.
	Group and territory are copied from an existing customer on the site.
	"""
	existing = frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")
	if existing:
		return existing
	template = frappe.db.get_value(
		"Customer",
		{"disabled": 0},
		["customer_group", "territory"],
		as_dict=True,
		order_by="creation asc",
	)
	series_field = frappe.get_meta("Customer").get_field("naming_series")
	naming_series = ""
	if series_field and series_field.options:
		naming_series = next((opt.strip() for opt in series_field.options.split("\n") if opt.strip()), "")
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"naming_series": naming_series or None,
			"customer_name": customer_name,
			"customer_type": "Company",
			"customer_group": template.customer_group if template else None,
			"territory": template.territory if template else None,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_sales_person(name: str) -> str:
	if not frappe.db.exists("Sales Person", name):
		frappe.get_doc({"doctype": "Sales Person", "sales_person_name": name, "enabled": 1}).insert(
			ignore_permissions=True
		)
	return name


def first_item_and_customer():
	item = frappe.db.get_value(
		"Item",
		{"disabled": 0, "is_sales_item": 1, "has_variants": 0},
		["name", "item_group"],
		as_dict=True,
	)
	customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
	return item, customer


def second_item_different_group(exclude_group: str):
	return frappe.db.get_value(
		"Item",
		{
			"disabled": 0,
			"is_sales_item": 1,
			"has_variants": 0,
			"item_group": ["!=", exclude_group],
		},
		["name", "item_group"],
		as_dict=True,
	)


def tax_account(company_name: str) -> str | None:
	"""A non-group Tax or Chargeable account for a sales tax row."""
	return frappe.db.get_value(
		"Account",
		{
			"company": company_name,
			"is_group": 0,
			"disabled": 0,
			"account_type": ["in", ["Tax", "Chargeable"]],
		},
		"name",
		order_by="name asc",
	)


def cost_center(company_name: str) -> str | None:
	cost_center_name = frappe.db.get_value("Company", company_name, "cost_center")
	if cost_center_name:
		return cost_center_name
	return frappe.db.get_value(
		"Cost Center",
		{"company": company_name, "is_group": 0, "disabled": 0},
		"name",
		order_by="name asc",
	)


def ensure_item_tax_template(company_name: str, account: str, title: str, tax_rate: float) -> str:
	"""Item Tax Template that overrides one tax account. Reused by title."""
	existing = frappe.db.get_value("Item Tax Template", {"title": title, "company": company_name}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Item Tax Template",
			"title": title,
			"company": company_name,
			"taxes": [{"tax_type": account, "tax_rate": tax_rate}],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def customer_tax_amount(parent: str, parenttype: str, item_row: str | None = None) -> float:
	"""Sum of Item Wise Tax Detail amounts, in company currency.

	Sales Taxes and Charges has no category column in ERPNext v16.
	"""
	conditions = [
		"iwt.parent = %(parent)s",
		"iwt.parenttype = %(parenttype)s",
	]
	values = {"parent": parent, "parenttype": parenttype}
	if item_row:
		conditions.append("iwt.item_row = %(item_row)s")
		values["item_row"] = item_row
	where_sql = " AND ".join(conditions)
	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(iwt.amount), 0)
		FROM `tabItem Wise Tax Detail` iwt
		INNER JOIN `tabSales Taxes and Charges` stc
			ON stc.name = iwt.tax_row
			AND stc.parent = iwt.parent
			AND stc.parenttype = iwt.parenttype
		WHERE {where_sql}
		""",
		values,
	)
	return flt(row[0][0]) if row else 0.0


def set_sales_team(parent: str, sales_persons: list[str], parenttype: str = "Sales Invoice"):
	frappe.db.delete("Sales Team", {"parent": parent, "parenttype": parenttype})
	pct = flt(100 / len(sales_persons))
	for idx, sp in enumerate(sales_persons, start=1):
		frappe.db.sql(
			"""
			INSERT INTO `tabSales Team`
				(name, creation, modified, modified_by, owner, docstatus, idx,
				 parent, parentfield, parenttype, sales_person, allocated_percentage)
			VALUES
				(%s, NOW(), NOW(), %s, %s, 0, %s, %s, 'sales_team', %s, %s, %s)
			""",
			(
				frappe.generate_hash(length=10),
				frappe.session.user,
				frappe.session.user,
				idx,
				parent,
				parenttype,
				sp,
				pct,
			),
		)


def make_si(
	*,
	company_name: str,
	customer: str,
	item: str,
	posting_date: str,
	qty: float = 1,
	rate: float = 100,
	sales_persons: list[str] | None = None,
	extra_items: list[dict] | None = None,
	taxes: list[dict] | None = None,
	item_tax_template: str | None = None,
	submit: bool = True,
	is_return: int = 0,
):
	si = frappe.new_doc("Sales Invoice")
	si.company = company_name
	si.customer = customer
	si.posting_date = posting_date
	si.due_date = posting_date
	si.set_posting_time = 1
	si.is_return = is_return
	first_item = {"item_code": item, "qty": qty, "rate": rate}
	if item_tax_template:
		first_item["item_tax_template"] = item_tax_template
	si.append("items", first_item)
	for row in extra_items or []:
		si.append("items", row)
	for row in taxes or []:
		si.append("taxes", row)
	if sales_persons:
		pct = flt(100 / len(sales_persons))
		for sp in sales_persons:
			si.append("sales_team", {"sales_person": sp, "allocated_percentage": pct})
	si.insert(ignore_permissions=True)
	if submit:
		si.submit()
	if sales_persons:
		set_sales_team(si.name, sales_persons)
		si.reload()
	return si


def make_so(
	*,
	company_name: str,
	customer: str,
	item: str,
	transaction_date: str,
	qty: float = 1,
	rate: float = 100,
	sales_persons: list[str] | None = None,
	submit: bool = True,
):
	from unittest.mock import patch

	so = frappe.new_doc("Sales Order")
	so.company = company_name
	so.customer = customer
	so.transaction_date = transaction_date
	so.delivery_date = transaction_date
	so.append("items", {"item_code": item, "qty": qty, "rate": rate, "delivery_date": transaction_date})
	if sales_persons:
		pct = flt(100 / len(sales_persons))
		for sp in sales_persons:
			so.append("sales_team", {"sales_person": sp, "allocated_percentage": pct})
	# Site workflow emails attach PDF via wkhtmltopdf (broken on this host).
	with patch("frappe.workflow.doctype.workflow_action.workflow_action.process_workflow_actions"):
		so.insert(ignore_permissions=True)
	if submit:
		frappe.db.set_value("Sales Order", so.name, "docstatus", 1, update_modified=False)
		so.reload()
	if sales_persons:
		set_sales_team(so.name, sales_persons, parenttype="Sales Order")
		so.reload()
	return so


def cancel_and_delete(doctype: str, name: str):
	if not frappe.db.exists(doctype, name):
		return
	docstatus = frappe.db.get_value(doctype, name, "docstatus")
	if docstatus == 1:
		try:
			frappe.get_doc(doctype, name).cancel()
		except Exception:
			frappe.db.set_value(doctype, name, "docstatus", 2, update_modified=False)
	frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


def amount_for_customer(result: dict, customer: str) -> float | None:
	row = next((r for r in result.get("rows") or [] if r["customer"] == customer), None)
	return None if row is None else flt(row["amount"])
