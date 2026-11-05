"""The "Back up now" button (Offsite Backup Settings form)."""

import frappe
from frappe import _

from offsitebackup.backup.run import SETTINGS, run_backup

JOB_TIMEOUT_SECONDS = 1500


@frappe.whitelist()
def backup_now():
	"""The button: queue one run on the long queue so the browser never waits (mirrors Dropbox's take_backup)."""
	from frappe.utils.background_jobs import enqueue

	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can start a backup."), frappe.PermissionError)
	if not frappe.db.get_single_value(SETTINGS, "enabled"):
		frappe.throw(_("Enable and save the settings first."))
	enqueue(
		run_backup, queue="long", timeout=JOB_TIMEOUT_SECONDS, trigger="Manual", enqueue_after_commit=True
	)
	frappe.msgprint(
		_("Backup queued. Watch the Offsite Backup Run list; the result lands there in a few minutes.")
	)
