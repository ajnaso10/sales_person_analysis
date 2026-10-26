// Copyright (c) 2026, Savad Ibrahim and Contributors
// License: MIT

frappe.pages["sales-person-wise-analysis"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Sales Person Wise Analysis"),
		single_column: true,
	});
	frappe.sales_person_wise_analysis = new SalesPersonWiseAnalysis(page);
};

class SalesPersonWiseAnalysis {
	constructor(page) {
		this.page = page;
		this.request_id = 0;
		this.loading = false;
		this.refresh_timer = null;
		this.page_size = 20;
		this.visible_chip_count = 8;

		this.state = {
			doctype: "Sales Invoice",
			sales_persons: [],
			year: String(new Date().getFullYear()),
			half: "All",
			quarter: "All",
			months: [],
			weeks: [],
			item_groups: [],
			page: 1,
			expand_sales_persons: false,
			expand_weeks: false,
			expand_item_groups: false,
			item_group_search: "",
		};

		this.options = {
			sales_persons: [],
			item_groups: [],
			years: [this.state.year],
			currency: "",
			period: {
				halves: ["All", "H1", "H2"],
				quarters: ["All", "Q1", "Q2", "Q3", "Q4"],
				months: [],
				weeks: [1, 2, 3, 4, 5, 6],
				week_start: 1,
				week_labels: {},
			},
		};

		this.data = {
			rows: [],
			grand_total: 0,
			customer_count: 0,
			total_pages: 1,
			currency: "",
		};

		this.make_actions();
		this.$root = $('<div class="spa-page"></div>').appendTo(page.main);
		this.render_shell();
		this.load_filter_options().then(() => this.refresh());
	}

	make_actions() {
		this.page.set_secondary_action(__("Clear All Filters"), () => this.clear_filters());
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
	}

	render_shell() {
		this.$root.html(`
			<div class="spa-filter-panel">
				<div class="spa-filter-row spa-doctype-row"></div>
				<div class="spa-filter-row spa-sales-person-row"></div>
				<div class="spa-filter-row spa-date-row"></div>
				<div class="spa-filter-row spa-month-row"></div>
				<div class="spa-filter-row spa-week-row"></div>
				<div class="spa-filter-row spa-item-group-row"></div>
			</div>
			<div class="spa-table-section">
				<div class="spa-table-header">
					<div class="spa-table-title">
						<span>${__("Customer Wise Sales")}</span>
						<span class="spa-count-badge spa-count">0 ${__("customers")}</span>
					</div>
					<button type="button" class="btn btn-default btn-sm spa-export-btn">
						<span class="octicon octicon-desktop-download"></span> ${__("Export")}
					</button>
				</div>
				<div class="spa-table-body"></div>
				<div class="spa-table-footer">
					<div class="spa-pagination"></div>
					<div class="spa-grand-total">
						${__("Grand Total")}
						<span class="spa-amount">0</span>
					</div>
				</div>
			</div>
		`);

		this.$root.find(".spa-export-btn").on("click", () => this.export_csv());
		this.bind_filter_events();
		this.render_filters();
		this.render_table();
	}

	bind_filter_events() {
		this.$root.on("click", "[data-doctype]", (e) => {
			const doctype = $(e.currentTarget).data("doctype");
			if (doctype === this.state.doctype) return;
			this.state.doctype = doctype;
			this.state.page = 1;
			this.load_filter_options().then(() => this.schedule_refresh());
		});

		this.$root.on("click", "[data-sales-person]", (e) => {
			const name = String($(e.currentTarget).data("sales-person"));
			if (name === "__all__") {
				this.state.sales_persons = [];
			} else {
				this.toggle_list(this.state.sales_persons, name);
			}
			this.state.page = 1;
			this.render_sales_persons();
			this.schedule_refresh();
		});

		this.$root.on("click", "[data-expand-sales]", () => {
			this.state.expand_sales_persons = !this.state.expand_sales_persons;
			this.render_sales_persons();
		});

		this.$root.on("change", ".spa-year-select, .spa-half-select, .spa-quarter-select", (e) => {
			const $el = $(e.currentTarget);
			if ($el.hasClass("spa-year-select")) {
				this.state.year = $el.val();
				this.state.page = 1;
				this.refresh_period_options()
					.catch(() => {
						this.options.period.week_labels = {};
					})
					.finally(() => {
						this.render_weeks();
						this.schedule_refresh();
					});
				return;
			} else if ($el.hasClass("spa-half-select")) {
				this.state.half = $el.val();
				this.state.quarter = "All";
				this.state.months = [];
				this.refresh_period_options().then(() => {
					this.state.page = 1;
					this.render_filters();
					this.schedule_refresh();
				});
				return;
			} else {
				this.state.quarter = $el.val();
				this.state.months = [];
				this.refresh_period_options().then(() => {
					this.state.page = 1;
					this.render_filters();
					this.schedule_refresh();
				});
				return;
			}
		});

		this.$root.on("click", "[data-month]", (e) => {
			const month = String($(e.currentTarget).data("month"));
			if (month === "__all__") {
				this.state.months = [];
			} else {
				this.toggle_list(this.state.months, month);
			}
			this.state.page = 1;
			this.render_months();
			this.render_weeks();
			this.schedule_refresh();
		});

		this.$root.on("click", "[data-week]", (e) => {
			const week = String($(e.currentTarget).data("week"));
			if (week === "__all__") {
				this.state.weeks = [];
			} else {
				this.toggle_list(this.state.weeks, week);
			}
			this.state.page = 1;
			this.render_weeks();
			this.schedule_refresh();
		});

		this.$root.on("click", "[data-expand-weeks]", () => {
			this.state.expand_weeks = !this.state.expand_weeks;
			this.render_weeks();
		});

		this.$root.on("click", "[data-item-group]", (e) => {
			const name = String($(e.currentTarget).data("item-group"));
			if (name === "__all__") {
				this.state.item_groups = [];
			} else {
				this.toggle_list(this.state.item_groups, name);
			}
			this.state.page = 1;
			this.render_item_groups();
			this.schedule_refresh();
		});

		this.$root.on("click", "[data-expand-item-groups]", () => {
			this.state.expand_item_groups = !this.state.expand_item_groups;
			this.render_item_groups();
		});

		this.$root.on("input", ".spa-item-search", (e) => {
			this.state.item_group_search = e.target.value || "";
			this.render_item_groups();
		});

		this.$root.on("click", "[data-page]", (e) => {
			const page = cint($(e.currentTarget).data("page"));
			if (!page || page === this.state.page) return;
			this.state.page = page;
			this.refresh();
		});
	}

	toggle_list(list, value) {
		const idx = list.indexOf(value);
		if (idx >= 0) {
			list.splice(idx, 1);
		} else {
			list.push(value);
		}
	}

	async load_filter_options() {
		try {
			const message = await frappe.xcall(
				"sales_person_analysis.api.analysis.get_filter_options",
				{ doctype: this.state.doctype }
			);
			this.options.sales_persons = message.sales_persons || [];
			this.options.item_groups = message.item_groups || [];
			this.options.years = (message.years || []).map(String);
			this.options.currency = message.currency || "";
			this.options.period = message.period || this.options.period;

			if (!this.options.years.includes(this.state.year)) {
				this.state.year = this.options.years[0] || String(new Date().getFullYear());
			}
			this.state.sales_persons = this.state.sales_persons.filter((n) =>
				this.options.sales_persons.includes(n)
			);
			this.state.item_groups = this.state.item_groups.filter((n) =>
				this.options.item_groups.includes(n)
			);
			await this.refresh_period_options();
			this.render_filters();
		} catch (err) {
			console.error(err);
			frappe.show_alert({ message: __("Failed to load filter options"), indicator: "red" });
		}
	}

	async refresh_period_options() {
		const message = await frappe.xcall("sales_person_analysis.api.analysis.get_period_options", {
			half: this.state.half,
			quarter: this.state.quarter,
			year: cint(this.state.year),
		});
		this.options.period = message;
		const allowed_months = message.months || [];
		this.state.months = this.state.months.filter((m) => allowed_months.includes(m));
		if (message.quarter && message.quarter !== this.state.quarter) {
			this.state.quarter = message.quarter;
		}
	}

	render_filters() {
		this.render_doctypes();
		this.render_sales_persons();
		this.render_date_controls();
		this.render_months();
		this.render_weeks();
		this.render_item_groups();
	}

	render_doctypes() {
		const html = ["Sales Invoice", "Sales Order"]
			.map((dt) => {
				const selected = this.state.doctype === dt ? "is-selected" : "";
				return `<button type="button" class="spa-chip ${selected}" data-doctype="${dt}" aria-pressed="${
					this.state.doctype === dt
				}">${__(dt)}</button>`;
			})
			.join("");
		this.$root.find(".spa-doctype-row").html(html);
	}

	render_sales_persons() {
		const all_selected = !this.state.sales_persons.length;
		let names = this.options.sales_persons.slice();
		const hidden = !this.state.expand_sales_persons
			? Math.max(0, names.length - this.visible_chip_count)
			: 0;
		if (hidden) {
			names = names.slice(0, this.visible_chip_count);
		}

		let html = `<button type="button" class="spa-chip ${
			all_selected ? "is-selected" : ""
		}" data-sales-person="__all__" aria-pressed="${all_selected}">${__("All Sales Persons")}</button>`;

		html += names
			.map((name) => {
				const selected = this.state.sales_persons.includes(name);
				return `<button type="button" class="spa-chip ${
					selected ? "is-selected-soft" : ""
				}" data-sales-person="${frappe.utils.escape_html(name)}" aria-pressed="${selected}">${frappe.utils.escape_html(
					name
				)}</button>`;
			})
			.join("");

		if (hidden) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-sales>+${hidden} ${__(
				"more"
			)}</button>`;
		} else if (this.state.expand_sales_persons && this.options.sales_persons.length > this.visible_chip_count) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-sales>${__("Show less")}</button>`;
		}

		this.$root.find(".spa-sales-person-row").html(html);
	}

	render_date_controls() {
		const years = this.options.years
			.map((y) => `<option value="${y}" ${y === this.state.year ? "selected" : ""}>${y}</option>`)
			.join("");
		const halves = (this.options.period.halves || ["All", "H1", "H2"])
			.map(
				(h) =>
					`<option value="${h}" ${h === this.state.half ? "selected" : ""}>${
						h === "All" ? __("All") : h
					}</option>`
			)
			.join("");
		const quarters = (this.options.period.quarters || ["All", "Q1", "Q2", "Q3", "Q4"])
			.map(
				(q) =>
					`<option value="${q}" ${q === this.state.quarter ? "selected" : ""}>${
						q === "All" ? __("All") : q
					}</option>`
			)
			.join("");

		this.$root.find(".spa-date-row").html(`
			<div class="spa-date-controls">
				<div class="spa-date-field">
					<label>${__("Year")}</label>
					<select class="form-control spa-year-select">${years}</select>
				</div>
				<div class="spa-date-field">
					<label>${__("Half Year")}</label>
					<select class="form-control spa-half-select">${halves}</select>
				</div>
				<div class="spa-date-field">
					<label>${__("Quarter")}</label>
					<select class="form-control spa-quarter-select">${quarters}</select>
				</div>
			</div>
		`);
	}

	render_months() {
		const months = this.options.period.months || [];
		const all_selected = !this.state.months.length;
		let html = `<button type="button" class="spa-chip ${
			all_selected ? "is-selected" : ""
		}" data-month="__all__" aria-pressed="${all_selected}">${__("All Months")}</button>`;
		html += months
			.map((m) => {
				const selected = this.state.months.includes(m);
				return `<button type="button" class="spa-chip ${
					selected ? "is-selected-soft" : ""
				}" data-month="${m}" aria-pressed="${selected}">${__(m)}</button>`;
			})
			.join("");
		this.$root.find(".spa-month-row").html(html);
	}

	render_weeks() {
		let weeks = (this.options.period.weeks || [1, 2, 3, 4, 5, 6]).map(String);
		const all_selected = !this.state.weeks.length;
		const hidden = !this.state.expand_weeks ? Math.max(0, weeks.length - 4) : 0;
		if (hidden) {
			weeks = weeks.slice(0, 4);
		}

		let html = `<button type="button" class="spa-chip ${
			all_selected ? "is-selected" : ""
		}" data-week="__all__" aria-pressed="${all_selected}">${__("All Weeks")}</button>`;
		html += weeks
			.map((w) => {
				const selected = this.state.weeks.includes(w);
				const label = frappe.utils.escape_html(this.week_chip_label(w));
				return `<button type="button" class="spa-chip ${
					selected ? "is-selected-soft" : ""
				}" data-week="${w}" aria-pressed="${selected}" title="${label}">${label}</button>`;
			})
			.join("");
		if (hidden) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-weeks>+ ${__("more")}</button>`;
		} else if (this.state.expand_weeks && (this.options.period.weeks || []).length > 4) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-weeks>${__("Show less")}</button>`;
		}
		this.$root.find(".spa-week-row").html(html);
	}

	week_chip_label(week) {
		// Date spans come from period.week_labels (week_of_month on the server).
		// Shown only when a single month is selected; otherwise the chip stays a number.
		if (this.state.months.length !== 1) {
			return String(week);
		}
		const labels = (this.options.period.week_labels || {})[this.state.months[0]];
		if (!labels) {
			return String(week);
		}
		return labels[String(week)] || `${__("Week")} ${week}`;
	}

	render_item_groups() {
		const search = (this.state.item_group_search || "").toLowerCase();
		let names = this.options.item_groups.filter((n) => !search || n.toLowerCase().includes(search));
		const all_selected = !this.state.item_groups.length;
		const hidden = !this.state.expand_item_groups
			? Math.max(0, names.length - this.visible_chip_count)
			: 0;
		if (hidden) {
			names = names.slice(0, this.visible_chip_count);
		}

		let html = `<button type="button" class="spa-chip ${
			all_selected ? "is-selected" : ""
		}" data-item-group="__all__" aria-pressed="${all_selected}">${__("All Item Groups")}</button>`;
		html += names
			.map((name) => {
				const selected = this.state.item_groups.includes(name);
				return `<button type="button" class="spa-chip ${
					selected ? "is-selected" : ""
				}" data-item-group="${frappe.utils.escape_html(name)}" aria-pressed="${selected}">${frappe.utils.escape_html(
					name
				)}</button>`;
			})
			.join("");
		if (hidden) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-item-groups>+ ${__(
				"more"
			)}</button>`;
		} else if (
			this.state.expand_item_groups &&
			this.options.item_groups.filter((n) => !search || n.toLowerCase().includes(search)).length >
				this.visible_chip_count
		) {
			html += `<button type="button" class="spa-chip spa-more" data-expand-item-groups>${__(
				"Show less"
			)}</button>`;
		}
		html += `<input type="search" class="form-control spa-item-search" placeholder="${__(
			"Search item groups"
		)}" value="${frappe.utils.escape_html(this.state.item_group_search || "")}">`;
		this.$root.find(".spa-item-group-row").html(html);
	}

	schedule_refresh() {
		if (this.refresh_timer) {
			clearTimeout(this.refresh_timer);
		}
		this.refresh_timer = setTimeout(() => this.refresh(), 250);
	}

	get_filters(extra = {}) {
		return {
			doctype: this.state.doctype,
			year: cint(this.state.year),
			half: this.state.half,
			quarter: this.state.quarter,
			months: this.state.months.slice(),
			weeks: this.state.weeks.map((w) => cint(w)),
			sales_persons: this.state.sales_persons.slice(),
			item_groups: this.state.item_groups.slice(),
			page: this.state.page,
			page_size: this.page_size,
			...extra,
		};
	}

	async refresh() {
		if (this.loading) {
			this.pending_refresh = true;
			return;
		}
		this.loading = true;
		this.pending_refresh = false;
		const request_id = ++this.request_id;
		this.render_loading();

		try {
			const message = await frappe.xcall(
				"sales_person_analysis.api.analysis.get_customer_wise_sales",
				{ filters: this.get_filters() }
			);
			if (request_id !== this.request_id) return;
			this.data = message;
			this.options.currency = message.currency || this.options.currency;
			this.render_table();
		} catch (err) {
			if (request_id !== this.request_id) return;
			console.error(err);
			this.$root.find(".spa-table-body").html(
				`<div class="spa-error">${__("Could not load sales data. Please try again.")}</div>`
			);
		} finally {
			if (request_id === this.request_id) {
				this.loading = false;
				if (this.pending_refresh) {
					this.refresh();
				}
			}
		}
	}

	render_loading() {
		this.$root.find(".spa-table-body").html(`<div class="spa-loading">${__("Loading...")}</div>`);
	}

	render_table() {
		const currency = this.data.currency || this.options.currency || "";
		const count = cint(this.data.customer_count);
		this.$root.find(".spa-count").text(`${count} ${count === 1 ? __("customer") : __("customers")}`);
		this.$root
			.find(".spa-grand-total .spa-amount")
			.text(format_currency(flt(this.data.grand_total), currency));

		const rows = this.data.rows || [];
		if (!rows.length) {
			this.$root.find(".spa-table-body").html(
				`<div class="spa-empty">${__(
					"No sales found for the selected filters."
				)}</div>`
			);
			this.render_pagination();
			return;
		}

		const amount_label = currency
			? `${__("Sales Amount")} (${frappe.utils.escape_html(currency)})`
			: __("Sales Amount");
		const start = (cint(this.data.page) - 1) * cint(this.data.page_size || this.page_size);

		const body = rows
			.map((row, idx) => {
				const customer = frappe.utils.escape_html(row.customer || "");
				const customer_name = frappe.utils.escape_html(row.customer_name || row.customer || "");
				return `<tr>
					<td class="spa-col-num">${start + idx + 1}</td>
					<td><a href="/app/customer/${encodeURIComponent(row.customer)}">${customer_name}</a></td>
					<td class="spa-col-amount">${format_currency(flt(row.amount), currency)}</td>
				</tr>`;
			})
			.join("");

		this.$root.find(".spa-table-body").html(`
			<div class="spa-table-wrap">
				<table class="spa-table table">
					<thead>
						<tr>
							<th class="spa-col-num">#</th>
							<th>${__("Customer")}</th>
							<th class="spa-col-amount">${amount_label}</th>
						</tr>
					</thead>
					<tbody>${body}</tbody>
				</table>
			</div>
		`);
		this.render_pagination();
	}

	render_pagination() {
		const total_pages = Math.max(1, cint(this.data.total_pages) || 1);
		const current = cint(this.data.page) || 1;
		if (total_pages <= 1) {
			this.$root.find(".spa-pagination").html("");
			return;
		}

		let html = `<button type="button" class="spa-page-btn" data-page="${
			current - 1
		}" ${current <= 1 ? "disabled" : ""}>&lsaquo;</button>`;
		for (let p = 1; p <= total_pages; p++) {
			if (total_pages > 7 && Math.abs(p - current) > 2 && p !== 1 && p !== total_pages) {
				if (p === 2 || p === total_pages - 1) {
					html += `<span>…</span>`;
				}
				continue;
			}
			html += `<button type="button" class="spa-page-btn ${
				p === current ? "is-active" : ""
			}" data-page="${p}">${p}</button>`;
		}
		html += `<button type="button" class="spa-page-btn" data-page="${
			current + 1
		}" ${current >= total_pages ? "disabled" : ""}>&rsaquo;</button>`;
		this.$root.find(".spa-pagination").html(html);
	}

	async clear_filters() {
		this.state = {
			...this.state,
			doctype: "Sales Invoice",
			sales_persons: [],
			year: String(new Date().getFullYear()),
			half: "All",
			quarter: "All",
			months: [],
			weeks: [],
			item_groups: [],
			page: 1,
			expand_sales_persons: false,
			expand_weeks: false,
			expand_item_groups: false,
			item_group_search: "",
		};
		await this.load_filter_options();
		this.refresh();
	}

	async export_csv() {
		try {
			frappe.dom.freeze(__("Exporting..."));
			const message = await frappe.xcall(
				"sales_person_analysis.api.analysis.get_customer_wise_sales",
				{ filters: this.get_filters({ export: 1, page: 1 }) }
			);
			const currency = message.currency || this.options.currency || "";
			const rows = [[__("Customer"), `${__("Sales Amount")} (${currency})`]];
			(message.rows || []).forEach((row) => {
				rows.push([row.customer_name || row.customer || "", flt(row.amount)]);
			});
			rows.push([__("Grand Total"), flt(message.grand_total)]);
			frappe.tools.downloadify([], null, rows, "Sales_Person_Wise_Analysis");
		} catch (err) {
			console.error(err);
			frappe.show_alert({ message: __("Export failed"), indicator: "red" });
		} finally {
			frappe.dom.unfreeze();
		}
	}
}
