// Copyright (c) 2026, SF Group of Companies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Offsite Backup Run", {
  refresh(frm) {
    const colour = { Success: "green", Failed: "red", Running: "orange" }[
      frm.doc.status
    ];
    if (colour) {
      frm.page.set_indicator(__(frm.doc.status), colour);
    }
  },
});
