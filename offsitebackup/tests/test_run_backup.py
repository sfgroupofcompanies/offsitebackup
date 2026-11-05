from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from offsitebackup.backup.run import run_backup
from offsitebackup.integrations.microsoft.token import MicrosoftError

MADE = {"path": "/tmp/x-database.sql.gz", "file_name": "x-database.sql.gz", "size_mb": 139.2}
PRUNED = {"kept": ["a", "b", "c"], "deleted": ["d"]}


def enable_settings(**values):
	doc = frappe.get_doc("Offsite Backup Settings")
	doc.update(
		{
			"enabled": 1,
			"site_url": "https://example.sharepoint.com/sites/ERPBackups",
			"folder": "test-site",
			"tenant_id": "tenant",
			"client_id": "client",
			"client_secret": "s3cr3t",
			"keep_daily": 30,
			"keep_monthly": 12,
			"send_notifications_to": "ops@example.com",
			"send_email_for_successful_backup": 0,
			"last_result": "",
		}
	)
	doc.update(values)
	doc.save()
	return doc


class Pieces:
	"""Every outside piece faked, with one call list to check the order."""

	def __init__(self, upload_error=None, prune_error=None):
		self.calls = []
		self.make_backup = MagicMock(side_effect=lambda: self.calls.append("backup") or MADE)
		self.get_token = MagicMock(side_effect=lambda *a: self.calls.append("token") or "tok")
		self.client = MagicMock()
		self.client.upload_file.side_effect = lambda path: self.calls.append("upload") or (
			self._raise(upload_error) if upload_error else {"id": "f"}
		)
		self.graph_client = MagicMock(return_value=self.client)
		self.prune_folder = MagicMock(
			side_effect=lambda *a, **k: self.calls.append("prune")
			or (self._raise(prune_error) if prune_error else PRUNED)
		)
		self.send_email = MagicMock(side_effect=lambda *a, **k: self.calls.append("email"))

	@staticmethod
	def _raise(error):
		raise error

	def __enter__(self):
		self.patches = [
			patch("offsitebackup.backup.run.make_backup", self.make_backup),
			patch("offsitebackup.backup.run.get_token", self.get_token),
			patch("offsitebackup.backup.run.GraphClient", self.graph_client),
			patch("offsitebackup.backup.run.prune_folder", self.prune_folder),
			patch("offsitebackup.backup.run.send_email", self.send_email),
		]
		for p in self.patches:
			p.start()
		return self

	def __exit__(self, *exc):
		for p in self.patches:
			p.stop()


class TestRunBackup(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Offsite Backup Run")
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_disabled_does_nothing(self):
		enable_settings(enabled=0, site_url="", tenant_id="", client_id="", client_secret="")
		with Pieces() as pieces:
			self.assertIsNone(run_backup())
		self.assertEqual(pieces.calls, [])
		self.assertEqual(frappe.db.count("Offsite Backup Run"), 0)

	def test_success_in_order_with_run_log_and_last_run(self):
		enable_settings()
		with Pieces() as pieces:
			name = run_backup("Manual")
		self.assertEqual(pieces.calls, ["backup", "token", "upload", "prune", "email"])
		pieces.get_token.assert_called_once_with("tenant", "client", "s3cr3t")
		pieces.graph_client.assert_called_once_with(
			"tok", "https://example.sharepoint.com/sites/ERPBackups", "test-site"
		)
		pieces.client.upload_file.assert_called_once_with(MADE["path"])
		pieces.prune_folder.assert_called_once_with(pieces.client, 30, 12)

		run = frappe.get_doc("Offsite Backup Run", name)
		self.assertEqual(run.status, "Success")
		self.assertEqual(run.trigger, "Manual")
		self.assertEqual(run.file_name, MADE["file_name"])
		self.assertAlmostEqual(run.size_mb, 139.2)
		self.assertIn("3 files kept, 1 deleted", run.message)

		settings = frappe.get_doc("Offsite Backup Settings")
		self.assertTrue(settings.last_result.startswith("Success:"))
		self.assertEqual(settings.last_file, MADE["file_name"])
		self.assertAlmostEqual(settings.last_size_mb, 139.2)
		self.assertIsNotNone(settings.last_run_on)
		# the success email goes through Frappe's helper, which itself honours the tick box
		pieces.send_email.assert_called_once_with(
			True, "Microsoft 365", "Offsite Backup Settings", "send_notifications_to", None
		)

	def test_upload_failure_is_logged_everywhere_and_emailed(self):
		enable_settings()
		errors_before = frappe.db.count("Error Log")
		with Pieces(upload_error=MicrosoftError("Microsoft answered 403 to PUT: Access denied")) as pieces:
			name = run_backup()
		self.assertEqual(pieces.calls, ["backup", "token", "upload", "email"])
		run = frappe.get_doc("Offsite Backup Run", name)
		self.assertEqual(run.status, "Failed")
		self.assertIn("Access denied", run.message)
		self.assertIn(MADE["file_name"], run.message, "the message says the dump itself was made")
		self.assertTrue(
			frappe.db.get_single_value("Offsite Backup Settings", "last_result").startswith("Failed:")
		)
		self.assertEqual(frappe.db.count("Error Log"), errors_before + 1)
		args = pieces.send_email.call_args.args
		self.assertFalse(args[0])
		self.assertIn("Access denied", args[4])

	def test_prune_failure_after_a_good_upload_is_still_a_failed_run(self):
		enable_settings()
		with Pieces(prune_error=MicrosoftError("Microsoft answered 500 to GET: boom")) as pieces:
			name = run_backup()
		run = frappe.get_doc("Offsite Backup Run", name)
		self.assertEqual(run.status, "Failed")
		self.assertIn("boom", run.message)
		self.assertEqual(run.file_name, MADE["file_name"])
		self.assertEqual(pieces.calls, ["backup", "token", "upload", "prune", "email"])

	def test_broken_email_never_hides_the_outcome(self):
		enable_settings()
		with Pieces() as pieces:
			pieces.send_email.side_effect = Exception("smtp down")
			name = run_backup()
		self.assertEqual(frappe.db.get_value("Offsite Backup Run", name, "status"), "Success")

	def test_backup_failure_has_no_file_name(self):
		enable_settings()
		with Pieces() as pieces:
			pieces.make_backup.side_effect = frappe.ValidationError(
				"Frappe did not produce a database backup file."
			)
			name = run_backup()
		run = frappe.get_doc("Offsite Backup Run", name)
		self.assertEqual(run.status, "Failed")
		self.assertEqual(run.file_name, "")
		self.assertIn("did not produce", run.message)
		self.assertEqual(pieces.calls, ["email"])

	def test_failure_email_text_is_escaped(self):
		enable_settings()
		with Pieces(upload_error=MicrosoftError('Microsoft answered 403: <img src=x onerror="x">')) as pieces:
			run_backup()
		emailed = pieces.send_email.call_args.args[4]
		self.assertNotIn("<img", emailed)
		self.assertIn("&lt;img", emailed)
