# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Shared helpers for Sales Person Analysis tests."""

from __future__ import annotations

import frappe
from frappe.utils import flt


def company() -> str | None:
	return frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)


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
	si.append("items", {"item_code": item, "qty": qty, "rate": rate})
	for row in extra_items or []:
		si.append("items", row)
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
