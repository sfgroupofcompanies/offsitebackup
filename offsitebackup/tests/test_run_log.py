import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from offsitebackup.offsite_backup.doctype.offsite_backup_run.offsite_backup_run import (
	days_since_last_good_backup,
	finish_run,
	last_good_run,
	start_run,
)
from offsitebackup.offsite_backup.report.offsite_backup_runs.offsite_backup_runs import execute


class TestRunLog(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Offsite Backup Run")
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_start_then_success(self):
		run = start_run("Manual", folder="gva-sf")
		self.assertEqual(run.status, "Running")
		self.assertEqual(run.trigger, "Manual")
		finish_run(run, True, file_name="x-database.sql.gz", size_mb=139.2)
		saved = frappe.get_doc("Offsite Backup Run", run.name)
		self.assertEqual(saved.status, "Success")
		self.assertEqual(saved.file_name, "x-database.sql.gz")
		self.assertAlmostEqual(saved.size_mb, 139.2)
		self.assertIsNotNone(saved.finished_on)
		self.assertGreaterEqual(saved.duration_seconds, 0)

	def test_failure_keeps_the_message(self):
		run = start_run()
		finish_run(run, False, message="Microsoft refused the credentials (401): bad secret")
		saved = frappe.get_doc("Offsite Backup Run", run.name)
		self.assertEqual(saved.status, "Failed")
		self.assertIn("401", saved.message)

	def test_days_since_last_good_backup(self):
		self.assertEqual(days_since_last_good_backup()["value"], 999)
		run = start_run()
		finish_run(run, True, file_name="a.sql.gz", size_mb=1)
		frappe.db.set_value("Offsite Backup Run", run.name, "started_on", add_days(now_datetime(), -3))
		self.assertEqual(days_since_last_good_backup()["value"], 3)
		failed = start_run()
		finish_run(failed, False, message="boom")
		self.assertEqual(
			last_good_run().name, run.name, "a later failure does not count as the last good run"
		)
		self.assertEqual(days_since_last_good_backup()["value"], 3)

	def test_report_lists_runs_newest_first_with_status_filter(self):
		first = start_run()
		finish_run(first, True, file_name="first.sql.gz", size_mb=1)
		frappe.db.set_value("Offsite Backup Run", first.name, "started_on", add_days(now_datetime(), -2))
		second = start_run()
		finish_run(second, False, message="boom")
		columns, rows = execute({})
		self.assertEqual([r.name for r in rows], [second.name, first.name])
		self.assertEqual(len(columns), 9)
		_columns, failed_only = execute({"status": "Failed"})
		self.assertEqual([r.name for r in failed_only], [second.name])
		_columns, old_window = execute(
			{"from_date": add_days(now_datetime(), -40), "to_date": add_days(now_datetime(), -1)}
		)
		self.assertEqual([r.name for r in old_window], [first.name])

	def test_nobody_edits_a_run_by_hand(self):
		meta = frappe.get_meta("Offsite Backup Run")
		self.assertTrue(meta.in_create)
		self.assertFalse(any(p.write or p.create for p in meta.permissions))
		self.assertTrue(
			all(f.read_only for f in meta.fields if f.fieldtype not in ("Column Break", "Section Break"))
		)

	def test_compliance_artifacts_are_installed(self):
		self.assertTrue(frappe.db.exists("Report", "Offsite Backup Runs"))
		self.assertTrue(frappe.db.exists("Dashboard Chart", "Backup Size per Day"))
		self.assertTrue(frappe.db.exists("Number Card", "Days Since Last Good Backup"))
		self.assertTrue(frappe.db.exists("Number Card", "Failed Backups (30 days)"))
		self.assertTrue(frappe.db.exists("Dashboard", "Offsite Backup"))
		self.assertTrue(frappe.db.exists("Workspace", "Offsite Backup"))
