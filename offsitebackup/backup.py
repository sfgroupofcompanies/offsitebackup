"""Making the backup file: Frappe's own database dump, nothing else.

No attachment archives are made. Frappe always writes a copy of the site
config (with the encryption key) next to the dump on the site's own disk,
as it does for its scheduled backups; that copy is never uploaded. Only the
path of the database file is handed on (decision D-5).
"""

import os

import frappe
from frappe import _
from frappe.utils.backups import new_backup


def make_backup() -> dict:
	"""A fresh, database-only dump through Frappe's own backup.

	Returns the file's path, name and size in MB. `force=True` so every run
	makes a new file instead of reusing one Frappe took earlier in the day.
	"""
	backup = new_backup(ignore_files=True, force=True)
	path = getattr(backup, "backup_path_db", None)
	if not path or not os.path.exists(path):
		frappe.throw(_("Frappe did not produce a database backup file."))
	size_mb = round(os.path.getsize(path) / (1024 * 1024), 2)
	return {"path": path, "file_name": os.path.basename(path), "size_mb": size_mb}


# ---------------------------------------------------------------------------
# The nightly run: backup → token → upload → prune, with the run log and emails
# ---------------------------------------------------------------------------

SERVICE_NAME = "Microsoft 365"
SETTINGS = "Offsite Backup Settings"


def run_backup(trigger: str = "Scheduled"):
	"""One complete backup run. Returns the run's name, or None when backups are disabled.

	Mirrors Dropbox's take_backup_to_dropbox: nothing here raises to the caller;
	every failure is written to the run log, the settings' Last Run fields, the
	Error Log and the failure email.
	"""
	from frappe.integrations.offsite_backup_utils import send_email

	from offsitebackup.microsoft import GraphClient, get_token
	from offsitebackup.offsite_backup.doctype.offsite_backup_run.offsite_backup_run import (
		finish_run,
		start_run,
	)
	from offsitebackup.prune import prune_folder

	settings = frappe.get_single(SETTINGS)
	if not settings.enabled:
		return None

	run = start_run(trigger, folder=settings.folder)
	made = None
	try:
		made = make_backup()
		token = get_token(settings.tenant_id, settings.client_id, settings.get_password("client_secret"))
		client = GraphClient(token, settings.site_url, settings.folder)
		client.upload_file(made["path"])
		pruned = prune_folder(client, settings.keep_daily, settings.keep_monthly)
		summary = _("Uploaded {0} ({1} MB); {2} files kept, {3} deleted.").format(
			made["file_name"], made["size_mb"], len(pruned["kept"]), len(pruned["deleted"])
		)
		finish_run(run, True, file_name=made["file_name"], size_mb=made["size_mb"], message=summary)
		_write_last_run(run, "Success: " + summary)
		_notify(send_email, True)
	except Exception as exc:
		frappe.log_error(title=_("Offsite backup failed"), message=frappe.get_traceback())
		reason = str(exc) or type(exc).__name__
		if made:
			reason = _("Backup file {0} was made; the step after it failed: {1}").format(
				made["file_name"], reason
			)
		finish_run(
			run,
			False,
			file_name=made["file_name"] if made else "",
			size_mb=made["size_mb"] if made else 0,
			message=reason,
		)
		_write_last_run(run, "Failed: " + reason)
		_notify(send_email, False, reason)
	return run.name


def _write_last_run(run, result: str):
	frappe.db.set_single_value(
		SETTINGS,
		{
			"last_run_on": run.finished_on,
			"last_file": run.file_name,
			"last_size_mb": run.size_mb,
			"last_result": result[:2000],
		},
		update_modified=False,
	)


def _notify(send_email, success: bool, error: str = ""):
	"""The success email only when ticked (send_email checks that itself); failures always. Never raises."""
	try:
		send_email(success, SERVICE_NAME, SETTINGS, "send_notifications_to", error or None)
	except Exception:
		frappe.log_error(
			title=_("Offsite backup: could not send the status email"), message=frappe.get_traceback()
		)


# ---------------------------------------------------------------------------
# Entry points: the night-time job and the "Back up now" button
# ---------------------------------------------------------------------------

WEEKLY_RUN_DAY = 6  # Sunday, as Python counts (Monday = 0)
JOB_TIMEOUT_SECONDS = 1500


def scheduled_backup():
	"""The 02:30 job. Daily runs every night; Weekly runs on Sundays only."""
	from frappe.utils import getdate, nowdate

	frequency = frappe.db.get_single_value(SETTINGS, "backup_frequency") or "Daily"
	if frequency == "Weekly" and getdate(nowdate()).weekday() != WEEKLY_RUN_DAY:
		return None
	return run_backup("Scheduled")


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
