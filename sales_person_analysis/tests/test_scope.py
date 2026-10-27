# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Role scope for Sales Person Wise Analysis.

Own Only, Team, and See All come from Sales Person Analysis Settings.
Tree position is not a scope. Administrator always sees every Sales Person.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from frappe.utils import flt, getdate, today

from sales_person_analysis.api.analysis import get_customer_wise_sales, get_filter_options
from sales_person_analysis.api.scope import SCOPE_OWN, SCOPE_SEE_ALL, SCOPE_TEAM, resolve_scope
from sales_person_analysis.install import (
	SETTINGS_DOCTYPE,
	ensure_sales_person_analysis_settings,
)
from sales_person_analysis.tests import utils as tu

SCOPE_USER = "_spa.scope@example.com"
SEEALL_USER = "_spa.seeall@example.com"
UNMAPPED_USER = "_spa.unmapped@example.com"
NOLINK_USER = "_spa.nolink@example.com"
# Baseline roles. Every test sets the roles it needs; setUp puts these back
# so a Has Role write cannot leak through the roles cache after rollback.
FIXTURE_ROLES = {
	SCOPE_USER: ("Sales User",),
	SEEALL_USER: ("System Manager",),
	UNMAPPED_USER: ("Accounts User",),
	NOLINK_USER: ("Sales User",),
}
PARENT_SP = "_SPA Scope Parent"
CHILD_SP = "_SPA Scope Child"
OUTSIDE_SP = "_SPA Scope Outside"
CUSTOMER_NAME = "_SPA Scope Customer"


class TestScopeResolution(UnitTestCase):
	def test_administrator_is_always_see_all(self):
		with patch("sales_person_analysis.api.scope.get_configured_role_sets") as configured:
			self.assertEqual(resolve_scope("Administrator"), SCOPE_SEE_ALL)
		configured.assert_not_called()

	def test_broadest_role_wins(self):
		configured = {
			"own_only_roles": {"Sales User"},
			"team_roles": {"Sales Manager"},
			"see_all_roles": {"System Manager"},
		}
		cases = (
			(["Sales User"], SCOPE_OWN),
			(["Sales Manager"], SCOPE_TEAM),
			(["System Manager"], SCOPE_SEE_ALL),
			(["Sales User", "Sales Manager"], SCOPE_TEAM),
			(["Sales User", "System Manager"], SCOPE_SEE_ALL),
			(["Accounts User"], "none"),
			([], "none"),
		)
		with patch(
			"sales_person_analysis.api.scope.get_configured_role_sets",
			return_value=configured,
		):
			for roles, expected in cases:
				with patch("sales_person_analysis.api.scope.frappe.get_roles", return_value=roles):
					self.assertEqual(resolve_scope("person@example.com"), expected, roles)


class TestSalesPersonScope(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = tu.company()
		cls._previous_company_default = tu.current_user_company()
		cls.ready = False
		frappe.reload_doc("sales_person_analysis", "doctype", "sales_person_analysis_role")
		frappe.reload_doc("sales_person_analysis", "doctype", "sales_person_analysis_settings")
		ensure_sales_person_analysis_settings()
		if cls.company:
			frappe.defaults.set_user_default("company", cls.company)
		cls.customer = None
		cls.parent_sp = PARENT_SP
		cls.child_sp = CHILD_SP
		cls.outside_sp = OUTSIDE_SP
		cls.scope_user = SCOPE_USER
		cls.seeall_user = SEEALL_USER
		cls.unmapped_user = UNMAPPED_USER
		cls.nolink_user = NOLINK_USER
		cls.own_total = 0.0
		cls.child_total = 0.0
		cls.team_total = 0.0
		cls.all_total = 0.0
		if cls._fixtures_possible():
			cls._build_fixtures()
			cls.ready = True
		# Commit so a per-test rollback keeps the tree, invoices, and defaults.
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		if getattr(cls, "company", None):
			cls._destroy_fixtures()
			tu.restore_user_company(getattr(cls, "_previous_company_default", None))
			frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		if self.ready:
			self._restore_fixture_roles()

	def _restore_fixture_roles(self):
		for user, roles in FIXTURE_ROLES.items():
			if frappe.db.exists("User", user):
				_set_roles(user, roles)

	@classmethod
	def _fixtures_possible(cls):
		if not cls.company:
			return False
		item, _customer = tu.first_item_and_customer()
		if not item:
			return False
		cls.item = item.name
		cls.root = frappe.db.get_value("Sales Person", "Sales Team", "name") or frappe.db.get_value(
			"Sales Person", {"is_group": 1}, "name"
		)
		return bool(cls.root)

	@classmethod
	def _build_fixtures(cls):
		cls._delete_invoices()
		for name in (CHILD_SP, OUTSIDE_SP, PARENT_SP):
			if frappe.db.exists("Sales Person", name):
				frappe.delete_doc("Sales Person", name, force=True, ignore_permissions=True)

		for email, roles in FIXTURE_ROLES.items():
			cls._ensure_user(email, roles)
		for user in (SCOPE_USER, SEEALL_USER, UNMAPPED_USER, NOLINK_USER):
			frappe.defaults.set_user_default("company", cls.company, user)

		employee = cls._ensure_employee("_SPA Scope Emp", SCOPE_USER)
		parent = cls._ensure_sales_person(PARENT_SP, cls.root, employee=employee, is_group=1)
		cls._ensure_sales_person(CHILD_SP, parent, is_group=0)
		cls._ensure_sales_person(OUTSIDE_SP, cls.root, is_group=0)
		cls.customer = tu.ensure_customer(CUSTOMER_NAME)
		posting_date = today()
		parent_si = tu.make_si(
			company_name=cls.company,
			customer=cls.customer,
			item=cls.item,
			posting_date=posting_date,
			qty=1,
			rate=110,
			sales_persons=[PARENT_SP],
		)
		child_si = tu.make_si(
			company_name=cls.company,
			customer=cls.customer,
			item=cls.item,
			posting_date=posting_date,
			qty=1,
			rate=220,
			sales_persons=[CHILD_SP],
		)
		outside_si = tu.make_si(
			company_name=cls.company,
			customer=cls.customer,
			item=cls.item,
			posting_date=posting_date,
			qty=1,
			rate=440,
			sales_persons=[OUTSIDE_SP],
		)
		cls.invoice_names = [parent_si.name, child_si.name, outside_si.name]
		cls.parent_invoice = parent_si.name
		cls.outside_invoice = outside_si.name
		cls.own_total = flt(parent_si.base_grand_total)
		cls.child_total = flt(child_si.base_grand_total)
		cls.outside_total = flt(outside_si.base_grand_total)
		cls.team_total = cls.own_total + cls.child_total
		cls.all_total = cls.team_total + cls.outside_total

	@classmethod
	def _destroy_fixtures(cls):
		frappe.set_user("Administrator")
		cls._delete_invoices()
		for name in (CHILD_SP, OUTSIDE_SP, PARENT_SP):
			if frappe.db.exists("Sales Person", name):
				frappe.delete_doc("Sales Person", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Employee", filters={"user_id": SCOPE_USER}, pluck="name"):
			frappe.delete_doc("Employee", name, force=True, ignore_permissions=True)
		for user in (SCOPE_USER, SEEALL_USER, UNMAPPED_USER, NOLINK_USER):
			frappe.db.delete("DefaultValue", {"parent": user, "defkey": "company"})
			if frappe.db.exists("User", user):
				frappe.delete_doc("User", user, force=True, ignore_permissions=True)

	@classmethod
	def _delete_invoices(cls):
		customer = frappe.db.get_value("Customer", {"customer_name": CUSTOMER_NAME}, "name")
		names = set(getattr(cls, "invoice_names", []) or [])
		if customer:
			names.update(frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name"))
		for name in names:
			tu.cancel_and_delete("Sales Invoice", name)

	@classmethod
	def _ensure_user(cls, email, roles):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@", 1)[0],
					"enabled": 1,
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			)
			user.insert(ignore_permissions=True)
		_set_roles(user.name, roles)
		return user.name

	@classmethod
	def _ensure_employee(cls, employee_name, user):
		existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if existing:
			return existing
		if not frappe.db.exists("Gender", "Other"):
			frappe.get_doc({"doctype": "Gender", "gender": "Other"}).insert(ignore_permissions=True)
		employee = frappe.new_doc("Employee")
		employee.employee_name = employee_name
		employee.first_name = employee_name
		employee.company = cls.company
		employee.status = "Active"
		employee.gender = "Other"
		employee.date_of_birth = "1990-01-01"
		employee.date_of_joining = "2020-01-01"
		employee.user_id = user
		series = frappe.get_meta("Employee").get_field("naming_series")
		if series and series.options:
			employee.naming_series = next(
				(opt.strip() for opt in series.options.split("\n") if opt.strip()), None
			)
		if employee.meta.get_field("create_user_permission"):
			employee.create_user_permission = 0
		employee.insert(ignore_permissions=True)
		return employee.name

	@classmethod
	def _ensure_sales_person(cls, name, parent, employee=None, is_group=0):
		if frappe.db.exists("Sales Person", name):
			return name
		doc = frappe.get_doc(
			{
				"doctype": "Sales Person",
				"sales_person_name": name,
				"parent_sales_person": parent,
				"is_group": is_group,
				"enabled": 1,
				"employee": employee,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _need_data(self):
		if not self.ready:
			self.skipTest("Need a company, an item, and a Sales Person root")

	def _filters(self, **extra):
		filters = {
			"doctype": "Sales Invoice",
			"year": getdate().year,
			"page": 1,
			"page_size": 50,
		}
		filters.update(extra)
		return filters

	def _amount(self, **extra):
		result = get_customer_wise_sales(self._filters(**extra))
		return flt(tu.amount_for_customer(result, self.customer))

	@contextmanager
	def _as(self, user, roles):
		"""Run as `user` with exactly these roles, then restore the fixture roles."""
		_set_roles(user, roles)
		frappe.set_user(user)
		try:
			yield
		finally:
			frappe.set_user("Administrator")
			_set_roles(user, FIXTURE_ROLES[user])

	def test_own_only_excludes_descendants_and_outsiders(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales User"]):
			self.assertAlmostEqual(self._amount(), self.own_total, places=2)
			self.assertAlmostEqual(self._amount(sales_persons=[self.parent_sp]), self.own_total, places=2)
			options = get_filter_options("Sales Invoice")
		self.assertEqual(options["sales_persons"], [self.parent_sp])
		self.assertEqual(options["restriction"]["scope"], "own")
		self.assertTrue(options["restriction"]["read_only"])

	def test_own_only_rejects_descendant_and_outsider(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales User"]):
			for blocked in (self.child_sp, self.outside_sp):
				with self.assertRaises(frappe.PermissionError) as raised:
					self._amount(sales_persons=[blocked])
				self.assertIn(blocked, str(raised.exception))

	def test_own_only_ignores_client_allow_list(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales User"]):
			amount = self._amount(allowed_sales_persons=[self.outside_sp, self.child_sp])
		self.assertAlmostEqual(amount, self.own_total, places=2)

	def test_team_includes_descendants_only(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales Manager"]):
			self.assertAlmostEqual(self._amount(), self.team_total, places=2)
			self.assertAlmostEqual(self._amount(sales_persons=[self.child_sp]), self.child_total, places=2)
			with self.assertRaises(frappe.PermissionError):
				self._amount(sales_persons=[self.outside_sp])
			options = get_filter_options("Sales Invoice")
		self.assertEqual(options["sales_persons"], sorted([self.parent_sp, self.child_sp]))
		self.assertEqual(options["restriction"]["scope"], "team")
		self.assertFalse(options["restriction"]["read_only"])
		self.assertNotIn(self.outside_sp, options["sales_persons"])

	def test_multiple_roles_use_team(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales User", "Sales Manager"]):
			self.assertAlmostEqual(self._amount(), self.team_total, places=2)
			options = get_filter_options("Sales Invoice")
		self.assertEqual(options["restriction"]["scope"], "team")

	def test_see_all_includes_every_fixture_invoice(self):
		self._need_data()
		self.assertAlmostEqual(self._amount(), self.all_total, places=2)
		with self._as(self.seeall_user, ["System Manager"]):
			self.assertAlmostEqual(self._amount(), self.all_total, places=2)
			options = get_filter_options("Sales Invoice")
		self.assertFalse(options["restriction"]["restricted"])
		self.assertIn(self.outside_sp, options["sales_persons"])
		self.assertIn(self.child_sp, options["sales_persons"])

	def test_see_all_wins_without_an_employee_link(self):
		self._need_data()
		with self._as(self.nolink_user, ["Sales User", "System Manager"]):
			self.assertAlmostEqual(self._amount(), self.all_total, places=2)

	def test_unmapped_role_is_denied(self):
		self._need_data()
		with self._as(self.unmapped_user, ["Accounts User"]):
			with self.assertRaises(frappe.PermissionError) as raised:
				self._amount()
			with self.assertRaises(frappe.PermissionError):
				get_filter_options("Sales Invoice")
		self.assertIn("Sales Person Analysis Settings", str(raised.exception))

	def test_own_only_without_employee_link_is_denied(self):
		self._need_data()
		with self._as(self.nolink_user, ["Sales User"]):
			with self.assertRaises(frappe.PermissionError) as raised:
				self._amount()
		self.assertIn("Employee", str(raised.exception))

	def test_return_outside_scope_is_not_visible(self):
		self._need_data()
		posting_date = today()
		outside_credit = tu.make_return_against(
			self.outside_invoice,
			posting_date=posting_date,
			sales_persons=[self.outside_sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", outside_credit.name))
		self.assertLess(flt(outside_credit.base_grand_total), 0)
		with self._as(self.scope_user, ["Sales User"]):
			self.assertAlmostEqual(self._amount(), self.own_total, places=2)

		own_credit = tu.make_return_against(
			self.parent_invoice,
			posting_date=posting_date,
			sales_persons=[self.parent_sp],
		)
		self.addCleanup(lambda: tu.cancel_and_delete("Sales Invoice", own_credit.name))
		self.assertLess(flt(own_credit.base_grand_total), 0)
		with self._as(self.scope_user, ["Sales User"]):
			self.assertAlmostEqual(
				self._amount(), self.own_total + flt(own_credit.base_grand_total), places=2
			)

	def test_export_uses_the_same_scope(self):
		self._need_data()
		with self._as(self.scope_user, ["Sales User"]):
			result = get_customer_wise_sales(self._filters(export=1))
		self.assertAlmostEqual(flt(tu.amount_for_customer(result, self.customer)), self.own_total, places=2)
		self.assertAlmostEqual(flt(result["grand_total"]), self.own_total, places=2)

	def test_defaults_are_not_reapplied(self):
		doc = frappe.get_doc(SETTINGS_DOCTYPE)
		snapshot = _snapshot_settings(doc)
		try:
			doc.defaults_applied = 1
			doc.set("own_only_roles", [])
			doc.save(ignore_permissions=True)
			ensure_sales_person_analysis_settings()
			doc.reload()
			self.assertEqual(doc.own_only_roles, [])
			self.assertEqual(doc.defaults_applied, 1)
		finally:
			_restore_settings(snapshot)

	def test_role_can_belong_to_only_one_scope(self):
		doc = frappe.get_doc(SETTINGS_DOCTYPE)
		snapshot = _snapshot_settings(doc)
		try:
			if not any(row.role == "Sales User" for row in doc.own_only_roles):
				doc.append("own_only_roles", {"role": "Sales User"})
			doc.append("team_roles", {"role": "Sales User"})
			with self.assertRaises(frappe.ValidationError):
				doc.save(ignore_permissions=True)
		finally:
			_restore_settings(snapshot)


def _set_roles(user, roles):
	doc = frappe.get_doc("User", user)
	protected = {"All", "Guest", "Desk User"}
	keep = {row.role for row in doc.roles} & protected
	doc.set("roles", [])
	for role in sorted(set(roles) | keep):
		doc.append("roles", {"role": role})
	doc.save(ignore_permissions=True)
	# Has Role is cached. The per-test rollback restores the rows and leaves
	# this cache behind, so drop it whenever the roles change.
	frappe.cache.hdel("roles", user)
	frappe.clear_cache(user=user)


def _snapshot_settings(doc):
	return {
		"defaults_applied": doc.defaults_applied,
		"own_only_roles": [row.role for row in doc.own_only_roles],
		"team_roles": [row.role for row in doc.team_roles],
		"see_all_roles": [row.role for row in doc.see_all_roles],
	}


def _restore_settings(snapshot):
	doc = frappe.get_doc(SETTINGS_DOCTYPE)
	doc.defaults_applied = snapshot["defaults_applied"]
	for field in ("own_only_roles", "team_roles", "see_all_roles"):
		doc.set(field, [])
		for role in snapshot[field]:
			doc.append(field, {"role": role})
	doc.save(ignore_permissions=True)
