"""The scheduled entry point (hooks.py: cron 30 2 * * *)."""

import frappe

from offsitebackup.backup.run import SETTINGS, run_backup

WEEKLY_RUN_DAY = 6  # Sunday, as Python counts (Monday = 0)


def scheduled_backup():
	"""The 02:30 job. Daily runs every night; Weekly runs on Sundays only."""
	from frappe.utils import getdate, nowdate

	frequency = frappe.db.get_single_value(SETTINGS, "backup_frequency") or "Daily"
	if frequency == "Weekly" and getdate(nowdate()).weekday() != WEEKLY_RUN_DAY:
		return None
	return run_backup("Scheduled")
