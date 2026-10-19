# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from sales_person_analysis.constants import PAGE_LABEL, PAGE_NAME
from sales_person_analysis.install import (
	after_install,
	after_migrate,
	remove_navigation,
	sync_navigation,
	sync_page,
)
from sales_person_analysis.uninstall import after_uninstall, before_uninstall


class TestInstallSync(IntegrationTestCase):
	def test_page_exists_after_sync(self):
		sync_page()
		self.assertTrue(frappe.db.exists("Page", PAGE_NAME))
		page = frappe.get_doc("Page", PAGE_NAME)
		self.assertEqual(page.title, "Sales Person Wise Analysis")
		roles = {r.role for r in page.roles}
		self.assertIn("Sales User", roles)
		self.assertIn("System Manager", roles)

	def test_navigation_sync_idempotent(self):
		sync_navigation()
		sync_navigation()
		found = False
		for workspace in ("Sales", "Selling"):
			if not frappe.db.exists("Workspace", workspace):
				continue
			ws = frappe.get_doc("Workspace", workspace)
			if any(r.type == "Link" and r.link_to == PAGE_NAME for r in ws.links):
				found = True
				labels = [r.label for r in ws.links if r.link_to == PAGE_NAME]
				self.assertIn(PAGE_LABEL, labels)
		# At least one workspace should have the link on this site
		if frappe.db.exists("Workspace", "Selling") or frappe.db.exists("Workspace", "Sales"):
			self.assertTrue(found)

	def test_after_install_and_migrate_hooks(self):
		after_install()
		after_migrate()
		self.assertTrue(frappe.db.exists("Page", PAGE_NAME))

	def test_remove_and_restore_navigation(self):
		sync_navigation()
		remove_navigation()
		for workspace in ("Sales", "Selling"):
			if not frappe.db.exists("Workspace", workspace):
				continue
			ws = frappe.get_doc("Workspace", workspace)
			self.assertFalse(any(r.type == "Link" and r.link_to == PAGE_NAME for r in ws.links))
		sync_navigation()
		self.assertTrue(
			any(
				frappe.db.exists("Workspace", w)
				and any(
					r.type == "Link" and r.link_to == PAGE_NAME
					for r in frappe.get_doc("Workspace", w).links
				)
				for w in ("Sales", "Selling")
			)
		)

	def test_uninstall_hooks_run_without_error(self):
		sync_page()
		sync_navigation()
		# before_uninstall swallows errors by design; ensure call + restore succeed.
		before_uninstall()
		after_uninstall()
		sync_page()
		sync_navigation()
		self.assertTrue(frappe.db.exists("Page", PAGE_NAME))
