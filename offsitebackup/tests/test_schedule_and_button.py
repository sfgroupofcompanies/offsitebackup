from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from offsitebackup.backup import backup_now, run_backup, scheduled_backup

from .test_run_backup import enable_settings


class TestScheduleAndButton(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_the_job_is_registered_at_half_past_two(self):
		cron = frappe.get_hooks("scheduler_events", app_name="offsitebackup").get("cron", {})
		self.assertEqual(cron.get("30 2 * * *"), ["offsitebackup.backup.scheduled_backup"])

	def test_daily_runs_every_night(self):
		enable_settings(backup_frequency="Daily")
		with patch("offsitebackup.backup.run_backup", return_value="RUN-1") as run:
			self.assertEqual(scheduled_backup(), "RUN-1")
		run.assert_called_once_with("Scheduled")

	def test_weekly_runs_on_sunday_only(self):
		enable_settings(backup_frequency="Weekly")
		with patch("offsitebackup.backup.run_backup", return_value="RUN-1") as run:
			with patch("frappe.utils.nowdate", return_value=date(2026, 11, 4).isoformat()):  # a Wednesday
				self.assertIsNone(scheduled_backup())
			run.assert_not_called()
			with patch("frappe.utils.nowdate", return_value=date(2026, 11, 8).isoformat()):  # a Sunday
				self.assertEqual(scheduled_backup(), "RUN-1")
			run.assert_called_once_with("Scheduled")

	def test_button_queues_a_manual_run_on_the_long_queue(self):
		enable_settings()
		with patch("frappe.utils.background_jobs.enqueue") as enqueue:
			backup_now()
		enqueue.assert_called_once()
		self.assertIs(enqueue.call_args.args[0], run_backup)
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		self.assertEqual(enqueue.call_args.kwargs["trigger"], "Manual")
		self.assertGreaterEqual(enqueue.call_args.kwargs["timeout"], 600)

	def test_button_refuses_while_disabled(self):
		enable_settings(enabled=0, site_url="", tenant_id="", client_id="", client_secret="")
		with patch("frappe.utils.background_jobs.enqueue") as enqueue:
			self.assertRaises(frappe.ValidationError, backup_now)
		enqueue.assert_not_called()

	def test_button_is_for_system_managers_only(self):
		enable_settings()
		frappe.set_user("Guest")
		with patch("frappe.utils.background_jobs.enqueue") as enqueue:
			self.assertRaises(frappe.PermissionError, backup_now)
		enqueue.assert_not_called()
