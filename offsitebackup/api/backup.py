"""The "Back up now" button (Offsite Backup Settings form)."""

import frappe
from frappe import _

from offsitebackup.backup.run import SETTINGS, run_backup

JOB_TIMEOUT_SECONDS = 1500
JOB_ID = "offsitebackup-run"  # one queued run per site at a time; Frappe prefixes the site name


@frappe.whitelist(methods=["POST"])
def backup_now():
	"""The button: queue one run on the long queue so the browser never waits (mirrors Dropbox's take_backup).

	POST only, System Manager only, and never two runs in the queue at once: a second press
	while one is queued or running would mean two full dumps of the database side by side.
	"""
	from frappe.utils.background_jobs import enqueue, is_job_enqueued

	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can start a backup."), frappe.PermissionError)
	if not frappe.db.get_single_value(SETTINGS, "enabled"):
		frappe.throw(_("Enable and save the settings first."))
	if is_job_enqueued(JOB_ID):
		frappe.msgprint(_("A backup is already queued or running. Watch the Offsite Backup Run list."))
		return
	enqueue(
		run_backup,
		queue="long",
		timeout=JOB_TIMEOUT_SECONDS,
		trigger="Manual",
		enqueue_after_commit=True,
		job_id=JOB_ID,
		deduplicate=True,
	)
	frappe.msgprint(
		_("Backup queued. Watch the Offsite Backup Run list; the result lands there in a few minutes.")
	)
