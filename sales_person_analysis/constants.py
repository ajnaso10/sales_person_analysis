# Copyright (c) 2026, Savad Ibrahim and Contributors
# License: MIT

PAGE_NAME = "sales-person-wise-analysis"
PAGE_LABEL = "Sales Person Wise Analysis"
PAGE_MODULE = "Sales Person Analysis"

WORKSPACE_NAMES = ("Selling", "Sales")
SIDEBAR_NAMES = ("Selling", "Sales")
AFTER_LINKS = (
	"Sales by Customer",
	"Sales Person Wise Sales Report",
	"Sales Analytics",
	"Sales Order",
)

ALLOWED_DOCTYPES = ("Sales Invoice", "Sales Order")

# Payment filter on submitted documents. Drafts and cancelled stay out.
# Pending: unpaid or only partly paid. Paid: nothing left to collect. All: both.
STATUS_PENDING = "Pending"
STATUS_PAID = "Paid"
STATUS_ALL = "All"
DOCUMENT_STATUSES = (STATUS_PENDING, STATUS_PAID, STATUS_ALL)
DEFAULT_PAGE_SIZE = 20
MAX_EXPORT_ROWS = 10000
VISIBLE_CHIP_COUNT = 8

# MariaDB DAYOFWEEK: 1=Sunday, 2=Monday, ..., 7=Saturday.
# Week-of-month uses this as the first day of the week. Set to 2 for Monday-start weeks.
WEEK_START_DAYOFWEEK = 1
