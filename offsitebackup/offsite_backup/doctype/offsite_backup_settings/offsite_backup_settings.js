// Copyright (c) 2026, SF Group of Companies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Offsite Backup Settings", {
  refresh(frm) {
    if (frm.doc.last_result) {
      const failed = frm.doc.last_result.startsWith("Failed");
      frm.dashboard.set_headline(
        __("Last run: {0}", [frappe.utils.escape_html(frm.doc.last_result)]),
        failed ? "red" : "green"
      );
    }
    if (frm.doc.enabled && !frm.is_dirty()) {
      frm.add_custom_button(__("Back up now"), () => {
        frappe.call({
          method: "offsitebackup.backup.backup_now",
          freeze: true,
          freeze_message: __("Queueing the backup..."),
        });
      });
    }
    frm.add_custom_button(__("Runs"), () => {
      frappe.set_route("List", "Offsite Backup Run");
    });
  },
});
