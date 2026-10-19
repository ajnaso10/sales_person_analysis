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
DEFAULT_PAGE_SIZE = 20
MAX_EXPORT_ROWS = 10000
VISIBLE_CHIP_COUNT = 8
