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

## Weeks

Week filters are Sunday-Saturday calendar weeks inside the month (not fixed blocks of days 1-7, 8-14, ...). Week 1 contains the 1st and ends on Saturday. A month can span six weeks, so weeks 1-6 are available. With one month selected, a chip shows that week's dates, for example `Week 1 (1-3 Oct)` in October 2026. The week start is `WEEK_START_DAYOFWEEK` in `sales_person_analysis/constants.py` (MariaDB `DAYOFWEEK`: 1 = Sunday). Set it to 2 for Monday-start weeks.

## License

MIT
