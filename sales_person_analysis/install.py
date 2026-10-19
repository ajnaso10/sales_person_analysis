# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Install / migrate hooks for Sales Person Analysis."""

from __future__ import annotations

import frappe
from frappe.modules.import_file import import_file_by_path

from sales_person_analysis.constants import (
	AFTER_LINKS,
	PAGE_LABEL,
	PAGE_NAME,
	SIDEBAR_NAMES,
	WORKSPACE_NAMES,
)


def after_install():
	sync_page()
	sync_navigation()


def after_migrate():
	sync_page()
	sync_navigation()


def sync_page():
	page_path = (
		frappe.get_app_path("sales_person_analysis")
		+ "/sales_person_analysis/page/sales_person_wise_analysis/sales_person_wise_analysis.json"
	)
	import_file_by_path(page_path, force=True)
	frappe.clear_cache()


def sync_navigation():
	try:
		link = {
			"label": PAGE_LABEL,
			"link_to": PAGE_NAME,
			"link_type": "Page",
		}
		for workspace_name in WORKSPACE_NAMES:
			_sync_workspace_link(workspace_name, link, AFTER_LINKS)
		for sidebar_name in SIDEBAR_NAMES:
			_sync_sidebar_link(sidebar_name, link, AFTER_LINKS)
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="sales_person_analysis: failed to sync navigation")


def remove_navigation():
	try:
		for workspace_name in WORKSPACE_NAMES:
			_remove_workspace_link(workspace_name, PAGE_NAME)
		for sidebar_name in SIDEBAR_NAMES:
			_remove_sidebar_link(sidebar_name, PAGE_NAME)
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="sales_person_analysis: failed to remove navigation")


def _child_as_dict(row):
	data = row.as_dict()
	for key in (
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"parent",
		"parentfield",
		"parenttype",
		"idx",
		"docstatus",
	):
		data.pop(key, None)
	return data


def _insert_links_after(rows, after_link_tos, new_rows):
	if isinstance(after_link_tos, str):
		after_link_tos = (after_link_tos,)
	result = []
	inserted = False
	for row in rows:
		result.append(row)
		if (
			not inserted
			and row.get("type") == "Link"
			and (row.get("link_to") in after_link_tos or row.get("label") in after_link_tos)
		):
			result.extend(new_rows)
			inserted = True
	if not inserted:
		result.extend(new_rows)
	return result


def _link_exists(rows, link_to):
	return any(row.get("type") == "Link" and row.get("link_to") == link_to for row in rows)


def _workspace_link_row(link):
	return {
		"type": "Link",
		"label": link["label"],
		"link_type": link["link_type"],
		"link_to": link["link_to"],
		"onboard": 0,
		"hidden": 0,
		"is_query_report": 0,
	}


def _sidebar_link_row(link):
	return {
		"type": "Link",
		"label": link["label"],
		"link_type": link["link_type"],
		"link_to": link["link_to"],
		"child": 1,
		"collapsible": 1,
	}


def _save_without_export(doc):
	was_dev = frappe.conf.developer_mode
	frappe.conf.developer_mode = 0
	try:
		doc.save()
	finally:
		frappe.conf.developer_mode = was_dev


def _sync_workspace_link(workspace_name, link, after_links):
	if not frappe.db.exists("Workspace", workspace_name):
		return
	if not frappe.db.exists("Page", link["link_to"]):
		return

	ws = frappe.get_doc("Workspace", workspace_name)
	rows = [_child_as_dict(r) for r in ws.links]
	if _link_exists(rows, link["link_to"]):
		return

	ws.set("links", [])
	for row in _insert_links_after(rows, after_links, [_workspace_link_row(link)]):
		ws.append("links", row)
	ws.flags.ignore_permissions = True
	ws.flags.ignore_links = True
	_save_without_export(ws)


def _sync_sidebar_link(sidebar_name, link, after_links):
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return
	if not frappe.db.exists("Page", link["link_to"]):
		return

	sb = frappe.get_doc("Workspace Sidebar", sidebar_name)
	rows = [_child_as_dict(r) for r in sb.items]
	if _link_exists(rows, link["link_to"]):
		return

	sb.set("items", [])
	for row in _insert_links_after(rows, after_links, [_sidebar_link_row(link)]):
		sb.append("items", row)
	sb.flags.ignore_permissions = True
	_save_without_export(sb)


def _remove_workspace_link(workspace_name, link_to):
	if not frappe.db.exists("Workspace", workspace_name):
		return
	ws = frappe.get_doc("Workspace", workspace_name)
	rows = [_child_as_dict(r) for r in ws.links if not (r.type == "Link" and r.link_to == link_to)]
	if len(rows) == len(ws.links):
		return
	ws.set("links", [])
	for row in rows:
		ws.append("links", row)
	ws.flags.ignore_permissions = True
	ws.flags.ignore_links = True
	_save_without_export(ws)


def _remove_sidebar_link(sidebar_name, link_to):
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return
	sb = frappe.get_doc("Workspace Sidebar", sidebar_name)
	rows = [_child_as_dict(r) for r in sb.items if not (r.type == "Link" and r.link_to == link_to)]
	if len(rows) == len(sb.items):
		return
	sb.set("items", [])
	for row in rows:
		sb.append("items", row)
	sb.flags.ignore_permissions = True
	_save_without_export(sb)
