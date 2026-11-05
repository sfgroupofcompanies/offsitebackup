// Copyright (c) 2026, SF Group of Companies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Offsite Backup Settings", {
  refresh(frm) {
    if (frm.doc.last_result && !frm.doc.last_result.startsWith("Failed")) {
      frm.dashboard.set_headline(
        __("Last backup: {0}", [frm.doc.last_result])
      );
    }
  },
});
