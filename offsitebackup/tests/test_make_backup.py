import os
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_backups_path

from offsitebackup.backup.dump import make_backup


class TestMakeBackup(FrappeTestCase):
	def test_real_dump_of_this_site(self):
		before = set(os.listdir(get_backups_path()))
		result = make_backup()
		new_files = set(os.listdir(get_backups_path())) - before
		for name in new_files:
			full = os.path.join(get_backups_path(), name)
			self.addCleanup(lambda p=full: os.path.exists(p) and os.remove(p))

		self.assertTrue(os.path.exists(result["path"]))
		self.assertTrue(result["file_name"].endswith("-database.sql.gz"))
		self.assertIn(frappe.local.site.replace(".", "_"), result["file_name"])
		self.assertGreater(result["size_mb"], 0)

		self.assertIn(result["file_name"], new_files)
		for name in new_files:
			self.assertFalse(name.endswith((".tar", ".tgz")), "no attachment archive may be written")
		# Frappe always writes the site config copy next to the dump; it stays on disk, never uploaded
		self.assertTrue(any(n.endswith("site_config_backup.json") for n in new_files))

	def test_missing_file_is_an_error(self):
		fake = MagicMock()
		fake.backup_path_db = "/nowhere/backup.sql.gz"
		with patch("offsitebackup.backup.dump.new_backup", return_value=fake):
			self.assertRaises(frappe.ValidationError, make_backup)

	def test_frappe_is_asked_for_database_only(self):
		fake = MagicMock()
		fake.backup_path_db = __file__
		with patch("offsitebackup.backup.dump.new_backup", return_value=fake) as new_backup:
			make_backup()
		kwargs = new_backup.call_args.kwargs
		self.assertTrue(kwargs["ignore_files"])
		self.assertTrue(kwargs["force"])
