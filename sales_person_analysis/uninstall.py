# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Uninstall cleanup for Sales Person Analysis."""

from __future__ import annotations

import frappe

from sales_person_analysis.constants import PAGE_NAME
from sales_person_analysis.install import remove_navigation


def before_uninstall():
	try:
		remove_navigation()
		if frappe.db.exists("Page", PAGE_NAME):
			frappe.delete_doc("Page", PAGE_NAME, force=True, ignore_permissions=True)
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="sales_person_analysis: before_uninstall failed")


def after_uninstall():
	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error(title="sales_person_analysis: after_uninstall failed")
