"""One complete backup run: dump → token → upload → prune, with the run log, the Last Run fields and the emails."""

import frappe
from frappe import _

from offsitebackup.backup.dump import make_backup

SERVICE_NAME = "Microsoft 365"
SETTINGS = "Offsite Backup Settings"


def run_backup(trigger: str = "Scheduled"):
	"""One complete backup run. Returns the run's name, or None when backups are disabled.

	Mirrors Dropbox's take_backup_to_dropbox: nothing here raises to the caller;
	every failure is written to the run log, the settings' Last Run fields, the
	Error Log and the failure email.
	"""
	from frappe.integrations.offsite_backup_utils import send_email

	from offsitebackup.backup.prune import prune_folder
	from offsitebackup.integrations.microsoft.graph import GraphClient
	from offsitebackup.integrations.microsoft.token import get_token
	from offsitebackup.offsite_backup.doctype.offsite_backup_run.offsite_backup_run import (
		finish_run,
		start_run,
	)

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
