# Sales Person Analysis

Desk page **Sales Person Wise Analysis** for interactive Sales Invoice / Sales Order customer-wise sales analysis.

## Setup

```bash
bench --site dev.local install-app sales_person_analysis
bench --site dev.local migrate
bench --site dev.local clear-cache
bench build --app sales_person_analysis
```

Open from the Awesome Bar: `Sales Person Wise Analysis`, or via Selling / Sales workspace.

After pulling this app, run `bench migrate` once. Migrate creates **Sales Person Analysis Settings** and fills it only when it has never been saved (`defaults_applied`). Later edits are left as they are.

## Role access

Who can see sales is the user's role, configured in **Sales Person Analysis Settings** (System Manager). It is not the user's place in the Sales Person tree. The tree is used only to expand a Team role.

| Scope | Default role | What they see |
| --- | --- | --- |
| Own Only | Sales User | The Sales Person linked to their active Employee, and nobody under that node |
| Team | Sales Manager | That Sales Person plus every descendant |
| See All | System Manager | Every Sales Person |

If a user has more than one of these roles, the broadest scope wins: See All, then Team, then Own Only. **Administrator** always sees everything, even when See All is empty. A role that is not in any list can open the page only to be denied. Accounts User and Accounts Manager are on the page and are not in the default lists, so add them (usually to See All) if they should use it.

Link the user on an active Employee (`user_id`) and that Employee on an enabled Sales Person. Own Only and Team with no such link are denied. A user cannot request a Sales Person outside their scope, including by export or by editing the request.

## Returns

Sales Invoice mode includes submitted credit notes (`is_return` = 1, docstatus Submitted). A credit note already stores a negative VAT-inclusive total, so it reduces the customer row, the grand total, item-group amounts, and the CSV export. The week and month are the credit note's own posting date. A customer whose only document in that period is a credit note still appears, with a negative amount. Drafts and cancelled credit notes are left out.

The sales person is the one on the credit note's Sales Team, and role scope applies to that person. ERPNext's Return button does not copy Sales Team, so the sales person has to be on the credit note or it will not reduce that person's figures.

Sales Order has no credit note. A return does not change the submitted order total, so Sales Order mode stays the order amounts only.

## Weeks

Week filters are Sunday-Saturday calendar weeks inside the month (not fixed blocks of days 1-7, 8-14, ...). Week 1 contains the 1st and ends on Saturday. A month can span six weeks, so weeks 1-6 are available. With one month selected, a chip shows that week's dates, for example `Week 1 (1-3 Oct)` in October 2026. The week start is `WEEK_START_DAYOFWEEK` in `sales_person_analysis/constants.py` (MariaDB `DAYOFWEEK`: 1 = Sunday). Set it to 2 for Monday-start weeks.

## License

MIT
