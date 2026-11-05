// Copyright (c) 2026, SF Group of Companies and contributors
// For license information, please see license.txt

frappe.query_reports["Offsite Backup Runs"] = {
  filters: [
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
    },
    {
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Select",
      options: "\nRunning\nSuccess\nFailed",
    },
  ],
  formatter(value, row, column, data, default_formatter) {
    let formatted = default_formatter(value, row, column, data);
    if (data && column.fieldname === "status") {
      const colour = { Success: "green", Failed: "red", Running: "orange" }[
        data.status
      ];
      if (colour) {
        formatted = `<span class="indicator-pill ${colour}">${formatted}</span>`;
      }
    }
    return formatted;
  },
};
