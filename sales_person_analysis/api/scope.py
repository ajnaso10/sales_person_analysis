# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

"""Role scope for Sales Person Wise Analysis.

Visibility follows Sales Person Analysis Settings, not a hardcoded place in
the Sales Person tree:

- Own Only: the Sales Person linked to the logged-in user
- Team: that Sales Person plus its descendants (lft/rgt already on the site)
- See All: every Sales Person, and also the Administrator user

When several roles match, the broadest scope wins. A role in none of the
lists cannot load the page data.
"""

from __future__ import annotations

import frappe
from frappe import _

SCOPE_SEE_ALL = "see_all"
SCOPE_TEAM = "team"
SCOPE_OWN = "own"
SCOPE_NONE = "none"

SETTINGS_NAME = "Sales Person Analysis Settings"
ROLE_CHILD = "Sales Person Analysis Role"

_ROLE_FIELDS = ("own_only_roles", "team_roles", "see_all_roles")


def restriction_context(user: str | None = None) -> dict:
	"""Scope for `user` (defaults to the session user)."""
	return _restriction_context(user or frappe.session.user)


def enforce_sales_person_filter(requested: list[str] | None) -> list[str]:
	"""Sales persons the query is allowed to use.

	See All returns the requested names unchanged (an empty list means no
	sales-person filter). Own Only and Team always stay inside the allowed
	set. A client allow-list is not an input to this function.
	"""
	ctx = _restriction_context(frappe.session.user)
	if ctx["error"]:
		frappe.throw(ctx["error"], frappe.PermissionError)
	requested = [name for name in (requested or []) if name]
	if not ctx["restricted"]:
		return requested

	allowed = list(ctx["allowed_sales_persons"])
	allowed_set = set(allowed)
	if requested:
		blocked = [name for name in requested if name not in allowed_set]
		if blocked:
			frappe.throw(
				_("You are not permitted to view sales for {0}.").format(frappe.bold(", ".join(blocked))),
				frappe.PermissionError,
			)
		return requested
	return allowed


def resolve_scope(user: str) -> str:
	"""Broadest matching role wins. Tree position is not a scope."""
	if user == "Administrator":
		return SCOPE_SEE_ALL

	roles = set(frappe.get_roles(user))
	configured = get_configured_role_sets()
	if roles & configured["see_all_roles"]:
		return SCOPE_SEE_ALL
	if roles & configured["team_roles"]:
		return SCOPE_TEAM
	if roles & configured["own_only_roles"]:
		return SCOPE_OWN
	return SCOPE_NONE


def get_configured_role_sets() -> dict[str, set[str]]:
	from sales_person_analysis.install import ensure_sales_person_analysis_settings

	ensure_sales_person_analysis_settings()
	grouped = {field: set() for field in _ROLE_FIELDS}
	if not frappe.db.exists("DocType", ROLE_CHILD):
		return grouped

	rows = frappe.db.sql(
		f"""
		SELECT parentfield, role
		FROM `tab{ROLE_CHILD}`
		WHERE parent = %s
			AND parenttype = %s
			AND IFNULL(role, '') != ''
		""",
		(SETTINGS_NAME, SETTINGS_NAME),
		as_dict=True,
	)
	for row in rows:
		if row.parentfield in grouped and row.role:
			grouped[row.parentfield].add(row.role)
	return grouped


def get_linked_sales_persons(user: str) -> list[str]:
	"""Enabled Sales Persons for the user's active Employee (Employee.user_id)."""
	return frappe.db.sql(
		"""
		SELECT sp.name
		FROM `tabSales Person` sp
		INNER JOIN `tabEmployee` emp ON emp.name = sp.employee
		WHERE emp.user_id = %s
			AND emp.status = 'Active'
			AND IFNULL(sp.enabled, 0) = 1
		ORDER BY sp.name
		""",
		(user,),
		pluck=True,
	)


def expand_with_descendants(sales_persons: list[str]) -> list[str]:
	"""Linked nodes plus descendants. The site's nested set is the team."""
	seen = set()
	allowed = []
	for name in sales_persons:
		for descendant in _subtree_names(name):
			if descendant in seen:
				continue
			seen.add(descendant)
			allowed.append(descendant)
	allowed.sort()
	return allowed


def _subtree_names(sales_person: str) -> list[str]:
	lft, rgt = frappe.db.get_value("Sales Person", sales_person, ["lft", "rgt"]) or (None, None)
	if lft is None or rgt is None:
		return [sales_person]
	names = frappe.db.sql(
		"""
		SELECT name
		FROM `tabSales Person`
		WHERE lft >= %s AND rgt <= %s
		ORDER BY name
		""",
		(lft, rgt),
		pluck=True,
	)
	return names or [sales_person]


def _restriction_context(user: str) -> dict:
	scope = resolve_scope(user)
	if scope == SCOPE_SEE_ALL:
		return _context(scope, restricted=False)

	if scope == SCOPE_NONE:
		return _context(scope, restricted=True, read_only=True, error=_role_not_allowed_message())

	linked = get_linked_sales_persons(user)
	if not linked:
		return _context(scope, restricted=True, read_only=True, error=_no_sales_person_message())

	allowed = expand_with_descendants(linked) if scope == SCOPE_TEAM else list(linked)
	return _context(
		scope,
		restricted=True,
		sales_person=linked[0] if len(linked) == 1 else None,
		allowed_sales_persons=allowed,
		read_only=len(allowed) == 1,
	)


def _context(
	scope,
	*,
	restricted,
	sales_person=None,
	allowed_sales_persons=None,
	read_only=False,
	error=None,
):
	return {
		"restricted": restricted,
		"scope": scope,
		"sales_person": sales_person,
		"allowed_sales_persons": allowed_sales_persons or [],
		"read_only": bool(read_only),
		"error": error,
	}


def _no_sales_person_message():
	return _(
		"No Sales Person is linked to your user. Link an active Employee (User ID) to an enabled Sales Person."
	)


def _role_not_allowed_message():
	return _(
		"You are not permitted to view Sales Person Wise Analysis. "
		"A System Manager can add your role in Sales Person Analysis Settings."
	)


def public_restriction(ctx: dict) -> dict:
	"""Fields the page needs. The error string is raised, not returned."""
	return {
		"restricted": bool(ctx["restricted"]),
		"scope": ctx["scope"],
		"read_only": bool(ctx["read_only"]),
		"sales_person": ctx.get("sales_person"),
	}
