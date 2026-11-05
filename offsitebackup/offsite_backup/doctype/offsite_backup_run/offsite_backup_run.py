# Copyright (c) 2026, SF Group of Companies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import date_diff, now_datetime, nowdate, time_diff_in_seconds


class OffsiteBackupRun(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		duration_seconds: DF.Int
		file_name: DF.Data | None
		finished_on: DF.Datetime | None
		folder: DF.Data | None
		message: DF.SmallText | None
		size_mb: DF.Float
		started_on: DF.Datetime
		status: DF.Literal["Running", "Success", "Failed"]
		trigger: DF.Literal["Scheduled", "Manual"]
	# end: auto-generated types

	pass


def start_run(trigger: str = "Scheduled", folder: str | None = None) -> "OffsiteBackupRun":
	"""One row per backup attempt, written the moment it starts."""
	run = frappe.get_doc(
		{
			"doctype": "Offsite Backup Run",
			"started_on": now_datetime(),
			"status": "Running",
			"trigger": trigger,
			"folder": folder,
		}
	)
	run.insert(ignore_permissions=True)
	return run


def finish_run(run, ok: bool, file_name: str = "", size_mb: float = 0, message: str = ""):
	"""Close the row with the outcome; the message holds the error text on failure."""
	run.finished_on = now_datetime()
	run.status = "Success" if ok else "Failed"
	run.file_name = file_name
	run.size_mb = size_mb
	run.message = (message or "")[:2000]
	run.duration_seconds = int(time_diff_in_seconds(run.finished_on, run.started_on))
	run.save(ignore_permissions=True)
	return run


def last_good_run():
	"""The most recent successful run, or None."""
	rows = frappe.get_all(
		"Offsite Backup Run",
		filters={"status": "Success"},
		fields=["name", "started_on", "file_name", "size_mb"],
		order_by="started_on desc",
		limit=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def days_since_last_good_backup():
	"""Number card: how many days since a backup last reached the library. 999 means never."""
	frappe.only_for("System Manager")
	last = last_good_run()
	value = date_diff(nowdate(), last.started_on) if last else 999
	return {
		"value": value,
		"fieldtype": "Int",
		"route_options": {"status": "Success"},
		"route": ["offsite-backup-run"],
	}
